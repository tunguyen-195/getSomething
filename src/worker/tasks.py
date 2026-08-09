import inspect

from src.worker.worker import celery_app
from src.services.audio_service import process_task_with_diarization
from src.services.task_service import safe_summary_message


class SafeProcessTaskError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(safe_summary_message("SUMMARY_GENERATION_FAILED"))

@celery_app.task(bind=True)
def process_task_async(self, task_id, model_name, diarization_method="none"):
    """
    Celery task để xử lý process_task ở chế độ nền.
    Each Celery task owns and closes its SQLAlchemy Session.
    """
    from src.database.config.database import SessionLocal

    with SessionLocal() as db:
        try:
            kwargs = {}
            if "summary_attempt_id" in inspect.signature(
                process_task_with_diarization
            ).parameters:
                kwargs["summary_attempt_id"] = (
                    str(self.request.id) if self.request.id else None
                )
            return process_task_with_diarization(
                task_id,
                model_name,
                db,
                diarization_method,
                **kwargs,
            )
        except Exception:
            db.rollback()
            raise SafeProcessTaskError() from None
