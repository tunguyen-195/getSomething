from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Query, Form, Body, Depends, Request
from typing import List, Dict, Any
import json
import os
from src.services.audio_service import summarize_multi_transcripts, summarize_transcript, save_audio_and_create_task, process_task
from src.services.task_service import create_task, get_task, list_tasks, update_task
from src.core.logging import logger
import uuid
from datetime import datetime, timedelta
from src.database.models.models import Case, AudioFile, Task
from src.database.config.database import get_db
from sqlalchemy.orm import Session
import subprocess
from src.speech_to_text.transcriber import OllamaProcessor
from fastapi.responses import FileResponse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote

router = APIRouter()

@router.get("/")
def read_audio():
    return {"message": "Audio endpoint"}

@router.post("/upload")
async def upload_audio(
    file: UploadFile = File(...),
    case_id: str = Form(None),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Upload file, chỉ lưu file và tạo AudioFile/Task, không xử lý ngay"""
    return save_audio_and_create_task(file, db, case_id=int(case_id) if case_id else None)

@router.get("/tasks")
async def get_tasks(date: str = Query(None), case_id: str = Query(None)) -> List[Dict[str, Any]]:
    """Get all tasks, optionally filter by date (YYYY-MM-DD) and case_id"""
    try:
        all_tasks = list_tasks()
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
async def get_task_by_id(task_id: str) -> Dict[str, Any]:
    """Get task by ID"""
    try:
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/summarize-multi")
async def summarize_multi(
    transcripts: Dict[str, List[str]] = Body(...),
    case_id: str = Body(None),
    model_name: str = Body("google/mt5-base"),
    context_analysis: dict = Body(None)
):
    """Tóm tắt nhiều transcript thành một summary tổng hợp với model và context tuỳ chọn"""
    try:
        if case_id:
            all_transcripts = []
            tasks = list_tasks()
            for task in tasks:
                if task.get("case_id") == case_id:
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
    except Exception as e:
        logger.error(f"Error summarizing multi transcripts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/summarize-case")
def summarize_case(
    case_id: str = Body(...),
    model_name: str = Body("google/mt5-base"),
    context_analysis: dict = Body(None)
):
    """Tóm tắt toàn bộ các file thuộc một case"""
    try:
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
def get_cases(db: Session = Depends(get_db)):
    return db.query(Case).all()

@router.post("/cases")
def create_case(data: Dict[str, Any], db: Session = Depends(get_db)):
    case = Case(title=data["title"], case_code=str(uuid.uuid4()))
    db.add(case)
    db.commit()
    db.refresh(case)
    return case

@router.patch("/tasks/{task_id}/context")
def update_task_context(task_id: str, context_analysis: dict = Body(...)):
    """Cập nhật context_analysis hoặc user_context_prompt cho task"""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
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
def resummarize_task(task_id: str):
    """Tóm tắt lại file với user_context_prompt mới (nếu có), luôn ưu tiên model tốt nhất."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
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

@router.get("/{audio_id}/download")
def download_audio(audio_id: int, db: Session = Depends(get_db)):
    audio = db.query(AudioFile).filter(AudioFile.id == audio_id).first()
    if not audio or not audio.file_path:
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(audio.file_path, filename=audio.filename, media_type="audio/mpeg")

@router.post("/process-task/{task_id}")
async def process_uploaded_task(
    task_id: str,
    model_name: str = Body("gemma2:9b", embed=True),
    db: Session = Depends(get_db)
):
    """Xử lý file đã upload: transcribe, summarize, update task/audio_file"""
    return process_task(task_id, model_name, db) 

@router.post("/process-tasks")
async def process_multiple_tasks(
    task_ids: List[str] = Body(..., embed=True),
    model_name: str = Body("gemma2:9b", embed=True),
    db: Session = Depends(get_db)
):
    """Xử lý nhiều task (nhiều file/audio) song song, trả về trạng thái từng task."""
    results = []
    with ThreadPoolExecutor(max_workers=min(8, len(task_ids))) as executor:
        future_to_task = {executor.submit(process_task, tid, model_name, db): tid for tid in task_ids}
        for future in as_completed(future_to_task):
            tid = future_to_task[future]
            try:
                result = future.result()
                results.append({"task_id": tid, "status": "success", "result": result})
            except Exception as e:
                results.append({"task_id": tid, "status": "error", "message": str(e)})
    return {"results": results}

@router.post("/batch")
async def batch_upload_audio(
    files: List[UploadFile] = File(...),
    case_id: str = Form(...),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Batch upload audio files, create AudioFile and Task for each."""
    task_ids = []
    results = []
    status = "success"
    for file in files:
        try:
            result = save_audio_and_create_task(file, db, case_id=int(case_id) if case_id else None)
            task_ids.append(result.get("task_id"))
            results.append(result)
        except Exception as e:
            status = "error"
            results.append({"error": str(e), "filename": file.filename})
    return {"task_ids": task_ids, "results": results, "status": status}

@router.get("/public/{filename}")
def get_audio_public(filename: str):
    filename = unquote(filename)
    file_path = os.path.join("storage/audio", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Audio file not found")
    # Đoán Content-Type từ đuôi file
    ext = filename.split('.')[-1].lower()
    if ext == 'mp3':
        media_type = 'audio/mpeg'
    elif ext == 'wav':
        media_type = 'audio/wav'
    elif ext == 'ogg':
        media_type = 'audio/ogg'
    elif ext == 'm4a':
        media_type = 'audio/mp4'
    else:
        media_type = 'application/octet-stream'
    return FileResponse(file_path, media_type=media_type, filename=filename) 