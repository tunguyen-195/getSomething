from src.worker.worker import celery_app
from src.services.audio_service import process_task

@celery_app.task(bind=True)
def process_task_async(self, task_id, model_name, db_url=None):
    """
    Celery task để xử lý process_task ở chế độ nền.
    db_url: nếu cần, truyền vào để tạo session mới (tránh dùng session cũ).
    """
    from src.database.config.database import get_db
    db = next(get_db())
    return process_task(task_id, model_name, db)
