import os
import shutil
import json
from fastapi import UploadFile, HTTPException
from pathlib import Path
from src.core.logging import logger
from src.database.models.models import AudioFile
from src.services.task_service import create_task, update_task, get_task
from src.speech_to_text.transcriber import Transcriber, OllamaProcessor

def save_audio_and_create_task(file: UploadFile, db, case_id: int = None) -> dict:
    """Lưu file audio vào storage/audio, tạo AudioFile và Task (status: pending). Trả về task_id, audio_file_id."""
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
        return {"task_id": task["id"], "audio_file_id": audio_file.id, "status": "pending"}
    except Exception as e:
        logger.error(f"Error saving audio and creating task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def process_task(task_id: str, model_name: str, db) -> dict:
    """Xử lý task: transcribe, summarize, update DB. Trả về kết quả gọn."""
    try:
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        audio_file = db.query(AudioFile).filter(AudioFile.task_id == task_id).first()
        if not audio_file:
            raise HTTPException(status_code=404, detail="Audio file not found")
        transcriber = Transcriber()
        result = transcriber.transcribe(audio_file.file_path)
        transcript = result.get("transcription")
        if not transcript or not transcript.strip():
            update_task(task_id, {"status": "failed", "error": "Không nhận diện được nội dung từ file âm thanh."})
            audio_file.status = "failed"
            db.commit()
            return {"status": "failed", "error": "Không nhận diện được nội dung từ file âm thanh."}
        summary = summarize_transcript(transcript, context=result.get("context_analysis"), model_name=model_name)
        update_task(task_id, {
            "status": "completed",
            "result": {
                "filename": audio_file.filename,
                "duration": result.get("duration"),
                "transcription": transcript,
                "summary": summary,
                "language": result.get("language"),
                "confidence": result.get("confidence"),
                "processing_time": result.get("processing_time"),
                "context_analysis": result.get("context_analysis"),
                "audio_url": f"/storage/audio/{audio_file.filename}"
            }
        })
        audio_file.status = "completed"
        db.commit()
        return {
            "status": "completed",
            "task_id": task_id,
            "audio_file_id": audio_file.id,
            "transcription": transcript,
            "summary": summary
        }
    except Exception as e:
        logger.error(f"Error processing task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def summarize_transcript(transcript: str, context: dict = None, model_name: str = "gemma2:9b", user_context_prompt: str = None, max_length: int = 150, min_length: int = 50) -> str:
    if not transcript:
        return "Không có tóm tắt."
    if context is None:
        context = OllamaProcessor(model_name="gemma2:9b").analyze_context(transcript)
    if model_name.startswith("ollama:"):
        model = model_name.split(":", 1)[1]
    else:
        model = model_name
    user_prompt = (user_context_prompt + "\n") if user_context_prompt else ""
    if model in ["gemma2:9b", "deepseek-r1:7b", "mistral:7b-instruct", "llama3.2:3b"]:
        prompt = (
            user_prompt +
            "Bạn là một trợ lý AI chuyên nghiệp. Hãy tóm tắt hội thoại dưới đây một cách chi tiết, tập trung vào các thông tin quan trọng, các thực thể (người, địa điểm, thời gian, liên hệ), các quyết định, hành động, cảm xúc, mối quan hệ, mức độ nhạy cảm, mục đích, chủ đề, và các điểm chính.\n"
            "Hãy phân tích sâu ngữ cảnh, chỉ ra các mối liên hệ giữa các thực thể, các quyết định quan trọng, các hành động cần thực hiện, cảm xúc của các bên, và các thông tin nhạy cảm.\n"
            "Nếu có context_analysis, hãy ưu tiên sử dụng để làm rõ tóm tắt.\n"
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
            "Hãy tóm tắt ngắn gọn, rõ ràng, dễ hiểu nội dung chính nhất của cuộc trò chuyện dưới đây trong 1-2 câu. Chỉ trình bày tổng quan, không liệt kê chi tiết.\n"
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
                    "max_tokens": 60
                }
            }
        )
        if response_main.status_code == 200:
            main_summary = response_main.json().get("response", "")
        else:
            main_summary = ""
        if main_summary:
            return f"Nội dung chính: {main_summary.strip()}\n\n{deep_summary.strip()}"
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