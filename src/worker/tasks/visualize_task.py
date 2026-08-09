"""
Visualize Task - Celery background task for visualization
Handles: Transcribe → Visualize (entity graph, timeline, etc.)
"""
import logging
from src.worker.worker import celery_app
from src.services.task_service import get_task

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name='tasks.visualize')
def visualize_task(
    self,
    task_id: str,
    visualization_type: str = "all"
):
    """
    Celery task for visualization generation

    Args:
        task_id: Task ID (must have transcript)
        visualization_type: Type (timeline, entity_graph, relationship_map, all)

    Returns:
        Result dict or error
    """
    logger.info(
        f"[CELERY_VISUALIZE] Task started | task_id={task_id} | "
        f"celery_id={self.request.id} | type={visualization_type}"
    )

    try:
        # Get task to extract transcript
        task = get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        task_result = task.get("result") if isinstance(task.get("result"), dict) else {}
        released_run = task_result.get("released_investigation_run")

        # Import here to avoid circular dependencies.
        from src.services.visualization_service import generate_visualization

        result = generate_visualization(
            released_run=released_run,
            visualization_type=visualization_type
        )

        logger.info(f"[CELERY_VISUALIZE] Task complete | task_id={task_id}")

        return {
            "status": "success",
            "task_id": task_id,
            "result": result
        }

    except Exception as e:
        logger.error(f"[CELERY_VISUALIZE] Task failed | task_id={task_id} | error={e}", exc_info=True)

        return {
            "status": "error",
            "task_id": task_id,
            "error": str(e)
        }
