"""
Summary Service v2 - Refactored with LLM Manager
OPTIONAL: Only called when user explicitly requests summarization
"""
import logging
from typing import Dict, Optional, List
from src.services.investigation.narrative_attestation import (
    released_narrative_metadata,
    render_released_narrative_text,
)
from .models.llm_manager import get_llm_manager
from .context_service import analyze_conversation_context

logger = logging.getLogger(__name__)


def _summarize_released_investigation_narrative(
    *,
    released_narrative: object | None,
    model_name: str | None,
    source_metadata: dict | None,
) -> Dict:
    """Render only the deterministic projection minted by the T5 release gate."""

    if released_narrative is None:
        return {
            "summary": "",
            "context": None,
            "model": None,
            "requested_model": model_name,
            "summary_type": "investigation",
            "available": False,
            "error": {
                "code": "INVESTIGATION_NARRATIVE_ATTESTATION_REQUIRED",
                "message": (
                    "Investigation summaries require a trusted released narrative."
                ),
            },
        }

    try:
        summary = render_released_narrative_text(released_narrative).strip()
        metadata = released_narrative_metadata(released_narrative)
    except Exception as exc:
        logger.warning(
            "[SUMMARY_V2] Released investigation narrative rejected | error=%s",
            type(exc).__name__,
        )
        return {
            "summary": "",
            "context": None,
            "model": None,
            "requested_model": model_name,
            "summary_type": "investigation",
            "available": False,
            "error": {
                "code": "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID",
                "message": "The released narrative failed trusted attestation replay.",
            },
        }

    expected_revision = str((source_metadata or {}).get("source_revision_id") or "")
    actual_revision = str(metadata.get("source_revision_id") or "")
    if expected_revision and actual_revision != expected_revision:
        return {
            "summary": "",
            "context": None,
            "model": None,
            "requested_model": model_name,
            "summary_type": "investigation",
            "available": False,
            "error": {
                "code": "INVESTIGATION_SOURCE_REVISION_MISMATCH",
                "message": (
                    "Released narrative does not match the requested source revision."
                ),
            },
        }
    if not summary:
        return {
            "summary": "",
            "context": None,
            "model": None,
            "requested_model": model_name,
            "summary_type": "investigation",
            "available": False,
            "error": {
                "code": "INVESTIGATION_NARRATIVE_EMPTY",
                "message": "The trusted released narrative is empty.",
            },
        }

    return {
        "summary": summary,
        "context": None,
        "model": None,
        "requested_model": model_name,
        "summary_type": "investigation",
        "available": True,
        "release": metadata,
        "visualization_data": None,
        "has_visualization": False,
        "runtime": {
            "llm_call_count": 0,
            "last_generation": None,
            "summary_generation": "attested_deterministic_projection",
        },
    }


def summarize_transcript_v2(
    transcript: str,
    model_name: str = None,
    summary_type: str = "detailed",
    include_context: bool = True,
    user_prompt: str = None,
    max_length: int = 200,
    min_length: int = 50,
    source_metadata: dict | None = None,
    released_narrative: object | None = None,
) -> Dict:
    """
    Summarize transcript using LLM

    Args:
        transcript: Text to summarize
        model_name: LLM model to use (None = auto-select)
        summary_type: Type of summary (brief, detailed, investigation, forensic)
        include_context: Include context analysis
        user_prompt: Optional user context prompt
        max_length: Maximum summary length
        min_length: Minimum summary length

    Returns:
        Dict with summary, context (optional), model info
    """
    if summary_type == "investigation":
        return _summarize_released_investigation_narrative(
            released_narrative=released_narrative,
            model_name=model_name,
            source_metadata=source_metadata,
        )

    # Use Cherry Core for forensic analysis
    if summary_type == "forensic" or model_name == "forensic":
        return {
            "summary": "",
            "context": None,
            "model": model_name,
            "summary_type": "forensic",
            "available": False,
            "error": {
                "code": "FORENSIC_LEGACY_PROVIDER_DISABLED",
                "message": (
                    "Legacy forensic generation is disabled because it is not bound "
                    "to the canonical evidence-grounded investigation contract."
                ),
            },
        }

    # Use LlamaCppAdapter for vistral/qwen3 (llama.cpp - faster, Vietnamese support)
    if model_name in ["vistral", "qwen3"]:
        try:
            from src.cherry_core.adapters.llm.llamacpp_adapter import LlamaCppAdapter
            logger.info(f"[SUMMARY_V2] Using LlamaCpp with model: {model_name}")

            adapter = LlamaCppAdapter(model_type=model_name)
            if adapter.load():
                # Build prompt
                prompt = f"""Bạn là chuyên gia phân tích điều tra. Tóm tắt chi tiết cuộc hội thoại sau bằng tiếng Việt:

{transcript}

TÓM TẮT CHI TIẾT:
"""
                summary = adapter.generate(prompt, max_tokens=2048, temperature=0.1)

                # Context analysis via adapter
                context = None
                if include_context:
                    context_prompt = f"""Phân tích và trích xuất thông tin quan trọng từ cuộc hội thoại sau:

{transcript}

Trả về dạng JSON với các trường: entities, events, relationships, key_info.
"""
                    try:
                        context_raw = adapter.generate(context_prompt, max_tokens=1024, temperature=0.1)
                        import json
                        context = json.loads(context_raw)
                    except:
                        context = {"raw": context_raw if 'context_raw' in dir() else None}

                return {
                    "summary": summary,
                    "context": context,
                    "model": model_name,
                    "summary_type": summary_type,
                    "available": True,
                    "engine": "llama.cpp"
                }
            else:
                logger.warning(f"[SUMMARY_V2] LlamaCpp failed to load {model_name}, falling back to Ollama")
        except Exception as e:
            logger.warning(f"[SUMMARY_V2] LlamaCpp error: {e}, falling back to Ollama")

    # Default: Use Ollama via LLM Manager
    try:
        llm_mgr = get_llm_manager()

        if not llm_mgr.check_availability():
            logger.warning("[SUMMARY_V2] LLM not available")
            return {
                "summary": "LLM not available for summarization",
                "context": None,
                "model": None,
                "available": False
            }

        # Select model if not specified
        if model_name is None or model_name in ["vistral", "qwen3"]:  # Fallback to Ollama
            model_name = llm_mgr.select_best_model()

        logger.info(
            f"[SUMMARY_V2] Summarizing | model={model_name} | "
            f"type={summary_type} | context={include_context}"
        )

        # Step 1: Context analysis (optional)
        context = None
        if include_context:
            logger.info("[SUMMARY_V2] Analyzing context...")
            context = analyze_conversation_context(transcript, model_name, user_prompt)

        # Step 2: Generate summary
        logger.info("[SUMMARY_V2] Generating summary...")

        # Build prompt based on summary type
        if summary_type == "brief":
            prompt = f"""
Tóm tắt ngắn gọn cuộc hội thoại sau (1-2 câu, tối đa {min_length} từ):

{transcript}

Tóm tắt:
"""
        else:  # detailed
            prompt = f"""
Tóm tắt chi tiết cuộc hội thoại sau ({min_length}-{max_length} từ):
- Nội dung chính
- Các điểm quan trọng
- Kết luận/quyết định (nếu có)

{transcript}

Tóm tắt:
"""

        # Add user prompt if provided
        if user_prompt:
            prompt += f"\n\nYêu cầu bổ sung: {user_prompt}"

        # Generate summary
        summary = llm_mgr.generate(
            prompt,
            model=model_name,
            temperature=0.7,
            max_tokens=max_length * 5  # Roughly 5 chars per token
        )

        # Validate summary
        if not summary or len(summary) < 10:
             raise Exception("Generated summary is too short or empty")

        # Step 3: Extract structured data for visualization (Analysis Tab)
        # This replaces the regex-based extraction in frontend
        visualization_data = {}
        try:
            if summary_type in ["investigation", "detailed", "forensic"]:
                logger.info("[SUMMARY_V2] Extracting structured data for visualization...")

                extract_prompt = f"""
Trích xuất các thực thể từ văn bản sau thành format JSON phục vụ phân tích điều tra.
Chỉ trả về JSON hợp lệ, không có markdown formatting.

Format JSON yêu cầu:
{{
  "nodes": [
    {{"id": "p1", "label": "Tên Người 1", "type": "person"}},
    {{"id": "l1", "label": "Địa điểm 1", "type": "place"}}
  ],
  "edges": [],
  "main_events": ["Sự kiện 1", "Sự kiện 2"],
  "timeline": [
    {{"time": "Ngày/Giờ", "event": "Mô tả sự kiện"}}
  ],
  "extracted_entities": [
    {{"type": "money", "value": "Số tiền", "context": "Ngữ cảnh"}},
    {{"type": "phone", "value": "SĐT", "context": "Chủ sở hữu"}},
    {{"type": "email", "value": "Email", "context": "Chủ sở hữu"}}
  ]
}}

Văn bản cần trích xuất:
{summary}

Lưu ý:
- "type" của nodes chỉ nhận: "person", "place", "organization"
- Nếu không có thông tin, trả về danh sách rỗng []
- Trích xuất tối đa các thông tin quan trọng.
"""
                extraction = llm_mgr.generate(
                    extract_prompt,
                    model=model_name,
                    temperature=0.3, # Low temp for structured output
                    max_tokens=1024
                )

                # Parse JSON safely
                import json
                import re

                # Cleanup markdown code blocks if present
                clean_json = extraction.replace("```json", "").replace("```", "").strip()
                try:
                    visualization_data = json.loads(clean_json)
                    logger.info(f"[SUMMARY_V2] Extracted: {len(visualization_data.get('nodes', []))} nodes, {len(visualization_data.get('main_events', []))} events")
                except json.JSONDecodeError:
                    logger.warning(f"[SUMMARY_V2] Failed to parse extraction JSON: {clean_json[:100]}...")
                    # Fallback empty
                    visualization_data = {}

        except Exception as e_extract:
            logger.error(f"[SUMMARY_V2] Extraction error: {e_extract}")
            # Non-fatal, continue with valid summary

        logger.info("[SUMMARY_V2] Summary complete")

        return {
            "summary": summary.strip(),
            "context": context,
            "model": model_name,
            "summary_type": summary_type,
            "available": True,
            "visualization_data": visualization_data,
            "has_visualization": bool(visualization_data)
        }

    except Exception as e:
        logger.error(f"[SUMMARY_V2] Error: {e}", exc_info=True)
        return {
            "summary": f"Error: {str(e)}",
            "context": None,
            "model": model_name,
            "available": False
        }


def summarize_multi_transcripts_v2(
    transcripts: List[str],
    model_name: str = None,
    summary_type: str = "detailed",
    case_id: str = None
) -> Dict:
    """
    Summarize multiple transcripts into one comprehensive summary

    Args:
        transcripts: List of transcript texts
        model_name: LLM model to use
        summary_type: Type of summary
        case_id: Case ID for context

    Returns:
        Dict with summary and metadata
    """
    try:
        llm_mgr = get_llm_manager()

        if not llm_mgr.check_availability():
            logger.warning("[SUMMARY_V2] LLM not available for multi-summary")
            return {
                "summary": "LLM not available",
                "num_transcripts": len(transcripts),
                "available": False
            }

        if model_name is None:
            model_name = llm_mgr.select_best_model()

        logger.info(
            f"[SUMMARY_V2] Multi-summary | count={len(transcripts)} | "
            f"model={model_name} | case={case_id}"
        )

        # Combine transcripts
        combined = "\n\n---\n\n".join(f"File {i+1}:\n{t}" for i, t in enumerate(transcripts))

        # Build prompt
        prompt = f"""
Tóm tắt tổng hợp từ {len(transcripts)} cuộc hội thoại sau:
- Nội dung chính từ tất cả các cuộc hội thoại
- Mối liên hệ giữa các cuộc hội thoại (nếu có)
- Các điểm quan trọng xuyên suốt
- Kết luận tổng thể

{combined}

Tóm tắt tổng hợp:
"""

        summary = llm_mgr.generate(
            prompt,
            model=model_name,
            temperature=0.7,
            max_tokens=1024
        )

        logger.info("[SUMMARY_V2] Multi-summary complete")

        return {
            "summary": summary.strip(),
            "num_transcripts": len(transcripts),
            "model": model_name,
            "case_id": case_id,
            "available": True
        }

    except Exception as e:
        logger.error(f"[SUMMARY_V2] Multi-summary error: {e}", exc_info=True)
        return {
            "summary": f"Error: {str(e)}",
            "num_transcripts": len(transcripts),
            "available": False
        }


# Note: Old summary_service.py in summarization/ directory no longer exists
# All summarization functionality is now in this v2 module
# For database CRUD operations, see src/services/summary_service.py
