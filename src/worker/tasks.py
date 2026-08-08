from src.worker.worker import celery_app
from src.services.audio_service import process_task_with_diarization

@celery_app.task(bind=True)
def process_task_async(self, task_id, model_name, diarization_method="none"):
    """
    Celery task để xử lý process_task ở chế độ nền.
    Each Celery task owns and closes its SQLAlchemy Session.
    """
    from src.database.config.database import SessionLocal

    with SessionLocal() as db:
        try:
            return process_task_with_diarization(
                task_id, model_name, db, diarization_method
            )
        except Exception:
            db.rollback()
            raise
