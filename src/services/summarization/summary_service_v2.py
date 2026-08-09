"""
Summary Service v2 - Refactored with LLM Manager
OPTIONAL: Only called when user explicitly requests summarization
"""
import logging
from typing import Dict, List
from src.services.investigation.narrative_attestation import (
    released_narrative_metadata,
    render_released_narrative_text,
)
from .contracts import (
    DEFAULT_MULTI_SUMMARY_MAX_WORDS,
    DEFAULT_MULTI_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_MAX_WORDS,
    DEFAULT_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_TYPE,
    SummaryType,
    evaluate_summary_length,
    validate_summary_request_options,
)
from .models.llm_manager import get_llm_manager
from .context_service import analyze_conversation_context

logger = logging.getLogger(__name__)


def _summarize_released_investigation_narrative(
    *,
    released_narrative: object | None,
    model_name: str | None,
    min_length: int,
    max_length: int,
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

    length_contract = evaluate_summary_length(
        summary,
        min_length=min_length,
        max_length=max_length,
    )
    if not length_contract["maximum_met"]:
        return {
            "summary": "",
            "context": None,
            "model": None,
            "requested_model": model_name,
            "summary_type": "investigation",
            "available": False,
            "error": {
                "code": "SUMMARY_MAX_LENGTH_EXCEEDED",
                "message": (
                    f"Released narrative contains {length_contract['actual']} words; "
                    f"maximum is {max_length}."
                ),
            },
            "runtime": {"length_contract": length_contract},
        }

    return {
        "summary": summary,
        "context": None,
        "model": None,
        "requested_model": model_name,
        "summary_type": "investigation",
        "available": True,
        "release": metadata,
        "runtime": {
            "llm_call_count": 0,
            "last_generation": None,
            "visualization_projection": "not_requested",
            "summary_generation": "attested_deterministic_projection",
            "length_contract": length_contract,
        },
    }


def summarize_transcript_v2(
    transcript: str,
    model_name: str = None,
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE,
    include_context: bool = True,
    user_prompt: str = None,
    max_length: int = DEFAULT_SUMMARY_MAX_WORDS,
    min_length: int = DEFAULT_SUMMARY_MIN_WORDS,
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
        min_length: Advisory target; short complete summaries remain releasable

    Returns:
        Dict with summary, context (optional), model info
    """
    options = validate_summary_request_options(
        summary_type=summary_type,
        min_length=min_length,
        max_length=max_length,
    )
    summary_type = options.summary_type
    min_length = options.min_length
    max_length = options.max_length

    if summary_type == "investigation":
        return _summarize_released_investigation_narrative(
            released_narrative=released_narrative,
            model_name=model_name,
            min_length=min_length,
            max_length=max_length,
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
                summary = summary.strip() if isinstance(summary, str) else ""
                length_contract = evaluate_summary_length(
                    summary,
                    min_length=min_length,
                    max_length=max_length,
                )
                if not summary:
                    return {
                        "summary": "",
                        "context": None,
                        "model": model_name,
                        "summary_type": summary_type,
                        "available": False,
                        "error": {
                            "code": "SUMMARY_EMPTY",
                            "message": "The llama.cpp backend returned an empty summary.",
                        },
                        "runtime": {"length_contract": length_contract},
                    }

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

                if not length_contract["maximum_met"]:
                    return {
                        "summary": "",
                        "context": context,
                        "model": model_name,
                        "summary_type": summary_type,
                        "available": False,
                        "error": {
                            "code": "SUMMARY_MAX_LENGTH_EXCEEDED",
                            "message": (
                                f"Generated summary contains {length_contract['actual']} "
                                f"words; maximum is {max_length}."
                            ),
                        },
                        "runtime": {"length_contract": length_contract},
                    }
                return {
                    "summary": summary,
                    "context": context,
                    "model": model_name,
                    "summary_type": summary_type,
                    "available": True,
                    "engine": "llama.cpp",
                    "runtime": {"length_contract": length_contract},
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
                "summary": "",
                "context": None,
                "model": None,
                "summary_type": summary_type,
                "available": False,
                "error": {
                    "code": "LLM_UNAVAILABLE",
                    "message": "LLM not available for summarization.",
                },
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
Tóm tắt ngắn gọn cuộc hội thoại sau. Mục tiêu khoảng {min_length} từ nếu evidence
đủ, nhưng không thêm nội dung để đạt độ dài. Tuyệt đối không vượt quá {max_length} từ:

{transcript}

Tóm tắt:
"""
        else:  # detailed
            prompt = f"""
Tóm tắt chi tiết cuộc hội thoại sau. Mục tiêu khoảng {min_length} từ nếu evidence
đủ, nhưng không thêm nội dung để đạt độ dài. Tuyệt đối không vượt quá {max_length} từ:
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
        if not summary or not summary.strip():
            raise Exception("Generated summary is empty")

        summary = summary.strip()
        length_contract = evaluate_summary_length(
            summary,
            min_length=min_length,
            max_length=max_length,
        )
        if not length_contract["maximum_met"]:
            return {
                "summary": "",
                "context": context,
                "model": model_name,
                "summary_type": summary_type,
                "available": False,
                "error": {
                    "code": "SUMMARY_MAX_LENGTH_EXCEEDED",
                    "message": (
                        f"Generated summary contains {length_contract['actual']} words; "
                        f"maximum is {max_length}."
                    ),
                },
                "runtime": {"length_contract": length_contract},
            }

        logger.info("[SUMMARY_V2] Summary complete")

        return {
            "summary": summary,
            "context": context,
            "model": model_name,
            "summary_type": summary_type,
            "available": True,
            "runtime": {
                "visualization_projection": "not_requested",
                "length_contract": length_contract,
            },
        }

    except Exception as e:
        logger.error(f"[SUMMARY_V2] Error: {e}", exc_info=True)
        return {
            "summary": "",
            "context": None,
            "model": model_name,
            "summary_type": summary_type,
            "available": False,
            "error": {
                "code": "SUMMARY_GENERATION_FAILED",
                "message": "Summary generation failed.",
            },
        }


def summarize_multi_transcripts_v2(
    transcripts: List[str],
    model_name: str = None,
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE,
    case_id: str = None,
    max_length: int = DEFAULT_MULTI_SUMMARY_MAX_WORDS,
    min_length: int = DEFAULT_MULTI_SUMMARY_MIN_WORDS,
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
    options = validate_summary_request_options(
        summary_type=summary_type,
        min_length=min_length,
        max_length=max_length,
    )
    summary_type = options.summary_type
    min_length = options.min_length
    max_length = options.max_length

    if summary_type in {"investigation", "forensic"}:
        return {
            "summary": "",
            "num_transcripts": len(transcripts),
            "model": model_name,
            "summary_type": summary_type,
            "case_id": case_id,
            "available": False,
            "error": {
                "code": "MULTI_EVIDENCE_RELEASE_REQUIRED",
                "message": (
                    "Multi-file investigation or forensic summaries require a "
                    "released evidence narrative."
                ),
            },
        }

    try:
        llm_mgr = get_llm_manager()

        if not llm_mgr.check_availability():
            logger.warning("[SUMMARY_V2] LLM not available for multi-summary")
            return {
                "summary": "",
                "num_transcripts": len(transcripts),
                "model": model_name,
                "summary_type": summary_type,
                "case_id": case_id,
                "available": False,
                "error": {
                    "code": "LLM_UNAVAILABLE",
                    "message": "LLM not available for multi-summary.",
                },
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
            max_tokens=min(2048, max(256, max_length * 4)),
        )

        summary = summary.strip()
        length_contract = evaluate_summary_length(
            summary,
            min_length=min_length,
            max_length=max_length,
        )
        if not summary:
            return {
                "summary": "",
                "num_transcripts": len(transcripts),
                "model": model_name,
                "summary_type": summary_type,
                "case_id": case_id,
                "available": False,
                "error": {
                    "code": "SUMMARY_EMPTY",
                    "message": "The LLM backend returned an empty multi-summary.",
                },
                "runtime": {"length_contract": length_contract},
            }
        if not length_contract["maximum_met"]:
            return {
                "summary": "",
                "num_transcripts": len(transcripts),
                "model": model_name,
                "summary_type": summary_type,
                "case_id": case_id,
                "available": False,
                "error": {
                    "code": "SUMMARY_MAX_LENGTH_EXCEEDED",
                    "message": (
                        f"Generated multi-summary contains {length_contract['actual']} "
                        f"words; maximum is {max_length}."
                    ),
                },
                "runtime": {"length_contract": length_contract},
            }

        logger.info("[SUMMARY_V2] Multi-summary complete")

        return {
            "summary": summary,
            "num_transcripts": len(transcripts),
            "model": model_name,
            "summary_type": summary_type,
            "case_id": case_id,
            "available": True,
            "runtime": {"length_contract": length_contract},
        }

    except Exception as e:
        logger.error(f"[SUMMARY_V2] Multi-summary error: {e}", exc_info=True)
        return {
            "summary": "",
            "num_transcripts": len(transcripts),
            "model": model_name,
            "summary_type": summary_type,
            "case_id": case_id,
            "available": False,
            "error": {
                "code": "SUMMARY_GENERATION_FAILED",
                "message": "Multi-summary generation failed.",
            },
        }


# Note: Old summary_service.py in summarization/ directory no longer exists
# All summarization functionality is now in this v2 module
# For database CRUD operations, see src/services/summary_service.py
