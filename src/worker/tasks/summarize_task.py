"""
Summarize Task - Celery background task for summarization
Handles: Transcribe → Summarize (OPTIONAL, only if requested)
"""
import logging
from src.worker.worker import celery_app
from src.services.task_service import get_task, update_task
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

_SUMMARY_SERVICE_RESULT_FIELDS = frozenset(
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


def _summary_persistence_patch(result: dict, summary_type: SummaryType) -> dict:
    """Project service output onto the canonical stored summary fields."""

    return {
        "summary": result["summary"],
        "context_analysis": (
            result.get("context") if isinstance(result.get("context"), dict) else None
        ),
        "summary_model": result.get("model"),
        "summary_type": summary_type,
        "summary_runtime": (
            result.get("runtime") if isinstance(result.get("runtime"), dict) else {}
        ),
    }


def _safe_summary_service_result(result: dict) -> dict:
    """Preserve service/API parity without replaying visualization projections."""

    return {
        key: value
        for key, value in result.items()
        if key in _SUMMARY_SERVICE_RESULT_FIELDS
    }


def _summary_failure_message(result: object, default: str) -> str:
    if not isinstance(result, dict):
        return default
    error = result.get("error")
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    summary = result.get("summary")
    return str(summary) if summary else default


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

    try:
        # Get task to extract transcript
        task = get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Get transcript from task result (standardized to "transcription")
        transcript = None
        if task.get("result") and isinstance(task["result"], dict):
            # Transcript is stored in result["transcription"] (TaskResult schema)
            transcript = task["result"].get("transcription")

        if not transcript or not transcript.strip():
            logger.warning(f"[CELERY_SUMMARIZE] No transcription found for task {task_id}. Task result keys: {list(task.get('result', {}).keys()) if task.get('result') else 'No result'}")
            raise ValueError(f"Task {task_id} has no transcription. Run transcription first.")

        # Import here to avoid circular dependencies
        from src.services.summarization.summary_service_v2 import summarize_transcript_v2

        # Update status
        update_task(task_id, {"status": "summarizing"})

        # Execute summarization with timeout protection
        logger.info(f"[CELERY_SUMMARIZE] Starting summarization | transcript_length={len(transcript)}")

        try:
            result = summarize_transcript_v2(
                transcript=transcript,
                model_name=model_name,
                summary_type=summary_type,
                include_context=include_context,
                user_prompt=user_prompt,
                min_length=min_length,
                max_length=max_length,
            )
        except Exception as summary_error:
            logger.error(f"[CELERY_SUMMARIZE] Summarization failed: {summary_error}", exc_info=True)
            raise ValueError(f"Summarization failed: {str(summary_error)}")

        if not result.get("available"):
            error_msg = _summary_failure_message(
                result,
                "LLM not available for summarization",
            )
            logger.error(f"[CELERY_SUMMARIZE] {error_msg}")
            raise ValueError(error_msg)

        # Summary owns only this partial result patch. The task service merges it
        # atomically so independently published visualization bytes stay untouched.
        summary_result_patch = _summary_persistence_patch(result, summary_type)
        safe_result = _safe_summary_service_result(result)

        # Update task with summary
        update_task(task_id, {
            "status": "summarized",
            "result": summary_result_patch,
            "summary": result["summary"],  # Also save as direct field for backward compatibility
            "model_name": result.get("model")
        })

        logger.info(f"[CELERY_SUMMARIZE] Task complete | task_id={task_id}")

        return {
            "status": "success",
            "task_id": task_id,
            "result": safe_result,
        }

    except Exception as e:
        logger.error(f"[CELERY_SUMMARIZE] Task failed | task_id={task_id} | error={e}", exc_info=True)

        # Update task status
        try:
            update_task(task_id, {"status": "failed", "error": str(e)})
        except:
            pass

        return {
            "status": "error",
            "task_id": task_id,
            "error": str(e)
        }


@celery_app.task(bind=True, name='tasks.summarize_multi')
def summarize_multi_task(
    self,
    task_ids: list,
    model_name: str = None,
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE,
    case_id: str = None,
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
        from src.services.summarization.summary_service_v2 import summarize_multi_transcripts_v2

        # Execute multi-summarization
        result = summarize_multi_transcripts_v2(
            transcripts=transcripts,
            model_name=model_name,
            summary_type=summary_type,
            case_id=case_id,
            min_length=min_length,
            max_length=max_length,
        )

        if not result.get("available"):
            error_msg = _summary_failure_message(
                result,
                "LLM not available for multi-summary",
            )
            logger.error(f"[CELERY_MULTI_SUMMARY] {error_msg}")
            raise ValueError(error_msg)

        safe_result = _safe_summary_service_result(result)

        logger.info(f"[CELERY_MULTI_SUMMARY] Task complete | case={case_id}")

        return {
            "status": "success",
            "case_id": case_id,
            "result": safe_result,
        }

    except Exception as e:
        logger.error(f"[CELERY_MULTI_SUMMARY] Task failed | error={e}", exc_info=True)

        return {
            "status": "error",
            "case_id": case_id,
            "error": str(e)
        }
