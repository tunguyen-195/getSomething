"""
Cherry Summarizer Integration Layer
Connects Cherry Core forensic analysis to SpeechToInformation system.
"""
import logging
import re
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Lazy import to avoid import errors if cherry_core not properly setup
_analysis_service = None

def get_analysis_service():
    """Get or create AnalysisService singleton."""
    global _analysis_service
    if _analysis_service is None:
        try:
            from src.cherry_core.services.analysis_service import AnalysisService
            _analysis_service = AnalysisService()
            logger.info("[CHERRY_SUMMARIZER] AnalysisService initialized")
        except Exception as e:
            logger.error(f"[CHERRY_SUMMARIZER] Failed to initialize: {e}")
            return None
    return _analysis_service


def parse_visualization_data(report_text: str) -> Dict[str, Any]:
    """
    Parse the plain text forensic report to extract structured data for VisualizationPanel.
    Matches the 'forensic_report.j2' sections.
    """
    viz_data = {
        "nodes": [],
        "edges": [],
        "timeline": [],
        "main_events": [],
        "entity_types": ["Person", "Location", "Phone", "Event", "Money"]
    }

    # Helper to clean text
    def clean(s): return s.strip().strip("-").strip()

    try:
        # 1. Parse Entities (Section 3: INFO & 4: FINANCE)
        # 3. THÔNG TIN NHÂN THÂN
        # Expect: "Họ tên đầy đủ: ABC", "Số điện thoại: 123", "Địa chỉ: XYZ"

        # Regex for generic key-value extraction in Section 3
        # Match lines like "   Key: Value" or "- Key: Value"
        person_matches = re.findall(r"(?:Họ tên đầy đủ|Tên|Đối tượng)[:\s]+(.+)", report_text, re.IGNORECASE)
        for p in person_matches:
            if clean(p) and clean(p).lower() != "[không có]":
                viz_data["nodes"].append({"id": clean(p), "label": clean(p), "type": "Person"})

        phone_matches = re.findall(r"(?:Số điện thoại|SĐT)[:\s]+(.+)", report_text, re.IGNORECASE)
        for p in phone_matches:
            if clean(p) and clean(p).lower() != "[không có]":
                viz_data["nodes"].append({"id": clean(p), "label": clean(p), "type": "Phone"})

        loc_matches = re.findall(r"(?:Địa chỉ|Nơi ở|Địa điểm)[:\s]+(.+)", report_text, re.IGNORECASE)
        for l in loc_matches:
             if clean(l) and clean(l).lower() != "[không có]":
                viz_data["nodes"].append({"id": clean(l), "label": clean(l), "type": "Location"})

        # 4. THÔNG TIN TÀI CHÍNH
        money_matches = re.findall(r"(?:Số tiền|Giao dịch)[:\s]+(.+)", report_text, re.IGNORECASE)
        for m in money_matches:
             if clean(m) and clean(m).lower() != "[không có]":
                # Create a node for the transaction
                viz_data["nodes"].append({"id": clean(m), "label": clean(m), "type": "Money"})

        # 2. Parse Timeline (Section 5: MỐC THỜI GIAN)
        # Look for the section
        timeline_section = re.search(r"5\. MỐC THỜI GIAN QUAN TRỌNG:(.*?)(?=\n\d+\.|\Z)", report_text, re.DOTALL)
        if timeline_section:
            lines = timeline_section.group(1).strip().split('\n')
            for line in lines:
                line = clean(line)
                if not line: continue
                # Try to split date - event
                # e.g. "12/10/2023 - Gặp mặt" or "10:30: Gọi điện"
                parts = re.split(r"[-:]", line, 1)
                if len(parts) >= 2:
                    time_str = parts[0].strip()
                    event_str = parts[1].strip()
                    viz_data["timeline"].append({"time": time_str, "event": event_str})
                    viz_data["main_events"].append(event_str) # Also add to main events
                else:
                    viz_data["timeline"].append({"time": "", "event": line})
                    viz_data["main_events"].append(line)

        # 3. Parse Relationships (Edges) - Infer from context
        # If we have people and phones, link them (naive) -> Actually hard without specific grammar.
        # But we can try to link Person -> Phone if they appear on same line in original report?
        # The prompt output format separates them.
        # Let's just create edges if "Người gọi" and "Người nghe" are identified in Section 9.

        behavior_section = re.search(r"9\. PHÂN TÍCH HÀNH VI:(.*?)(?=\n\d+\.|\Z)", report_text, re.DOTALL)
        if behavior_section:
            content = behavior_section.group(1)
            caller = re.search(r"Người gọi[:\s]+(.+)", content)
            listener = re.search(r"Người nghe[:\s]+(.+)", content)

            caller_name = clean(caller.group(1)) if caller else "Người gọi"
            listener_name = clean(listener.group(1)) if listener else "Người nghe"

            if caller_name and listener_name:
                viz_data["edges"].append({"from": caller_name, "to": listener_name, "label": "Liên lạc"})

        # Deduplicate nodes
        unique_nodes = {}
        for n in viz_data["nodes"]:
            if n["id"] not in unique_nodes:
                unique_nodes[n["id"]] = n
        viz_data["nodes"] = list(unique_nodes.values())

    except Exception as e:
        logger.warning(f"[CHERRY_SUMMARIZER] Failed to parse visualization data: {e}")

    return viz_data


def summarize_forensic(
    transcript: str,
    scenario: str = "general_intelligence",
    fallback_to_existing: bool = True
) -> Dict:
    """
    Generate forensic analysis report using Cherry Core.
    Returns Dict with summary, and visualization data.
    """
    try:
        service = get_analysis_service()
        if service is None:
            raise RuntimeError("AnalysisService not available")

        # Analyze using LLM
        result = service.analyze_transcript(transcript, scenario)

        # Parse for visualization
        report_text = result.get("summary", "")
        viz_data = parse_visualization_data(report_text)

        # Merge viz data into result
        result["visualization_data"] = viz_data
        result["has_visualization"] = True

        logger.info(f"[CHERRY_SUMMARIZER] Forensic analysis complete | scenario={scenario}")
        return result

    except Exception as e:
        logger.error(f"[CHERRY_SUMMARIZER] Cherry Core failed: {e}")

        if fallback_to_existing:
            logger.info("[CHERRY_SUMMARIZER] Falling back to existing LLM...")
            return _fallback_summarize(transcript)

        return {
            "summary": f"Error: {str(e)}",
            "scenario": scenario,
            "model": None,
            "format": "error",
            "has_visualization": False,
            "visualization_data": {}
        }


def _fallback_summarize(transcript: str) -> Dict:
    """Fallback to existing summarization service."""
    try:
        from src.services.summarization.summary_service_v2 import summarize_transcript_v2
        result = summarize_transcript_v2(
            transcript=transcript,
            summary_type="investigation",
            include_context=True
        )
        return {
            "summary": result.get("summary", ""),
            "scenario": "fallback",
            "model": result.get("model"),
            "format": "investigation",
            "visualization_data": {}, # Fallback usually doesn't have structured viz yet
            "has_visualization": False
        }
    except Exception as e:
        logger.error(f"[CHERRY_SUMMARIZER] Fallback also failed: {e}")
        return {
            "summary": f"Both Cherry Core and fallback failed: {e}",
            "scenario": "error",
            "model": None,
            "format": "error",
            "visualization_data": {},
            "has_visualization": False
        }


def check_cherry_core_available() -> bool:
    """Check if Cherry Core is properly configured and available."""
    try:
        from src.cherry_core.config import MODELS_DIR
        # Check if models directory exists
        if not MODELS_DIR.exists():
            return False

        # Check if llama_cpp is installed
        try:
            from llama_cpp import Llama
        except ImportError:
            return False

        return True
    except Exception:
        return False
