"""
Visualization Service - Generate visualization data from transcript
Handles timeline, entity graph, relationship map generation
"""
from src.core.logging import logger
from src.speech_to_text.transcriber import OllamaProcessor
from src.services.task_service import get_task, update_task
from fastapi import HTTPException


def generate_visualization(
    task_id: str,
    visualization_type: str = "all"
) -> dict:
    """
    Generate visualization data from transcript.
    
    Args:
        task_id: Task ID (must have transcript)
        visualization_type: Type of visualization (timeline, entity_graph, relationship_map, all)
        
    Returns:
        dict with nodes, edges, timeline, entity_types, main_events
    """
    logger.info(
        f"[VISUALIZATION_SERVICE] Generating visualization | "
        f"task_id={task_id} | type={visualization_type}"
    )
    
    try:
        # Get task
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Check if transcript exists
        transcript = task.get('transcript')
        if not transcript:
            raise HTTPException(
                status_code=400, 
                detail="Task must be transcribed first. Please run transcription before visualization."
            )
        
        # Use Ollama to analyze and generate visualization data
        processor = OllamaProcessor()
        
        logger.info(f"[VISUALIZATION_SERVICE] Analyzing transcript for visualization...")
        viz_data = processor.visualize_context(transcript)
        
        # Ensure all required fields exist
        if not isinstance(viz_data, dict):
            viz_data = {}
        
        # Add default values if missing
        viz_data.setdefault('nodes', [])
        viz_data.setdefault('edges', [])
        viz_data.setdefault('timeline', [])
        viz_data.setdefault('entity_types', [])
        viz_data.setdefault('main_events', [])
        
        # Filter by type if not "all"
        if visualization_type != "all":
            if visualization_type == "timeline":
                viz_data = {
                    'timeline': viz_data.get('timeline', []),
                    'main_events': viz_data.get('main_events', [])
                }
            elif visualization_type == "entity_graph":
                viz_data = {
                    'nodes': viz_data.get('nodes', []),
                    'edges': viz_data.get('edges', []),
                    'entity_types': viz_data.get('entity_types', [])
                }
            elif visualization_type == "relationship_map":
                viz_data = {
                    'nodes': viz_data.get('nodes', []),
                    'edges': viz_data.get('edges', [])
                }
        
        # Prepare response
        response = {
            "task_id": task_id,
            "status": "visualization_ready",
            "visualization_type": visualization_type,
            "data": viz_data
        }
        
        # Update task with visualization data
        update_task(task_id, {
            "visualization_data": viz_data,
            "has_visualization": True
        })
        
        logger.info(
            f"[VISUALIZATION_SERVICE] Completed | task_id={task_id} | "
            f"nodes={len(viz_data.get('nodes', []))} | "
            f"edges={len(viz_data.get('edges', []))} | "
            f"events={len(viz_data.get('main_events', []))}"
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VISUALIZATION_SERVICE] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))