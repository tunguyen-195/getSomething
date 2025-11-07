"""
Celery Tasks - Separated by workflow
Each task handles one specific operation
"""
# New modular tasks
from .transcribe_task import transcribe_audio_task
from .summarize_task import summarize_transcript_task, summarize_multi_task
from .visualize_task import visualize_task

# Old task from tasks.py for backward compatibility (v1 API)
import importlib.util
import os
spec = importlib.util.spec_from_file_location("old_tasks", os.path.join(os.path.dirname(__file__), "..", "tasks.py"))
old_tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old_tasks)
process_task_async = old_tasks.process_task_async

__all__ = [
    'transcribe_audio_task',
    'summarize_transcript_task',
    'summarize_multi_task',
    'visualize_task',
    'process_task_async'  # v1 API compatibility
]
