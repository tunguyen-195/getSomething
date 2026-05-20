"""
Transcribe Task - Celery background task for audio transcription
Handles: Upload → Transcribe (with optional diarization)
"""
import logging
from src.worker.worker import celery_app
from src.database.config.database import get_db

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name='tasks.transcribe_audio')
def transcribe_audio_task(
    self,
    task_id: str,
    enable_diarization: bool = True,
    diarization_method: str = "pyannote",
    language: str = "auto",
    fast_mode: bool = True
):
    """
    Celery task for audio transcription

    Args:
        task_id: Task ID
        enable_diarization: Enable speaker diarization
        diarization_method: Method (pyannote, simple_vad, none)
        language: Language code
        fast_mode: Skip heavy processing

    Returns:
        Result dict or error
    """
    logger.info(
        f"[CELERY_TRANSCRIBE] Task started | task_id={task_id} | "
        f"celery_id={self.request.id} | diarization={enable_diarization}"
    )

    db = None
    try:
        # Import here to avoid circular dependencies
        from src.services.transcription.transcribe_service_v2 import transcribe_audio_v2

        # Get DB session
        db = next(get_db())

        # Execute transcription
        result = transcribe_audio_v2(
            task_id=task_id,
            db=db,
            enable_diarization=enable_diarization,
            diarization_method=diarization_method,
            language=language,
            fast_mode=fast_mode
        )

        # Ensure DB session is closed
        if db:
            try:
                db.close()
            except:
                pass

        logger.info(
            f"[CELERY_TRANSCRIBE] Task complete | task_id={task_id} | "
            f"speakers={result.get('num_speakers')} | time={result.get('processing_time'):.1f}s"
        )

        return {
            "status": "success",
            "task_id": task_id,
            "result": result
        }

    except Exception as e:
        logger.error(f"[CELERY_TRANSCRIBE] Task failed | task_id={task_id} | error={e}", exc_info=True)

        # Ensure DB session is closed even on error
        if db:
            try:
                db.close()
            except:
                pass

        # Update task status
        try:
            from src.services.task_service import update_task
            update_task(task_id, {"status": "failed", "error": str(e)})
        except Exception as update_error:
            logger.error(f"[CELERY_TRANSCRIBE] Failed to update task status: {update_error}")

        # Retry logic (optional) - only for transient errors
        if self.request.retries < 2 and not isinstance(e, (ValueError, TypeError, AttributeError)):
            logger.info(f"[CELERY_TRANSCRIBE] Retrying task {task_id}...")
            raise self.retry(exc=e, countdown=10, max_retries=2)

        return {
            "status": "error",
            "task_id": task_id,
            "error": str(e)
        }
