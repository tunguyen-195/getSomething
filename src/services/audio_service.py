import os
import json
import uuid
from fastapi import UploadFile, HTTPException
from pathlib import Path
from src.core.logging import logger
from src.core.config import settings
from src.database.models.models import AudioFile
from src.services.task_service import (
    SummaryResultRejected,
    begin_summary_attempt,
    build_summary_attempt_binding,
    build_summary_result_patch,
    create_task,
    fail_summary_attempt,
    get_task,
    safe_summary_message,
    succeed_summary_attempt,
    update_task,
    validate_persisted_terminal_summary,
    validate_summary_service_result,
)
from src.speech_to_text.transcriber import Transcriber, OllamaProcessor
from src.audio_processing.processor import AudioProcessor
from src.services.audio_storage import (
    cleanup_file,
    finalize_staged_upload,
    resolve_audio_path,
    stage_upload,
)
from src.services.summarization.legacy_context_adapter import (
    project_legacy_key_points,
)
from src.services.summarization.contracts import (
    DEFAULT_MULTI_SUMMARY_MAX_WORDS,
    DEFAULT_MULTI_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_MAX_WORDS,
    DEFAULT_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_TYPE,
    SummaryMaximumExceeded,
    SummaryRequestContractError,
    SummaryType,
    enforce_summary_maximum,
    validate_summary_request_options,
)


def _validate_legacy_summary_request(
    *,
    summary_type: SummaryType,
    min_length: int,
    max_length: int,
):
    options = validate_summary_request_options(
        summary_type=summary_type,
        min_length=min_length,
        max_length=max_length,
    )
    if options.summary_type in {"investigation", "forensic"}:
        raise SummaryRequestContractError(
            "LEGACY_EVIDENCE_SUMMARY_DISABLED",
            "Legacy generic summarization cannot release investigation or forensic "
            "content without the trusted evidence narrative contract.",
        )
    return options


def _finalize_legacy_summary(
    summary: str,
    *,
    min_length: int,
    max_length: int,
) -> str:
    final_summary = force_vietnamese_output(summary.strip())
    enforce_summary_maximum(
        final_summary,
        min_length=min_length,
        max_length=max_length,
    )
    return final_summary



def save_audio_and_create_task(file: UploadFile, db, case_id: int = None, user_id: int | None = None) -> dict:
    """Lưu file audio an toàn, tạo AudioFile và Task, trả về task_id/audio_id."""
    logger.info(f"[AUDIO_SERVICE] Bắt đầu lưu upload audio | case_id={case_id}")
    staged = None
    stored = None
    try:
        if case_id is not None and not isinstance(case_id, int):
            try:
                case_id = int(case_id)
            except Exception:
                raise HTTPException(status_code=400, detail="case_id phải là số nguyên")
        staged = stage_upload(file)
        task = create_task(staged.original_filename, case_id=case_id, db=db, user_id=user_id, commit=False)
        if not task:
            raise HTTPException(status_code=400, detail="Case ID không tồn tại hoặc không thể tạo task")
        stored = finalize_staged_upload(staged, int(task["case_id"]))
        audio_file = AudioFile(
            filename=stored.original_filename,
            case_id=task["case_id"],
            task_id=task["id"],
            file_path=stored.relative_path,
            status="uploaded",
            language_id=1,
            uploaded_by=user_id or task.get("user_id") or 1,
            file_size=stored.size,
            duration=None,
            audio_status_id=None,
            processed_at=None,
            error_message=None,
            updated_at=None,
            is_archived=False,
            archive_reason=None,
            storage_type='local',
            storage_config={},
            extra_metadata={"original_filename": stored.original_filename}
        )
        db.add(audio_file)
        db.flush()
        update_task(task["id"], {
            "result": {
                "audio_id": audio_file.id,
                "download_url": f"/api/v1/audio/{audio_file.id}/download",
                "filename": stored.original_filename,
            }
        }, db=db)
        db.commit()
        db.refresh(audio_file)
        logger.info(
            "[AUDIO_SERVICE] Đã lưu upload audio | "
            f"task_id={task['id']} | audio_file_id={audio_file.id}"
        )
        return {
            "task_id": task["id"],
            "audio_id": audio_file.id,
            "audio_file_id": audio_file.id,
            "filename": audio_file.filename,
            "status": "uploaded",
            "file_size": audio_file.file_size,
            "download_url": f"/api/v1/audio/{audio_file.id}/download",
        }
    except Exception as e:
        db.rollback()
        if staged:
            cleanup_file(staged.temp_path)
        if stored:
            cleanup_file(stored.absolute_path)
        logger.error(f"Error saving audio and creating task: {str(e)}", exc_info=True)
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))



def _safe_process_failure(code: str, *, status: str = "failed") -> dict:
    return {
        "status": status,
        "error": {
            "code": code,
            "message": safe_summary_message(code),
        },
    }


def _summary_transition_failure_code(outcome, requested_code: str) -> str:
    if outcome.accepted:
        return requested_code
    if outcome.outcome == "conflict":
        return outcome.code
    return "SUMMARY_PERSISTENCE_FAILED"


def _summarize_processed_transcript(
    task_id: str,
    transcript: str,
    *,
    model_name: str | None,
    attempt_id: str | None = None,
) -> dict:
    from src.services.summarization.summary_service_v2 import summarize_transcript_v2

    request_fingerprint, source_revision_id = build_summary_attempt_binding(
        transcript,
        model_name=model_name,
        summary_type=DEFAULT_SUMMARY_TYPE,
        include_context=True,
        min_length=DEFAULT_SUMMARY_MIN_WORDS,
        max_length=DEFAULT_SUMMARY_MAX_WORDS,
    )
    attempt_id = str(attempt_id or uuid.uuid4())
    begun = begin_summary_attempt(
        task_id,
        attempt_id,
        request_fingerprint=request_fingerprint,
        source_revision_id=source_revision_id,
        stage="execution",
    )
    if not begun.accepted:
        return _safe_process_failure(
            begun.code if begun.outcome == "conflict" else "SUMMARY_PERSISTENCE_FAILED"
        )
    if begun.outcome == "duplicate" and begun.state in {
        "succeeded",
        "failed",
        "needs_review",
    }:
        if begun.state != "succeeded":
            return _safe_process_failure(begun.code, status=begun.state)
        stored_task = get_task(task_id) or {}
        stored_result = stored_task.get("result")
        try:
            validated = validate_persisted_terminal_summary(
                stored_result,
                expected_attempt_id=attempt_id,
            )
        except SummaryResultRejected as rejection:
            return _safe_process_failure(rejection.code)
        return {
            "status": "summarized",
            "attempt_id": attempt_id,
            "summary": validated.summary,
            "model_name": validated.model,
            "summary_type": validated.summary_type,
            "context_analysis": validated.context,
            "result": validated.safe_result,
        }

    try:
        raw_result = summarize_transcript_v2(
            transcript=transcript,
            model_name=model_name,
            summary_type=DEFAULT_SUMMARY_TYPE,
            include_context=True,
            min_length=DEFAULT_SUMMARY_MIN_WORDS,
            max_length=DEFAULT_SUMMARY_MAX_WORDS,
            source_metadata={
                "summary_source_revision_id": source_revision_id,
                "request_fingerprint": request_fingerprint,
            },
        )
        validated = validate_summary_service_result(
            raw_result,
            expected_summary_type=DEFAULT_SUMMARY_TYPE,
            expected_source_revision_id=source_revision_id,
            expected_request_fingerprint=request_fingerprint,
        )
    except SummaryResultRejected as rejection:
        persisted = fail_summary_attempt(
            task_id,
            attempt_id,
            code=rejection.code,
            stage=rejection.stage,
            retryable=rejection.retryable,
            needs_review=rejection.needs_review,
        )
        code = _summary_transition_failure_code(persisted, rejection.code)
        status = persisted.state if persisted.accepted else "failed"
        return _safe_process_failure(code, status=status)
    except Exception as exc:
        logger.error(
            "[AUDIO_SERVICE] Summary provider failed | task_id=%s | error_type=%s",
            task_id,
            type(exc).__name__,
        )
        rejection = SummaryResultRejected(
            "SUMMARY_GENERATION_FAILED",
            stage="execution",
            retryable=True,
            needs_review=False,
        )
        persisted = fail_summary_attempt(
            task_id,
            attempt_id,
            code=rejection.code,
            stage=rejection.stage,
            retryable=rejection.retryable,
            needs_review=False,
        )
        code = _summary_transition_failure_code(persisted, rejection.code)
        return _safe_process_failure(code)

    result_patch = build_summary_result_patch(
        validated,
        summary_type=DEFAULT_SUMMARY_TYPE,
    )
    persisted = succeed_summary_attempt(task_id, attempt_id, result_patch)
    if not persisted.accepted:
        return _safe_process_failure(
            persisted.code
            if persisted.outcome == "conflict"
            else "SUMMARY_PERSISTENCE_FAILED"
        )
    return {
        "status": "summarized",
        "attempt_id": attempt_id,
        "summary": validated.summary,
        "model_name": validated.model,
        "summary_type": DEFAULT_SUMMARY_TYPE,
        "context_analysis": validated.context,
        "result": validated.safe_result,
    }


def process_task_with_diarization(
    task_id: str,
    model_name: str,
    db,
    diarization_method: str = "none",
    summary_attempt_id: str | None = None,
) -> dict:
    """Transcribe first, then run the shared typed summary state machine."""
    from src.audio_processing.diarization.manager import get_pipeline

    logger.info(
        "[AUDIO_SERVICE] Process task | task_id=%s | model=%s | diarization=%s",
        task_id,
        model_name,
        diarization_method,
    )
    try:
        task = get_task(task_id)
        if not task:
            return _safe_process_failure("SUMMARY_RESULT_INVALID")
        task_result = task.get("result")
        task_result = task_result if isinstance(task_result, dict) else {}
        current_summary_state = task_result.get("summary_state")
        if (
            summary_attempt_id
            and isinstance(current_summary_state, dict)
            and current_summary_state.get("attempt_id") == summary_attempt_id
            and current_summary_state.get("status")
            in {"running", "succeeded", "failed", "needs_review"}
        ):
            current_transcript = task_result.get("transcription")
            if not isinstance(current_transcript, str) or not current_transcript.strip():
                return _safe_process_failure("SUMMARY_RESULT_INVALID")
            return _summarize_processed_transcript(
                task_id,
                current_transcript,
                model_name=model_name,
                attempt_id=summary_attempt_id,
            )
        audio_file = db.query(AudioFile).filter(AudioFile.task_id == task_id).first()
        if not audio_file:
            return _safe_process_failure("SUMMARY_RESULT_INVALID")
        audio_path_str = str(resolve_audio_path(audio_file.file_path))
        audio_processor = AudioProcessor()
        audio, _sample_rate = audio_processor.load_audio(audio_path_str)
        audio_processor.enhance_speech_llase(audio)
        pipeline = get_pipeline(diarization_method)

        if pipeline:
            segments = pipeline.run(audio_path_str)
            transcript = " ".join(
                segment.get("text", "")
                for segment in segments
                if isinstance(segment, dict)
            ).strip()
            transcription_result = {
                "filename": audio_file.filename,
                "transcription": transcript,
                "segments": segments,
                "diarization_method": diarization_method,
                "download_url": f"/api/v1/audio/{audio_file.id}/download",
            }
        else:
            transcriber = Transcriber()
            options = {}
            if hasattr(audio_file, "options") and audio_file.options:
                options = (
                    json.loads(audio_file.options)
                    if isinstance(audio_file.options, str)
                    else audio_file.options
                )
            fast_mode = options.get(
                "fast_mode", getattr(settings, "WHISPER_FAST_MODE", True)
            )
            enable_diarization = options.get(
                "enable_diarization", diarization_method != "none"
            )
            if enable_diarization and diarization_method != "none":
                raw_transcription = transcriber.transcribe_with_diarization(
                    audio_path_str,
                    fast_mode=fast_mode,
                    enable_diarization=True,
                )
            else:
                raw_transcription = transcriber.transcribe(
                    audio_path_str,
                    fast_mode=fast_mode,
                )
            transcript = str(raw_transcription.get("transcription") or "").strip()
            wer, cer, noise_score = benchmark_asr(transcript, audio_path_str)
            logger.info(
                "[AUDIO_SERVICE] ASR benchmark | WER=%s | CER=%s | noise=%s",
                wer,
                cer,
                noise_score,
            )
            transcription_result = {
                "filename": audio_file.filename,
                "duration": raw_transcription.get("duration"),
                "transcription": transcript,
                "caption": raw_transcription.get("caption"),
                "segments": raw_transcription.get("segments", []),
                "language": raw_transcription.get("language"),
                "confidence": raw_transcription.get("confidence"),
                "processing_time": raw_transcription.get("processing_time"),
                "diarization_method": diarization_method,
                "download_url": f"/api/v1/audio/{audio_file.id}/download",
            }

        if not transcript:
            update_task(
                task_id,
                {
                    "status": "failed",
                    "error": safe_summary_message("SUMMARY_RESULT_INVALID"),
                },
                db=db,
            )
            audio_file.status = "failed"
            db.commit()
            return _safe_process_failure("SUMMARY_RESULT_INVALID")

        if not update_task(
            task_id,
            {
                "status": "transcribed",
                "result": transcription_result,
                "transcript": transcript,
            },
            db=db,
        ):
            db.rollback()
            return _safe_process_failure("SUMMARY_PERSISTENCE_FAILED")
        audio_file.status = "transcribed"
        if transcription_result.get("duration") is not None:
            audio_file.duration = transcription_result["duration"]
        db.commit()

        summary_result = _summarize_processed_transcript(
            task_id,
            transcript,
            model_name=model_name,
            attempt_id=summary_attempt_id,
        )
        if summary_result["status"] != "summarized":
            return summary_result
        return {
            **transcription_result,
            **summary_result,
        }
    except Exception as exc:
        db.rollback()
        logger.error(
            "[AUDIO_SERVICE] Process task failed | task_id=%s | error_type=%s",
            task_id,
            type(exc).__name__,
        )
        return _safe_process_failure("SUMMARY_GENERATION_FAILED")


def translate_line_to_vietnamese(text: str) -> str:
    """Dịch một dòng văn bản sang tiếng Việt"""
    if not text:
        return text

    # Kiểm tra có tiếng Anh không
    import re
    english_pattern = re.compile(r'[a-zA-Z]+')
    if not english_pattern.search(text):
        return text  # Đã là tiếng Việt

    # Thay thế các từ tiếng Anh phổ biến
    replacements = {
        # Cụm từ dài trước
        'This text appears to be': 'Văn bản này là',
        'a transcript of': 'bản ghi của',
        'phone conversation': 'cuộc trò chuyện qua điện thoại',
        'between two people': 'giữa hai người',
        'likely': 'có thể là',
        'lawyer': 'luật sư',
        'client': 'khách hàng',
        'legal trouble': 'vấn đề pháp lý',
        'seeking advice': 'tìm kiếm lời khuyên',
        'Here is a breakdown': 'Đây là phân tích',
        'what I understand': 'những gì tôi hiểu',
        'The Client is facing': 'Khách hàng đang đối mặt với',
        'legal charges': 'cáo buộc pháp lý',
        'court': 'tòa án',
        'trial': 'phiên tòa',
        'jail time': 'thời gian tù',
        'fines': 'tiền phạt',
        'advised by': 'được tư vấn bởi',
        'seeking help': 'tìm kiếm sự giúp đỡ',
        'trying to explain': 'đang cố gắng giải thích',
        'legal process': 'quy trình pháp lý',
        'timelines': 'thời gian',
        'procedures': 'thủ tục',
        'potential outcomes': 'kết quả tiềm năng',
        'involved': 'liên quan',
        'assistance': 'hỗ trợ',
        'Key takeaways': 'Điểm chính',
        'stressful situation': 'tình huống căng thẳng',
        'needs legal help': 'cần sự giúp đỡ pháp lý',
        'provide clear': 'cung cấp rõ ràng',
        'concise information': 'thông tin ngắn gọn',
        'multiple people': 'nhiều người',
        'each with their own role': 'mỗi người có vai trò riêng',
        'perspective': 'góc nhìn',
        'difficult to provide': 'khó để cung cấp',
        'more specific details': 'chi tiết cụ thể hơn',
        'without the full context': 'mà không có ngữ cảnh đầy đủ',
        'conversation': 'cuộc trò chuyện',
        'nature of the legal charges': 'bản chất của các cáo buộc pháp lý',
        'relationship between': 'mối quan hệ giữa',
        'identities of': 'danh tính của',
        'Let me know if you have': 'Hãy cho tôi biết nếu bạn có',
        'further questions': 'câu hỏi khác',
        'anything else I can help with': 'điều gì khác tôi có thể giúp',
        'The text you provided': 'Văn bản bạn cung cấp',
        'appears to be': 'có vẻ là',
        'Here is what I can gather': 'Đây là những gì tôi có thể thu thập',
        'woman': 'người phụ nữ',
        'recipient': 'người nhận',
        'accused of something': 'bị cáo buộc về điều gì đó',
        'facing potential': 'đang đối mặt với tiềm năng',
        'court proceedings': 'thủ tục tòa án',
        'caller': 'người gọi',
        'navigate': 'điều hướng',
        'legal system': 'hệ thống pháp lý',
        'connected to people': 'kết nối với những người',
        'influence the case': 'ảnh hưởng đến vụ án',
        'possibly': 'có thể',
        'officials': 'quan chức',
        'focuses on': 'tập trung vào',
        'specific legal terms': 'thuật ngữ pháp lý cụ thể',
        'type of court hearing': 'loại phiên tòa',
        'referring to': 'đề cập đến',
        'appeal process': 'quy trình kháng cáo',
        'sense of urgency': 'cảm giác khẩn cấp',
        'pressure': 'áp lực',
        'worried about': 'lo lắng về',
        'tries to reassure': 'cố gắng trấn an',
        'guide through': 'hướng dẫn qua',
        'Challenges in Understanding': 'Thách thức trong việc hiểu',
        'Informal Language': 'Ngôn ngữ không chính thức',
        'slang': 'tiếng lóng',
        'colloquialisms': 'từ ngữ thông tục',
        'make it difficult': 'làm cho khó khăn',
        'full context': 'ngữ cảnh đầy đủ',
        'Missing Background Information': 'Thiếu thông tin nền',
        'individuals are': 'cá nhân là',
        'relationship': 'mối quan hệ',
        'hard to fully grasp': 'khó để hiểu đầy đủ',
        'Unclear Legal Terms': 'Thuật ngữ pháp lý không rõ ràng',
        'used without explanation': 'được sử dụng mà không có giải thích',
        'challenging for someone': 'thách thức đối với ai đó',
        'unfamiliar with': 'không quen thuộc với',
        'Vietnamese law': 'luật Việt Nam',
        'follow': 'theo dõi',
        'better understand this conversation': 'hiểu rõ hơn cuộc trò chuyện này',
        'need more context': 'cần thêm ngữ cảnh',
        'Who are the people involved': 'Ai là những người liên quan',
        'What is the nature': 'Bản chất là gì',
        'legal case': 'vụ án pháp lý',
        'understanding the charges': 'hiểu các cáo buộc',
        'accusations': 'cáo buộc',
        'provide insight': 'cung cấp cái nhìn sâu sắc',
        'seriousness of the situation': 'mức độ nghiêm trọng của tình huống',
        'What specific actions': 'Hành động cụ thể nào',
        'being discussed': 'đang được thảo luận',
        'identifying the tasks': 'xác định các nhiệm vụ',
        'deadlines mentioned': 'thời hạn được đề cập',
        'clarify the immediate needs': 'làm rõ nhu cầu ngay lập tức',
        'Let me know if you have any': 'Hãy cho tôi biết nếu bạn có bất kỳ',
        'other questions': 'câu hỏi khác',
        'need further clarification': 'cần làm rõ thêm',
        'any points': 'bất kỳ điểm nào',
        # Thêm các từ phổ biến khác
        'seeking': 'tìm kiếm',
        'legal': 'pháp lý',
        'assistance': 'hỗ trợ',
        'help': 'giúp đỡ',
        'with': 'với',
        'court': 'tòa án',
        'proceedings': 'thủ tục',
        'worried': 'lo lắng',
        'about': 'về',
        'situation': 'tình huống',
        'wants': 'muốn',
        'to': 'để',
        'understand': 'hiểu',
        'her': 'của cô ấy',
        'his': 'của anh ấy',
        'their': 'của họ',
        'my': 'của tôi',
        'your': 'của bạn',
        'our': 'của chúng ta',
        'its': 'của nó',
        'this': 'này',
        'that': 'đó',
        'these': 'những cái này',
        'those': 'những cái đó',
        'here': 'ở đây',
        'there': 'ở đó',
        'where': 'ở đâu',
        'when': 'khi nào',
        'why': 'tại sao',
        'how': 'như thế nào',
        'what': 'cái gì',
        'who': 'ai',
        'which': 'cái nào',
        'whom': 'ai',
        'whose': 'của ai',
        'if': 'nếu',
        'else': 'khác',
        'then': 'sau đó',
        'now': 'bây giờ',
        'today': 'hôm nay',
        'tomorrow': 'ngày mai',
        'yesterday': 'hôm qua',
        'soon': 'sớm',
        'later': 'sau',
        'before': 'trước',
        'after': 'sau',
        'during': 'trong khi',
        'while': 'trong khi',
        'since': 'từ khi',
        'until': 'cho đến khi',
        'because': 'bởi vì',
        'although': 'mặc dù',
        'however': 'tuy nhiên',
        'therefore': 'do đó',
        'thus': 'do đó',
        'hence': 'do đó',
        'moreover': 'hơn nữa',
        'furthermore': 'hơn nữa',
        'additionally': 'thêm vào đó',
        'also': 'cũng',
        'too': 'cũng',
        'as': 'như',
        'like': 'như',
        'such': 'như vậy',
        'very': 'rất',
        'quite': 'khá',
        'rather': 'khá',
        'somewhat': 'một chút',
        'almost': 'gần như',
        'nearly': 'gần như',
        'approximately': 'khoảng',
        'exactly': 'chính xác',
        'precisely': 'chính xác',
        'definitely': 'chắc chắn',
        'certainly': 'chắc chắn',
        'probably': 'có thể',
        'possibly': 'có thể',
        'maybe': 'có thể',
        'perhaps': 'có thể',
        'surely': 'chắc chắn',
        'obviously': 'rõ ràng',
        'clearly': 'rõ ràng',
        'evidently': 'rõ ràng',
        'apparently': 'rõ ràng',
        'seemingly': 'có vẻ như',
        'supposedly': 'được cho là',
        'allegedly': 'được cho là',
        'reportedly': 'theo báo cáo',
        'accordingly': 'theo đó',
        'consequently': 'kết quả là',
        'subsequently': 'sau đó',
        'previously': 'trước đó',
        'originally': 'ban đầu',
        'initially': 'ban đầu',
        'finally': 'cuối cùng',
        'eventually': 'cuối cùng',
        'ultimately': 'cuối cùng',
        'gradually': 'dần dần',
        'slowly': 'chậm',
        'quickly': 'nhanh',
        'rapidly': 'nhanh chóng',
        'immediately': 'ngay lập tức',
        'instantly': 'ngay lập tức',
        'suddenly': 'đột ngột',
        'abruptly': 'đột ngột',
        'carefully': 'cẩn thận',
        'properly': 'đúng cách',
        'correctly': 'đúng cách',
        'accurately': 'chính xác',
        'completely': 'hoàn toàn',
        'entirely': 'hoàn toàn',
        'totally': 'hoàn toàn',
        'fully': 'hoàn toàn',
        'partially': 'một phần',
        'mostly': 'phần lớn',
        'mainly': 'chủ yếu',
        'primarily': 'chủ yếu',
        'essentially': 'về cơ bản',
        'basically': 'về cơ bản',
        'fundamentally': 'về cơ bản',
        'generally': 'nói chung',
        'usually': 'thường xuyên',
        'normally': 'bình thường',
        'typically': 'thường xuyên',
        'commonly': 'thường xuyên',
        'frequently': 'thường xuyên',
        'often': 'thường xuyên',
        'sometimes': 'đôi khi',
        'occasionally': 'thỉnh thoảng',
        'rarely': 'hiếm khi',
        'seldom': 'hiếm khi',
        'never': 'không bao giờ',
        'always': 'luôn luôn',
        'forever': 'mãi mãi',
        'permanently': 'vĩnh viễn',
        'temporarily': 'tạm thời',
        'briefly': 'ngắn gọn',
        'shortly': 'ngắn gọn',
        'currently': 'hiện tại',
        'presently': 'hiện tại',
        'nowadays': 'ngày nay',
        'earlier': 'sớm hơn',
        'sooner': 'sớm hơn'
    }

    # Thay thế cụm từ trước
    result = text
    for english, vietnamese in replacements.items():
        result = result.replace(english, vietnamese)

    # Sau đó thay thế các từ đơn với word boundary
    word_replacements = {
        'a': 'một',
        'and': 'và',
        'from': 'từ',
        'of': 'của',
        'the': '',
        'is': 'là',
        'are': 'là',
        'was': 'đã',
        'were': 'đã',
        'will': 'sẽ',
        'can': 'có thể',
        'could': 'có thể',
        'should': 'nên',
        'would': 'sẽ',
        'have': 'có',
        'has': 'có',
        'had': 'đã có',
        'do': 'làm',
        'do': 'làm',
        'does': 'làm',
        'did': 'đã làm',
        'be': 'là',
        'been': 'đã',
        'being': 'đang',
        'get': 'nhận',
        'gets': 'nhận',
        'got': 'đã nhận',
        'make': 'làm',
        'makes': 'làm',
        'made': 'đã làm',
        'go': 'đi',
        'goes': 'đi',
        'went': 'đã đi',
        'gone': 'đã đi',
        'come': 'đến',
        'comes': 'đến',
        'came': 'đã đến',
        'see': 'thấy',
        'sees': 'thấy',
        'saw': 'đã thấy',
        'seen': 'đã thấy',
        'know': 'biết',
        'knows': 'biết',
        'knew': 'đã biết',
        'known': 'đã biết',
        'think': 'nghĩ',
        'thinks': 'nghĩ',
        'thought': 'đã nghĩ',
        'say': 'nói',
        'says': 'nói',
        'said': 'đã nói',
        'tell': 'nói',
        'tells': 'nói',
        'told': 'đã nói',
        'give': 'cho',
        'gives': 'cho',
        'gave': 'đã cho',
        'given': 'đã cho',
        'take': 'lấy',
        'takes': 'lấy',
        'took': 'đã lấy',
        'taken': 'đã lấy',
        'find': 'tìm',
        'finds': 'tìm',
        'found': 'đã tìm',
        'look': 'nhìn',
        'looks': 'nhìn',
        'looked': 'đã nhìn',
        'want': 'muốn',
        'wants': 'muốn',
        'wanted': 'đã muốn',
        'need': 'cần',
        'needs': 'cần',
        'needed': 'đã cần',
        'help': 'giúp',
        'helps': 'giúp',
        'helped': 'đã giúp',
        'work': 'làm việc',
        'works': 'làm việc',
        'worked': 'đã làm việc',
        'call': 'gọi',
        'calls': 'gọi',
        'called': 'đã gọi',
        'ask': 'hỏi',
        'asks': 'hỏi',
        'asked': 'đã hỏi',
        'try': 'thử',
        'tries': 'thử',
        'tried': 'đã thử',
        'use': 'sử dụng',
        'uses': 'sử dụng',
        'used': 'đã sử dụng',
        'feel': 'cảm thấy',
        'feels': 'cảm thấy',
        'felt': 'đã cảm thấy',
        'become': 'trở thành',
        'becomes': 'trở thành',
        'became': 'đã trở thành',
        'begin': 'bắt đầu',
        'begins': 'bắt đầu',
        'began': 'đã bắt đầu',
        'begun': 'đã bắt đầu',
        'keep': 'giữ',
        'keeps': 'giữ',
        'kept': 'đã giữ',
        'hold': 'giữ',
        'holds': 'giữ',
        'held': 'đã giữ',
        'put': 'đặt',
        'puts': 'đặt',
        'put_verb': 'đã đặt',
        'bring': 'mang',
        'brings': 'mang',
        'brought': 'đã mang',
        'start': 'bắt đầu',
        'starts': 'bắt đầu',
        'started': 'đã bắt đầu',
        'move': 'di chuyển',
        'moves': 'di chuyển',
        'moved': 'đã di chuyển',
        'turn': 'quay',
        'turns': 'quay',
        'turned': 'đã quay',
        'stop': 'dừng',
        'stops': 'dừng',
        'stopped': 'đã dừng',
        'leave': 'rời',
        'leaves': 'rời',
        'left': 'đã rời',
        'stand': 'đứng',
        'stands': 'đứng',
        'stood': 'đã đứng',
        'sit': 'ngồi',
        'ngồi': 'ngồi',
        'sat': 'đã ngồi',
        'lie': 'nằm',
        'lies': 'nằm',
        'lay': 'đã nằm',
        'run': 'chạy',
        'runs': 'chạy',
        'ran': 'đã chạy',
        'walk': 'đi bộ',
        'walks': 'đi bộ',
        'walked': 'đã đi bộ'
    }

    # Thay thế từ đơn với word boundary
    for english, vietnamese in word_replacements.items():
        # Sử dụng regex để thay thế chỉ khi là từ riêng biệt
        pattern = r'\b' + re.escape(english) + r'\b'
        result = re.sub(pattern, vietnamese, result, flags=re.IGNORECASE)

    # Dọn dẹp khoảng trắng thừa
    result = re.sub(r'\s+', ' ', result).strip()

    # Thêm cảnh báo nếu vẫn còn tiếng Anh
    if english_pattern.search(result):
        result += "\n\n[LƯU Ý: Vẫn còn một số từ tiếng Anh do không thể dịch tự động]"

    return result


def process_task(task_id: str, model_name: str, db):
    """Tương thích ngược: gọi pipeline mới với diarization_method='none'"""
    return process_task_with_diarization(task_id, model_name, db, diarization_method="none")


def summarize_transcript(
    transcript: str,
    context: dict = None,
    model_name: str = None,
    user_context_prompt: str = None,
    max_length: int = DEFAULT_SUMMARY_MAX_WORDS,
    min_length: int = DEFAULT_SUMMARY_MIN_WORDS,
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE,
) -> str:
    options = _validate_legacy_summary_request(
        summary_type=summary_type,
        min_length=min_length,
        max_length=max_length,
    )
    summary_type = options.summary_type
    min_length = options.min_length
    max_length = options.max_length

    if not transcript:
        return _finalize_legacy_summary(
            "Không có tóm tắt.",
            min_length=min_length,
            max_length=max_length,
        )

    # Sử dụng model mặc định từ config nếu không chỉ định
    if model_name is None:
        model_name = settings.DEFAULT_AI_MODEL

    if context is None:
        context = OllamaProcessor(model_name=model_name).analyze_context(transcript)
    if context is None:
        context = {}
    if model_name.startswith("ollama:"):
        model = model_name.split(":", 1)[1]
    else:
        model = model_name
    # Ép đầu ra tiếng Việt ở mọi prompt tóm tắt - MẠNH MẼ HƠN
    vi_requirement = """YÊU CẦU BẮT BUỘC:
1. TRẢ LỜI 100% BẰNG TIẾNG VIỆT
2. KHÔNG ĐƯỢC DÙNG TIẾNG ANH
3. NẾU VIẾT TIẾNG ANH SẼ BỊ TỪ CHỐI
4. CHỈ ĐƯỢC VIẾT TIẾNG VIỆT
5. KHÔNG CÓ NGOẠI LỆ

"""
    user_prompt = ((user_context_prompt + "\n") if user_context_prompt else "") + vi_requirement
    if model in ["gpt-oss", "qwen2.5:7b", "gemma2:9b", "deepseek-r1:7b", "mistral:7b-instruct", "llama3.2:3b"]:
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
        key_points = project_legacy_key_points(context)
        if key_points:
            key_points_str = ', '.join(key_points)
            prompt += f"\nCác điểm chính: {key_points_str}"
        if context and 'entities' in context and context['entities']:
            entities_json = json.dumps(context['entities'], ensure_ascii=False)
            prompt += f"\nThực thể: {entities_json}"
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
            "Hãy tóm tắt tổng quan hội thoại dưới đây trong 5-6 dòng, "
            "nêu rõ bối cảnh, mục đích, các bên tham gia, diễn biến chính, "
            "kết quả, cảm xúc tổng thể. Không liệt kê chi tiết, chỉ trình bày "
            "tổng quan sâu sắc.\n"
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
        if summary_type == "brief":
            raw_summary = main_summary.strip() or deep_summary.strip()
        elif main_summary:
            raw_summary = f"Nội dung tổng quan: {main_summary.strip()}\n\n{deep_summary.strip()}"
        else:
            raw_summary = deep_summary.strip()
        return _finalize_legacy_summary(
            raw_summary,
            min_length=min_length,
            max_length=max_length,
        )
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
            key_points = project_legacy_key_points(context)
            if key_points:
                prompt += f"\nCác điểm chính: {', '.join(key_points)}"
            if 'entities' in context and context['entities']:
                prompt += f"\nThực thể: {json.dumps(context['entities'], ensure_ascii=False)}"
            if 'privacy_summary' in context:
                prompt += f"\nThông tin nhạy cảm: {context['privacy_summary']}"
            prompt += f"\nNội dung hội thoại: {transcript}"
            deep_summary = summarizer.summarize(
                prompt,
                context=context,
                max_length=max_length,
                min_length=0,
            )
        else:
            deep_summary = summarizer.summarize(
                transcript,
                context=context,
                max_length=max_length,
                min_length=0,
            )
        main_prompt = (
            user_prompt +
            "Hãy tóm tắt ngắn gọn, rõ ràng, dễ hiểu nội dung chính nhất của cuộc trò chuyện dưới đây trong 1-2 câu. Chỉ trình bày tổng quan, không liệt kê chi tiết.\n"
            f"Nội dung hội thoại: {transcript}"
        )
        main_summary = summarizer.summarize(
            main_prompt,
            context=context,
            max_length=min(60, max_length),
            min_length=0,
        )
        if summary_type == "brief":
            raw_summary = main_summary.strip() or deep_summary.strip()
        elif main_summary:
            raw_summary = f"Nội dung chính: {main_summary.strip()}\n\n{deep_summary.strip()}"
        else:
            raw_summary = deep_summary.strip()
        return _finalize_legacy_summary(
            raw_summary,
            min_length=min_length,
            max_length=max_length,
        )



def summarize_multi_transcripts(
    transcripts: list[str],
    context: dict = None,
    model_name: str = None,
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE,
    max_length: int = DEFAULT_MULTI_SUMMARY_MAX_WORDS,
    min_length: int = DEFAULT_MULTI_SUMMARY_MIN_WORDS,
) -> str:
    options = _validate_legacy_summary_request(
        summary_type=summary_type,
        min_length=min_length,
        max_length=max_length,
    )
    summary_type = options.summary_type
    min_length = options.min_length
    max_length = options.max_length

    if not transcripts:
        return _finalize_legacy_summary(
            "Không có transcript nào để tóm tắt.",
            min_length=min_length,
            max_length=max_length,
        )
    # Sử dụng model mặc định từ config nếu không chỉ định
    if model_name is None:
        model_name = settings.DEFAULT_AI_MODEL

    if context is None and transcripts:
        context = OllamaProcessor(model_name=model_name).analyze_context('\n'.join(transcripts))
    if context is None:
        context = {}
    if model_name.startswith("ollama:"):
        model = model_name.split(":", 1)[1]
    else:
        model = model_name
    joined = '\n'.join(transcripts)
    if model in ["gpt-oss", "qwen2.5:7b", "gemma2:9b", "deepseek-r1:7b", "mistral:7b-instruct", "llama3.2:3b"]:
        vi_requirement = """YÊU CẦU BẮT BUỘC:
1. TRẢ LỜI 100% BẰNG TIẾNG VIỆT
2. KHÔNG ĐƯỢC DÙNG TIẾNG ANH
3. NẾU VIẾT TIẾNG ANH SẼ BỊ TỪ CHỐI
4. CHỈ ĐƯỢC VIẾT TIẾNG VIỆT
5. KHÔNG CÓ NGOẠI LỆ

"""
        prompt = (
            vi_requirement +
            (
                "Tóm tắt ngắn gọn các hội thoại dưới đây, chỉ nêu các điểm cốt lõi.\n"
                if summary_type == "brief"
                else "Tóm tắt tổng hợp các hội thoại dưới đây, tập trung vào các thông tin quan trọng, "
            ) +
            "các thực thể, mối quan hệ, mức độ nhạy cảm, quyết định, hành động, cảm xúc, ngữ cảnh.\n"
        )
        if 'summary' in context:
            prompt += f"\nTóm tắt ngữ cảnh: {context['summary']}"
        key_points = project_legacy_key_points(context)
        if key_points:
            prompt += f"\nCác điểm chính: {', '.join(key_points)}"
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
                return _finalize_legacy_summary(
                    result.get("response", ""),
                    min_length=min_length,
                    max_length=max_length,
                )
            else:
                return _finalize_legacy_summary(
                    f"[Ollama error {response.status_code}]",
                    min_length=min_length,
                    max_length=max_length,
                )
        except SummaryMaximumExceeded:
            raise
        except Exception as e:
            return _finalize_legacy_summary(
                f"[Ollama error: {e}]",
                min_length=min_length,
                max_length=max_length,
            )
    else:
        from src.summarization.summarizer import Summarizer
        summarizer = Summarizer(model_name=model_name)
        summary = summarizer.summarize(
            joined,
            context=context,
            max_length=max_length,
            min_length=0,
        )
        return _finalize_legacy_summary(
            summary,
            min_length=min_length,
            max_length=max_length,
        )



def benchmark_asr(transcription: str, audio_path: str):
    """Benchmark tự động WER/CER/noise (placeholder)"""
    # TODO: Tích hợp Speech Robust Bench thực tế
    wer = 0.1  # giả lập
    cer = 0.05
    noise_score = 0.2
    return wer, cer, noise_score



def force_vietnamese_output(text: str, preserve_original: bool = False) -> str:
    """Ép buộc đầu ra tiếng Việt - nếu phát hiện tiếng Anh sẽ thay thế bằng tiếng Việt tương ứng

    Args:
        text: Văn bản cần xử lý
        preserve_original: Nếu True, giữ nguyên ngôn ngữ gốc và chỉ dịch tóm tắt
    """
    if not text:
        return text

    # Nếu cần giữ nguyên ngôn ngữ gốc, chỉ xử lý phần tóm tắt
    if preserve_original and settings.PRESERVE_ORIGINAL_LANGUAGE:
        # Tách phần transcript gốc và phần tóm tắt
        lines = text.split('\n')
        processed_lines = []

        for line in lines:
            if any(keyword in line.lower() for keyword in ['tóm tắt', 'summary', 'nội dung', 'content', 'kết luận']):
                # Đây là phần tóm tắt - áp dụng dịch tiếng Việt
                processed_lines.append(translate_line_to_vietnamese(line))
            else:
                # Đây là transcript gốc - giữ nguyên
                processed_lines.append(line)

        return '\n'.join(processed_lines)

    # Kiểm tra có tiếng Anh không
    import re
    english_pattern = re.compile(r'[a-zA-Z]+')
    if not english_pattern.search(text):
        return text  # Đã là tiếng Việt

    # Thay thế các từ tiếng Anh phổ biến
    replacements = {
        # Cụm từ dài trước
        'This text appears to be': 'Văn bản này là',
        'a transcript of': 'bản ghi của',
        'phone conversation': 'cuộc trò chuyện qua điện thoại',
        'between two people': 'giữa hai người',
        'likely': 'có thể là',
        'lawyer': 'luật sư',
        'client': 'khách hàng',
        'legal trouble': 'vấn đề pháp lý',
        'seeking advice': 'tìm kiếm lời khuyên',
        'Here is a breakdown': 'Đây là phân tích',
        'what I understand': 'những gì tôi hiểu',
        'The Client is facing': 'Khách hàng đang đối mặt với',
        'legal charges': 'cáo buộc pháp lý',
        'court': 'tòa án',
        'trial': 'phiên tòa',
        'jail time': 'thời gian tù',
        'fines': 'tiền phạt',
        'advised by': 'được tư vấn bởi',
        'seeking help': 'tìm kiếm sự giúp đỡ',
        'trying to explain': 'đang cố gắng giải thích',
        'legal process': 'quy trình pháp lý',
        'timelines': 'thời gian',
        'procedures': 'thủ tục',
        'potential outcomes': 'kết quả tiềm năng',
        'involved': 'liên quan',
        'assistance': 'hỗ trợ',
        'Key takeaways': 'Điểm chính',
        'stressful situation': 'tình huống căng thẳng',
        'needs legal help': 'cần sự giúp đỡ pháp lý',
        'provide clear': 'cung cấp rõ ràng',
        'concise information': 'thông tin ngắn gọn',
        'multiple people': 'nhiều người',
        'each with their own role': 'mỗi người có vai trò riêng',
        'perspective': 'góc nhìn',
        'difficult to provide': 'khó để cung cấp',
        'more specific details': 'chi tiết cụ thể hơn',
        'without the full context': 'mà không có ngữ cảnh đầy đủ',
        'conversation': 'cuộc trò chuyện',
        'nature of the legal charges': 'bản chất của các cáo buộc pháp lý',
        'relationship between': 'mối quan hệ giữa',
        'identities of': 'danh tính của',
        'Let me know if you have': 'Hãy cho tôi biết nếu bạn có',
        'further questions': 'câu hỏi khác',
        'anything else I can help with': 'điều gì khác tôi có thể giúp',
        'The text you provided': 'Văn bản bạn cung cấp',
        'appears to be': 'có vẻ là',
        'Here is what I can gather': 'Đây là những gì tôi có thể thu thập',
        'woman': 'người phụ nữ',
        'recipient': 'người nhận',
        'accused of something': 'bị cáo buộc về điều gì đó',
        'facing potential': 'đang đối mặt với tiềm năng',
        'court proceedings': 'thủ tục tòa án',
        'caller': 'người gọi',
        'navigate': 'điều hướng',
        'legal system': 'hệ thống pháp lý',
        'connected to people': 'kết nối với những người',
        'influence the case': 'ảnh hưởng đến vụ án',
        'possibly': 'có thể',
        'officials': 'quan chức',
        'focuses on': 'tập trung vào',
        'specific legal terms': 'thuật ngữ pháp lý cụ thể',
        'type of court hearing': 'loại phiên tòa',
        'referring to': 'đề cập đến',
        'appeal process': 'quy trình kháng cáo',
        'sense of urgency': 'cảm giác khẩn cấp',
        'pressure': 'áp lực',
        'worried about': 'lo lắng về',
        'tries to reassure': 'cố gắng trấn an',
        'guide through': 'hướng dẫn qua',
        'Challenges in Understanding': 'Thách thức trong việc hiểu',
        'Informal Language': 'Ngôn ngữ không chính thức',
        'slang': 'tiếng lóng',
        'colloquialisms': 'từ ngữ thông tục',
        'make it difficult': 'làm cho khó khăn',
        'full context': 'ngữ cảnh đầy đủ',
        'Missing Background Information': 'Thiếu thông tin nền',
        'individuals are': 'cá nhân là',
        'relationship': 'mối quan hệ',
        'hard to fully grasp': 'khó để hiểu đầy đủ',
        'Unclear Legal Terms': 'Thuật ngữ pháp lý không rõ ràng',
        'used without explanation': 'được sử dụng mà không có giải thích',
        'challenging for someone': 'thách thức đối với ai đó',
        'unfamiliar with': 'không quen thuộc với',
        'Vietnamese law': 'luật Việt Nam',
        'follow': 'theo dõi',
        'better understand this conversation': 'hiểu rõ hơn cuộc trò chuyện này',
        'need more context': 'cần thêm ngữ cảnh',
        'Who are the people involved': 'Ai là những người liên quan',
        'What is the nature': 'Bản chất là gì',
        'legal case': 'vụ án pháp lý',
        'understanding the charges': 'hiểu các cáo buộc',
        'accusations': 'cáo buộc',
        'provide insight': 'cung cấp cái nhìn sâu sắc',
        'seriousness of the situation': 'mức độ nghiêm trọng của tình huống',
        'What specific actions': 'Hành động cụ thể nào',
        'being discussed': 'đang được thảo luận',
        'identifying the tasks': 'xác định các nhiệm vụ',
        'deadlines mentioned': 'thời hạn được đề cập',
        'clarify the immediate needs': 'làm rõ nhu cầu ngay lập tức',
        'Let me know if you have any': 'Hãy cho tôi biết nếu bạn có bất kỳ',
        'other questions': 'câu hỏi khác',
        'need further clarification': 'cần làm rõ thêm',
        'any points': 'bất kỳ điểm nào',
        # Thêm các từ phổ biến khác
        'seeking': 'tìm kiếm',
        'legal': 'pháp lý',
        'assistance': 'hỗ trợ',
        'help': 'giúp đỡ',
        'with': 'với',
        'court': 'tòa án',
        'proceedings': 'thủ tục',
        'worried': 'lo lắng',
        'about': 'về',
        'situation': 'tình huống',
        'wants': 'muốn',
        'to': 'để',
        'understand': 'hiểu',
        'her': 'của cô ấy',
        'his': 'của anh ấy',
        'their': 'của họ',
        'my': 'của tôi',
        'your': 'của bạn',
        'our': 'của chúng ta',
        'its': 'của nó',
        'this': 'này',
        'that': 'đó',
        'these': 'những cái này',
        'those': 'những cái đó',
        'here': 'ở đây',
        'there': 'ở đó',
        'where': 'ở đâu',
        'when': 'khi nào',
        'why': 'tại sao',
        'how': 'như thế nào',
        'what': 'cái gì',
        'who': 'ai',
        'which': 'cái nào',
        'whom': 'ai',
        'whose': 'của ai',
        'if': 'nếu',
        'else': 'khác',
        'then': 'sau đó',
        'now': 'bây giờ',
        'today': 'hôm nay',
        'tomorrow': 'ngày mai',
        'yesterday': 'hôm qua',
        'soon': 'sớm',
        'later': 'sau',
        'before': 'trước',
        'after': 'sau',
        'during': 'trong khi',
        'while': 'trong khi',
        'since': 'từ khi',
        'until': 'cho đến khi',
        'because': 'bởi vì',
        'although': 'mặc dù',
        'however': 'tuy nhiên',
        'therefore': 'do đó',
        'thus': 'do đó',
        'hence': 'do đó',
        'moreover': 'hơn nữa',
        'furthermore': 'hơn nữa',
        'additionally': 'thêm vào đó',
        'also': 'cũng',
        'too': 'cũng',
        'as': 'như',
        'like': 'như',
        'such': 'như vậy',
        'very': 'rất',
        'quite': 'khá',
        'rather': 'khá',
        'somewhat': 'một chút',
        'almost': 'gần như',
        'nearly': 'gần như',
        'approximately': 'khoảng',
        'exactly': 'chính xác',
        'precisely': 'chính xác',
        'definitely': 'chắc chắn',
        'certainly': 'chắc chắn',
        'probably': 'có thể',
        'possibly': 'có thể',
        'maybe': 'có thể',
        'perhaps': 'có thể',
        'surely': 'chắc chắn',
        'obviously': 'rõ ràng',
        'clearly': 'rõ ràng',
        'evidently': 'rõ ràng',
        'apparently': 'rõ ràng',
        'seemingly': 'có vẻ như',
        'supposedly': 'được cho là',
        'allegedly': 'được cho là',
        'reportedly': 'theo báo cáo',
        'accordingly': 'theo đó',
        'consequently': 'kết quả là',
        'subsequently': 'sau đó',
        'previously': 'trước đó',
        'originally': 'ban đầu',
        'initially': 'ban đầu',
        'finally': 'cuối cùng',
        'eventually': 'cuối cùng',
        'ultimately': 'cuối cùng',
        'gradually': 'dần dần',
        'slowly': 'chậm',
        'quickly': 'nhanh',
        'rapidly': 'nhanh chóng',
        'immediately': 'ngay lập tức',
        'instantly': 'ngay lập tức',
        'suddenly': 'đột ngột',
        'abruptly': 'đột ngột',
        'carefully': 'cẩn thận',
        'properly': 'đúng cách',
        'correctly': 'đúng cách',
        'accurately': 'chính xác',
        'completely': 'hoàn toàn',
        'entirely': 'hoàn toàn',
        'totally': 'hoàn toàn',
        'fully': 'hoàn toàn',
        'partially': 'một phần',
        'mostly': 'phần lớn',
        'mainly': 'chủ yếu',
        'primarily': 'chủ yếu',
        'essentially': 'về cơ bản',
        'basically': 'về cơ bản',
        'fundamentally': 'về cơ bản',
        'generally': 'nói chung',
        'usually': 'thường xuyên',
        'normally': 'bình thường',
        'typically': 'thường xuyên',
        'commonly': 'thường xuyên',
        'frequently': 'thường xuyên',
        'often': 'thường xuyên',
        'sometimes': 'đôi khi',
        'occasionally': 'thỉnh thoảng',
        'rarely': 'hiếm khi',
        'seldom': 'hiếm khi',
        'never': 'không bao giờ',
        'always': 'luôn luôn',
        'forever': 'mãi mãi',
        'permanently': 'vĩnh viễn',
        'temporarily': 'tạm thời',
        'briefly': 'ngắn gọn',
        'shortly': 'ngắn gọn',
        'currently': 'hiện tại',
        'presently': 'hiện tại',
        'nowadays': 'ngày nay',
        'earlier': 'sớm hơn',
        'sooner': 'sớm hơn'
    }

    # Thay thế cụm từ trước
    result = text
    for english, vietnamese in replacements.items():
        result = result.replace(english, vietnamese)

    # Sau đó thay thế các từ đơn với word boundary
    word_replacements = {
        'a': 'một',
        'and': 'và',
        'from': 'từ',
        'of': 'của',
        'the': '',
        'is': 'là',
        'are': 'là',
        'was': 'đã',
        'were': 'đã',
        'will': 'sẽ',
        'can': 'có thể',
        'could': 'có thể',
        'should': 'nên',
        'would': 'sẽ',
        'have': 'có',
        'has': 'có',
        'had': 'đã có',
        'do': 'làm',
        'does': 'làm',
        'did': 'đã làm',
        'be': 'là',
        'been': 'đã',
        'being': 'đang',
        'get': 'nhận',
        'gets': 'nhận',
        'got': 'đã nhận',
        'make': 'làm',
        'makes': 'làm',
        'made': 'đã làm',
        'go': 'đi',
        'goes': 'đi',
        'went': 'đã đi',
        'gone': 'đã đi',
        'come': 'đến',
        'comes': 'đến',
        'came': 'đã đến',
        'see': 'thấy',
        'sees': 'thấy',
        'saw': 'đã thấy',
        'seen': 'đã thấy',
        'know': 'biết',
        'knows': 'biết',
        'knew': 'đã biết',
        'known': 'đã biết',
        'think': 'nghĩ',
        'thinks': 'nghĩ',
        'thought': 'đã nghĩ',
        'say': 'nói',
        'says': 'nói',
        'said': 'đã nói',
        'tell': 'nói',
        'tells': 'nói',
        'told': 'đã nói',
        'give': 'cho',
        'gives': 'cho',
        'gave': 'đã cho',
        'given': 'đã cho',
        'take': 'lấy',
        'takes': 'lấy',
        'took': 'đã lấy',
        'taken': 'đã lấy',
        'find': 'tìm',
        'finds': 'tìm',
        'found': 'đã tìm',
        'look': 'nhìn',
        'looks': 'nhìn',
        'looked': 'đã nhìn',
        'want': 'muốn',
        'wants': 'muốn',
        'wanted': 'đã muốn',
        'need': 'cần',
        'needs': 'cần',
        'needed': 'đã cần',
        'help': 'giúp',
        'helps': 'giúp',
        'helped': 'đã giúp',
        'work': 'làm việc',
        'works': 'làm việc',
        'worked': 'đã làm việc',
        'call': 'gọi',
        'calls': 'gọi',
        'called': 'đã gọi',
        'ask': 'hỏi',
        'asks': 'hỏi',
        'asked': 'đã hỏi',
        'try': 'thử',
        'tries': 'thử',
        'tried': 'đã thử',
        'use': 'sử dụng',
        'uses': 'sử dụng',
        'used': 'đã sử dụng',
        'feel': 'cảm thấy',
        'feels': 'cảm thấy',
        'felt': 'đã cảm thấy',
        'become': 'trở thành',
        'becomes': 'trở thành',
        'became': 'đã trở thành',
        'begin': 'bắt đầu',
        'begins': 'bắt đầu',
        'began': 'đã bắt đầu',
        'begun': 'đã bắt đầu',
        'keep': 'giữ',
        'keeps': 'giữ',
        'kept': 'đã giữ',
        'hold': 'giữ',
        'holds': 'giữ',
        'held': 'đã giữ',
        'put': 'đặt',
        'puts': 'đặt',
        'put_verb': 'đã đặt',
        'bring': 'mang',
        'brings': 'mang',
        'brought': 'đã mang',
        'start': 'bắt đầu',
        'starts': 'bắt đầu',
        'started': 'đã bắt đầu',
        'move': 'di chuyển',
        'moves': 'di chuyển',
        'moved': 'đã di chuyển',
        'turn': 'quay',
        'turns': 'quay',
        'turned': 'đã quay',
        'stop': 'dừng',
        'stops': 'dừng',
        'stopped': 'đã dừng',
        'leave': 'rời',
        'leaves': 'rời',
        'left': 'đã rời',
        'stand': 'đứng',
        'stands': 'đứng',
        'stood': 'đã đứng',
        'sit': 'ngồi',
        'sits': 'ngồi',
        'sat': 'đã ngồi',
        'lie': 'nằm',
        'lies': 'nằm',
        'lay': 'đã nằm',
        'run': 'chạy',
        'runs': 'chạy',
        'ran': 'đã chạy',
        'walk': 'đi bộ',
        'walks': 'đi bộ',
        'walked': 'đã đi bộ'
    }

    # Thay thế từ đơn với word boundary
    for english, vietnamese in word_replacements.items():
        # Sử dụng regex để thay thế chỉ khi là từ riêng biệt
        pattern = r'\b' + re.escape(english) + r'\b'
        result = re.sub(pattern, vietnamese, result, flags=re.IGNORECASE)

    # Dọn dẹp khoảng trắng thừa
    result = re.sub(r'\s+', ' ', result).strip()

    # Thêm cảnh báo nếu vẫn còn tiếng Anh
    if english_pattern.search(result):
        result += "\n\n[LƯU Ý: Vẫn còn một số từ tiếng Anh do không thể dịch tự động]"

    return result
