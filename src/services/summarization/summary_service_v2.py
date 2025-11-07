"""
Summary Service v2 - Refactored with LLM Manager
OPTIONAL: Only called when user explicitly requests summarization
"""
import logging
from typing import Dict, Optional, List
from .models.llm_manager import get_llm_manager
from .context_service import analyze_conversation_context

logger = logging.getLogger(__name__)


def summarize_transcript_v2(
    transcript: str,
    model_name: str = None,
    summary_type: str = "detailed",
    include_context: bool = True,
    user_prompt: str = None,
    max_length: int = 200,
    min_length: int = 50
) -> Dict:
    """
    Summarize transcript using LLM
    
    Args:
        transcript: Text to summarize
        model_name: LLM model to use (None = auto-select)
        summary_type: Type of summary (brief, detailed, investigation)
        include_context: Include context analysis
        user_prompt: Optional user context prompt
        max_length: Maximum summary length
        min_length: Minimum summary length
        
    Returns:
        Dict with summary, context (optional), model info
    """
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
        if model_name is None:
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
        elif summary_type == "investigation":
            prompt = f"""
Phân tích cuộc hội thoại sau theo góc độ điều tra:
- Các sự kiện quan trọng theo trình tự thời gian
- Các nhân vật liên quan và vai trò
- Thông tin nhạy cảm, dấu hiệu bất thường
- Các hành động, quyết định quan trọng
- Điểm cần làm rõ thêm

{transcript}

Phân tích:
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
        
        logger.info("[SUMMARY_V2] Summary complete")
        
        return {
            "summary": summary.strip(),
            "context": context,
            "model": model_name,
            "summary_type": summary_type,
            "available": True
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


# Backward compatibility - import from old service if needed
try:
    from ..summary_service import summarize_transcript as summarize_transcript_old
    from ..summary_service import summarize_multi_transcripts as summarize_multi_transcripts_old
except ImportError:
    summarize_transcript_old = None
    summarize_multi_transcripts_old = None
