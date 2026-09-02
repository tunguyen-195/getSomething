"""
Summarize Task - Celery background task for summarization
Handles: Transcribe → Summarize (OPTIONAL, only if requested)
"""
import hashlib
import logging

from contextlib import contextmanager
from typing import Any, Final, Iterator

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from src.core.config import settings
from src.database.config.database import SessionLocal, engine
from src.database.models.models import (
    AudioBatch,
    AudioBatchItem,
    AudioBatchSummaryJob,
    AudioFile,
    Summary,
    Task,
)
from src.services.audio_batch_contracts import (
    AudioBatchContractError,
    AudioBatchSummaryManifestItem,
    canonical_summary_source_manifest_sha256,
    normalize_audio_batch_id,
)
from src.services.audio_storage import compute_sha256, resolve_audio_path
from src.services.model_runtime.gpu_lease import (
    arm_gpu_quarantine,
    verify_and_clear_gpu_quarantine,
)
from src.services.summarization.contracts import (
    DEFAULT_MULTI_SUMMARY_MAX_WORDS,
    DEFAULT_MULTI_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_MAX_WORDS,
    DEFAULT_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_TYPE,
    SummaryType,
    validate_summary_request_options,
)
from src.services.summarization.investigation_scenarios import (
    DEFAULT_INVESTIGATION_SCENARIO,
    InvestigationScenario,
    require_investigation_scenario,
)
from src.services.summarization.failure_contract import (
    SAFE_SUMMARY_MESSAGES as _SAFE_TASK_MESSAGES,
    SafeSummaryTaskError,
    build_safe_summary_failure_update as _safe_failure_update,
)
from src.worker.worker import celery_app
from src.services.task_service import (
    get_task,
    released_investigation_run_identity,
    update_task,
)

logger = logging.getLogger(__name__)


class UnsafeGpuHandoff(RuntimeError):
    """Raised when llama-server cannot prove it released GPU memory."""


def _result_error_code(result: object, fallback: str) -> str:
    if not isinstance(result, dict):
        return fallback
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    code = error.get("code")
    return code if isinstance(code, str) and code in _SAFE_TASK_MESSAGES else fallback


def _current_transcript_segments(task_result: dict) -> list[dict]:
    """Keep summary grounding on the latest diarized segment projection."""

    segments = task_result.get("segments")
    if isinstance(segments, list) and all(isinstance(item, dict) for item in segments):
        return segments

    transcription_result = task_result.get("transcription_result")
    if isinstance(transcription_result, dict):
        segments = transcription_result.get("segments")
        if isinstance(segments, list) and all(
            isinstance(item, dict) for item in segments
        ):
            return segments
    return []


def _verify_llama_server_sleeping() -> bool:
    from src.services.summarization.models.llm_manager import get_llm_manager

    return bool(get_llm_manager().unload_last_model())


@contextmanager
def _llama_server_handoff(owner: str, summary_stage: str) -> Iterator[None]:
    """Keep non-LLM GPU stages quarantined until server sleep is verified."""

    if str(settings.LOCAL_LLM_PROVIDER).strip().casefold() != "llama_cpp_server":
        yield
        return
    if not settings.GPU_LEASE_ENABLED:
        raise UnsafeGpuHandoff(
            "llama-server requires GPU_LEASE_ENABLED=true for a safe GPU handoff"
        )

    quarantine = arm_gpu_quarantine(
        stage=summary_stage,
        owner=owner,
        reason="llama-server GPU handoff is pending sleep verification",
        allowed_stages=(summary_stage,),
    )
    try:
        yield
    finally:
        try:
            cleared = verify_and_clear_gpu_quarantine(
                _verify_llama_server_sleeping,
                verified_by=f"{owner}:{summary_stage}:sleep-check",
                expected_quarantine_id=quarantine.quarantine_id,
            )
        except Exception as exc:
            raise UnsafeGpuHandoff(
                "llama-server sleep verification failed; GPU quarantine remains "
                "active. Confirm /props reports is_sleeping=true and run the "
                "quarantine recovery verifier before starting audio GPU work."
            ) from exc
        if not cleared:
            raise UnsafeGpuHandoff(
                "llama-server did not enter idle sleep; GPU quarantine remains "
                "active. Confirm /props reports is_sleeping=true and run the "
                "quarantine recovery verifier before starting audio GPU work."
            )


@celery_app.task(bind=True, name="tasks.summarize_transcript")
def summarize_transcript_task(
    self,
    task_id: str,
    model_name: str = None,
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE,
    include_context: bool = True,
    user_prompt: str = None,
    min_length: int = DEFAULT_SUMMARY_MIN_WORDS,
    max_length: int = DEFAULT_SUMMARY_MAX_WORDS,
    length_mode: str = "auto",
    investigation_scenario: InvestigationScenario = DEFAULT_INVESTIGATION_SCENARIO,
    **unexpected_options: object,
):
    """
    Celery task for transcript summarization

    Args:
        task_id: Task ID (must have transcript)
        model_name: LLM model to use
        summary_type: Type of summary
        include_context: Include context analysis
        user_prompt: Optional user prompt

    Returns:
        Result dict or error
    """
    options = validate_summary_request_options(
        summary_type=summary_type,
        min_length=min_length,
        max_length=max_length,
        length_mode=length_mode,
        user_prompt=user_prompt,
    )
    summary_type = options.summary_type
    min_length = options.min_length
    max_length = options.max_length
    length_mode = options.length_mode
    user_prompt = options.user_prompt
    investigation_scenario = require_investigation_scenario(investigation_scenario)

    logger.info(
        f"[CELERY_SUMMARIZE] Task started | task_id={task_id} | "
        f"celery_id={self.request.id} | model={model_name}"
    )

    try:
        if unexpected_options:
            logger.error(
                "[CELERY_SUMMARIZE] Request contract mismatch | task_id=%s | fields=%s",
                task_id,
                sorted(unexpected_options),
            )
            raise SafeSummaryTaskError("SUMMARY_REQUEST_CONTRACT_MISMATCH")

        # Get task to extract transcript
        task = get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Get transcript from task result (standardized to "transcription")
        transcript = None
        transcript_segments = []
        grounded_context = None
        source_metadata = {"task_id": task_id}
        if task.get("result") and isinstance(task["result"], dict):
            # Transcript is stored in result["transcription"] (TaskResult schema)
            task_result = task["result"]
            transcript = task_result.get("transcription")
            transcript_segments = _current_transcript_segments(task_result)
            grounded_context = task_result.get("context_analysis")
            source_metadata.update(
                audio_id=task_result.get("audio_id"),
                audio_sha256=task_result.get("audio_sha256"),
                audio_integrity_status=task_result.get("audio_integrity_status"),
                case_id=task.get("case_id") or task_result.get("case_id"),
                file_name=task.get("filename") or task_result.get("filename"),
                num_speakers=task_result.get("num_speakers"),
                has_diarization=task_result.get("has_diarization"),
                degraded=task_result.get("degraded"),
                diarization_status=task_result.get("diarization_status"),
                diarization_method_used=task_result.get("diarization_method_used"),
                diarization_fallback_reason=task_result.get(
                    "diarization_fallback_reason"
                ),
                diarization_degraded_reasons=task_result.get(
                    "diarization_degraded_reasons"
                ),
                speaker_provenance=task_result.get("speaker_provenance"),
                current_transcript_segments=transcript_segments,
            )

        if not transcript or not transcript.strip():
            logger.warning(
                f"[CELERY_SUMMARIZE] No transcription found for task {task_id}. Task result keys: {list(task.get('result', {}).keys()) if task.get('result') else 'No result'}"
            )
            raise ValueError(
                f"Task {task_id} has no transcription. Run transcription first."
            )

        # Import here to avoid circular dependencies
        from src.services.summarization.summary_service_v2 import (
            summarize_transcript_v2,
        )

        if not update_task(task_id, {"status": "summarizing"}):
            raise SafeSummaryTaskError("SUMMARY_PERSISTENCE_FAILED")

        # Execute summarization with timeout protection
        logger.info(
            f"[CELERY_SUMMARIZE] Starting summarization | transcript_length={len(transcript)}"
        )

        try:
            with _llama_server_handoff(f"task:{task_id}", "summary"):
                result = summarize_transcript_v2(
                    transcript=transcript,
                    model_name=model_name,
                    summary_type=summary_type,
                    include_context=include_context,
                    user_prompt=user_prompt,
                    min_length=min_length,
                    max_length=max_length,
                    length_mode=length_mode,
                    transcript_segments=transcript_segments,
                    source_metadata=source_metadata,
                    grounded_context=(
                        grounded_context if isinstance(grounded_context, dict) else None
                    ),
                    allow_evidence_preview=summary_type == "investigation",
                    investigation_scenario=investigation_scenario,
                )
        except UnsafeGpuHandoff:
            raise SafeSummaryTaskError("SUMMARY_UNSAFE_HANDOFF") from None
        except SafeSummaryTaskError:
            raise
        except Exception as summary_error:
            logger.error(
                "[CELERY_SUMMARIZE] Summarization failed | task_id=%s | error_type=%s",
                task_id,
                type(summary_error).__name__,
            )
            raise SafeSummaryTaskError("SUMMARY_GENERATION_FAILED") from None

        if not result.get("available"):
            raise SafeSummaryTaskError(
                _result_error_code(result, "SUMMARY_UNAVAILABLE"),
                result=result,
            )

        summary_state = result.get("summary_state")
        summary_text = result.get("summary")
        if not isinstance(summary_text, str):
            summary_text = ""
        if summary_state == "grounded_transcript_only":
            raise SafeSummaryTaskError("SUMMARY_PREVIEW_ONLY")
        if not summary_text.strip():
            raise SafeSummaryTaskError("SUMMARY_EMPTY")

        # Summary owns only this partial result patch. The task service merges it
        # atomically so independently published visualization bytes stay untouched.
        summary_result_patch = {
            "summary": summary_text or None,
            "summary_model": result.get("model"),
            "summary_type": summary_type,
            "summary_state": summary_state,
            "summary_authority": result.get("summary_authority"),
            "summary_notice": result.get("summary_notice"),
            "summary_error": result.get("error"),
            "summary_preview": result.get("summary_preview"),
            "summary_runtime": result.get("runtime") or {},
        }
        generated_context = result.get("context")
        if isinstance(generated_context, dict):
            summary_result_patch["context_analysis"] = generated_context

        # Update task with summary
        persisted = update_task(
            task_id,
            {
                "status": "summarized",
                "result": summary_result_patch,
                "summary": summary_text or None,
                "model_name": result.get("model"),
                "error": None,
            },
        )
        if not persisted:
            raise SafeSummaryTaskError("SUMMARY_PERSISTENCE_FAILED")

        logger.info(f"[CELERY_SUMMARIZE] Task complete | task_id={task_id}")

        return {"status": "success", "task_id": task_id, "result": result}

    except SafeSummaryTaskError as exc:
        logger.error(
            "[CELERY_SUMMARIZE] Task failed | task_id=%s | code=%s",
            task_id,
            exc.code,
        )
        persisted = update_task(
            task_id,
            _safe_failure_update(exc),
        )
        if not persisted and exc.code != "SUMMARY_PERSISTENCE_FAILED":
            raise SafeSummaryTaskError("SUMMARY_PERSISTENCE_FAILED") from None
        raise
    except Exception as exc:
        logger.error(
            "[CELERY_SUMMARIZE] Task failed | task_id=%s | error_type=%s",
            task_id,
            type(exc).__name__,
        )
        persisted = update_task(
            task_id,
            {
                "status": "failed",
                "error": _SAFE_TASK_MESSAGES["SUMMARY_GENERATION_FAILED"],
            },
        )
        if not persisted:
            raise SafeSummaryTaskError("SUMMARY_PERSISTENCE_FAILED") from None
        raise SafeSummaryTaskError("SUMMARY_GENERATION_FAILED") from None


@celery_app.task(bind=True, name="tasks.summarize_multi")
def summarize_multi_task(
    self,
    task_ids: list,
    model_name: str = None,
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE,
    case_id: str = None,
    min_length: int = DEFAULT_MULTI_SUMMARY_MIN_WORDS,
    max_length: int = DEFAULT_MULTI_SUMMARY_MAX_WORDS,
    length_mode: str = "auto",
    user_prompt: str = None,
):
    """
    Celery task for multi-transcript summarization

    Args:
        task_ids: List of task IDs
        model_name: LLM model to use
        summary_type: Type of summary
        case_id: Case ID

    Returns:
        Result dict or error
    """
    options = validate_summary_request_options(
        summary_type=summary_type,
        min_length=min_length,
        max_length=max_length,
        length_mode=length_mode,
        user_prompt=user_prompt,
    )
    summary_type = options.summary_type
    min_length = options.min_length
    max_length = options.max_length
    length_mode = options.length_mode
    user_prompt = options.user_prompt

    logger.info(
        f"[CELERY_MULTI_SUMMARY] Task started | count={len(task_ids)} | "
        f"celery_id={self.request.id} | case={case_id}"
    )

    try:
        # Collect transcripts from all tasks
        transcripts = []

        for tid in task_ids:
            task = get_task(tid)
            if task and task.get("result"):
                transcript = task["result"].get("transcription")
                if transcript:
                    transcripts.append(transcript)

        if not transcripts:
            raise ValueError("No transcripts found in provided tasks")

        # Import here
        from src.services.summarization.summary_service_v2 import (
            summarize_multi_transcripts_v2,
        )

        # Execute multi-summarization
        owner = f"case:{case_id or 'synchronous'}"
        with _llama_server_handoff(owner, "multi_summary"):
            result = summarize_multi_transcripts_v2(
                transcripts=transcripts,
                model_name=model_name,
                summary_type=summary_type,
                case_id=case_id,
                min_length=min_length,
                max_length=max_length,
                length_mode=length_mode,
                user_prompt=user_prompt,
            )

        if not result.get("available"):
            raise SafeSummaryTaskError(
                _result_error_code(result, "SUMMARY_UNAVAILABLE"),
                result=result,
            )

        logger.info(f"[CELERY_MULTI_SUMMARY] Task complete | case={case_id}")

        return {"status": "success", "case_id": case_id, "result": result}

    except SafeSummaryTaskError as exc:
        logger.error(
            "[CELERY_MULTI_SUMMARY] Task failed | case=%s | code=%s",
            case_id,
            exc.code,
        )
        raise
    except Exception as exc:
        logger.error(
            "[CELERY_MULTI_SUMMARY] Task failed | case=%s | error_type=%s",
            case_id,
            type(exc).__name__,
        )
        raise SafeSummaryTaskError("SUMMARY_GENERATION_FAILED") from None


_SAFE_BATCH_SUMMARY_MESSAGES: Final[dict[str, str]] = {
    **_SAFE_TASK_MESSAGES,
    "SUMMARY_JOB_NOT_FOUND": "The merged-summary job is unavailable.",
    "SUMMARY_JOB_ALREADY_DISPATCHED": "The merged-summary job is already running.",
    "SUMMARY_JOB_SCOPE_MISMATCH": "The merged-summary job failed its ownership check.",
    "SUMMARY_MANIFEST_INVALID": "The merged-summary source manifest is invalid.",
    "SUMMARY_MANIFEST_HASH_MISMATCH": "The merged-summary source manifest failed integrity verification.",
    "SUMMARY_SOURCE_STATE_INVALID": "A selected transcript is not ready for summary.",
    "SUMMARY_SOURCE_SCOPE_MISMATCH": "A selected transcript failed its ownership check.",
    "SUMMARY_SOURCE_AUDIO_MISMATCH": "A selected audio source failed integrity verification.",
    "SUMMARY_SOURCE_TRANSCRIPT_MISMATCH": "A selected transcript failed integrity verification.",
    "SUMMARY_REQUEST_CONTRACT_MISMATCH": _SAFE_TASK_MESSAGES[
        "SUMMARY_REQUEST_CONTRACT_MISMATCH"
    ],
    "SUMMARY_GENERATION_FAILED": _SAFE_TASK_MESSAGES["SUMMARY_GENERATION_FAILED"],
    "SUMMARY_PERSISTENCE_FAILED": _SAFE_TASK_MESSAGES["SUMMARY_PERSISTENCE_FAILED"],
    "SUMMARY_RESULT_INVALID": _SAFE_TASK_MESSAGES["SUMMARY_RESULT_INVALID"],
    "SUMMARY_UNAVAILABLE": _SAFE_TASK_MESSAGES["SUMMARY_UNAVAILABLE"],
    "SUMMARY_UNSAFE_HANDOFF": _SAFE_TASK_MESSAGES["SUMMARY_UNSAFE_HANDOFF"],
}


class SafeAudioBatchSummaryJobError(RuntimeError):
    """Fail-closed summary-job error that never reflects source or prompt bytes."""

    def __init__(self, code: str, *, user_prompt_applied: bool = False) -> None:
        self.code = (
            code
            if code in _SAFE_BATCH_SUMMARY_MESSAGES
            else "SUMMARY_GENERATION_FAILED"
        )
        self.user_prompt_applied = bool(user_prompt_applied)
        super().__init__(_SAFE_BATCH_SUMMARY_MESSAGES[self.code])


def _summary_job_request_id(task: Any, summary_job_id: str) -> str:
    request = getattr(task, "request", None)
    value = getattr(request, "id", None)
    if isinstance(value, str) and value.strip():
        return value
    return f"eager-audio-batch-summary:{summary_job_id}"


def _summary_job_payload(job: AudioBatchSummaryJob) -> dict[str, object]:
    return {
        "status": job.status,
        "summary_job_id": job.id,
        "batch_id": job.batch_id,
        "summary_id": job.summary_id,
        "source_manifest_sha256": job.source_manifest_sha256,
        "user_prompt_applied": bool(job.user_prompt_applied),
        "error_code": job.error_code,
    }


def _claim_summary_job(
    *,
    summary_job_id: str,
    celery_task_id: str,
) -> tuple[str, dict[str, object]]:
    with SessionLocal() as db:
        try:
            job = (
                db.query(AudioBatchSummaryJob)
                .filter(AudioBatchSummaryJob.id == summary_job_id)
                .with_for_update()
                .one_or_none()
            )
            if job is None:
                return "missing", {}
            if job.status in {"succeeded", "failed", "cancelled"}:
                payload = _summary_job_payload(job)
                db.commit()
                return "terminal", payload
            if job.status == "cancel_requested":
                job.status = "cancelled"
                job.error_code = None
                job.user_prompt_applied = False
                payload = _summary_job_payload(job)
                db.commit()
                return "cancelled", payload
            if job.celery_task_id and job.celery_task_id != celery_task_id:
                payload = _summary_job_payload(job)
                db.commit()
                return "already_dispatched", payload
            job.celery_task_id = celery_task_id
            job.status = "processing"
            job.error_code = None
            job.user_prompt_applied = False
            payload = _summary_job_payload(job)
            db.commit()
            return "claimed", payload
        except Exception:
            db.rollback()
            raise


def _validated_summary_job_options(
    raw_options: object,
    *,
    user_prompt: object,
) -> tuple[object, str | None]:
    if not isinstance(raw_options, dict):
        raise SafeAudioBatchSummaryJobError("SUMMARY_REQUEST_CONTRACT_MISMATCH")
    allowed_keys = {
        "model_name",
        "summary_type",
        "min_length",
        "max_length",
        "length_mode",
    }
    if set(raw_options) - allowed_keys:
        raise SafeAudioBatchSummaryJobError("SUMMARY_REQUEST_CONTRACT_MISMATCH")
    model_name = raw_options.get("model_name")
    if model_name is not None and (
        type(model_name) is not str
        or not model_name.strip()
        or model_name != model_name.strip()
        or len(model_name) > 255
    ):
        raise SafeAudioBatchSummaryJobError("SUMMARY_REQUEST_CONTRACT_MISMATCH")
    try:
        options = validate_summary_request_options(
            summary_type=raw_options.get("summary_type", DEFAULT_SUMMARY_TYPE),
            min_length=raw_options.get("min_length", DEFAULT_MULTI_SUMMARY_MIN_WORDS),
            max_length=raw_options.get("max_length", DEFAULT_MULTI_SUMMARY_MAX_WORDS),
            length_mode=raw_options.get("length_mode", "auto"),
            user_prompt=user_prompt,
        )
    except Exception as exc:
        raise SafeAudioBatchSummaryJobError(
            "SUMMARY_REQUEST_CONTRACT_MISMATCH"
        ) from exc
    return options, model_name


def _expected_source_revision_id(task_result: dict[str, object], digest: str) -> str:
    identity = released_investigation_run_identity(
        task_result.get("released_investigation_run")
    )
    if identity is not None:
        return identity[1]
    return f"transcript-sha256:{digest}"


def _load_verified_summary_sources(
    db: Any,
    job: AudioBatchSummaryJob,
) -> tuple[list[str], list[dict[str, object]]]:
    raw_manifest = job.source_manifest
    if not isinstance(raw_manifest, list):
        raise SafeAudioBatchSummaryJobError("SUMMARY_MANIFEST_INVALID")
    try:
        manifest = [
            AudioBatchSummaryManifestItem.model_validate(item) for item in raw_manifest
        ]
    except (AudioBatchContractError, ValidationError, TypeError, ValueError) as exc:
        raise SafeAudioBatchSummaryJobError("SUMMARY_MANIFEST_INVALID") from exc
    if (
        not manifest
        or len(manifest) != job.selected_count
        or [item.position for item in manifest] != list(range(len(manifest)))
        or len({item.batch_item_id for item in manifest}) != len(manifest)
        or len({item.task_id for item in manifest}) != len(manifest)
        or len({item.audio_id for item in manifest}) != len(manifest)
    ):
        raise SafeAudioBatchSummaryJobError("SUMMARY_MANIFEST_INVALID")
    try:
        manifest_sha256 = canonical_summary_source_manifest_sha256(manifest)
    except (AudioBatchContractError, ValidationError, TypeError, ValueError) as exc:
        raise SafeAudioBatchSummaryJobError("SUMMARY_MANIFEST_INVALID") from exc
    if manifest_sha256 != job.source_manifest_sha256:
        raise SafeAudioBatchSummaryJobError("SUMMARY_MANIFEST_HASH_MISMATCH")

    batch = db.query(AudioBatch).filter(AudioBatch.id == job.batch_id).one_or_none()
    if batch is None or batch.case_id != job.case_id or batch.user_id != job.user_id:
        raise SafeAudioBatchSummaryJobError("SUMMARY_JOB_SCOPE_MISMATCH")

    item_ids = [entry.batch_item_id for entry in manifest]
    task_ids = [entry.task_id for entry in manifest]
    audio_ids = [entry.audio_id for entry in manifest]
    items = {
        item.id: item
        for item in db.query(AudioBatchItem)
        .filter(AudioBatchItem.id.in_(item_ids))
        .all()
    }
    tasks = {
        task.id: task for task in db.query(Task).filter(Task.id.in_(task_ids)).all()
    }
    audio_files = {
        audio.id: audio
        for audio in db.query(AudioFile).filter(AudioFile.id.in_(audio_ids)).all()
    }
    if (
        len(items) != len(manifest)
        or len(tasks) != len(manifest)
        or len(audio_files) != len(manifest)
    ):
        raise SafeAudioBatchSummaryJobError("SUMMARY_SOURCE_SCOPE_MISMATCH")

    transcripts: list[str] = []
    provenance: list[dict[str, object]] = []
    for entry in manifest:
        item = items[entry.batch_item_id]
        task = tasks[entry.task_id]
        audio = audio_files[entry.audio_id]
        if (
            item.batch_id != job.batch_id
            or item.task_id != entry.task_id
            or item.audio_id != entry.audio_id
            or item.original_filename != entry.filename
            or task.case_id != job.case_id
            or task.user_id != job.user_id
            or audio.case_id != job.case_id
            or audio.uploaded_by != job.user_id
            or audio.task_id != entry.task_id
        ):
            raise SafeAudioBatchSummaryJobError("SUMMARY_SOURCE_SCOPE_MISMATCH")
        if item.status != "transcribed":
            raise SafeAudioBatchSummaryJobError("SUMMARY_SOURCE_STATE_INVALID")

        task_result = task.result if isinstance(task.result, dict) else {}
        transcript = task_result.get("transcription")
        if not isinstance(transcript, str) or not transcript.strip():
            raise SafeAudioBatchSummaryJobError("SUMMARY_SOURCE_STATE_INVALID")
        transcript_sha256 = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
        if (
            transcript_sha256 != entry.transcript_sha256
            or _expected_source_revision_id(task_result, transcript_sha256)
            != entry.source_revision_id
        ):
            raise SafeAudioBatchSummaryJobError("SUMMARY_SOURCE_TRANSCRIPT_MISMATCH")

        stored_audio_sha256 = (audio.extra_metadata or {}).get("sha256")
        result_audio_sha256 = task_result.get("audio_sha256")
        if (
            stored_audio_sha256 != item.verified_audio_sha256
            or result_audio_sha256 != item.verified_audio_sha256
        ):
            raise SafeAudioBatchSummaryJobError("SUMMARY_SOURCE_AUDIO_MISMATCH")
        try:
            audio_path = resolve_audio_path(audio.file_path)
            if not audio_path.is_file():
                raise OSError("source unavailable")
            actual_audio_sha256 = compute_sha256(audio_path)
        except (HTTPException, OSError, TypeError, ValueError) as exc:
            raise SafeAudioBatchSummaryJobError(
                "SUMMARY_SOURCE_AUDIO_MISMATCH"
            ) from exc
        if actual_audio_sha256 != item.verified_audio_sha256:
            raise SafeAudioBatchSummaryJobError("SUMMARY_SOURCE_AUDIO_MISMATCH")

        transcripts.append(transcript)
        provenance.append(
            {
                "position": entry.position,
                "batch_item_id": entry.batch_item_id,
                "task_id": entry.task_id,
                "audio_id": entry.audio_id,
                "filename": entry.filename,
                "audio_sha256": item.verified_audio_sha256,
                "transcript_sha256": entry.transcript_sha256,
                "source_revision_id": entry.source_revision_id,
            }
        )
    return transcripts, provenance


def _fail_summary_job(
    *,
    summary_job_id: str,
    celery_task_id: str,
    code: str,
    user_prompt_applied: bool,
) -> None:
    safe_code = (
        code if code in _SAFE_BATCH_SUMMARY_MESSAGES else "SUMMARY_GENERATION_FAILED"
    )
    with SessionLocal() as db:
        try:
            job = (
                db.query(AudioBatchSummaryJob)
                .filter(AudioBatchSummaryJob.id == summary_job_id)
                .with_for_update()
                .one_or_none()
            )
            if job is None or job.status in {"succeeded", "cancelled"}:
                db.commit()
                return
            if job.celery_task_id and job.celery_task_id != celery_task_id:
                db.commit()
                return
            if job.status == "cancel_requested":
                job.status = "cancelled"
                job.summary_id = None
                job.error_code = None
                job.user_prompt_applied = False
                db.commit()
                return
            job.status = "failed"
            job.summary_id = None
            job.error_code = safe_code
            job.user_prompt_applied = bool(user_prompt_applied)
            db.commit()
        except Exception:
            db.rollback()
            raise


def _summary_job_advisory_key(summary_job_id: str) -> int:
    digest = hashlib.sha256(
        f"audio-batch-summary-job\0{summary_job_id}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@contextmanager
def _summary_job_execution_lock(summary_job_id: str) -> Iterator[bool]:
    """Serialize one job without holding a row lock or DB transaction during LLM."""

    lock_key = _summary_job_advisory_key(summary_job_id)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            ).scalar()
        )
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )


def _read_summary_job_payload(summary_job_id: str) -> dict[str, object]:
    with SessionLocal() as db:
        job = (
            db.query(AudioBatchSummaryJob)
            .filter(AudioBatchSummaryJob.id == summary_job_id)
            .one_or_none()
        )
        if job is None:
            raise SafeAudioBatchSummaryJobError("SUMMARY_JOB_NOT_FOUND")
        return _summary_job_payload(job)


def _prepare_summary_job_execution(
    *,
    summary_job_id: str,
    celery_task_id: str,
    user_prompt: object,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    """Read and verify a durable manifest in a short transaction."""

    with SessionLocal() as db:
        try:
            job = (
                db.query(AudioBatchSummaryJob)
                .filter(AudioBatchSummaryJob.id == summary_job_id)
                .with_for_update()
                .one_or_none()
            )
            if job is None:
                raise SafeAudioBatchSummaryJobError("SUMMARY_JOB_NOT_FOUND")
            if job.status in {"succeeded", "failed", "cancelled"}:
                payload = _summary_job_payload(job)
                db.commit()
                return payload, None
            if job.status == "cancel_requested":
                job.status = "cancelled"
                job.error_code = None
                job.user_prompt_applied = False
                payload = _summary_job_payload(job)
                db.commit()
                return payload, None
            if job.celery_task_id != celery_task_id:
                payload = _summary_job_payload(job)
                db.commit()
                return payload, None

            options, model_name = _validated_summary_job_options(
                job.summary_options,
                user_prompt=user_prompt,
            )
            transcripts, provenance = _load_verified_summary_sources(db, job)
            db.commit()
            return None, {
                "options": options,
                "model_name": model_name,
                "transcripts": transcripts,
                "provenance": provenance,
                "case_id": job.case_id,
            }
        except Exception:
            db.rollback()
            raise


def _persist_summary_job_success(
    *,
    summary_job_id: str,
    celery_task_id: str,
    result: object,
    expected_transcript_count: int,
    expected_provenance: list[dict[str, object]],
    user_prompt_applied: bool,
) -> dict[str, object]:
    if not isinstance(result, dict) or not result.get("available"):
        code = _result_error_code(result, "SUMMARY_UNAVAILABLE")
        raise SafeAudioBatchSummaryJobError(code)
    summary_text = result.get("summary")
    runtime = result.get("runtime")
    if (
        not isinstance(summary_text, str)
        or not summary_text.strip()
        or result.get("num_transcripts") != expected_transcript_count
        or not isinstance(runtime, dict)
        or runtime.get("user_prompt_applied") is not user_prompt_applied
        or type(runtime.get("llm_call_count")) is not int
        or runtime["llm_call_count"] < 1
    ):
        raise SafeAudioBatchSummaryJobError("SUMMARY_RESULT_INVALID")

    with SessionLocal() as db:
        try:
            job = (
                db.query(AudioBatchSummaryJob)
                .filter(AudioBatchSummaryJob.id == summary_job_id)
                .with_for_update()
                .one_or_none()
            )
            if job is None:
                raise SafeAudioBatchSummaryJobError("SUMMARY_JOB_NOT_FOUND")
            if job.status == "cancel_requested":
                job.status = "cancelled"
                job.summary_id = None
                job.error_code = None
                job.user_prompt_applied = False
                payload = _summary_job_payload(job)
                db.commit()
                return payload
            if job.status in {"succeeded", "failed", "cancelled"}:
                payload = _summary_job_payload(job)
                db.commit()
                return payload
            if job.celery_task_id != celery_task_id:
                payload = _summary_job_payload(job)
                db.commit()
                return payload

            # Sources may be edited while the model is running. Revalidate before
            # binding generated text to the immutable provenance snapshot.
            _transcripts, current_provenance = _load_verified_summary_sources(db, job)
            if current_provenance != expected_provenance:
                raise SafeAudioBatchSummaryJobError(
                    "SUMMARY_SOURCE_TRANSCRIPT_MISMATCH"
                )
            summary = Summary(
                type="multi",
                case_id=job.case_id,
                files=current_provenance,
                content=summary_text.strip(),
            )
            db.add(summary)
            db.flush()
            job.summary_id = summary.id
            job.status = "succeeded"
            job.error_code = None
            job.user_prompt_applied = user_prompt_applied
            payload = _summary_job_payload(job)
            db.commit()
            return payload
        except Exception:
            db.rollback()
            raise


def _run_summary_job_execution(
    *,
    summary_job_id: str,
    celery_task_id: str,
    user_prompt: object,
) -> dict[str, object]:
    terminal, execution = _prepare_summary_job_execution(
        summary_job_id=summary_job_id,
        celery_task_id=celery_task_id,
        user_prompt=user_prompt,
    )
    if terminal is not None:
        return terminal
    if execution is None:
        raise SafeAudioBatchSummaryJobError("SUMMARY_RESULT_INVALID")

    options = execution["options"]
    transcripts = execution["transcripts"]
    provenance = execution["provenance"]
    if not isinstance(transcripts, list) or not isinstance(provenance, list):
        raise SafeAudioBatchSummaryJobError("SUMMARY_RESULT_INVALID")

    from src.services.summarization.summary_service_v2 import (
        summarize_multi_transcripts_v2,
    )

    try:
        with _llama_server_handoff(f"summary_job:{summary_job_id}", "multi_summary"):
            result = summarize_multi_transcripts_v2(
                transcripts=transcripts,
                model_name=execution["model_name"],
                summary_type=options.summary_type,
                case_id=str(execution["case_id"]),
                min_length=options.min_length,
                max_length=options.max_length,
                length_mode=options.length_mode,
                user_prompt=options.user_prompt,
                gpu_owner=f"summary_job:{summary_job_id}",
            )
    except UnsafeGpuHandoff as exc:
        raise SafeAudioBatchSummaryJobError(
            "SUMMARY_UNSAFE_HANDOFF",
            user_prompt_applied=options.user_prompt is not None,
        ) from exc
    except SafeAudioBatchSummaryJobError:
        raise
    except Exception as exc:
        raise SafeAudioBatchSummaryJobError(
            "SUMMARY_GENERATION_FAILED",
            user_prompt_applied=options.user_prompt is not None,
        ) from exc

    try:
        return _persist_summary_job_success(
            summary_job_id=summary_job_id,
            celery_task_id=celery_task_id,
            result=result,
            expected_transcript_count=len(transcripts),
            expected_provenance=provenance,
            user_prompt_applied=options.user_prompt is not None,
        )
    except SafeAudioBatchSummaryJobError as exc:
        raise SafeAudioBatchSummaryJobError(
            exc.code,
            user_prompt_applied=options.user_prompt is not None,
        ) from exc


def _execute_summary_job(
    *,
    summary_job_id: str,
    celery_task_id: str,
    user_prompt: object,
) -> dict[str, object]:
    with _summary_job_execution_lock(summary_job_id) as acquired:
        if not acquired:
            return _read_summary_job_payload(summary_job_id)
        try:
            return _run_summary_job_execution(
                summary_job_id=summary_job_id,
                celery_task_id=celery_task_id,
                user_prompt=user_prompt,
            )
        except SafeAudioBatchSummaryJobError as exc:
            # Persist while the advisory lock is still held so a duplicate
            # delivery can never slip into model execution between unlock/fail.
            _fail_summary_job(
                summary_job_id=summary_job_id,
                celery_task_id=celery_task_id,
                code=exc.code,
                user_prompt_applied=exc.user_prompt_applied,
            )
            raise


@celery_app.task(bind=True, name="tasks.summarize_audio_batch_job")
def summarize_audio_batch_job_task(
    self: Any,
    summary_job_id: str,
    user_prompt: str | None = None,
) -> dict[str, object]:
    """Run one hash-bound merged summary without accepting raw task IDs."""

    try:
        normalized_job_id = normalize_audio_batch_id(summary_job_id)
    except AudioBatchContractError as exc:
        raise SafeAudioBatchSummaryJobError("SUMMARY_JOB_NOT_FOUND") from exc
    celery_task_id = _summary_job_request_id(self, normalized_job_id)
    logger.info(
        "[CELERY_AUDIO_BATCH_SUMMARY] Started | summary_job_id=%s | celery_id=%s | user_prompt_present=%s",
        normalized_job_id,
        celery_task_id,
        bool(isinstance(user_prompt, str) and user_prompt.strip()),
    )

    try:
        disposition, payload = _claim_summary_job(
            summary_job_id=normalized_job_id,
            celery_task_id=celery_task_id,
        )
        if disposition == "missing":
            raise SafeAudioBatchSummaryJobError("SUMMARY_JOB_NOT_FOUND")
        if disposition != "claimed":
            return payload
        result = _execute_summary_job(
            summary_job_id=normalized_job_id,
            celery_task_id=celery_task_id,
            user_prompt=user_prompt,
        )
        logger.info(
            "[CELERY_AUDIO_BATCH_SUMMARY] Finished | summary_job_id=%s | status=%s | user_prompt_applied=%s",
            normalized_job_id,
            result["status"],
            result["user_prompt_applied"],
        )
        return result
    except SafeAudioBatchSummaryJobError as exc:
        logger.error(
            "[CELERY_AUDIO_BATCH_SUMMARY] Failed | summary_job_id=%s | code=%s",
            normalized_job_id,
            exc.code,
        )
        try:
            _fail_summary_job(
                summary_job_id=normalized_job_id,
                celery_task_id=celery_task_id,
                code=exc.code,
                user_prompt_applied=exc.user_prompt_applied,
            )
        except Exception as persistence_error:
            logger.error(
                "[CELERY_AUDIO_BATCH_SUMMARY] Failure persistence failed | summary_job_id=%s | error_type=%s",
                normalized_job_id,
                type(persistence_error).__name__,
            )
            raise SafeAudioBatchSummaryJobError("SUMMARY_PERSISTENCE_FAILED") from None
        raise
    except Exception as exc:
        logger.error(
            "[CELERY_AUDIO_BATCH_SUMMARY] Failed | summary_job_id=%s | error_type=%s",
            normalized_job_id,
            type(exc).__name__,
        )
        try:
            _fail_summary_job(
                summary_job_id=normalized_job_id,
                celery_task_id=celery_task_id,
                code="SUMMARY_GENERATION_FAILED",
                user_prompt_applied=False,
            )
        except Exception:
            raise SafeAudioBatchSummaryJobError("SUMMARY_PERSISTENCE_FAILED") from None
        raise SafeAudioBatchSummaryJobError("SUMMARY_GENERATION_FAILED") from None
