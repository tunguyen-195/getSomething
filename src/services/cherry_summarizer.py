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
    try:
        from src.services.analysis_intelligence.service import generate_text_graph

        graph = generate_text_graph(
            report_text,
            source_kind="report_text",
            source_method="cherry_report_derived",
        )
        return graph.to_storage_dict()
    except Exception as e:
        logger.warning(f"[CHERRY_SUMMARIZER] Failed to parse visualization data: {e}")
        return {
            "nodes": [],
            "edges": [],
            "timeline": [],
            "main_events": [],
            "entity_types": [],
        }


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
