"""
Summarize Task - Celery background task for summarization
Handles: Transcribe → Summarize (OPTIONAL, only if requested)
"""
import logging
import uuid
from contextlib import nullcontext
from typing import NoReturn

from src.worker.worker import celery_app
from src.services.task_service import (
    SummaryResultRejected,
    SummaryTransitionResult,
    begin_summary_attempt,
    build_summary_attempt_binding,
    build_summary_result_patch,
    fail_summary_attempt,
    get_task,
    safe_summary_message,
    succeed_summary_attempt,
    validate_persisted_terminal_summary,
    validate_summary_service_result,
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

logger = logging.getLogger(__name__)


class SafeSummaryTaskError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(safe_summary_message(code))


def _llama_server_handoff():
    """Test seam for G1; the real GPU lease implementation is intentionally separate."""

    return nullcontext()


def _accepted(outcome: SummaryTransitionResult) -> bool:
    return outcome.accepted


def _begin_attempt(
    task_id: str,
    attempt_id: str,
    *,
    request_fingerprint: str,
    source_revision_id: str,
) -> SummaryTransitionResult:
    return begin_summary_attempt(
        task_id,
        attempt_id,
        request_fingerprint=request_fingerprint,
        source_revision_id=source_revision_id,
    )


def _persist_success(
    task_id: str,
    attempt_id: str,
    result_patch: dict,
) -> SummaryTransitionResult:
    return succeed_summary_attempt(task_id, attempt_id, result_patch)


def _persist_failure(
    task_id: str,
    attempt_id: str,
    rejection: SummaryResultRejected,
) -> SummaryTransitionResult:
    return fail_summary_attempt(
        task_id,
        attempt_id,
        code=rejection.code,
        stage=rejection.stage,
        retryable=rejection.retryable,
        needs_review=rejection.needs_review,
    )


def _raise_safe_task_error(code: str) -> NoReturn:
    raise SafeSummaryTaskError(code)


def _failure_transition_code(
    outcome: SummaryTransitionResult,
    requested_code: str,
) -> str:
    if outcome.accepted:
        return requested_code
    if outcome.outcome == "conflict":
        return outcome.code
    return "SUMMARY_PERSISTENCE_FAILED"


def _stored_terminal_success(task_id: str, expected_attempt_id: str) -> dict:
    task = get_task(task_id)
    task_result = task.get("result") if isinstance(task, dict) else None
    try:
        validated = validate_persisted_terminal_summary(
            task_result,
            expected_attempt_id=expected_attempt_id,
        )
    except SummaryResultRejected as rejection:
        _raise_safe_task_error(rejection.code)
    return {
        "status": "success",
        "task_id": task_id,
        "result": validated.safe_result,
    }


@celery_app.task(bind=True, name='tasks.summarize_transcript')
def summarize_transcript_task(
    self,
    task_id: str,
    model_name: str = None,
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE,
    include_context: bool = True,
    user_prompt: str = None,
    min_length: int = DEFAULT_SUMMARY_MIN_WORDS,
    max_length: int = DEFAULT_SUMMARY_MAX_WORDS,
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
    )
    summary_type = options.summary_type
    min_length = options.min_length
    max_length = options.max_length

    logger.info(
        f"[CELERY_SUMMARIZE] Task started | task_id={task_id} | "
        f"celery_id={self.request.id} | model={model_name}"
    )
    attempt_id = str(self.request.id or uuid.uuid4())
    task = get_task(task_id)
    transcript = None
    if task and isinstance(task.get("result"), dict):
        transcript = task["result"].get("transcription")
    binding_transcript = transcript if isinstance(transcript, str) else ""
    request_fingerprint, source_revision_id = build_summary_attempt_binding(
        binding_transcript,
        model_name=model_name,
        summary_type=summary_type,
        include_context=include_context,
        min_length=min_length,
        max_length=max_length,
        user_prompt=user_prompt,
    )
    begun = _begin_attempt(
        task_id,
        attempt_id,
        request_fingerprint=request_fingerprint,
        source_revision_id=source_revision_id,
    )
    if not _accepted(begun):
        code = begun.code if begun.outcome == "conflict" else "SUMMARY_PERSISTENCE_FAILED"
        _raise_safe_task_error(code)

    if begun.outcome == "duplicate" and begun.state in {
        "succeeded",
        "failed",
        "needs_review",
    }:
        if begun.state == "succeeded":
            return _stored_terminal_success(task_id, attempt_id)
        _raise_safe_task_error(begun.code)

    if not isinstance(transcript, str) or not transcript.strip():
        rejection = SummaryResultRejected(
            "SUMMARY_RESULT_INVALID",
            stage="validation",
            retryable=False,
            needs_review=False,
        )
        persisted = _persist_failure(task_id, attempt_id, rejection)
        code = _failure_transition_code(persisted, rejection.code)
        _raise_safe_task_error(code)

    from src.services.summarization.summary_service_v2 import summarize_transcript_v2

    try:
        with _llama_server_handoff():
            try:
                raw_result = summarize_transcript_v2(
                    transcript=transcript,
                    model_name=model_name,
                    summary_type=summary_type,
                    include_context=include_context,
                    user_prompt=user_prompt,
                    min_length=min_length,
                    max_length=max_length,
                    source_metadata={
                        "summary_source_revision_id": source_revision_id,
                        "request_fingerprint": request_fingerprint,
                    },
                )
            except Exception as exc:
                logger.error(
                    "[CELERY_SUMMARIZE] Provider call failed | task_id=%s | error_type=%s",
                    task_id,
                    type(exc).__name__,
                )
                raise SummaryResultRejected(
                    "SUMMARY_GENERATION_FAILED",
                    stage="execution",
                    retryable=True,
                    needs_review=False,
                ) from None
    except SummaryResultRejected as rejection:
        persisted = _persist_failure(task_id, attempt_id, rejection)
        code = _failure_transition_code(persisted, rejection.code)
        _raise_safe_task_error(code)
    except Exception as exc:
        logger.error(
            "[CELERY_SUMMARIZE] Model handoff failed | task_id=%s | error_type=%s",
            task_id,
            type(exc).__name__,
        )
        rejection = SummaryResultRejected(
            "SUMMARY_UNSAFE_HANDOFF",
            stage="handoff",
            retryable=True,
            needs_review=False,
        )
        persisted = _persist_failure(task_id, attempt_id, rejection)
        code = _failure_transition_code(persisted, rejection.code)
        _raise_safe_task_error(code)

    try:
        validated = validate_summary_service_result(
            raw_result,
            expected_summary_type=summary_type,
            expected_source_revision_id=source_revision_id,
            expected_request_fingerprint=request_fingerprint,
        )
    except SummaryResultRejected as rejection:
        persisted = _persist_failure(task_id, attempt_id, rejection)
        code = _failure_transition_code(persisted, rejection.code)
        _raise_safe_task_error(code)

    summary_result_patch = build_summary_result_patch(
        validated,
        summary_type=summary_type,
    )
    persisted = _persist_success(task_id, attempt_id, summary_result_patch)
    if not _accepted(persisted):
        code = persisted.code if persisted.outcome == "conflict" else "SUMMARY_PERSISTENCE_FAILED"
        _raise_safe_task_error(code)

    logger.info("[CELERY_SUMMARIZE] Task complete | task_id=%s", task_id)
    return {
        "status": "success",
        "task_id": task_id,
        "result": validated.safe_result,
    }


@celery_app.task(bind=True, name='tasks.summarize_multi')
def summarize_multi_task(
    self,
    task_ids: list,
    model_name: str = None,
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE,
    case_id: str = None,
    context_analysis: dict | None = None,
    min_length: int = DEFAULT_MULTI_SUMMARY_MIN_WORDS,
    max_length: int = DEFAULT_MULTI_SUMMARY_MAX_WORDS,
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
    )
    summary_type = options.summary_type
    min_length = options.min_length
    max_length = options.max_length

    logger.info(
        f"[CELERY_MULTI_SUMMARY] Task started | count={len(task_ids)} | "
        f"celery_id={self.request.id} | case={case_id}"
    )

    transcripts = []
    for tid in task_ids:
        task = get_task(tid)
        if task and isinstance(task.get("result"), dict):
            transcript = task["result"].get("transcription")
            if isinstance(transcript, str) and transcript.strip():
                transcripts.append(transcript)

    if not transcripts:
        _raise_safe_task_error("SUMMARY_RESULT_INVALID")

    from src.services.summarization.summary_service_v2 import summarize_multi_transcripts_v2

    try:
        raw_result = summarize_multi_transcripts_v2(
            transcripts=transcripts,
            model_name=model_name,
            summary_type=summary_type,
            case_id=case_id,
            context_analysis=context_analysis,
            min_length=min_length,
            max_length=max_length,
        )
        validated = validate_summary_service_result(
            raw_result,
            multi=True,
            expected_summary_type=summary_type,
        )
    except SummaryResultRejected as rejection:
        _raise_safe_task_error(rejection.code)
    except Exception as exc:
        logger.error(
            "[CELERY_MULTI_SUMMARY] Provider call failed | error_type=%s",
            type(exc).__name__,
        )
        _raise_safe_task_error("SUMMARY_GENERATION_FAILED")

    logger.info("[CELERY_MULTI_SUMMARY] Task complete | case=%s", case_id)
    return {
        "status": "success",
        "case_id": case_id,
        "result": validated.safe_result,
    }
