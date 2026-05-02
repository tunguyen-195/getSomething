"""
Visualize Task - Celery background task for visualization
Handles: Transcribe → Visualize (entity graph, timeline, etc.)
"""
import logging
from src.worker.worker import celery_app
from src.services.task_service import get_task, update_task

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

        transcript = task.get("transcript")
        if not transcript:
            raise ValueError(f"Task {task_id} has no transcript. Run transcription first.")

        # Import here to avoid circular dependencies
        from src.services.task_service import extract_visualization_payload
        from src.services.visualization_service import generate_visualization

        # Update status
        update_task(task_id, {"status": "visualizing"})

        # Execute visualization
        result = generate_visualization(
            task_id=task_id,
            visualization_type=visualization_type
        )
        payload = extract_visualization_payload(result)

        # Update task with visualization data
        update_task(task_id, {
            "status": "visualized",
            "visualization": payload,
            "has_visualization": True,
        })

        logger.info(f"[CELERY_VISUALIZE] Task complete | task_id={task_id}")

        return {
            "status": "success",
            "task_id": task_id,
            "result": result
        }

    except Exception as e:
        logger.error(f"[CELERY_VISUALIZE] Task failed | task_id={task_id} | error={e}", exc_info=True)

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
