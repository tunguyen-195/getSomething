import os
import shutil
import json
from fastapi import UploadFile, HTTPException
from pathlib import Path
from src.core.logging import logger
from src.database.models.models import AudioFile
from src.services.task_service import create_task, update_task, get_task
from src.speech_to_text.transcriber import Transcriber, OllamaProcessor
from src.audio_processing.processor import AudioProcessor

def save_audio_and_create_task(file: UploadFile, db, case_id: int = None) -> dict:
    """Lưu file audio vào storage/audio, tạo AudioFile và Task (status: pending). Trả về task_id, audio_file_id."""
    logger.info(f"[AUDIO_SERVICE] Bắt đầu lưu file: {file.filename if file else 'None'} | case_id={case_id}")
    try:
        if not file.filename or not file.filename.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
            raise HTTPException(status_code=400, detail="Invalid or missing file format")
        audio_storage_dir = Path("storage/audio")
        audio_storage_dir.mkdir(parents=True, exist_ok=True)
        audio_storage_path = audio_storage_dir / file.filename
        with open(audio_storage_path, "wb") as out_file:
            shutil.copyfileobj(file.file, out_file)
        if case_id is not None and not isinstance(case_id, int):
            try:
                case_id = int(case_id)
            except Exception:
                raise HTTPException(status_code=400, detail="case_id phải là số nguyên")
        task = create_task(file.filename, case_id=case_id, db=db)
        if not task:
            raise HTTPException(status_code=400, detail="Case ID không tồn tại hoặc không thể tạo task")
        audio_file = AudioFile(
            filename=file.filename,
            case_id=case_id,
            task_id=task["id"],
            file_path=str(audio_storage_path),
            status="pending",
            language_id=1,
            uploaded_by=1,
            file_size=os.path.getsize(audio_storage_path),
            duration=None,
            audio_status_id=None,
            processed_at=None,
            error_message=None,
            updated_at=None,
            is_archived=False,
            archive_reason=None,
            storage_type='local',
            storage_config='{}',
            extra_metadata='{}'
        )
        db.add(audio_file)
        db.commit()
        db.refresh(audio_file)
        logger.info(f"[AUDIO_SERVICE] Đã lưu file: {file.filename if file else 'None'} | task_id={task['id']} | audio_file_id={audio_file.id}")
        return {"task_id": task["id"], "audio_file_id": audio_file.id, "status": "pending"}
    except Exception as e:
        logger.error(f"Error saving audio and creating task: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

def process_task(task_id: str, model_name: str, db) -> dict:
    """Xử lý task: transcribe, summarize, update DB. Trả về kết quả gọn."""
    logger.info(f"[AUDIO_SERVICE] Bắt đầu process_task | task_id={task_id} | model_name={model_name}")
    try:
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        audio_file = db.query(AudioFile).filter(AudioFile.task_id == task_id).first()
        if not audio_file:
            raise HTTPException(status_code=404, detail="Audio file not found")
        audio_processor = AudioProcessor()
        audio, sr = audio_processor.load_audio(audio_file.file_path)
        # Tự động enhance nếu phát hiện nhiễu (placeholder)
        # if audio_processor.normalize_audio(audio).std() < 0.01:  # Giả lập phát hiện nhiễu
        audio = audio_processor.enhance_speech_llase(audio)
        # Có thể thêm các bước robust khác ở đây
        # Sửa: chỉ khởi tạo Transcriber không truyền tham số
        transcriber = Transcriber()
        result = transcriber.transcribe(audio_file.file_path)
        logger.info(f"[AUDIO_SERVICE] Kết quả transcribe | task_id={task_id} | result={result}")
        # Benchmark tự động (placeholder)
        wer, cer, noise_score = benchmark_asr(result.get("transcription"), audio_file.file_path)
        logger.info(f"[AUDIO_SERVICE] Benchmark | WER={wer}, CER={cer}, noise_score={noise_score}")
        if wer > 0.3 or noise_score > 0.5:
            logger.warning(f"[BENCHMARK] WER cao ({wer}), noise ({noise_score}), cần cải tiến pipeline!")
        transcript = result.get("transcription")
        caption = result.get("caption")
        if not transcript or not transcript.strip():
            logger.warning(f"[AUDIO_SERVICE] Không nhận diện được nội dung từ file âm thanh | task_id={task_id}")
            update_task(task_id, {"status": "failed", "error": "Không nhận diện được nội dung từ file âm thanh."})
            audio_file.status = "failed"
            db.commit()
            return {"status": "failed", "error": "Không nhận diện được nội dung từ file âm thanh."}
        context_analysis = result.get("context_analysis") or result.get("analysis")
        if not isinstance(context_analysis, dict):
            context_analysis = {}
        # Nếu có caption, truyền vào context để tóm tắt sâu hơn
        if caption:
            context_analysis["caption"] = caption
        summary = summarize_transcript(transcript, context=context_analysis, model_name=model_name)
        logger.info(f"[AUDIO_SERVICE] Kết quả summarize | task_id={task_id} | summary={summary}")
        update_task(task_id, {
            "status": "completed",
            "result": {
                "filename": audio_file.filename,
                "duration": result.get("duration"),
                "transcription": transcript,
                "caption": caption,
                "summary": summary,
                "language": result.get("language"),
                "confidence": result.get("confidence"),
                "processing_time": result.get("processing_time"),
                "context_analysis": context_analysis,
                "audio_url": f"/storage/audio/{audio_file.filename}"
            }
        })
        audio_file.status = "completed"
        db.commit()
        # Chuẩn hóa schema trả về cho API
        def safe_str(val):
            try:
                return str(val)
            except Exception:
                return ""
        def safe_float(val):
            try:
                return float(val)
            except Exception:
                return 0.0
        def safe_dict(val):
            return val if isinstance(val, dict) else {}
        safe_result = {
            "status": "completed",
            "filename": safe_str(audio_file.filename),
            "duration": safe_float(result.get("duration", 0)),
            "transcription": safe_str(transcript) if transcript else "",
            "caption": safe_str(caption) if caption else "",
            "summary": safe_str(summary) if summary else "",
            "language": safe_str(result.get("language", "vi")),
            "confidence": safe_float(result.get("confidence", 0)),
            "processing_time": safe_float(result.get("processing_time", 0)),
            "context_analysis": safe_dict(context_analysis),
            "audio_url": f"/storage/audio/{audio_file.filename}"
        }
        logger.info(f"[AUDIO_SERVICE] Kết quả trả về process_task: {safe_result}")
        return safe_result
    except Exception as e:
        logger.error(f"Error processing task {task_id}: {str(e)}", exc_info=True)
        # Log chi tiết lỗi
        with open('logs/error_benchmark.log', 'a', encoding='utf-8') as f:
            f.write(f"Task {task_id} error: {str(e)}\n")
        return {"status": "failed", "error": str(e)}

def summarize_transcript(transcript: str, context: dict = None, model_name: str = "gemma2:9b", user_context_prompt: str = None, max_length: int = 150, min_length: int = 50) -> str:
    if not transcript:
        return "Không có tóm tắt."
    if context is None:
        context = OllamaProcessor(model_name="gemma2:9b").analyze_context(transcript)
    if context is None:
        context = {}
    if model_name.startswith("ollama:"):
        model = model_name.split(":", 1)[1]
    else:
        model = model_name
    user_prompt = (user_context_prompt + "\n") if user_context_prompt else ""
    if model in ["gemma2:9b", "deepseek-r1:7b", "mistral:7b-instruct", "llama3.2:3b"]:
        prompt = (
            user_prompt +
            """
Bạn là một trợ lý AI nghiệp vụ. Hãy tóm tắt hội thoại dưới đây một cách CHI TIẾT, PHÂN TÍCH SÂU, tập trung vào các trường thông tin sau (bắt buộc liệt kê nếu có, không bỏ sót):

- Nội dung tổng quan: Viết 5-6 dòng, nêu rõ bối cảnh, mục đích, các bên tham gia, diễn biến chính, kết quả, cảm xúc tổng thể.
- Thực thể:
  * Người: Liệt kê đầy đủ tên, vai trò, thông tin liên hệ (số điện thoại, email, số giấy tờ nếu có).
  * Địa điểm: Tên, địa chỉ.
  * Thời gian: Ngày, giờ, khoảng thời gian.
- Mối quan hệ giữa các thực thể (ai liên hệ với ai, vai trò, quan hệ nghiệp vụ).
- Mục đích, chủ đề hội thoại.
- Các điểm chính: Liệt kê từng ý quan trọng, giá trị, số lượng, dịch vụ, giá tiền, tổng tiền, ưu đãi, điều kiện đặc biệt...
- Hành động của từng bên (ai làm gì, xác nhận gì, quyết định gì).
- Cảm xúc của từng bên (hài lòng, thỏa mãn, lo lắng, nghi ngờ, v.v.).
- Thông tin nhạy cảm: Liệt kê rõ từng trường (số điện thoại, email, số giấy tờ, thông tin cá nhân...).
- Kết luận cuối cùng: Kết quả giao dịch, xác nhận đặt phòng, các cam kết hoặc hành động tiếp theo.

**Phân tích sâu về dấu hiệu vi phạm pháp luật, hành vi xấu, sử dụng tiếng lóng, ẩn ý, hoặc trao đổi đáng ngờ:**
- Nếu phát hiện bất kỳ dấu hiệu nào liên quan đến vi phạm pháp luật, hành vi xấu, trao đổi đáng ngờ, sử dụng tiếng lóng, ẩn ý, hãy phân tích kỹ, giải thích rõ ràng, cảnh báo và phân nhóm riêng các nội dung này.
- Nếu có, hãy liệt kê chi tiết: ai, hành vi gì, bằng chứng, mức độ nghiêm trọng, khả năng vi phạm, ý nghĩa của tiếng lóng/ẩn ý, tác động tiềm ẩn.
- Nếu không phát hiện, hãy xác nhận rõ ràng là không có dấu hiệu bất thường.

Nếu có context_analysis, hãy ưu tiên sử dụng để làm rõ tóm tắt. Trình bày rõ ràng, phân nhóm từng mục, không bỏ sót trường nào nếu có trong hội thoại.

"""
        )
        if context and 'summary' in context:
            prompt += f"\nTóm tắt ngữ cảnh: {context['summary']}"
        if context and 'key_points' in context and context['key_points']:
            prompt += f"\nCác điểm chính: {', '.join(context['key_points'])}"
        if context and 'entities' in context and context['entities']:
            prompt += f"\nThực thể: {json.dumps(context['entities'], ensure_ascii=False)}"
        if context and 'privacy_summary' in context:
            prompt += f"\nThông tin nhạy cảm: {context['privacy_summary']}"
        prompt += f"\nNội dung hội thoại: {transcript}"
        import requests
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "top_k": 40,
                    "num_ctx": 4096,
                    "max_tokens": max_length
                }
            }
        )
        if response.status_code == 200:
            result = response.json()
            deep_summary = result.get("response", "Không có tóm tắt.")
        else:
            deep_summary = "Không thể tóm tắt (Ollama lỗi)."
        main_prompt = (
            user_prompt +
            "Hãy tóm tắt tổng quan hội thoại dưới đây trong 5-6 dòng, nêu rõ bối cảnh, mục đích, các bên tham gia, diễn biến chính, kết quả, cảm xúc tổng thể. Không liệt kê chi tiết, chỉ trình bày tổng quan sâu sắc.\n"
            f"Nội dung hội thoại: {transcript}"
        )
        response_main = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": main_prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "top_k": 40,
                    "num_ctx": 4096,
                    "max_tokens": 120
                }
            }
        )
        if response_main.status_code == 200:
            main_summary = response_main.json().get("response", "")
        else:
            main_summary = ""
        if main_summary:
            return f"Nội dung tổng quan: {main_summary.strip()}\n\n{deep_summary.strip()}"
        else:
            return deep_summary.strip()
    else:
        from src.summarization.summarizer import Summarizer
        summarizer = Summarizer(model_name=model)
        if context:
            prompt = (
                user_prompt +
                "Tóm tắt hội thoại dưới đây một cách chi tiết, tập trung vào các thông tin quan trọng, các thực thể (người, địa điểm, thời gian, liên hệ), các quyết định, hành động, cảm xúc, mối quan hệ, mức độ nhạy cảm, mục đích, chủ đề, và các điểm chính.\n"
            )
            if 'summary' in context:
                prompt += f"\nTóm tắt ngữ cảnh: {context['summary']}"
            if 'key_points' in context and context['key_points']:
                prompt += f"\nCác điểm chính: {', '.join(context['key_points'])}"
            if 'entities' in context and context['entities']:
                prompt += f"\nThực thể: {json.dumps(context['entities'], ensure_ascii=False)}"
            if 'privacy_summary' in context:
                prompt += f"\nThông tin nhạy cảm: {context['privacy_summary']}"
            prompt += f"\nNội dung hội thoại: {transcript}"
            deep_summary = summarizer.summarize(prompt, context=context, max_length=max_length, min_length=min_length)
        else:
            deep_summary = summarizer.summarize(transcript, context=context, max_length=max_length, min_length=min_length)
        main_prompt = (
            user_prompt +
            "Hãy tóm tắt ngắn gọn, rõ ràng, dễ hiểu nội dung chính nhất của cuộc trò chuyện dưới đây trong 1-2 câu. Chỉ trình bày tổng quan, không liệt kê chi tiết.\n"
            f"Nội dung hội thoại: {transcript}"
        )
        main_summary = summarizer.summarize(main_prompt, context=context, max_length=60, min_length=20)
        if main_summary:
            return f"Nội dung chính: {main_summary.strip()}\n\n{deep_summary.strip()}"
        else:
            return deep_summary.strip()

def summarize_multi_transcripts(transcripts: list[str], context: dict = None, model_name: str = "gemma2:9b") -> str:
    if not transcripts:
        return "Không có transcript nào để tóm tắt."
    if context is None and transcripts:
        context = OllamaProcessor(model_name="gemma2:9b").analyze_context('\n'.join(transcripts))
    if context is None:
        context = {}
    if model_name.startswith("ollama:"):
        model = model_name.split(":", 1)[1]
    else:
        model = model_name
    joined = '\n'.join(transcripts)
    if model in ["gemma2:9b", "deepseek-r1:7b", "mistral:7b-instruct", "llama3.2:3b"]:
        prompt = f"Tóm tắt tổng hợp các hội thoại dưới đây, tập trung vào các thông tin quan trọng, các thực thể, mối quan hệ, mức độ nhạy cảm, quyết định, hành động, cảm xúc, ngữ cảnh.\n"
        if 'summary' in context:
            prompt += f"\nTóm tắt ngữ cảnh: {context['summary']}"
        if 'key_points' in context and context['key_points']:
            prompt += f"\nCác điểm chính: {', '.join(context['key_points'])}"
        if 'entities' in context and context['entities']:
            prompt += f"\nThực thể: {json.dumps(context['entities'], ensure_ascii=False)}"
        if 'privacy_summary' in context:
            prompt += f"\nThông tin nhạy cảm: {context['privacy_summary']}"
        prompt += f"\nNội dung hội thoại: {joined}"
        import requests
        try:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "top_p": 0.9, "top_k": 40, "num_ctx": 4096}
                }
            )
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "")
            else:
                return f"[Ollama error {response.status_code}]"
        except Exception as e:
            return f"[Ollama error: {e}]"
    else:
        from src.summarization.summarizer import Summarizer
        summarizer = Summarizer(model_name=model_name)
        return summarizer.summarize(joined, context=context)

def benchmark_asr(transcription: str, audio_path: str):
    """Benchmark tự động WER/CER/noise (placeholder)"""
    # TODO: Tích hợp Speech Robust Bench thực tế
    wer = 0.1  # giả lập
    cer = 0.05
    noise_score = 0.2
    return wer, cer, noise_score 