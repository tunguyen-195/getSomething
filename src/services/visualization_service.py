"""
Visualization Service - Generate visualization data from transcript
Handles timeline, entity graph, relationship map generation
"""
import re
from src.core.logging import logger
from src.speech_to_text.transcriber import OllamaProcessor
from src.services.task_service import extract_visualization_payload, get_task, update_task
from fastapi import HTTPException


def fallback_extract_visualization(text: str) -> dict:
    """
    Fallback extraction when Ollama is unavailable.
    Uses only high-precision regex patterns. It intentionally does not infer
    people, events, or relationships.
    """
    logger.info("[FALLBACK_VIZ] Using regex-based extraction (Ollama unavailable)")

    nodes = []
    edges = []
    timeline = []
    main_events = []
    node_id_counter = {'time': 0, 'phone': 0}

    # Phone patterns
    phone_pattern = r'\b(0\d{9,10}|\+84\d{9,10}|\d{3}[-.\s]?\d{3}[-.\s]?\d{4})\b'

    # Time patterns (Vietnamese)
    time_pattern = r'\b(\d{1,2}[:/h]\d{2}|\d{1,2}\s*giờ(?:\s*\d{1,2}\s*phút)?|sáng|chiều|tối|đêm|hôm nay|ngày mai|hôm qua|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b'

    # Extract phone numbers
    for match in re.finditer(phone_pattern, text):
        phone = match.group(1)
        node_id_counter['phone'] += 1
        nodes.append({
            'id': f"phone_{node_id_counter['phone']}",
            'label': phone,
            'type': 'contact',
            'importance': 5
        })

    # Extract times
    seen_times = set()
    for match in re.finditer(time_pattern, text, re.IGNORECASE):
        time_val = match.group(1).strip()
        if time_val and time_val not in seen_times:
            seen_times.add(time_val)
            node_id_counter['time'] += 1
            nodes.append({
                'id': f"time_{node_id_counter['time']}",
                'label': time_val,
                'type': 'time',
                'importance': 5
            })
            timeline.append({
                'time': time_val,
                'event': f'Sự kiện lúc {time_val}'
            })

    logger.info(f"[FALLBACK_VIZ] Extracted: {len(nodes)} nodes, {len(edges)} edges, {len(main_events)} events")

    return {
        'nodes': nodes,
        'edges': edges,
        'timeline': timeline,
        'main_events': main_events[:5],  # Limit events
        'entity_types': list(set(n['type'] for n in nodes)),
        'summary': {'topic': 'Hội thoại', 'source': 'fallback_extraction'},
        'sentiment': {'overall': 'neutral', 'confidence': 0.5},
        'insights': ['Dữ liệu trích xuất tự động (không dùng AI)']
    }




def normalize_viz_data(viz_data: dict) -> dict:
    """
    Normalize and validate visualization data.
    - Ensures unique node IDs
    - Filters invalid edges (must reference existing nodes)
    - Sorts timeline chronologically
    - Adds missing required fields
    """
    if not isinstance(viz_data, dict):
        return {
            'nodes': [], 'edges': [], 'timeline': [],
            'entity_types': [], 'main_events': []
        }

    # Ensure unique node IDs
    seen_ids = set()
    unique_nodes = []
    for node in viz_data.get('nodes', []):
        if not isinstance(node, dict):
            continue
        node_id = node.get('id')
        if node_id in seen_ids:
            # Generate unique ID
            counter = 1
            while f"{node_id}_{counter}" in seen_ids:
                counter += 1
            node['id'] = f"{node_id}_{counter}"
        seen_ids.add(node['id'])
        unique_nodes.append(node)
    viz_data['nodes'] = unique_nodes

    # Filter invalid edges (must reference existing nodes)
    valid_ids = {n['id'] for n in viz_data.get('nodes', [])}
    valid_edges = []
    for edge in viz_data.get('edges', []):
        if not isinstance(edge, dict):
            continue
        from_id = edge.get('from') or edge.get('source')
        to_id = edge.get('to') or edge.get('target')
        if from_id in valid_ids and to_id in valid_ids:
            # Normalize field names
            edge['from'] = from_id
            edge['to'] = to_id
            valid_edges.append(edge)
    viz_data['edges'] = valid_edges

    # Sort timeline - try to sort by time field
    timeline = viz_data.get('timeline', [])
    if isinstance(timeline, list):
        # Sort by time if available, otherwise keep order
        def get_sort_key(item):
            if not isinstance(item, dict):
                return 'zzz'
            time_val = item.get('time', '') or ''
            # Handle common patterns
            if 'đầu' in time_val.lower() or 'ban đầu' in time_val.lower():
                return 'aaa'
            if 'cuối' in time_val.lower() or 'sau' in time_val.lower():
                return 'yyy'
            return time_val.lower()
        viz_data['timeline'] = sorted(timeline, key=get_sort_key)

    # Ensure all required fields exist
    viz_data.setdefault('entity_types', list(set(
        n.get('type', 'unknown') for n in viz_data.get('nodes', [])
    )))
    viz_data.setdefault('main_events', [])
    viz_data.setdefault('summary', {})
    viz_data.setdefault('sentiment', {'overall': 'neutral', 'confidence': 0.5})
    viz_data.setdefault('insights', [])

    logger.info(
        f"[NORMALIZE_VIZ] nodes={len(viz_data['nodes'])} | "
        f"edges={len(viz_data['edges'])} | timeline={len(viz_data['timeline'])}"
    )

    return viz_data


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
        from src.services.analysis_intelligence.service import generate_task_graph

        graph = generate_task_graph(task_id, visualization_type)
        viz_data = graph.to_storage_dict()

        # Prepare response
        response = {
            "task_id": task_id,
            "status": "visualization_ready",
            "visualization_type": visualization_type,
            "data": viz_data,
            "visualization_data": viz_data,
            "has_visualization": True,
        }

        # Update task with visualization data - MUST merge into result JSON.
        # update_task also unwraps wrapper-shaped payloads for compatibility.
        try:
            update_task(task_id, {"visualization_data": response, "has_visualization": True})
            logger.info("[VISUALIZATION_SERVICE] Saved evidence-grounded visualization_data")
        except Exception as e:
            logger.warning(f"[VISUALIZATION_SERVICE] Failed to save visualization to result: {e}")


        logger.info(
            f"[VISUALIZATION_SERVICE] Completed | task_id={task_id} | "
            f"entities={len(viz_data.get('entities', []))} | "
            f"relations={len(viz_data.get('relations', []))} | "
            f"events={len(viz_data.get('events', []))}"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VISUALIZATION_SERVICE] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
