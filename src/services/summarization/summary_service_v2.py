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
        summary_type: Type of summary (brief, detailed, investigation, forensic)
        include_context: Include context analysis
        user_prompt: Optional user context prompt
        max_length: Maximum summary length
        min_length: Minimum summary length

    Returns:
        Dict with summary, context (optional), model info
    """
    # Use Cherry Core for forensic analysis
    if summary_type == "forensic" or model_name == "forensic":
        try:
            from src.services.cherry_summarizer import summarize_forensic, check_cherry_core_available
            if check_cherry_core_available():
                logger.info("[SUMMARY_V2] Using Cherry Core for forensic analysis")
                result = summarize_forensic(transcript, scenario="general_intelligence")
                return {
                    "summary": result.get("summary", ""),
                    "context": None,
                    "model": result.get("model"),
                    "summary_type": "forensic",
                    "available": True,
                    "visualization_data": result.get("visualization_data"),
                    "has_visualization": result.get("has_visualization", False)
                }
        except Exception as e:
            logger.warning(f"[SUMMARY_V2] Cherry Core failed, falling back: {e}")
            # Fall through to investigation type
            summary_type = "investigation"

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
        elif summary_type == "investigation":
            prompt = f"""
PHÂN TÍCH HỘI THOẠI CHO ĐIỀU TRA HÌNH SỰ

Bạn là chuyên gia phân tích hội thoại phục vụ điều tra tội phạm. Hãy phân tích cuộc hội thoại sau một cách CHI TIẾT, TOÀN DIỆN, KHÔNG GIỚI HẠN ĐỘ DÀI.

YÊU CẦU QUAN TRỌNG: Viết phân tích dưới dạng PLAIN TEXT, KHÔNG dùng markdown syntax (không dùng ###, ***, ---, -, *, v.v.). Sử dụng số thứ tự và xuống dòng để tổ chức nội dung.

HỘI THOẠI CẦN PHÂN TÍCH:
{transcript}

Hãy phân tích theo cấu trúc sau:

1. TÓM TẮT TOÀN DIỆN
Tóm tắt đầy đủ toàn bộ nội dung hội thoại, không bỏ sót chi tiết nào. Mô tả rõ ràng ngữ cảnh, mục đích cuộc trò chuyện. KHÔNG GIỚI HẠN ĐỘ DÀI.

2. THÔNG TIN NHÂN THÂN (ƯU TIÊN CAO)
Họ tên đầy đủ: [liệt kê tất cả người tham gia]
Số điện thoại: [tất cả số xuất hiện, ghi rõ chủ sở hữu]
Số CCCD/CMND/Hộ chiếu: [nếu có, ghi rõ chủ sở hữu]
Địa chỉ: [địa chỉ cụ thể với số nhà, đường, phường, quận, thành phố]
Email: [nếu có, ghi rõ chủ sở hữu]
Ngày sinh/Tuổi: [nếu có]
Nghề nghiệp/Nơi làm việc: [nếu có]
Biển số xe: [nếu có]
Tài khoản ngân hàng/Ví điện tử: [nếu có, ghi rõ số TK, ngân hàng, chủ TK]

3. THÔNG TIN TÀI CHÍNH
Số tiền giao dịch: [chính xác đến đồng, ghi rõ mục đích]
Phương thức thanh toán: [chuyển khoản, tiền mặt, ví điện tử, v.v.]
Thông tin tài khoản: [số TK, tên ngân hàng, chủ tài khoản]
Lịch sử giao dịch: [nếu được nhắc đến]
Khoản nợ/Khoản vay: [nếu có]
Ưu đãi tài chính: [nếu có]

4. THỜI GIAN VÀ ĐỊA ĐIỂM
Thời điểm cuộc gọi: [nếu xác định được]
Các thời gian được nhắc đến: [ngày, giờ, khoảng thời gian cụ thể]
Địa điểm cụ thể: [tên địa điểm, địa chỉ đầy đủ]
Lịch trình di chuyển: [nếu có]

5. HÀNH ĐỘNG VÀ GIAO DỊCH
Hành động đã thực hiện: [liệt kê chi tiết]
Hành động hẹn thực hiện: [liệt kê chi tiết]
Thỏa thuận/Cam kết: [nếu có]
Điều kiện giao dịch: [nếu có]
Quy trình thanh toán: [mô tả chi tiết]
Bước tiếp theo: [sau cuộc gọi]

6. MỐI QUAN HỆ
Quan hệ giữa các bên: [mô tả chi tiết vai trò và mối quan hệ]
Người thứ ba được nhắc đến: [tên, vai trò]
Tổ chức liên quan: [công ty, đơn vị]
Mối liên hệ ẩn: [nếu phát hiện được]

7. DẤU HIỆU BẤT THƯỜNG
Thái độ bất thường: [mô tả cụ thể nếu có]
Mâu thuẫn trong lời nói: [chi tiết nếu phát hiện]
Thông tin không nhất quán: [chi tiết nếu có]
Từ chối cung cấp thông tin: [ghi nhận nếu có]
Yêu cầu bí mật: [nếu có]
Giao dịch bất thường: [số tiền lớn, phương thức lạ]
Hành vi vội vã: [nếu phát hiện]
Ngôn ngữ mã hóa: [nếu có]

8. TIẾNG LÓNG VÀ MẬT NGỮ
Từ ngữ lạ/Không thông dụng: [liệt kê và giải thích nếu có]
Ẩn ý/Ngụ ý: [phân tích nếu phát hiện]
Mã số/Biệt danh: [nếu có]
Ngôn ngữ ngầm: [ví dụ: "đồ", "hàng", "deal" - giải thích nếu có]

9. CÁC BÊN THAM GIA
Với mỗi người trong cuộc gọi, mô tả:
Vai trò: [vai trò cụ thể trong cuộc gọi]
Thái độ/Cảm xúc: [bình tĩnh, lo lắng, hài lòng, tức giận, v.v.]
Mức độ hợp tác: [cao, trung bình, thấp]
Thông tin cung cấp/Giấu giếm: [phân tích]

10. RỦI RO VÀ CẢNH BÁO
Nguy cơ tội phạm: [lừa đảo, rửa tiền, buôn lậu - nếu phát hiện dấu hiệu]
Hoạt động phi pháp: [mô tả nếu có dấu hiệu]
Thông tin cần xác minh khẩn cấp: [liệt kê cụ thể]
Mối đe dọa an ninh: [nếu có]

11. ĐIỂM CẦN LÀM RÕ
Thông tin còn thiếu: [liệt kê cụ thể]
Mâu thuẫn cần điều tra: [chi tiết]
Câu hỏi cần truy vấn: [liệt kê]
Đối tượng/Địa điểm cần giám sát: [nếu có]

12. GHI CHÚ ĐIỀU TRA
Đánh giá tổng quan: [nhận định chung về cuộc gọi]
Mức độ nguy hiểm: [Thấp/Trung bình/Cao/Rất cao]
Khuyến nghị hành động: [cụ thể các bước tiếp theo]
Ưu tiên điều tra: [Thấp/Trung bình/Cao/Khẩn cấp]

LƯU Ý QUAN TRỌNG:
- Viết phân tích dưới dạng plain text, KHÔNG dùng markdown (###, ***, ---, -, *)
- Thông tin nhân thân (họ tên, số điện thoại, CCCD, địa chỉ) phải được trích xuất đầy đủ
- Nếu không có thông tin cho mục nào, ghi "Không có thông tin" hoặc "Cần xác minh thêm"
- KHÔNG GIỚI HẠN ĐỘ DÀI, viết chi tiết càng tốt

PHÂN TÍCH ĐIỀU TRA:
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
