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
        "src.worker.tasks.batch_task",
        "src.worker.tasks.summarize_task",
        "src.worker.tasks.runtime_contract_task",
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
    task_time_limit=7200,  # 2 hours for heavy transcription
    task_soft_time_limit=7000,  # Soft limit before hard kill
    task_acks_late=True,  # Acknowledge task after completion (not before)
    task_reject_on_worker_lost=True,  # Reject task if worker dies
    worker_max_tasks_per_child=0,  # 0 = unlimited (no restart after X tasks)
    worker_prefetch_multiplier=1,
    worker_concurrency=1,  # Process 1 task at a time (sequential)
    worker_pool_restarts=True,  # Auto-restart pool on failure
    broker_connection_retry=True,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=10,
    broker_transport_options={
        "visibility_timeout": 7200,
        "max_retries": 30,
        "retry_on_timeout": True,
        "socket_connect_timeout": 60,  # Increased from 30s to 60s
        "socket_timeout": 90,  # Increased from 30s to 90s (gevent needs more time)
        "socket_keepalive": True,
        "socket_keepalive_options": {
            1: 120,  # TCP_KEEPIDLE: 120 seconds before sending keepalive probes
            2: 10,   # TCP_KEEPINTVL: 10 seconds between keepalive probes
            3: 6     # TCP_KEEPCNT: 6 probes before declaring connection dead
        },
        "health_check_interval": 30,  # Check connection health every 30s
    },
    result_backend_transport_options={
        "retry_policy": {
            "timeout": 90.0,  # Increased from 30s to 90s
            "max_retries": 10
        },
        "socket_timeout": 90,  # Match broker timeout
        "socket_connect_timeout": 60,
    },
    # Prevent worker shutdown after task
    worker_disable_rate_limits=True,
    worker_lost_wait=10.0,
)

# Import old tasks for backward compatibility
from src.worker.tasks import *  # noqa

# Import new modular tasks
from src.worker.tasks.transcribe_task import transcribe_audio_task  # noqa
from src.worker.tasks.batch_task import transcribe_audio_batch_task  # noqa
from src.worker.tasks.summarize_task import (  # noqa
    summarize_audio_batch_job_task,
    summarize_multi_task,
    summarize_transcript_task,
)
from src.worker.tasks.runtime_contract_task import worker_runtime_contract_task  # noqa
from src.worker.tasks.visualize_task import visualize_task  # noqa
