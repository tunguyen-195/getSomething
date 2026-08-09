"""
Summarize Task - Celery background task for summarization
Handles: Transcribe → Summarize (OPTIONAL, only if requested)
"""
import logging
from src.worker.worker import celery_app
from src.services.task_service import get_task, update_task

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name='tasks.summarize_transcript')
def summarize_transcript_task(
    self,
    task_id: str,
    model_name: str = None,
    summary_type: str = "detailed",
    include_context: bool = True,
    user_prompt: str = None
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
                user_prompt=user_prompt
            )
        except Exception as summary_error:
            logger.error(f"[CELERY_SUMMARIZE] Summarization failed: {summary_error}", exc_info=True)
            raise ValueError(f"Summarization failed: {str(summary_error)}")

        if not result.get("available"):
            error_msg = result.get("summary", "LLM not available for summarization")
            logger.error(f"[CELERY_SUMMARIZE] {error_msg}")
            raise ValueError(error_msg)

        # Summary owns only this partial result patch. The task service merges it
        # atomically so independently published visualization bytes stay untouched.
        summary_result_patch = {
            "summary": result["summary"],
            "context_analysis": result.get("context") or None,
            "summary_model": result.get("model"),
            "summary_type": summary_type,
            "summary_runtime": result.get("runtime") or {},
        }

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
            "result": result
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
    summary_type: str = "detailed",
    case_id: str = None
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
            case_id=case_id
        )

        logger.info(f"[CELERY_MULTI_SUMMARY] Task complete | case={case_id}")

        return {
            "status": "success",
            "case_id": case_id,
            "result": result
        }

    except Exception as e:
        logger.error(f"[CELERY_MULTI_SUMMARY] Task failed | error={e}", exc_info=True)

        return {
            "status": "error",
            "case_id": case_id,
            "error": str(e)
        }
