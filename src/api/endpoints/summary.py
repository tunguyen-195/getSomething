from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from typing import List, Optional
import hashlib
import hmac
import json
import math
from src.database.config.database import get_db
from src.database.models.models import Summary as DBSummary, Case, AudioFile, User
from src.database.models.schemas import SummaryCreate, SummaryOut
from src.services.summary_service import (
    create_summary, get_summary, list_summaries, update_summary, delete_summary
)
from src.services.task_service import update_task, get_task
from src.services.summarization.context_service import analyze_conversation_context
from src.services.summarization.models.context_analysis import (
    ANALYSIS_SCHEMA_VERSION,
    CONTEXT_PROMPT_VERSION,
)
from src.services.summarization.investigation_scenarios import (
    DEFAULT_INVESTIGATION_SCENARIO,
    InvestigationScenario,
)
from src.services.summarization.public_projection import (
    public_context_analysis_payload,
)
from src.services.model_runtime import GpuLeaseTimeout, gpu_lease
import logging
from src.core.auth import (
    accessible_case_ids,
    assert_case_access,
    assert_task_access,
    check_rate_limit,
    get_current_user,
    is_admin,
)
from src.core.config import settings

router = APIRouter()

_ANALYSIS_ATTESTATION_VERSION = "context-analysis-attestation-v2"
_ANALYSIS_MODEL_NAME: str | None = None
_ANALYSIS_USER_PROMPT: str | None = None
_ANALYSIS_INVESTIGATION_SCENARIO = DEFAULT_INVESTIGATION_SCENARIO


class SummaryAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    task_id: str | None = None


def _exact_transcript_sha256(transcript: str) -> str:
    return hashlib.sha256(transcript.encode("utf-8")).hexdigest()


def _assert_strict_json_value(value: object, *, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Non-finite number at {path}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_strict_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"Non-string object key at {path}")
            _assert_strict_json_value(item, path=f"{path}.{key}")
        return
    raise TypeError(f"Non-JSON value at {path}: {type(value).__name__}")


def _canonical_json(value: object) -> str:
    _assert_strict_json_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _segments_sha256(segments: object) -> str:
    if not isinstance(segments, list):
        raise TypeError("Analysis segments must be a JSON list")
    return _canonical_sha256(segments)


def _analysis_sha256(context_analysis: dict) -> str:
    return _canonical_sha256(context_analysis)


def _generation_inputs_sha256(
    *,
    transcript: str,
    segments: object,
    source_metadata: object,
    model_name: str | None,
    user_prompt: str | None,
    investigation_scenario: InvestigationScenario,
) -> str:
    if not isinstance(segments, list):
        raise TypeError("Analysis segments must be a JSON list")
    if not isinstance(source_metadata, dict):
        raise TypeError("Analysis source metadata must be a JSON object")
    return _canonical_sha256(
        {
            "transcript_sha256": _exact_transcript_sha256(transcript),
            "segments": segments,
            "source_metadata": source_metadata,
            "prompt_version": CONTEXT_PROMPT_VERSION,
            "model_name": model_name,
            "user_prompt": user_prompt,
            "investigation_scenario": investigation_scenario,
        }
    )


def _attestation_payload(
    *,
    task_id: str,
    transcript_sha256: str,
    segments_sha256: str,
    generation_inputs_sha256: str,
    prompt_version: str,
    analysis_sha256: str,
) -> dict[str, str]:
    return {
        "attestation_version": _ANALYSIS_ATTESTATION_VERSION,
        "task_id": task_id,
        "transcript_sha256": transcript_sha256,
        "segments_sha256": segments_sha256,
        "generation_inputs_sha256": generation_inputs_sha256,
        "prompt_version": prompt_version,
        "analysis_sha256": analysis_sha256,
    }


def _attestation_signature(payload: dict[str, str]) -> str:
    canonical = _canonical_json(payload)
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_context_analysis_attestation(
    context_analysis: dict,
    *,
    task_id: str,
    transcript: str,
    segments: object,
    source_metadata: dict | None = None,
    model_name: str | None = _ANALYSIS_MODEL_NAME,
    user_prompt: str | None = _ANALYSIS_USER_PROMPT,
    investigation_scenario: InvestigationScenario = _ANALYSIS_INVESTIGATION_SCENARIO,
) -> dict[str, str]:
    metadata = (
        source_metadata
        if source_metadata is not None
        else _analysis_source_metadata({}, task_id)
    )
    payload = _attestation_payload(
        task_id=task_id,
        transcript_sha256=_exact_transcript_sha256(transcript),
        segments_sha256=_segments_sha256(segments),
        generation_inputs_sha256=_generation_inputs_sha256(
            transcript=transcript,
            segments=segments,
            source_metadata=metadata,
            model_name=model_name,
            user_prompt=user_prompt,
            investigation_scenario=investigation_scenario,
        ),
        prompt_version=CONTEXT_PROMPT_VERSION,
        analysis_sha256=_analysis_sha256(context_analysis),
    )
    return {**payload, "signature": _attestation_signature(payload)}


def _valid_context_analysis_attestation(
    attestation: object,
    context_analysis: dict,
    *,
    task_id: str,
    transcript: str,
    segments: object,
    source_metadata: dict | None = None,
    model_name: str | None = _ANALYSIS_MODEL_NAME,
    user_prompt: str | None = _ANALYSIS_USER_PROMPT,
    investigation_scenario: InvestigationScenario = _ANALYSIS_INVESTIGATION_SCENARIO,
) -> bool:
    if not isinstance(attestation, dict):
        return False
    metadata = (
        source_metadata
        if source_metadata is not None
        else _analysis_source_metadata({}, task_id)
    )
    try:
        expected = _attestation_payload(
            task_id=task_id,
            transcript_sha256=_exact_transcript_sha256(transcript),
            segments_sha256=_segments_sha256(segments),
            generation_inputs_sha256=_generation_inputs_sha256(
                transcript=transcript,
                segments=segments,
                source_metadata=metadata,
                model_name=model_name,
                user_prompt=user_prompt,
                investigation_scenario=investigation_scenario,
            ),
            prompt_version=CONTEXT_PROMPT_VERSION,
            analysis_sha256=_analysis_sha256(context_analysis),
        )
    except (TypeError, ValueError):
        return False
    if set(attestation) != {*expected, "signature"}:
        return False
    if any(attestation.get(key) != value for key, value in expected.items()):
        return False
    signature = attestation.get("signature")
    return isinstance(signature, str) and hmac.compare_digest(
        signature,
        _attestation_signature(expected),
    )


def _analysis_source_metadata(result_data: dict, task_id: str | None) -> dict:
    return {
        "task_id": task_id,
        "audio_id": result_data.get("audio_id"),
        "audio_sha256": result_data.get("audio_sha256"),
        "audio_integrity_status": result_data.get("audio_integrity_status"),
        "num_speakers": result_data.get("num_speakers"),
        "has_diarization": result_data.get("has_diarization"),
        "degraded": result_data.get("degraded"),
        "diarization_status": result_data.get("diarization_status"),
        "diarization_method_used": result_data.get("diarization_method_used"),
        "diarization_fallback_reason": result_data.get(
            "diarization_fallback_reason"
        ),
        "diarization_degraded_reasons": result_data.get(
            "diarization_degraded_reasons"
        ),
        "speaker_provenance": result_data.get("speaker_provenance"),
    }


def _analysis_segments(result_data: dict) -> object:
    if "segments" not in result_data or result_data.get("segments") is None:
        return []
    return result_data.get("segments")


def _cached_context_analysis(
    result_data: dict,
    transcript: str,
    task_id: str | None = None,
) -> dict | None:
    cached = result_data.get("context_analysis")
    if not isinstance(cached, dict) or cached.get("analysis_status") not in {
        "success",
        "partial",
    }:
        return None
    if cached.get("schema_version") != ANALYSIS_SCHEMA_VERSION:
        return None
    if cached.get("prompt_version") != CONTEXT_PROMPT_VERSION or not task_id:
        return None
    segments = _analysis_segments(result_data)
    source_metadata = _analysis_source_metadata(result_data, task_id)
    if not _valid_context_analysis_attestation(
        result_data.get("context_analysis_attestation"),
        cached,
        task_id=task_id,
        transcript=transcript,
        segments=segments,
        source_metadata=source_metadata,
    ):
        return None
    return cached


def _assert_global_summary_admin(current_user: User) -> None:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="Forbidden")


def _assert_summary_access(db: Session, current_user: User, summary: DBSummary, action: str) -> None:
    if summary.case_id is None:
        _assert_global_summary_admin(current_user)
        return
    assert_case_access(db, current_user, summary.case_id, action)


def _assert_summary_target(db: Session, current_user: User, case_id: int | None, action: str) -> None:
    if case_id is None:
        _assert_global_summary_admin(current_user)
        return
    assert_case_access(db, current_user, case_id, action)

@router.get("/", response_model=List[SummaryOut])
def get_all_summaries(
    case_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if case_id is not None:
        assert_case_access(db, current_user, case_id, "read")
        return list_summaries(db, case_id=case_id)
    if is_admin(current_user):
        return list_summaries(db)
    allowed_ids = accessible_case_ids(db, current_user) or set()
    if not allowed_ids:
        return []
    return (
        db.query(DBSummary)
        .filter(DBSummary.case_id.in_(allowed_ids))
        .order_by(DBSummary.created_at.desc())
        .all()
    )

@router.get("/{summary_id}", response_model=SummaryOut)
def get_one_summary(summary_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    summary = get_summary(db, summary_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    _assert_summary_access(db, current_user, summary, "read")
    return summary

@router.post("/", response_model=SummaryOut)
def create_one_summary(summary: SummaryCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _assert_summary_target(db, current_user, summary.case_id, "write")
    return create_summary(db, summary)

@router.patch("/{summary_id}", response_model=SummaryOut)
def update_one_summary(summary_id: int, data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    existing = get_summary(db, summary_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Summary not found")
    _assert_summary_access(db, current_user, existing, "write")
    target_case_id = data.get("case_id", existing.case_id)
    _assert_summary_target(db, current_user, target_case_id, "write")
    summary = update_summary(db, summary_id, data)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return summary

@router.delete("/{summary_id}")
def delete_one_summary(summary_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    summary = get_summary(db, summary_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    _assert_summary_access(db, current_user, summary, "delete")
    ok = delete_summary(db, summary_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"detail": "Summary deleted"}

@router.post("/analyze")
def analyze_summary(
    request: SummaryAnalysisRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Re-run evidence-backed analysis from the authorized task transcript.

    The summary body is retained for API compatibility but is never treated as
    evidence because it may already contain model-generated statements.
    """
    import logging

    summary = request.summary
    task_id = request.task_id
    logger = logging.getLogger("summary_analyze")
    logger.info(f"[SUMMARY_ANALYZE] Bắt đầu analyze_summary | summary_len={len(summary) if summary else 0} | task_id={task_id}")
    check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    if not task_id:
        raise HTTPException(
            status_code=400,
            detail="task_id is required for evidence-backed analysis",
        )
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    assert_task_access(db, current_user, task_id, "process")

    result_data = task.get("result") if isinstance(task.get("result"), dict) else {}
    transcript = result_data.get("transcription")
    if not transcript or not str(transcript).strip():
        raise HTTPException(status_code=400, detail="Task has no transcript")

    transcript = str(transcript)
    segments = _analysis_segments(result_data)
    source_metadata = _analysis_source_metadata(result_data, task_id)
    try:
        _generation_inputs_sha256(
            transcript=transcript,
            segments=segments,
            source_metadata=source_metadata,
            model_name=_ANALYSIS_MODEL_NAME,
            user_prompt=_ANALYSIS_USER_PROMPT,
            investigation_scenario=_ANALYSIS_INVESTIGATION_SCENARIO,
        )
    except (TypeError, ValueError) as exc:
        logger.error(
            "[SUMMARY_ANALYZE] Invalid generation inputs | task_id=%s | error=%s",
            task_id,
            exc,
        )
        raise HTTPException(status_code=500, detail="Task analysis inputs are invalid") from exc
    cached = _cached_context_analysis(result_data, transcript, task_id)
    if cached is not None:
        logger.info("[SUMMARY_ANALYZE] Reusing grounded analysis | task_id=%s", task_id)
        public_context = public_context_analysis_payload(cached)
        return {
            "context_analysis": public_context,
            "cache_hit": True,
            "result": {"context_analysis": public_context},
        }

    try:
        with gpu_lease("analysis", f"api:{task_id}"):
            try:
                context_analysis = analyze_conversation_context(
                    transcript,
                    model_name=_ANALYSIS_MODEL_NAME,
                    user_prompt=_ANALYSIS_USER_PROMPT,
                    segments=segments,
                    source_metadata=source_metadata,
                    investigation_scenario=_ANALYSIS_INVESTIGATION_SCENARIO,
                )
            finally:
                if settings.UNLOAD_MODELS_AFTER_TASK:
                    from src.services.summarization.models.llm_manager import (
                        get_llm_manager,
                    )

                    get_llm_manager().unload_last_model()
        logger.info(
            f"[SUMMARY_ANALYZE] Evidence-backed context keys: "
            f"{list(context_analysis.keys()) if isinstance(context_analysis, dict) else 'non-dict'}"
        )
        if not context_analysis or context_analysis.get("analysis_status") not in {
            "success",
            "partial",
        }:
            raise HTTPException(status_code=502, detail="Analysis generation failed")
        context_result_patch = {
            "context_analysis": context_analysis,
            "context_analysis_attestation": _build_context_analysis_attestation(
                context_analysis,
                task_id=task_id,
                transcript=transcript,
                segments=segments,
                source_metadata=source_metadata,
                model_name=_ANALYSIS_MODEL_NAME,
                user_prompt=_ANALYSIS_USER_PROMPT,
                investigation_scenario=_ANALYSIS_INVESTIGATION_SCENARIO,
            ),
        }
        if not update_task(task_id, {"result": context_result_patch}):
            raise HTTPException(status_code=500, detail="Analysis persistence failed")
        public_context = public_context_analysis_payload(context_analysis)
        return {
            "context_analysis": public_context,
            "cache_hit": False,
            "result": {"context_analysis": public_context},
        }
    except GpuLeaseTimeout as exc:
        logger.warning("[SUMMARY_ANALYZE] GPU busy | task_id=%s", task_id)
        raise HTTPException(status_code=503, detail="GPU is busy; retry later") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[SUMMARY_ANALYZE] Evidence-backed analysis failed | error_type=%s",
            type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail="Evidence-backed analysis failed")

@router.post("/visualize")
def visualize_summary(summary: str = Body(..., embed=True), current_user: User = Depends(get_current_user)):
    """
    Legacy summary-only visualization is disabled because it has no audio evidence.
    """
    logger = logging.getLogger("summary_visualize")
    logger.info(f"[SUMMARY_VISUALIZE] Bắt đầu visualize_summary | summary_len={len(summary) if summary else 0}")
    check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    raise HTTPException(
        status_code=410,
        detail="Summary-only visualization is disabled; use task investigation_knowledge",
    )
