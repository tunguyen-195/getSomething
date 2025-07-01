from celery import Celery
from src.core.config import settings

# Create Celery app
celery_app = Celery(
    "speech_to_information",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["src.worker.tasks"],
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour
    worker_max_tasks_per_child=100,
    worker_prefetch_multiplier=1,
    broker_transport_options={
        "visibility_timeout": 3600,
        "max_retries": 20,
        "retry_on_timeout": True,
        "socket_connect_timeout": 10,
        "socket_timeout": 10,
    },
    result_backend_transport_options={
        "retry_policy": {"timeout": 10.0},
    },
)

# Import tasks
from src.worker.tasks import *  # noqa 