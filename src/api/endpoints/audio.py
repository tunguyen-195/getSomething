from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Query, Form, Body, Depends, Request
from typing import List, Dict, Any
import json
import os
from src.services.audio_service import summarize_multi_transcripts, summarize_transcript, save_audio_and_create_task, process_task, process_task_with_diarization
from src.services.task_service import (
    create_task,
    effective_task_status,
    extract_visualization_payload,
    get_task,
    list_tasks,
    resolve_task_id,
    update_task,
)
from src.services.transcribe_service import transcribe_audio
from src.services.visualization_service import generate_visualization
from src.core.logging import logger
from src.core.config import settings
import uuid
from datetime import datetime, timedelta
from src.database.models.models import Case, AudioFile, Task, User
from src.database.config.database import get_db
from sqlalchemy.orm import Session
import subprocess
from fastapi.responses import FileResponse, StreamingResponse, Response
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote
from src.services.audio_storage import media_type_for_filename, resolve_audio_path
from src.core.auth import (
    accessible_case_ids,
    assert_audio_access,
    assert_case_access,
    assert_task_access,
    check_rate_limit,
    get_current_user,
)
from src.services.audit_service import log_activity

router = APIRouter()

@router.get("/")
def read_audio(
    case_id: int = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get audio file list.

    Full mode keeps the legacy payload for compatibility. Lite mode returns
    metadata only so dashboard/list responses do not carry transcript text,
    segments, visualization graphs, or context analysis.
    """
    try:
        metadata_only = settings.APP_EDITION == "lite" or settings.PROCESSING_RUNNER == "single_job_db_lease"
        query = db.query(AudioFile)
        if case_id:
            assert_case_access(db, current_user, case_id, "read")
            query = query.filter(AudioFile.case_id == case_id)
        else:
            allowed_ids = accessible_case_ids(db, current_user)
            if allowed_ids is not None:
                query = query.filter(AudioFile.case_id.in_(allowed_ids or {-1}))
        query = query.filter(AudioFile.is_archived.is_(False))

        audio_files = query.order_by(AudioFile.created_at.desc()).all()

        result = []
        for af in audio_files:
            # Get transcript/summary/visualization from Task.result JSON
            transcript = None
            summary = None
            num_speakers = None
            has_diarization = False
            visualization_data = None
            has_visualization = False
            duration = getattr(af, 'duration', None)
            formatted_transcript = None
            segments = []
            context_analysis = {}
            result_data = {}

            task_status = None
            if af.task_id:
                task = db.query(Task).filter(Task.id == af.task_id).first()
                if task:
                    task_status = task.status
                if task and task.result:
                    try:
                        if isinstance(task.result, str):
                            import json
                            result_data = json.loads(task.result)
                        else:
                            result_data = task.result

                        # Extract data from result JSON (check multiple locations for compatibility)
                        # Priority: result["transcription"] > result["transcript"] > result["text"]
                        transcript = result_data.get('transcription') or result_data.get('transcript') or result_data.get('text')
                        summary = result_data.get('summary')
                        num_speakers = result_data.get('num_speakers')
                        has_diarization = result_data.get('has_diarization', False)
                        visualization_data = result_data.get('visualization_data')
                        has_visualization = result_data.get('has_visualization', False)
                        formatted_transcript = result_data.get('formatted_transcript')
                        segments = result_data.get('segments', [])
                        context_analysis = result_data.get('context_analysis', {})
                        if not duration:
                            duration = result_data.get('duration')
                    except Exception as e:
                        logger.warning(f"[GET_AUDIO] Failed to parse task result for {af.id}: {e}")

            item = {
                "id": af.id,
                "audio_id": af.id,
                "task_id": af.task_id,
                "filename": af.filename,
                "case_id": af.case_id,
                "status": effective_task_status(task_status, af.status, result_data),
                "audio_status": af.status,
                "duration": duration,
                "num_speakers": num_speakers,
                "has_diarization": has_diarization,
                "has_visualization": has_visualization,
                "download_url": f"/api/v1/audio/{af.id}/download",
                "created_at": af.created_at.isoformat() if af.created_at else None,
            }
            if metadata_only:
                item.update({
                    "transcript_available": bool(transcript),
                    "formatted_transcript_available": bool(formatted_transcript),
                    "segments_available": bool(segments),
                    "summary_available": bool(summary),
                    "analysis_available": bool(visualization_data or context_analysis),
                })
            else:
                item.update({
                    "visualization_data": visualization_data,
                    "transcript": transcript,
                    "summary": summary,
                    "formatted_transcript": formatted_transcript,
                    "segments": segments,
                    "context_analysis": context_analysis,
                })
            result.append(item)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GET_AUDIO] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files/{file_id}/transcript")
async def get_file_transcript(
    file_id: int,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get transcript for an audio file by file ID.
    Extracts transcript from Task.result JSON in database.
    """
    try:
        audio_file = db.query(AudioFile).filter(AudioFile.id == file_id).first()
        if not audio_file:
            raise HTTPException(status_code=404, detail="Audio file not found")
        assert_case_access(db, current_user, audio_file.case_id, "read")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"

        transcript = None
        summary = None

        if audio_file.task_id:
            task = db.query(Task).filter(Task.id == audio_file.task_id).first()
            if task and task.result:
                try:
                    if isinstance(task.result, str):
                        import json
                        result_data = json.loads(task.result)
                    else:
                        result_data = task.result

                    # Extract transcript (check multiple locations for compatibility)
                    transcript = result_data.get('transcription') or result_data.get('transcript') or result_data.get('text')
                    summary = result_data.get('summary')
                except Exception as e:
                    logger.warning(f"[GET_FILE_TRANSCRIPT] Failed to parse task result for file {file_id}: {e}")

        return {
            "file_id": file_id,
            "task_id": audio_file.task_id,
            "transcript": transcript,
            "summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GET_FILE_TRANSCRIPT] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload")
async def upload_audio(
    file: UploadFile = File(...),
    case_id: str = Form(None),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Upload file, chỉ lưu file và tạo AudioFile/Task, không xử lý ngay"""
    try:
        logger.info(f"[UPLOAD] Bắt đầu upload audio | case_id={case_id}")
        if case_id:
            assert_case_access(db, current_user, int(case_id), "write")
        check_rate_limit(f"rl:upload:{current_user.id}", settings.UPLOAD_RATE_LIMIT_PER_HOUR, 3600)
        result = save_audio_and_create_task(file, db, case_id=int(case_id) if case_id else None, user_id=current_user.id)
        log_activity(
            db,
            "upload",
            current_user.id,
            request=request,
            case_id=int(case_id) if case_id else None,
            audio_id=result.get("audio_id"),
            task_id=result.get("task_id"),
            detail={"status": "pending", "file_size": result.get("file_size")},
        )
        db.commit()
        logger.info(f"[UPLOAD] Hoàn thành upload audio | task_id={result.get('task_id')} | audio_id={result.get('audio_id')}")
        return result
    except Exception as e:
        logger.error(f"[UPLOAD] Lỗi upload file: {e}", exc_info=True)
        raise

@router.get("/tasks")
async def get_tasks(
    date: str = Query(None),
    case_id: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Get all tasks, optionally filter by date (YYYY-MM-DD) and case_id"""
    try:
        all_tasks = list_tasks()
        allowed_ids = accessible_case_ids(db, current_user)
        if allowed_ids is not None:
            all_tasks = [t for t in all_tasks if t.get("case_id") in allowed_ids]
        if date:
            try:
                dt = datetime.strptime(date, "%Y-%m-%d")
                next_day = dt + timedelta(days=1)
                filtered = [t for t in all_tasks if t.get("created_at") and dt <= datetime.fromisoformat(t["created_at"]) < next_day]
                if case_id:
                    filtered = [t for t in filtered if str(t.get("case_id")) == str(case_id)]
                return filtered
            except Exception:
                pass
        if case_id:
            all_tasks = [t for t in all_tasks if str(t.get("case_id")) == str(case_id)]
        return all_tasks
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tasks/{task_id}")
async def get_task_by_id(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get task by ID (dùng cho polling trạng thái async). Trả về đầy đủ data từ task.result."""
    try:
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "read")

        # Extract data from task.result (matching v2 structure)
        result_data = task.get("result", {})
        if isinstance(result_data, str):
            import json
            try:
                result_data = json.loads(result_data)
            except:
                result_data = {}

        # Build response with all available data
        response = {
            "task_id": task_id,
            "id": task.get("id"),
            "filename": task.get("filename"),
            "status": task.get("status"),
            "error": task.get("error"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "case_id": task.get("case_id"),
        }

        # Extract transcript from result (check multiple locations for compatibility)
        if isinstance(result_data, dict):
            transcript = result_data.get("transcription") or result_data.get("transcript") or result_data.get("text")
            summary = result_data.get("summary")
            num_speakers = result_data.get("num_speakers")
            duration = result_data.get("duration")
            has_diarization = result_data.get("has_diarization", False)
            formatted_transcript = result_data.get("formatted_transcript")
            segments = result_data.get("segments", [])
            context_analysis = result_data.get("context_analysis", {})

            # Add extracted fields to response
            if transcript:
                response["transcript"] = transcript
            if summary:
                response["summary"] = summary
            if num_speakers is not None:
                response["num_speakers"] = num_speakers
            if duration is not None:
                response["duration"] = duration
            response["has_diarization"] = has_diarization
            if formatted_transcript:
                response["formatted_transcript"] = formatted_transcript
            if segments:
                response["segments"] = segments
            if context_analysis:
                response["context_analysis"] = context_analysis

            # Also include full result for backward compatibility
            response["result"] = result_data
        else:
            # Fallback: check direct fields (old format)
            if task.get("transcript"):
                response["transcript"] = task.get("transcript")
            if task.get("summary"):
                response["summary"] = task.get("summary")
            response["result"] = result_data

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GET_TASK] Error getting task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/visualize/{task_id}")
async def create_visualization(
    task_id: str,
    visualization_type: str = Body("all", embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate visualization from transcribed task.
    Creates timeline, entity graph, and relationship map.

    Args:
        task_id: Task ID (must have transcript)
        visualization_type: Type (timeline, entity_graph, relationship_map, all)

    Returns:
        Visualization data with nodes, edges, timeline, events
    """
    resolved_task_id: str | None = None
    try:
        resolved_task_id = resolve_task_id(task_id, db=db)
        if not resolved_task_id:
            raise HTTPException(status_code=404, detail="Task not found")

        logger.info(f"[VISUALIZE_API] Starting visualization | task_id={resolved_task_id} | type={visualization_type}")
        assert_task_access(db, current_user, resolved_task_id, "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)

        update_task(resolved_task_id, {"status": "visualizing"}, db=db)
        db.commit()

        # Generate visualization
        result = generate_visualization(resolved_task_id, visualization_type)

        payload = extract_visualization_payload(result)
        update_task(
            resolved_task_id,
            {"status": "visualized", "visualization_data": payload, "has_visualization": True},
            db=db,
        )
        db.commit()

        logger.info(f"[VISUALIZE_API] Completed | task_id={resolved_task_id}")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VISUALIZE_API] Error: {e}", exc_info=True)
        update_task(resolved_task_id or task_id, {"status": "failed", "error": str(e)}, db=db)
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/summarize-multi")
async def summarize_multi(
    transcripts: Dict[str, List[str]] = Body(...),
    case_id: str = Body(None),
    model_name: str = Body(None),
    context_analysis: dict = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tóm tắt nhiều transcript thành một summary tổng hợp với model và context tuỳ chọn"""

    # Sử dụng model mặc định nếu không chỉ định
    if model_name is None:
        model_name = settings.DEFAULT_AI_MODEL

    try:
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
        if case_id:
            numeric_case_id = int(case_id)
            assert_case_access(db, current_user, numeric_case_id, "process")
            all_transcripts = []
            tasks = list_tasks()
            for task in tasks:
                if task.get("case_id") == numeric_case_id:
                    all_transcripts.append(task.get("transcript", ""))
            summary = summarize_multi_transcripts(
                all_transcripts,
                context=context_analysis,
                model_name=model_name
            )
        else:
            summary = summarize_multi_transcripts(
                transcripts.get("transcripts", []),
                context=context_analysis,
                model_name=model_name
            )
        return {"summary": summary}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error summarizing multi transcripts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/summarize-case")
def summarize_case(
    case_id: str = Body(...),
    model_name: str = Body("google/mt5-base"),
    context_analysis: dict = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tóm tắt toàn bộ các file thuộc một case"""
    try:
        assert_case_access(db, current_user, int(case_id), "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
        tasks = list_tasks(case_id=case_id)
        transcripts = []
        # Nếu context_analysis không truyền lên, tự tổng hợp context từ các task
        context = context_analysis
        if not context:
            # Lấy context_analysis đầu tiên có trong các task
            for t in tasks:
                ctx = t.get("result", {}).get("context_analysis")
                if ctx:
                    context = ctx
                    break
        for t in tasks:
            transcript = t.get("result", {}).get("transcription") or t.get("result", {}).get("text")
            if transcript:
                transcripts.append(transcript)
        summary = summarize_multi_transcripts(transcripts, context=context, model_name=model_name)
        return {"summary": summary}
    except Exception as e:
        logger.error(f"Error summarizing case: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cases")
def get_cases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Case).filter(Case.is_archived.is_(False))
    allowed_ids = accessible_case_ids(db, current_user)
    if allowed_ids is not None:
        query = query.filter(Case.id.in_(allowed_ids or {-1}))
    return query.all()

@router.post("/cases")
def create_case(
    data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from src.database.models.models import CaseStatus, CasePriority
    status = db.query(CaseStatus).filter(CaseStatus.status_name == "active").first()
    priority = db.query(CasePriority).filter(CasePriority.priority_name == "high").first()
    if not status or not priority:
        raise HTTPException(status_code=500, detail="Missing default status or priority")
    case = Case(
        title=data["title"],
        case_code=str(uuid.uuid4()),
        description=data.get("description"),
        status_id=status.id,
        priority_id=priority.id,
        created_by=current_user.id,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case

@router.patch("/tasks/{task_id}/context")
def update_task_context(
    task_id: str,
    context_analysis: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cập nhật context_analysis hoặc user_context_prompt cho task"""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    assert_task_access(db, current_user, task_id, "write")
    result = task.get("result") or {}
    # Nếu có user_context_prompt thì lưu vào result
    if "user_context_prompt" in context_analysis:
        result["user_context_prompt"] = context_analysis["user_context_prompt"]
    # Nếu có context_analysis thì lưu như cũ, nhưng luôn ép về dict
    if "context_analysis" in context_analysis:
        ca = context_analysis["context_analysis"]
        if not isinstance(ca, dict):
            ca = {}
        result["context_analysis"] = ca
    update_task(task_id, {"result": result})
    return {"detail": "Context updated"}

@router.get("/ollama-models")
def get_ollama_models():
    """Trả về danh sách các model Ollama đang chạy trên hệ thống"""
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        models = []
        for line in result.stdout.splitlines():
            if line.strip() and not line.startswith("NAME"):
                parts = line.split()
                if parts:
                    models.append(parts[0])
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}

@router.post("/tasks/{task_id}/resummarize")
def resummarize_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tóm tắt lại file với user_context_prompt mới (nếu có), luôn ưu tiên model tốt nhất."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    assert_task_access(db, current_user, task_id, "process")
    check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    result = task.get("result") or {}
    transcript = result.get("transcription") or result.get("text")
    context = result.get("context_analysis")
    user_context_prompt = result.get("user_context_prompt")
    # Lấy danh sách model ollama đang chạy
    try:
        proc = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        models = [line.split()[0] for line in proc.stdout.splitlines() if line.strip() and not line.startswith("NAME")]
    except Exception:
        models = []
    # Ưu tiên gemma2:9b, nếu không thì chọn model đầu tiên
    model_name = "gemma2:9b" if "gemma2:9b" in models else (models[0] if models else "gemma2:9b")
    if not transcript:
        raise HTTPException(status_code=400, detail="No transcript found")
    # Nếu user_context_prompt thay đổi, phân tích lại context
    if user_context_prompt:
        from src.speech_to_text.transcriber import OllamaProcessor

        context = OllamaProcessor(model_name=model_name).analyze_context(transcript)
    if context is None or not isinstance(context, dict):
        context = {}
    # Tóm tắt với prompt mạnh hơn, tăng max_length
    summary = summarize_transcript(transcript, context=context, model_name=model_name, user_context_prompt=user_context_prompt, max_length=300, min_length=80)
    result["summary"] = summary
    result["context_analysis"] = context
    result["model_name"] = model_name
    update_task(task_id, {"result": result})
    return {"summary": summary, "model": model_name}


@router.get("/{audio_id}/clip")
def stream_audio_clip(
    audio_id: int,
    start: float = Query(..., ge=0),
    end: float = Query(..., gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if end <= start:
        raise HTTPException(status_code=400, detail="end must be greater than start")

    duration = end - start
    max_duration = float(settings.ANALYSIS_CLIP_MAX_DURATION_SECONDS)
    if duration > max_duration:
        raise HTTPException(status_code=400, detail="Audio clip duration exceeds configured limit")

    audio = assert_audio_access(db, current_user, audio_id, "read")
    check_rate_limit(f"rl:audio_clip:{current_user.id}:{audio_id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    if not audio.file_path:
        raise HTTPException(status_code=404, detail="Audio file not found")

    audio_path = resolve_audio_path(audio.file_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(audio_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-f",
        "wav",
        "pipe:1",
    ]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Audio clip encoder is unavailable")
    except Exception as exc:
        logger.warning("[AUDIO_CLIP] Failed to start encoder | audio_id=%s | error=%s", audio_id, exc)
        raise HTTPException(status_code=500, detail="Failed to start audio clip encoder")

    def iter_clip():
        try:
            if process.stdout is None:
                raise RuntimeError("ffmpeg stdout pipe was not created")
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
            return_code = process.wait(timeout=2)
            if return_code != 0:
                logger.warning("[AUDIO_CLIP] Encoder exited with code %s | audio_id=%s", return_code, audio_id)
        finally:
            for stream in (process.stdout, process.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    return StreamingResponse(
        iter_clip(),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="audio-clip.wav"',
        },
    )


@router.get("/{audio_id}/download")
def download_audio(
    audio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    audio = assert_audio_access(db, current_user, audio_id, "read")
    if not audio.file_path:
        raise HTTPException(status_code=404, detail="Audio file not found")
    audio_path = resolve_audio_path(audio.file_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(
        audio_path,
        filename=audio.filename,
        media_type=media_type_for_filename(audio.filename or str(audio_path)),
    )

@router.delete("/{audio_id}")
def delete_audio(
    audio_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete audio file from disk and database. Accepts both audio_id and task_id."""
    try:
        # Try to find by task_id first (since frontend uses task_id)
        audio = db.query(AudioFile).filter(AudioFile.task_id == audio_id).first()
        if not audio:
            # Fallback to audio id
            try:
                audio = db.query(AudioFile).filter(AudioFile.id == int(audio_id)).first()
            except ValueError:
                pass

        if not audio:
            raise HTTPException(status_code=404, detail="Audio file not found")
        assert_case_access(db, current_user, audio.case_id, "delete")

        # Delete file from disk
        if audio.file_path:
            try:
                audio_path = resolve_audio_path(audio.file_path)
                audio_path.unlink(missing_ok=True)
                logger.info(f"[DELETE_AUDIO] Deleted file for audio id={audio.id}")
            except Exception as e:
                logger.warning(f"[DELETE_AUDIO] Could not delete file from disk: {e}")

        # Delete associated task if exists
        if audio.task_id:
            task = db.query(Task).filter(Task.id == audio.task_id).first()
            if task:
                db.delete(task)

        # Delete from DB
        log_activity(
            db,
            "delete",
            current_user.id,
            request=request,
            case_id=audio.case_id,
            audio_id=audio.id,
            task_id=audio.task_id,
            detail={"resource": "audio"},
        )
        db.delete(audio)
        db.commit()

        logger.info(f"[DELETE_AUDIO] Deleted audio id={audio.id}, task_id={audio.task_id}")
        return {"detail": "Audio deleted", "id": str(audio.id)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[DELETE_AUDIO] Error: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# Import from old tasks.py file (backward compatibility with v1 API)
# The new modular tasks are in src.worker.tasks.* submodules
from src.worker.tasks import process_task_async

@router.post("/process-task/{task_id}")
async def process_uploaded_task(
    task_id: str,
    model_name: str = Body(None, embed=True),
    diarization_method: str = Body("none", embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Xử lý file đã upload: transcribe, summarize, speaker diarization nếu có. Gửi task cho Celery, trả về ngay, frontend polling trạng thái."""

    # Sử dụng model mặc định nếu không chỉ định
    if model_name is None:
        model_name = settings.DEFAULT_AI_MODEL

    logger.info(f"[PROCESS_TASK] [ASYNC] Nhận request xử lý task_id={task_id} với model={model_name}, diarization_method={diarization_method}")
    assert_task_access(db, current_user, task_id, "process")
    check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    # Đẩy xử lý sang Celery để tránh giữ kết nối lâu gây ECONNRESET qua proxy dev
    process_task_async.delay(task_id, model_name, diarization_method)
    # Trả về ngay để frontend polling qua /tasks/{task_id}
    try:
        # Đánh dấu trạng thái task theo vocabulary canonical.
        task = get_task(task_id) or {}
        if task.get("status") not in ["transcribing", "transcribed", "summarizing", "summarized", "visualizing", "visualized", "failed"]:
            update_task(task_id, {"status": "transcribing"})
    except Exception:
        # Không chặn response nếu cập nhật trạng thái thất bại
        pass
    return {"task_id": task_id, "status": "transcribing"}

@router.post("/process-tasks")
async def process_multiple_tasks(
    task_ids: List[str] = Body(..., embed=True),
    model_name: str = Body(None, embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Xử lý nhiều task (nhiều file/audio) theo batch, tận dụng batch_size và pipeline tối ưu."""

    # Sử dụng model mặc định nếu không chỉ định
    if model_name is None:
        model_name = settings.DEFAULT_AI_MODEL

    import time
    from src.speech_to_text.transcriber import Transcriber
    transcriber = Transcriber()
    batch_size = transcriber.batch_size
    results = []
    total_start = time.time()
    # Chia task_ids thành các batch nhỏ
    for task_id in task_ids:
        assert_task_access(db, current_user, task_id, "process")
    check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    for i in range(0, len(task_ids), batch_size):
        batch = task_ids[i:i+batch_size]
        batch_start = time.time()
        with ThreadPoolExecutor(max_workers=min(batch_size, 8)) as executor:
            future_to_task = {executor.submit(process_task, tid, model_name, db): tid for tid in batch}
            for future in as_completed(future_to_task):
                tid = future_to_task[future]
                try:
                    result = future.result()
                    results.append({"task_id": tid, "status": "success", "result": result})
                except Exception as e:
                    results.append({"task_id": tid, "status": "error", "message": str(e)})
        batch_end = time.time()
        logger.info(f"[BATCH] Xử lý batch {i//batch_size+1}: {len(batch)} task, thời gian: {batch_end-batch_start:.2f}s")
    total_end = time.time()
    logger.info(f"[BATCH] Tổng thời gian xử lý {len(task_ids)} task: {total_end-total_start:.2f}s")
    return {"results": results}

@router.post("/batch")
async def batch_upload_audio(
    files: List[UploadFile] = File(...),
    case_id: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Batch upload audio files, create AudioFile and Task for each."""
    task_ids = []
    results = []
    status = "success"
    assert_case_access(db, current_user, int(case_id), "write")
    check_rate_limit(f"rl:upload:{current_user.id}", settings.UPLOAD_RATE_LIMIT_PER_HOUR, 3600)
    for file in files:
        try:
            result = save_audio_and_create_task(file, db, case_id=int(case_id) if case_id else None, user_id=current_user.id)
            task_ids.append(result.get("task_id"))
            results.append(result)
        except Exception as e:
            status = "error"
            results.append({"error": str(e), "filename": file.filename})
    return {"task_ids": task_ids, "results": results, "status": status}

@router.get("/public/{filename}")
def get_audio_public(filename: str):
    raise HTTPException(status_code=410, detail="Use /api/v1/audio/{audio_id}/download")


# ============================================================================
# NEW ENDPOINTS - Separate Workflow Steps
# ============================================================================

@router.post("/transcribe/{task_id}")
async def transcribe_task(
    task_id: str,
    enable_diarization: bool = Body(True, embed=True),
    diarization_method: str = Body("pyannote", embed=True),
    fast_mode: bool = Body(True, embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Transcribe audio file (SEPARATE from summarization).

    Args:
        task_id: Task ID (file must be uploaded first)
        enable_diarization: Enable speaker diarization
        diarization_method: Method (pyannote, simple_vad, none)
        fast_mode: Skip heavy post-processing

    Returns:
        Transcription result with segments, speakers, etc.
    """
    logger.info(
        f"[API] POST /transcribe/{task_id} | "
        f"diarization={enable_diarization} | method={diarization_method} | fast={fast_mode}"
    )

    try:
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
        result = transcribe_audio(
            task_id=task_id,
            db=db,
            enable_diarization=enable_diarization,
            diarization_method=diarization_method if enable_diarization else "none",
            fast_mode=fast_mode
        )
        return result
    except Exception as e:
        logger.error(f"[API] Error transcribing task {task_id}: {e}", exc_info=True)
        raise


@router.post("/summarize-task/{task_id}")
async def summarize_task(
    task_id: str,
    model_name: str = Body("gemma2:9b", embed=True),
    summary_type: str = Body("detailed", embed=True),
    include_context_analysis: bool = Body(True, embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Summarize transcript (SEPARATE from transcription).
    Task must be transcribed first.

    Args:
        task_id: Task ID (must have transcript)
        model_name: AI model to use (gemma2:9b, deepseek-r1:7b, etc.)
        summary_type: Type of summary (brief, detailed, investigation)
        include_context_analysis: Include entity/action analysis

    Returns:
        Summary with context analysis
    """
    logger.info(
        f"[API] POST /summarize-task/{task_id} | "
        f"model={model_name} | type={summary_type} | context={include_context_analysis}"
    )

    try:
        # Get task
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)

        # Check if transcript exists
        transcript = task.get('transcript')
        if not transcript:
            raise HTTPException(
                status_code=400,
                detail="Task must be transcribed first. Please run transcription before summarization."
            )

        # Get context analysis if needed
        context = task.get('context_analysis') if include_context_analysis else None

        # Summarize using V2
        from src.services.summarization.summary_service_v2 import summarize_transcript_v2

        # Call V2 service
        result_v2 = summarize_transcript_v2(
            transcript=transcript,
            model_name=model_name,
            summary_type=summary_type,
            include_context=include_context_analysis
        )

        summary_text = result_v2.get("summary", "")
        visualization_data = result_v2.get("visualization_data")
        has_visualization = result_v2.get("has_visualization", False)

        # Prepare existing result from task to update, don't overwrite everything
        current_result = task.get("result") or {}
        if isinstance(current_result, str):
            import json
            try:
                current_result = json.loads(current_result)
            except:
                current_result = {}

        # Update result dict
        current_result["summary"] = summary_text
        if has_visualization:
            current_result["visualization_data"] = visualization_data
            current_result["has_visualization"] = True

        # Update task with summary and result
        update_task(task_id, {
            "status": "summarized",
            "summary": summary_text,
            "result": current_result
        })

        response = {
            "task_id": task_id,
            "status": "summarized",
            "summary": summary_text,
            "model_name": model_name,
            "summary_type": summary_type,
            "has_visualization": has_visualization,
            "visualization_data": visualization_data
        }

        logger.info(f"[API] Summary completed for task {task_id}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Error summarizing task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# DEPRECATED: Duplicate endpoint - using create_visualization (line 255) instead
# @router.post("/visualize/{task_id}")
# async def visualize_task(
#     task_id: str,
#     visualization_type: str = Body("all", embed=True)
# ):
#     """
#     Generate visualization data from transcript.
#     Task must be transcribed first.
#
#     Args:
#         task_id: Task ID (must have transcript)
#         visualization_type: Type (timeline, entity_graph, relationship_map, all)
#
#     Returns:
#         Visualization data (nodes, edges, timeline, events)
#     """
#     logger.info(
#         f"[API] POST /visualize/{task_id} | type={visualization_type}"
#     )
#
#     try:
#         result = generate_visualization(
#             task_id=task_id,
#             visualization_type=visualization_type
#         )
#         return result
#     except Exception as e:
#         logger.error(f"[API] Error generating visualization for task {task_id}: {e}", exc_info=True)
#         raise
