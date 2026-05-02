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
    Uses regex patterns to extract basic entities from Vietnamese text.
    """
    logger.info("[FALLBACK_VIZ] Using regex-based extraction (Ollama unavailable)")

    nodes = []
    edges = []
    timeline = []
    main_events = []
    node_id_counter = {'person': 0, 'location': 0, 'time': 0, 'phone': 0, 'event': 0}

    # Vietnamese name patterns (Nguyễn, Trần, Lê, etc.)
    name_pattern = r'\b((?:Ông|Bà|Anh|Chị|Em|Cô|Chú|Bác|Thầy|Cô)\s+)?([A-ZÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ][a-zàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]+(?:\s+[A-ZÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ][a-zàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]+){1,3})\b'

    # Phone patterns
    phone_pattern = r'\b(0\d{9,10}|\+84\d{9,10}|\d{3}[-.\s]?\d{3}[-.\s]?\d{4})\b'

    # Time patterns (Vietnamese)
    time_pattern = r'\b(\d{1,2}[:/h]\d{2}|\d{1,2}\s*giờ(?:\s*\d{1,2}\s*phút)?|sáng|chiều|tối|đêm|hôm nay|ngày mai|hôm qua|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b'

    # Location patterns
    location_pattern = r'\b((?:số\s+)?\d+\s+(?:đường|phố|ngõ|ngách|hẻm)\s+[A-ZĐa-zđ\s]+|(?:phường|quận|huyện|xã|thị trấn|thành phố|tỉnh)\s+[A-ZĐa-zđ\s]+|khách sạn\s+[A-ZĐa-zđ\s]+|nhà hàng\s+[A-ZĐa-zđ\s]+)\b'

    # Extract names
    seen_names = set()
    for match in re.finditer(name_pattern, text, re.IGNORECASE):
        name = match.group(2).strip()
        if name and len(name) > 2 and name not in seen_names:
            seen_names.add(name)
            node_id_counter['person'] += 1
            nodes.append({
                'id': f"person_{node_id_counter['person']}",
                'label': name,
                'type': 'person',
                'importance': 7
            })

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

    # Extract locations
    for match in re.finditer(location_pattern, text, re.IGNORECASE):
        loc = match.group(1).strip()
        if loc:
            node_id_counter['location'] += 1
            nodes.append({
                'id': f"location_{node_id_counter['location']}",
                'label': loc,
                'type': 'location',
                'importance': 6
            })

    # Extract sentence-like events (sentences with verbs)
    sentences = re.split(r'[.!?]', text)
    event_keywords = ['đặt', 'thuê', 'mua', 'bán', 'gọi', 'hẹn', 'gặp', 'đến', 'đi', 'nhận', 'gửi', 'trả', 'thanh toán', 'xác nhận', 'hủy']
    for sent in sentences[:10]:  # Limit to first 10 sentences
        sent = sent.strip()
        if len(sent) > 15:
            for keyword in event_keywords:
                if keyword in sent.lower():
                    main_events.append(sent[:100])  # Truncate long sentences
                    break

    # Create edges between people and locations/times
    person_nodes = [n for n in nodes if n['type'] == 'person']
    other_nodes = [n for n in nodes if n['type'] != 'person']

    for p in person_nodes[:3]:  # Limit edges
        for o in other_nodes[:3]:
            edges.append({
                'from': p['id'],
                'to': o['id'],
                'label': 'liên quan',
                'type': 'related_to'
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
        # Get task
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # Check if transcript exists (check multiple locations for compatibility)
        transcript = task.get('transcript')
        if not transcript:
            # Try to get from result (v2 format stores in result.transcription)
            result = task.get('result', {})
            if isinstance(result, str):
                import json
                try:
                    result = json.loads(result)
                except:
                    result = {}
            transcript = result.get('transcription') or result.get('transcript') or result.get('text')

        if not transcript:
            raise HTTPException(
                status_code=400,
                detail="Task must be transcribed first. Please run transcription before visualization."
            )

        # Try Ollama first, fallback to regex if fail
        viz_data = {}
        use_fallback = False

        try:
            processor = OllamaProcessor()
            logger.info(f"[VISUALIZATION_SERVICE] Trying Ollama analysis...")
            viz_data = processor.visualize_context(transcript)

            # Check if Ollama returned valid data (non-empty nodes or timeline)
            if not viz_data or (not viz_data.get('nodes') and not viz_data.get('timeline')):
                logger.warning("[VISUALIZATION_SERVICE] Ollama returned empty data, using fallback")
                use_fallback = True
        except Exception as ollama_error:
            logger.warning(f"[VISUALIZATION_SERVICE] Ollama failed: {ollama_error}, using fallback")
            use_fallback = True

        # Use fallback extraction if Ollama failed
        if use_fallback:
            viz_data = fallback_extract_visualization(transcript)

        # Normalize and validate visualization data
        viz_data = normalize_viz_data(viz_data)


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

        viz_data = extract_visualization_payload(viz_data)

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
            logger.info(f"[VISUALIZATION_SERVICE] Saved visualization_data to Task.result")
        except Exception as e:
            logger.warning(f"[VISUALIZATION_SERVICE] Failed to save visualization to result: {e}")


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
