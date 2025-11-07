"""Audio API v2 - Modular"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Depends, Form
from typing import Dict, Any
from src.core.logging import logger
from src.database.config.database import get_db
from src.database.models.models import AudioFile
from sqlalchemy.orm import Session
from pathlib import Path
import shutil

router = APIRouter()

@router.post("/upload")
async def upload_audio_v2(file: UploadFile = File(...), case_id: str = Form(None), db: Session = Depends(get_db)):
    try:
        logger.info(f"[API_V2] Upload | file={file.filename}")
        if not file.filename or not file.filename.lower().endswith((".mp3",".wav",".m4a",".ogg")):
            raise HTTPException(status_code=400, detail="Invalid format")
        audio_storage_dir = Path("storage/audio")
        audio_storage_dir.mkdir(parents=True, exist_ok=True)
        audio_storage_path = audio_storage_dir / file.filename
        with open(audio_storage_path, "wb") as out_file:
            shutil.copyfileobj(file.file, out_file)
        from src.services.task_service import create_task
        task = create_task(file.filename, case_id=int(case_id) if case_id else None, db=db)
        if not task:
            raise HTTPException(status_code=400, detail="Failed to create task")
        audio_file = AudioFile(filename=file.filename, case_id=int(case_id) if case_id else None, task_id=task["id"], file_path=str(audio_storage_path), status="uploaded", language_id=1, uploaded_by=1, file_size=audio_storage_path.stat().st_size, storage_type='local')
        db.add(audio_file)
        db.commit()
        db.refresh(audio_file)
        return {"task_id": task["id"], "audio_file_id": audio_file.id, "filename": file.filename, "status": "uploaded"}
    except Exception as e:
        logger.error(f"[API_V2] Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/transcribe/{task_id}")
async def transcribe_v2(task_id: str, enable_diarization: bool = Body(True), diarization_method: str = Body("pyannote"), language: str = Body("vi"), fast_mode: bool = Body(True), async_mode: bool = Body(True), db: Session = Depends(get_db)):
    try:
        from src.services.task_service import get_task, update_task
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if async_mode:
            from src.worker.tasks.transcribe_task import transcribe_audio_task
            celery_task = transcribe_audio_task.delay(task_id, enable_diarization, diarization_method, language, fast_mode)
            update_task(task_id, {"status": "processing"})
            return {"task_id": task_id, "celery_task_id": celery_task.id, "status": "processing"}
        else:
            from src.services.transcription.transcribe_service_v2 import transcribe_audio_v2
            return transcribe_audio_v2(task_id, db, enable_diarization, diarization_method, language, fast_mode)
    except Exception as e:
        logger.error(f"[API_V2] Transcribe error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/summarize/{task_id}")
async def summarize_v2(task_id: str, model_name: str = Body(None), summary_type: str = Body("detailed"), include_context: bool = Body(True), async_mode: bool = Body(True)):
    try:
        from src.services.task_service import get_task, update_task
        task = get_task(task_id)
        if not task or not task.get("transcript"):
            raise HTTPException(status_code=400, detail="No transcript")
        if async_mode:
            from src.worker.tasks.summarize_task import summarize_transcript_task
            celery_task = summarize_transcript_task.delay(task_id, model_name, summary_type, include_context, None)
            update_task(task_id, {"status": "summarizing"})
            return {"task_id": task_id, "status": "summarizing"}
        else:
            from src.services.summarization.summary_service_v2 import summarize_transcript_v2
            result = summarize_transcript_v2(task["transcript"], model_name, summary_type, include_context)
            update_task(task_id, {"status": "summarized", "summary": result["summary"]})
            return {"task_id": task_id, "status": "summarized", "result": result}
    except Exception as e:
        logger.error(f"[API_V2] Summarize error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tasks/{task_id}/status")
async def get_status_v2(task_id: str):
    try:
        from src.services.task_service import get_task
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task_id": task_id, "status": task.get("status"), "transcript": task.get("transcript"), "summary": task.get("summary"), "num_speakers": task.get("num_speakers"), "duration": task.get("duration"), "error": task.get("error")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
