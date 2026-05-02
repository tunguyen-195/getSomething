"""
Context Analysis Service
Separate service for analyzing conversation context using LLM
OPTIONAL: Only called when explicitly requested
"""
import logging
from typing import Dict, Optional
from .models.llm_manager import get_llm_manager

logger = logging.getLogger(__name__)


def analyze_conversation_context(
    transcript: str,
    model_name: str = None,
    user_prompt: str = None
) -> Optional[Dict]:
    """
    Analyze conversation context using LLM

    Args:
        transcript: Text to analyze
        model_name: LLM model to use (None = auto-select best)
        user_prompt: Optional user-provided context prompt

    Returns:
        Context analysis dict or None if LLM not available
    """
    try:
        llm_mgr = get_llm_manager()

        if not llm_mgr.check_availability():
            logger.warning("[CONTEXT_SERVICE] LLM not available, skipping context analysis")
            return None

        logger.info(f"[CONTEXT_SERVICE] Analyzing context | model={model_name or 'auto'}")

        # Build prompt
        base_prompt = """
Phân tích hội thoại sau và trích xuất thông tin chi tiết theo cấu trúc JSON.
Tập trung vào:
- Thực thể: người, địa điểm, thời gian, tổ chức
- Mối quan hệ giữa các thực thể
- Hành động, quyết định, ưu đãi
- Cảm xúc, thái độ
- Thông tin nhạy cảm

"""

        if user_prompt:
            base_prompt += f"\nYêu cầu bổ sung: {user_prompt}\n"

        base_prompt += f"\nHội thoại:\n{transcript}\n\nJSON:"

        # Use LLM manager
        result = llm_mgr.analyze_context(transcript, model=model_name)

        logger.info("[CONTEXT_SERVICE] Context analysis complete")
        return result

    except Exception as e:
        logger.error(f"[CONTEXT_SERVICE] Error: {e}", exc_info=True)
        return None


def extract_entities(context: Dict) -> Dict:
    """
    Extract entities from context analysis

    Args:
        context: Context analysis dict

    Returns:
        Entities dict with people, locations, time, etc.
    """
    if not context:
        return {"people": [], "locations": [], "time": [], "organizations": []}

    entities = context.get("entities", {})

    return {
        "people": entities.get("people", []),
        "locations": entities.get("locations", []),
        "time": entities.get("time", []),
        "organizations": entities.get("organizations", []),
        "contact_info": entities.get("contact_info", [])
    }


def extract_relationships(context: Dict) -> list:
    """
    Extract relationships from context analysis

    Args:
        context: Context analysis dict

    Returns:
        List of relationships
    """
    if not context:
        return []

    return context.get("relationships", [])


def extract_key_points(context: Dict) -> list:
    """
    Extract key points from context analysis

    Args:
        context: Context analysis dict

    Returns:
        List of key points
    """
    if not context:
        return []

    return context.get("key_points", [])
