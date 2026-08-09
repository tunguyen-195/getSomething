import copy
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, NoReturn, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.database.config.database import SessionLocal
from src.database.models.models import (
    AudioFile,
    Case,
    CaseParticipant,
    CasePriority,
    CaseStatus,
    ParticipantRole,
    Task as DBTask,
    User,
)
from src.services.investigation.contracts import sha256_canonical_json
from src.services.investigation.narrative_attestation import (
    released_narrative_metadata,
    render_released_narrative_text,
)

logger = logging.getLogger(__name__)

CANONICAL_STATUSES = {
    "uploaded",
    "transcribing",
    "transcribed",
    "summarizing",
    "summarized",
    "visualizing",
    "visualized",
    "failed",
    "needs_review",
}

LEGACY_STATUS_ALIASES = {
    "pending": "uploaded",
    "processing": "transcribing",
}

RESULT_FIELD_ALIASES = {
    "transcript": "transcription",
    "context": "context_analysis",
    "visualization": "visualization_data",
}

RESULT_FIELDS = {
    "transcription",
    "summary",
    "segments",
    "duration",
    "context_analysis",
    "visualization_data",
    "has_visualization",
    "audio_id",
    "download_url",
    "language",
    "confidence",
    "processing_time",
    "formatted_transcript",
    "transcript_file",
    "has_diarization",
    "num_speakers",
    "speed_factor",
    "diarization_method",
    "transcription_time",
    "diarization_time",
    "fast_mode",
    "caption",
    "model_name",
    "summary_model",
    "summary_type",
    "requested_engine",
    "engine_used",
    "fallback_reason",
    "audio_sha256",
    "audio_integrity_status",
    "summary_state",
}

SUMMARY_STATE_SCHEMA = "summary-attempt-state-v1"
SUMMARY_STATE_FIELDS = frozenset(
    {
        "schema_version",
        "attempt_id",
        "request_fingerprint",
        "source_revision_id",
        "status",
        "code",
        "stage",
        "retryable",
    }
)
SUMMARY_OWNED_RESULT_FIELDS = frozenset(
    {
        "summary",
        "context_analysis",
        "model_name",
        "summary_model",
        "summary_type",
        "summary_runtime",
        "summary_release",
    }
)
SUMMARY_TRANSITION_ONLY_FIELDS = frozenset(
    {
        "summary",
        "summary_model",
        "summary_type",
        "summary_runtime",
        "summary_release",
    }
)
SUMMARY_SERVICE_RESULT_FIELDS = frozenset(
    {
        "available",
        "summary",
        "context",
        "model",
        "requested_model",
        "summary_type",
        "release",
        "runtime",
        "error",
        "num_transcripts",
        "case_id",
    }
)
SUMMARY_SAFE_CODES = frozenset(
    {
        "FORENSIC_LEGACY_PROVIDER_DISABLED",
        "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID",
        "INVESTIGATION_NARRATIVE_ATTESTATION_REQUIRED",
        "INVESTIGATION_NARRATIVE_EMPTY",
        "INVESTIGATION_SOURCE_REVISION_MISMATCH",
        "LLM_UNAVAILABLE",
        "MULTI_EVIDENCE_RELEASE_REQUIRED",
        "SUMMARY_ATTEMPT_CONFLICT",
        "SUMMARY_ATTEMPT_STARTED",
        "SUMMARY_ENQUEUE_FAILED",
        "SUMMARY_EMPTY",
        "SUMMARY_GENERATION_FAILED",
        "SUMMARY_MAX_LENGTH_EXCEEDED",
        "SUMMARY_PERSISTENCE_FAILED",
        "SUMMARY_RESULT_INVALID",
        "SUMMARY_SUCCEEDED",
        "SUMMARY_UNAVAILABLE",
        "SUMMARY_UNSAFE_HANDOFF",
    }
)
SUMMARY_SAFE_STAGES = frozenset(
    {"enqueue", "execution", "handoff", "persistence", "release", "validation"}
)
SUMMARY_RELEASE_FAILURE_CODES = frozenset(
    {
        "FORENSIC_LEGACY_PROVIDER_DISABLED",
        "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID",
        "INVESTIGATION_NARRATIVE_ATTESTATION_REQUIRED",
        "INVESTIGATION_NARRATIVE_EMPTY",
        "INVESTIGATION_SOURCE_REVISION_MISMATCH",
        "MULTI_EVIDENCE_RELEASE_REQUIRED",
    }
)
SUMMARY_RETRYABLE_CODES = frozenset(
    {
        "LLM_UNAVAILABLE",
        "SUMMARY_ENQUEUE_FAILED",
        "SUMMARY_GENERATION_FAILED",
        "SUMMARY_PERSISTENCE_FAILED",
        "SUMMARY_UNAVAILABLE",
        "SUMMARY_UNSAFE_HANDOFF",
    }
)
SUMMARY_SAFE_MESSAGES = {
    "FORENSIC_LEGACY_PROVIDER_DISABLED": "The requested forensic summary path is not released.",
    "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID": "The released investigation narrative could not be verified.",
    "INVESTIGATION_NARRATIVE_ATTESTATION_REQUIRED": "A verified released investigation narrative is required.",
    "INVESTIGATION_NARRATIVE_EMPTY": "The released investigation narrative is empty.",
    "INVESTIGATION_SOURCE_REVISION_MISMATCH": "The released narrative does not match the active source revision.",
    "LLM_UNAVAILABLE": "The summarization service is unavailable.",
    "MULTI_EVIDENCE_RELEASE_REQUIRED": "A released evidence narrative is required for this multi-file summary.",
    "SUMMARY_ATTEMPT_CONFLICT": "The summary attempt is stale or conflicts with a terminal result.",
    "SUMMARY_ENQUEUE_FAILED": "The summary job could not be queued.",
    "SUMMARY_EMPTY": "The summarization service returned no usable summary.",
    "SUMMARY_GENERATION_FAILED": "Summary generation failed.",
    "SUMMARY_MAX_LENGTH_EXCEEDED": "The generated summary exceeded the configured maximum length.",
    "SUMMARY_PERSISTENCE_FAILED": "The summary state could not be persisted.",
    "SUMMARY_RESULT_INVALID": "The summarization service returned an invalid result.",
    "SUMMARY_UNAVAILABLE": "The summarization service did not produce an available result.",
    "SUMMARY_UNSAFE_HANDOFF": "The model handoff did not complete safely.",
}


@dataclass(frozen=True)
class ValidatedSummaryResult:
    summary: str
    context: dict[str, Any] | None
    model: str | None
    summary_type: str | None
    runtime: dict[str, Any]
    safe_result: dict[str, Any]


class SummaryResultRejected(ValueError):
    def __init__(
        self,
        code: str,
        *,
        stage: str,
        retryable: bool,
        needs_review: bool,
    ) -> None:
        self.code = canonical_summary_code(code)
        self.stage = canonical_summary_stage(stage)
        self.retryable = retryable is True
        self.needs_review = needs_review is True
        super().__init__(safe_summary_message(self.code))


@dataclass(frozen=True)
class SummaryTransitionResult:
    outcome: Literal["applied", "duplicate", "conflict", "missing", "error"]
    state: str
    code: str

    @property
    def accepted(self) -> bool:
        return self.outcome in {"applied", "duplicate"}


def canonical_summary_code(code: object, default: str = "SUMMARY_UNAVAILABLE") -> str:
    candidate = str(code or "").strip().upper()
    return candidate if candidate in SUMMARY_SAFE_CODES else default


def canonical_summary_stage(stage: object, default: str = "execution") -> str:
    candidate = str(stage or "").strip().lower()
    return candidate if candidate in SUMMARY_SAFE_STAGES else default


def safe_summary_message(code: object) -> str:
    canonical = canonical_summary_code(code)
    return SUMMARY_SAFE_MESSAGES.get(
        canonical,
        SUMMARY_SAFE_MESSAGES["SUMMARY_UNAVAILABLE"],
    )


def _summary_failure_properties(code: str) -> tuple[str, bool, bool]:
    canonical = canonical_summary_code(code)
    needs_review = canonical in SUMMARY_RELEASE_FAILURE_CODES
    stage = (
        "release"
        if canonical in SUMMARY_RELEASE_FAILURE_CODES
        else "handoff" if canonical == "SUMMARY_UNSAFE_HANDOFF" else "execution"
    )
    return stage, canonical in SUMMARY_RETRYABLE_CODES, needs_review


def _safe_summary_service_result(result: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in SUMMARY_SERVICE_RESULT_FIELDS:
        if key not in result:
            continue
        value = result[key]
        if key == "error" and isinstance(value, dict):
            safe[key] = {"code": canonical_summary_code(value.get("code"))}
        elif key in {"context", "runtime", "release"}:
            safe[key] = copy.deepcopy(value) if isinstance(value, dict) else None
        elif key in {"model", "requested_model", "summary_type", "case_id"}:
            safe[key] = value if isinstance(value, str) else None
        elif key == "num_transcripts":
            if type(value) is int and value >= 0:
                safe[key] = value
        elif key == "available":
            safe[key] = value is True
        else:
            safe[key] = copy.deepcopy(value)
    return safe


def _invalid_summary_service_result() -> SummaryResultRejected:
    return SummaryResultRejected(
        "SUMMARY_RESULT_INVALID",
        stage="validation",
        retryable=False,
        needs_review=False,
    )


def _validate_summary_service_result_shape(
    result: dict[str, Any],
    *,
    multi: bool,
) -> None:
    if type(result.get("available")) is not bool:
        raise _invalid_summary_service_result()
    if "summary" in result and not isinstance(result["summary"], str):
        raise _invalid_summary_service_result()

    context = result.get("context")
    if "context" in result and context is not None and not isinstance(context, dict):
        raise _invalid_summary_service_result()
    for key in ("runtime", "release"):
        if key in result and not isinstance(result[key], dict):
            raise _invalid_summary_service_result()

    if "error" in result:
        error = result["error"]
        if not isinstance(error, dict):
            raise _invalid_summary_service_result()
        for key in ("code", "message"):
            if key in error and not isinstance(error[key], str):
                raise _invalid_summary_service_result()
        if result["available"] is True:
            raise _invalid_summary_service_result()

    for key in ("model", "requested_model", "summary_type", "case_id"):
        value = result.get(key)
        if key in result and value is not None and not isinstance(value, str):
            raise _invalid_summary_service_result()

    num_transcripts = result.get("num_transcripts")
    if "num_transcripts" in result and (
        type(num_transcripts) is not int or num_transcripts < 0
    ):
        raise _invalid_summary_service_result()
    if multi and "num_transcripts" not in result:
        raise _invalid_summary_service_result()


def _reject_investigation_result(code: str) -> NoReturn:
    raise SummaryResultRejected(
        code,
        stage="release",
        retryable=False,
        needs_review=True,
    )


def _validate_investigation_release_metadata(
    release: dict[str, Any],
    *,
    summary: str,
    expected_source_revision_id: str | None,
    expected_request_fingerprint: str | None,
) -> None:
    required_strings = (
        "run_id",
        "source_revision_id",
        "content_sha256",
        "attestation_schema_version",
        "producer_id",
    )
    if any(
        not isinstance(release.get(key), str) or not release[key].strip()
        for key in required_strings
    ):
        _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")
    content_sha256 = release["content_sha256"].casefold()
    if len(content_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in content_sha256
    ):
        _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")
    if hashlib.sha256(summary.encode("utf-8")).hexdigest() != content_sha256:
        _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")
    sentence_ids = release.get("sentence_ids")
    if (
        not isinstance(sentence_ids, list)
        or not sentence_ids
        or any(not isinstance(value, str) or not value.strip() for value in sentence_ids)
    ):
        _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")
    sentences = release.get("sentences")
    if not isinstance(sentences, list) or len(sentences) != len(sentence_ids):
        _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")
    released_sentence_ids: list[str] = []
    for sentence in sentences:
        if not isinstance(sentence, dict):
            _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")
        sentence_id = sentence.get("sentence_id")
        evidence_refs = sentence.get("evidence_refs")
        claim_refs = sentence.get("claim_refs")
        if (
            not isinstance(sentence_id, str)
            or not sentence_id.strip()
            or not isinstance(claim_refs, list)
            or any(not isinstance(value, str) or not value for value in claim_refs)
            or not isinstance(evidence_refs, list)
            or not evidence_refs
            or any(not isinstance(value, str) or not value for value in evidence_refs)
        ):
            _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")
        released_sentence_ids.append(sentence_id)
    if released_sentence_ids != sentence_ids or len(set(sentence_ids)) != len(sentence_ids):
        _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")

    if (
        not isinstance(expected_source_revision_id, str)
        or not expected_source_revision_id.strip()
        or not isinstance(expected_request_fingerprint, str)
        or not expected_request_fingerprint.strip()
    ):
        _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")
    bound_source_revision_id = release.get(
        "summary_source_revision_id",
        release.get("source_revision_id"),
    )
    if bound_source_revision_id != expected_source_revision_id:
        _reject_investigation_result("INVESTIGATION_SOURCE_REVISION_MISMATCH")
    if release.get("request_fingerprint") != expected_request_fingerprint:
        _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")


def _validate_investigation_release(
    result: dict[str, Any],
    *,
    summary: str,
    expected_source_revision_id: str | None,
    expected_request_fingerprint: str | None,
) -> None:
    release = result.get("release")
    if not isinstance(release, dict):
        _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_REQUIRED")

    _validate_investigation_release_metadata(
        release,
        summary=summary,
        expected_source_revision_id=expected_source_revision_id,
        expected_request_fingerprint=expected_request_fingerprint,
    )

    authority = result.get("_released_narrative_authority")
    try:
        trusted_summary = render_released_narrative_text(authority).strip()
        trusted_metadata = released_narrative_metadata(authority)
    except Exception:
        _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")

    expected_release = copy.deepcopy(trusted_metadata)
    expected_release["summary_source_revision_id"] = expected_source_revision_id
    expected_release["request_fingerprint"] = expected_request_fingerprint
    if trusted_summary != summary or release != expected_release:
        _reject_investigation_result("INVESTIGATION_NARRATIVE_ATTESTATION_INVALID")


def validate_summary_service_result(
    result: object,
    *,
    multi: bool = False,
    expected_summary_type: str | None = None,
    expected_source_revision_id: str | None = None,
    expected_request_fingerprint: str | None = None,
) -> ValidatedSummaryResult:
    if not isinstance(result, dict):
        raise _invalid_summary_service_result()
    _validate_summary_service_result_shape(result, multi=multi)
    if result.get("available") is not True:
        error = result.get("error")
        raw_code = error.get("code") if isinstance(error, dict) else None
        code = canonical_summary_code(raw_code)
        stage, retryable, needs_review = _summary_failure_properties(code)
        raise SummaryResultRejected(
            code,
            stage=stage,
            retryable=retryable,
            needs_review=needs_review,
        )
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise SummaryResultRejected(
            "SUMMARY_EMPTY",
            stage="validation",
            retryable=False,
            needs_review=False,
        )
    result_summary_type = result.get("summary_type")
    if expected_summary_type is not None and result_summary_type != expected_summary_type:
        if expected_summary_type == "investigation":
            _reject_investigation_result(
                "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID"
            )
        raise _invalid_summary_service_result()
    effective_summary_type = expected_summary_type or result_summary_type
    if effective_summary_type == "investigation":
        _validate_investigation_release(
            result,
            summary=summary.strip(),
            expected_source_revision_id=expected_source_revision_id,
            expected_request_fingerprint=expected_request_fingerprint,
        )
    context = result.get("context")
    model = result.get("model")
    summary_type = result.get("summary_type")
    runtime = result.get("runtime")
    normalized_summary = summary.strip()
    safe_result = _safe_summary_service_result(result)
    safe_result["summary"] = normalized_summary
    return ValidatedSummaryResult(
        summary=normalized_summary,
        context=copy.deepcopy(context) if isinstance(context, dict) else None,
        model=str(model) if isinstance(model, str) else None,
        summary_type=str(summary_type) if isinstance(summary_type, str) else None,
        runtime=copy.deepcopy(runtime) if isinstance(runtime, dict) else {},
        safe_result=safe_result,
    )


def validate_persisted_terminal_summary(
    task_result: object,
    *,
    expected_attempt_id: str,
) -> ValidatedSummaryResult:
    """Read a success previously written only by the CAS transition helper."""

    if not isinstance(task_result, dict):
        raise _invalid_summary_service_result()
    state = task_result.get("summary_state")
    if (
        not isinstance(state, dict)
        or set(state) != SUMMARY_STATE_FIELDS
        or state.get("schema_version") != SUMMARY_STATE_SCHEMA
        or state.get("attempt_id") != expected_attempt_id
        or state.get("status") != "succeeded"
        or state.get("code") != "SUMMARY_SUCCEEDED"
    ):
        raise SummaryResultRejected(
            "SUMMARY_ATTEMPT_CONFLICT",
            stage="validation",
            retryable=False,
            needs_review=False,
        )
    transcript = task_result.get("transcription")
    if (
        not isinstance(transcript, str)
        or _summary_source_revision_id(transcript) != state.get("source_revision_id")
    ):
        raise SummaryResultRejected(
            "SUMMARY_ATTEMPT_CONFLICT",
            stage="validation",
            retryable=False,
            needs_review=False,
        )

    raw_result = {
        "available": True,
        "summary": task_result.get("summary"),
        "context": task_result.get("context_analysis"),
        "model": task_result.get("summary_model"),
        "summary_type": task_result.get("summary_type"),
        "runtime": task_result.get("summary_runtime") or {},
        **(
            {"release": task_result["summary_release"]}
            if isinstance(task_result.get("summary_release"), dict)
            else {}
        ),
    }
    summary_type = raw_result.get("summary_type")
    if summary_type != "investigation":
        return validate_summary_service_result(
            raw_result,
            expected_summary_type=summary_type,
        )

    _validate_summary_service_result_shape(raw_result, multi=False)
    summary = raw_result.get("summary")
    release = raw_result.get("release")
    if not isinstance(summary, str) or not summary.strip() or not isinstance(release, dict):
        raise _invalid_summary_service_result()
    normalized_summary = summary.strip()
    _validate_investigation_release_metadata(
        release,
        summary=normalized_summary,
        expected_source_revision_id=state.get("source_revision_id"),
        expected_request_fingerprint=state.get("request_fingerprint"),
    )
    safe_result = _safe_summary_service_result(raw_result)
    safe_result["summary"] = normalized_summary
    context = raw_result.get("context")
    model = raw_result.get("model")
    runtime = raw_result.get("runtime")
    return ValidatedSummaryResult(
        summary=normalized_summary,
        context=copy.deepcopy(context) if isinstance(context, dict) else None,
        model=model if isinstance(model, str) else None,
        summary_type="investigation",
        runtime=copy.deepcopy(runtime) if isinstance(runtime, dict) else {},
        safe_result=safe_result,
    )


def build_summary_result_patch(
    result: ValidatedSummaryResult,
    *,
    summary_type: str,
) -> dict[str, Any]:
    patch = {
        "summary": result.summary,
        "context_analysis": copy.deepcopy(result.context),
        "summary_model": result.model,
        "summary_type": summary_type,
        "summary_runtime": copy.deepcopy(result.runtime),
    }
    release = result.safe_result.get("release")
    if isinstance(release, dict):
        patch["summary_release"] = copy.deepcopy(release)
    return patch


def _summary_source_revision_id(transcript: str) -> str:
    source_digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    return f"summary-source-sha256:{source_digest}"


def build_summary_attempt_binding(
    transcript: str,
    *,
    model_name: str | None,
    summary_type: str,
    include_context: bool,
    min_length: int,
    max_length: int,
    user_prompt: str | None = None,
) -> tuple[str, str]:
    source_revision_id = _summary_source_revision_id(transcript)
    canonical_model_name = (
        model_name.strip()
        if isinstance(model_name, str) and model_name.strip()
        else "auto"
    )
    prompt_digest = (
        hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()
        if isinstance(user_prompt, str) and user_prompt
        else None
    )
    request_fingerprint = sha256_canonical_json(
        {
            "schema_version": "summary-request-fingerprint-v1",
            "source_revision_id": source_revision_id,
            "model_name": canonical_model_name,
            "summary_type": summary_type,
            "include_context": include_context is True,
            "min_length": min_length,
            "max_length": max_length,
            "user_prompt_sha256": prompt_digest,
        }
    )
    return request_fingerprint, source_revision_id


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    return {}


def released_investigation_run_identity(value: Any) -> tuple[str, str, str] | None:
    """Read routing identity only; this never rehydrates release authority."""

    if not isinstance(value, dict):
        return None
    if (
        value.get("schema_version") != "investigation-run-v1.0"
        or value.get("run_status") != "success"
    ):
        return None
    provenance = value.get("provenance")
    run_id = value.get("run_id")
    source_revision_id = (
        provenance.get("source_revision_id")
        if isinstance(provenance, dict)
        else None
    )
    if not isinstance(run_id, str) or not run_id.strip():
        return None
    if not isinstance(source_revision_id, str) or not source_revision_id.strip():
        return None
    return run_id, source_revision_id, sha256_canonical_json(value)


def extract_visualization_payload(
    value: Any,
    *,
    expected_run_id: str | None = None,
    expected_source_revision_id: str | None = None,
    expected_release_subject_sha256: str | None = None,
) -> Any:
    """Return an artifact only when it matches the active released run identity."""

    if not isinstance(value, dict):
        return None
    if "visualization_data" in value:
        return extract_visualization_payload(
            value["visualization_data"],
            expected_run_id=expected_run_id,
            expected_source_revision_id=expected_source_revision_id,
            expected_release_subject_sha256=expected_release_subject_sha256,
        )
    if "data" in value and (
        "visualization_type" in value
        or value.get("status") in {"visualization_ready", "visualized", "success"}
        or "task_id" in value
    ):
        return extract_visualization_payload(
            value["data"],
            expected_run_id=expected_run_id,
            expected_source_revision_id=expected_source_revision_id,
            expected_release_subject_sha256=expected_release_subject_sha256,
        )
    if "result" in value and value.get("status") == "success":
        return extract_visualization_payload(
            value["result"],
            expected_run_id=expected_run_id,
            expected_source_revision_id=expected_source_revision_id,
            expected_release_subject_sha256=expected_release_subject_sha256,
        )
    if (
        not expected_run_id
        or not expected_source_revision_id
        or not expected_release_subject_sha256
    ):
        return None
    try:
        from src.services.visualization import InvestigationVisualization

        artifact = InvestigationVisualization.model_validate(value)
    except (ImportError, TypeError, ValueError):
        return None
    if (
        artifact.run_id != expected_run_id
        or artifact.source_revision_id != expected_source_revision_id
        or artifact.release_subject_sha256 != expected_release_subject_sha256
    ):
        return None
    return artifact.model_dump(mode="json", exclude_none=True)


def extract_active_visualization_payload(result: Any) -> Any:
    """Project the visualization visible for the current stored release identity."""

    if not isinstance(result, dict):
        return None
    identity = released_investigation_run_identity(
        result.get("released_investigation_run")
    )
    if identity is None:
        return None
    return extract_visualization_payload(
        result.get("visualization_data"),
        expected_run_id=identity[0],
        expected_source_revision_id=identity[1],
        expected_release_subject_sha256=identity[2],
    )


def _deep_merge(
    base: Dict[str, Any],
    patch: Dict[str, Any],
    *,
    bind_visualization: bool = True,
) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if key == "has_visualization":
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(
                merged[key],
                value,
                bind_visualization=False,
            )
        else:
            merged[key] = copy.deepcopy(value)
    if bind_visualization and (
        "visualization_data" in patch
        or "released_investigation_run" in patch
    ):
        identity = released_investigation_run_identity(
            merged.get("released_investigation_run")
        )
        merged["visualization_data"] = (
            extract_visualization_payload(
                merged.get("visualization_data"),
                expected_run_id=identity[0],
                expected_source_revision_id=identity[1],
                expected_release_subject_sha256=identity[2],
            )
            if identity is not None
            else None
        )
        merged["has_visualization"] = bool(merged.get("visualization_data"))
    return merged


def canonical_status(status: str | None, result: Dict[str, Any] | None = None) -> str | None:
    if not status:
        return status
    if status in CANONICAL_STATUSES:
        return status
    if status == "completed":
        result = result or {}
        if result.get("has_visualization") or result.get("visualization_data"):
            return "visualized"
        if result.get("summary"):
            return "summarized"
        if result.get("transcription") or result.get("transcript") or result.get("text"):
            return "transcribed"
        return "transcribed"
    return LEGACY_STATUS_ALIASES.get(status, status)


def effective_task_status(task_status: str | None, audio_status: str | None = None, result: Dict[str, Any] | None = None) -> str | None:
    status = canonical_status(task_status, result)
    if status:
        return status
    return canonical_status(audio_status, result)


def _sync_audio_status(db: Session, task: DBTask, status: str | None) -> None:
    if not status:
        return
    normalized = canonical_status(status, _as_dict(task.result))
    audio_files = list(task.audio_files or [])
    if not audio_files:
        audio_files = db.query(AudioFile).filter(AudioFile.task_id == task.id).all()
    for audio in audio_files:
        audio.status = normalized
        audio.updated_at = datetime.utcnow()


def _task_to_dict(task: DBTask) -> Dict[str, Any]:
    result = _as_dict(task.result)
    audio = task.audio_files[0] if task.audio_files else None
    if audio:
        result.setdefault("audio_id", audio.id)
        result.setdefault("download_url", f"/api/v1/audio/{audio.id}/download")

    data = {
        "id": task.id,
        "filename": task.filename,
        "status": effective_task_status(task.status, audio.status if audio else None, result),
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "result": result,
        "error": task.error,
        "case_id": task.case_id,
        "user_id": task.user_id,
    }
    for key, value in result.items():
        data.setdefault(key, value)
    data.setdefault("transcript", result.get("transcription"))
    return data


def _get_actor(db: Session, user_id: int | None) -> User | None:
    if user_id:
        return db.query(User).filter(User.id == user_id).first()
    return db.query(User).filter(User.username == "admin").first()


def create_task(
    filename: str,
    case_id: int | None = None,
    db: Session | None = None,
    user_id: int | None = None,
    commit: bool = True,
) -> Optional[Dict[str, Any]]:
    own_session = db is None
    db = db or SessionLocal()
    try:
        actor = _get_actor(db, user_id)
        if not actor:
            logger.error("Cannot create task without a valid actor/admin user")
            return None

        if case_id is not None:
            case = db.query(Case).filter(Case.id == case_id).first()
            if not case:
                logger.error("Case with id %s does not exist", case_id)
                return None
        else:
            status = db.query(CaseStatus).filter(CaseStatus.status_name == "active").first()
            priority = db.query(CasePriority).filter(CasePriority.priority_name == "high").first()
            if not status or not priority:
                logger.error("Missing default case status or priority")
                return None
            case = Case(
                title=filename,
                case_code=str(uuid.uuid4()),
                description=None,
                status_id=status.id,
                priority_id=priority.id,
                created_by=actor.id,
            )
            db.add(case)
            db.flush()
            owner_role = db.query(ParticipantRole).filter(ParticipantRole.role_name == "owner").first()
            if owner_role:
                db.add(
                    CaseParticipant(
                        case_id=case.id,
                        user_id=actor.id,
                        role_id=owner_role.id,
                        is_active=True,
                    )
                )

        now = datetime.utcnow()
        task = DBTask(
            id=str(uuid.uuid4()),
            filename=filename,
            status="pending",
            case_id=case.id,
            user_id=actor.id,
            created_at=now,
            updated_at=now,
            result={},
        )
        db.add(task)
        db.flush()
        if own_session or commit:
            db.commit()
            db.refresh(task)
        return _task_to_dict(task)
    except Exception:
        if own_session or commit:
            db.rollback()
        logger.exception("Error creating task")
        return None
    finally:
        if own_session:
            db.close()


def get_task(task_id: str, db: Session | None = None) -> Optional[Dict[str, Any]]:
    own_session = db is None
    db = db or SessionLocal()
    try:
        task = db.query(DBTask).filter(DBTask.id == task_id).first()
        if not task:
            return None
        return _task_to_dict(task)
    except Exception:
        logger.exception("Error getting task %s", task_id)
        return None
    finally:
        if own_session:
            db.close()


def _summary_state_payload(
    *,
    attempt_id: str,
    request_fingerprint: str,
    source_revision_id: str,
    status: Literal["running", "succeeded", "failed", "needs_review"],
    code: str,
    stage: str,
    retryable: bool,
) -> dict[str, Any]:
    return {
        "schema_version": SUMMARY_STATE_SCHEMA,
        "attempt_id": attempt_id,
        "request_fingerprint": request_fingerprint,
        "source_revision_id": source_revision_id,
        "status": status,
        "code": canonical_summary_code(code),
        "stage": canonical_summary_stage(stage),
        "retryable": retryable is True,
    }


def _summary_terminal_is_exact_duplicate(
    task: DBTask,
    result: dict[str, Any],
    desired_state: dict[str, Any],
    result_patch: dict[str, Any] | None,
) -> bool:
    if result.get("summary_state") != desired_state:
        return False
    state = desired_state["status"]
    expected_status = "summarized" if state == "succeeded" else state
    if task.status != expected_status:
        return False
    if state == "succeeded":
        direct_summary_matches = (
            not hasattr(task, "summary")
            or task.summary == (result_patch or {}).get("summary")
        )
        direct_model_matches = (
            not hasattr(task, "model_name")
            or task.model_name == (result_patch or {}).get("summary_model")
        )
        return (
            task.error is None
            and direct_summary_matches
            and direct_model_matches
            and bool(result_patch)
            and all(result.get(key) == value for key, value in result_patch.items())
        )
    direct_summary_cleared = not hasattr(task, "summary") or task.summary is None
    direct_model_cleared = not hasattr(task, "model_name") or task.model_name is None
    return (
        task.error == safe_summary_message(desired_state["code"])
        and direct_summary_cleared
        and direct_model_cleared
        and all(key not in result for key in SUMMARY_OWNED_RESULT_FIELDS)
    )


def transition_summary_attempt(
    task_id: str,
    attempt_id: str,
    *,
    state: Literal["running", "succeeded", "failed", "needs_review"],
    code: str,
    stage: str,
    retryable: bool,
    request_fingerprint: str | None = None,
    source_revision_id: str | None = None,
    result_patch: dict[str, Any] | None = None,
    db: Session | None = None,
) -> SummaryTransitionResult:
    """Apply one attempt-scoped transition while holding the task row lock."""

    if state not in {"running", "succeeded", "failed", "needs_review"}:
        raise ValueError("Unsupported summary attempt state")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError("Summary attempt_id must be a non-empty string")
    attempt_id = attempt_id.strip()
    canonical_code = canonical_summary_code(code)
    if state == "running" and canonical_code != "SUMMARY_ATTEMPT_STARTED":
        raise ValueError("Running summary transition requires SUMMARY_ATTEMPT_STARTED")
    if state == "succeeded" and canonical_code != "SUMMARY_SUCCEEDED":
        raise ValueError("Successful summary transition requires SUMMARY_SUCCEEDED")
    if state == "needs_review" and canonical_code not in SUMMARY_RELEASE_FAILURE_CODES:
        raise ValueError("needs_review requires a release or attestation failure code")
    if state == "failed" and canonical_code in SUMMARY_RELEASE_FAILURE_CODES:
        raise ValueError("Release or attestation failures require needs_review")
    if state == "running":
        if not isinstance(request_fingerprint, str) or not request_fingerprint.strip():
            raise ValueError("Running summary transition requires request_fingerprint")
        if not isinstance(source_revision_id, str) or not source_revision_id.strip():
            raise ValueError("Running summary transition requires source_revision_id")
    if state == "succeeded":
        if not isinstance(result_patch, dict):
            raise ValueError("Successful summary transition requires a result patch")
        unexpected = set(result_patch) - SUMMARY_OWNED_RESULT_FIELDS
        if unexpected:
            raise ValueError("Successful summary transition contains unsupported fields")
        summary = result_patch.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("Successful summary transition requires a non-empty summary")
    elif result_patch is not None:
        raise ValueError("Only successful summary transitions accept a result patch")

    own_session = db is None
    db = db or SessionLocal()
    try:
        query = db.query(DBTask).filter(DBTask.id == task_id)
        bind = getattr(db, "bind", None)
        if bind is not None and bind.dialect.name != "sqlite":
            query = query.with_for_update()
        task = query.first()
        if not task:
            return SummaryTransitionResult("missing", state, "SUMMARY_PERSISTENCE_FAILED")

        result = _as_dict(task.result)
        current = result.get("summary_state")
        current = current if isinstance(current, dict) else None
        if current is not None and (
            set(current) != SUMMARY_STATE_FIELDS
            or current.get("schema_version") != SUMMARY_STATE_SCHEMA
        ):
            return SummaryTransitionResult("conflict", state, "SUMMARY_ATTEMPT_CONFLICT")
        current_attempt = current.get("attempt_id") if current else None
        current_state = current.get("status") if current else None

        if state == "running":
            binding_request_fingerprint = str(request_fingerprint).strip()
            binding_source_revision_id = str(source_revision_id).strip()
            live_transcript = result.get("transcription")
            if (
                not isinstance(live_transcript, str)
                or _summary_source_revision_id(live_transcript)
                != binding_source_revision_id
            ):
                return SummaryTransitionResult(
                    "conflict", state, "SUMMARY_ATTEMPT_CONFLICT"
                )
        else:
            if current is None:
                return SummaryTransitionResult("conflict", state, "SUMMARY_ATTEMPT_CONFLICT")
            binding_request_fingerprint = str(
                current.get("request_fingerprint") or ""
            ).strip()
            binding_source_revision_id = str(
                current.get("source_revision_id") or ""
            ).strip()
            if not binding_request_fingerprint or not binding_source_revision_id:
                return SummaryTransitionResult("conflict", state, "SUMMARY_ATTEMPT_CONFLICT")
            live_transcript = result.get("transcription")
            if (
                not isinstance(live_transcript, str)
                or _summary_source_revision_id(live_transcript)
                != binding_source_revision_id
            ):
                return SummaryTransitionResult(
                    "conflict", state, "SUMMARY_ATTEMPT_CONFLICT"
                )

        desired_state = _summary_state_payload(
            attempt_id=attempt_id,
            request_fingerprint=binding_request_fingerprint,
            source_revision_id=binding_source_revision_id,
            status=state,
            code=canonical_code,
            stage=stage,
            retryable=retryable,
        )

        claim_enqueued_attempt = False
        if state == "running":
            if current_attempt == attempt_id:
                if (
                    current.get("request_fingerprint") != binding_request_fingerprint
                    or current.get("source_revision_id") != binding_source_revision_id
                ):
                    return SummaryTransitionResult(
                        "conflict", state, "SUMMARY_ATTEMPT_CONFLICT"
                    )
                if current_state == "running":
                    if current.get("stage") == "enqueue" and desired_state["stage"] == "execution":
                        claim_enqueued_attempt = True
                    elif current.get("stage") == desired_state["stage"] == "enqueue":
                        return SummaryTransitionResult(
                            "duplicate",
                            current_state,
                            canonical_summary_code(current.get("code")),
                        )
                    else:
                        return SummaryTransitionResult(
                            "conflict", state, "SUMMARY_ATTEMPT_CONFLICT"
                        )
                elif current_state in {"succeeded", "failed", "needs_review"}:
                    return SummaryTransitionResult(
                        "duplicate",
                        current_state,
                        canonical_summary_code(current.get("code")),
                    )
                elif current_state != "running":
                    return SummaryTransitionResult(
                        "conflict", state, "SUMMARY_ATTEMPT_CONFLICT"
                    )
            if current_state == "running" and not claim_enqueued_attempt:
                if current_attempt == attempt_id or (
                    current.get("source_revision_id") == binding_source_revision_id
                ):
                    return SummaryTransitionResult(
                        "conflict", state, "SUMMARY_ATTEMPT_CONFLICT"
                    )
        else:
            if current_attempt != attempt_id or current_state not in {
                "running",
                "succeeded",
                "failed",
                "needs_review",
            }:
                return SummaryTransitionResult("conflict", state, "SUMMARY_ATTEMPT_CONFLICT")
            if current_state != "running":
                if _summary_terminal_is_exact_duplicate(
                    task,
                    result,
                    desired_state,
                    result_patch,
                ):
                    return SummaryTransitionResult("duplicate", state, desired_state["code"])
                return SummaryTransitionResult("conflict", state, "SUMMARY_ATTEMPT_CONFLICT")

        if state in {"running", "failed", "needs_review"}:
            for key in SUMMARY_OWNED_RESULT_FIELDS:
                result.pop(key, None)
            if hasattr(task, "summary"):
                task.summary = None
            if hasattr(task, "model_name"):
                task.model_name = None
        if state == "succeeded":
            result.update(copy.deepcopy(result_patch or {}))
            if hasattr(task, "summary"):
                task.summary = result_patch["summary"]
            if hasattr(task, "model_name"):
                task.model_name = result_patch.get("summary_model")
        result["summary_state"] = desired_state
        task.result = result
        task.status = "summarized" if state == "succeeded" else (
            "summarizing" if state == "running" else state
        )
        task.error = (
            None
            if state in {"running", "succeeded"}
            else safe_summary_message(canonical_code)
        )
        task.updated_at = datetime.utcnow()

        if own_session:
            db.commit()
        else:
            db.flush()
        return SummaryTransitionResult("applied", state, desired_state["code"])
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            "Summary transition persistence failed | task_id=%s | error_type=%s",
            task_id,
            type(exc).__name__,
        )
        return SummaryTransitionResult("error", state, "SUMMARY_PERSISTENCE_FAILED")
    finally:
        if own_session:
            db.close()


def begin_summary_attempt(
    task_id: str,
    attempt_id: str,
    *,
    request_fingerprint: str,
    source_revision_id: str,
    stage: str = "execution",
    db: Session | None = None,
) -> SummaryTransitionResult:
    return transition_summary_attempt(
        task_id,
        attempt_id,
        state="running",
        code="SUMMARY_ATTEMPT_STARTED",
        stage=stage,
        retryable=False,
        request_fingerprint=request_fingerprint,
        source_revision_id=source_revision_id,
        db=db,
    )


def succeed_summary_attempt(
    task_id: str,
    attempt_id: str,
    result_patch: dict[str, Any],
    *,
    db: Session | None = None,
) -> SummaryTransitionResult:
    return transition_summary_attempt(
        task_id,
        attempt_id,
        state="succeeded",
        code="SUMMARY_SUCCEEDED",
        stage="execution",
        retryable=False,
        result_patch=result_patch,
        db=db,
    )


def fail_summary_attempt(
    task_id: str,
    attempt_id: str,
    *,
    code: str,
    stage: str = "execution",
    retryable: bool = False,
    needs_review: bool = False,
    db: Session | None = None,
) -> SummaryTransitionResult:
    canonical_code = canonical_summary_code(code)
    if canonical_code in SUMMARY_RELEASE_FAILURE_CODES:
        needs_review = True
    terminal_state: Literal["failed", "needs_review"] = (
        "needs_review" if needs_review else "failed"
    )
    return transition_summary_attempt(
        task_id,
        attempt_id,
        state=terminal_state,
        code=canonical_code,
        stage=stage,
        retryable=retryable,
        db=db,
    )


def _summary_placeholder_update(key: str, value: Any) -> bool:
    if key == "summary":
        return value is None or (isinstance(value, str) and not value.strip())
    if key == "context_analysis":
        return value is None or value == {}
    return False


def _sanitize_generic_task_update(data: Dict[str, Any]) -> Dict[str, Any] | None:
    sanitized: Dict[str, Any] = {}
    for key, value in data.items():
        normalized_key = RESULT_FIELD_ALIASES.get(key, key)
        if normalized_key == "status" and value in {
            "summarizing",
            "summarized",
            "needs_review",
        }:
            logger.error("Summary statuses require summary transition helpers")
            return None
        if normalized_key == "summary_state":
            logger.error(
                "summary_state can only be changed by summary transition helpers"
            )
            return None
        if normalized_key == "result":
            if not isinstance(value, dict):
                logger.error("Task result update must be a dict")
                return None
            result_value = copy.deepcopy(value)
            if "summary_state" in result_value:
                logger.error(
                    "summary_state can only be changed by summary transition helpers"
                )
                return None
            for owned_key in SUMMARY_TRANSITION_ONLY_FIELDS:
                if owned_key not in result_value:
                    continue
                if _summary_placeholder_update(owned_key, result_value[owned_key]):
                    result_value.pop(owned_key)
                    continue
                logger.error(
                    "Summary-owned result fields require summary transition helpers"
                )
                return None
            sanitized[key] = result_value
            continue
        if normalized_key in SUMMARY_TRANSITION_ONLY_FIELDS or normalized_key == "model_name":
            if _summary_placeholder_update(normalized_key, value):
                continue
            logger.error(
                "Summary-owned result fields require summary transition helpers"
            )
            return None
        sanitized[key] = value
    return sanitized


def update_task(task_id: str, data: Dict[str, Any], db: Session | None = None) -> bool:
    own_session = db is None
    db = db or SessionLocal()
    try:
        sanitized_data = _sanitize_generic_task_update(data)
        if sanitized_data is None:
            return False
        query = db.query(DBTask).filter(DBTask.id == task_id)
        if db.bind and db.bind.dialect.name != "sqlite":
            query = query.with_for_update()
        task = query.first()
        if not task:
            logger.warning("Task %s not found", task_id)
            return False

        result_patch: Dict[str, Any] = {}
        status_update: str | None = None
        attribute_updates: Dict[str, Any] = {}
        for key, value in sanitized_data.items():
            normalized_key = RESULT_FIELD_ALIASES.get(key, key)
            if normalized_key == "result":
                result_patch = _deep_merge(
                    result_patch,
                    value,
                    bind_visualization=False,
                )
            elif hasattr(task, normalized_key):
                if normalized_key == "status":
                    status_update = value
                else:
                    attribute_updates[normalized_key] = value
            elif normalized_key in RESULT_FIELDS:
                if normalized_key == "visualization_data":
                    result_patch[normalized_key] = copy.deepcopy(value)
                elif normalized_key == "has_visualization":
                    continue
                else:
                    result_patch[normalized_key] = value
            else:
                result_patch[normalized_key] = value

        current_result = _as_dict(task.result)
        source_changed = False
        incoming_transcript = result_patch.get("transcription")
        if isinstance(incoming_transcript, str):
            current_transcript = current_result.get("transcription")
            current_state = current_result.get("summary_state")
            source_changed = (
                isinstance(current_transcript, str)
                and current_transcript != incoming_transcript
            ) or (
                isinstance(current_state, dict)
                and current_state.get("source_revision_id")
                != _summary_source_revision_id(incoming_transcript)
            )
            if source_changed:
                for key in SUMMARY_OWNED_RESULT_FIELDS:
                    current_result.pop(key, None)
                current_result.pop("summary_state", None)
                current_result.pop("visualization_data", None)
                current_result.pop("has_visualization", None)
                if hasattr(task, "summary"):
                    task.summary = None
                if hasattr(task, "model_name"):
                    task.model_name = None

        merged_result = (
            _deep_merge(current_result, result_patch)
            if result_patch
            else current_result
        )
        normalized_status = None
        if status_update:
            normalized_status = canonical_status(status_update, merged_result)
            if normalized_status in {"summarizing", "summarized", "needs_review"}:
                logger.error("Summary statuses require summary transition helpers")
                return False
        if result_patch:
            task.result = merged_result
        for key, value in attribute_updates.items():
            setattr(task, key, value)
        if status_update:
            task.status = normalized_status
            if task.status != "failed" and "error" not in sanitized_data:
                task.error = None
            _sync_audio_status(db, task, task.status)
        elif source_changed:
            task.status = "transcribed"
            task.error = None
            _sync_audio_status(db, task, task.status)
        task.updated_at = datetime.utcnow()
        if own_session:
            db.commit()
        else:
            db.flush()
        return True
    except Exception:
        if own_session:
            db.rollback()
        logger.exception("Error updating task %s", task_id)
        return False
    finally:
        if own_session:
            db.close()


def delete_task(task_id: str) -> bool:
    db = SessionLocal()
    try:
        task = db.query(DBTask).filter(DBTask.id == task_id).first()
        if not task:
            return False
        db.delete(task)
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("Error deleting task %s", task_id)
        return False
    finally:
        db.close()


def list_tasks(case_id: str | None = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        query = db.query(DBTask)
        if case_id:
            query = query.filter(DBTask.case_id == case_id)
        return [_task_to_dict(task) for task in query.order_by(desc(DBTask.created_at)).all()]
    except Exception:
        logger.exception("Error listing tasks")
        return []
    finally:
        db.close()
