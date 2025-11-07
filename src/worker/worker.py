from celery import Celery
from src.core.config import settings

# Create Celery app
celery_app = Celery(
    "speech_to_information",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "src.worker.tasks",  # Old tasks for backward compatibility
        "src.worker.tasks.transcribe_task",
        "src.worker.tasks.summarize_task",
        "src.worker.tasks.visualize_task"
    ],
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
    worker_max_tasks_per_child=0,  # 0 = unlimited (no restart after X tasks)
    worker_prefetch_multiplier=1,
    worker_concurrency=1,  # Process 1 task at a time (sequential)
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

# Import old tasks for backward compatibility
from src.worker.tasks import *  # noqa

# Import new modular tasks
from src.worker.tasks.transcribe_task import transcribe_audio_task  # noqa
from src.worker.tasks.summarize_task import summarize_transcript_task, summarize_multi_task  # noqa
from src.worker.tasks.visualize_task import visualize_task  # noqa 