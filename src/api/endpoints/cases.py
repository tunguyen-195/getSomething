from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from src.database.models.models import Case, CaseStatus, CasePriority, User, AudioFile
from src.database.config.database import get_db
import uuid
import logging
from src.database.models.schemas import TaskResult

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/", response_model=List[Dict[str, Any]])
def get_cases(db: Session = Depends(get_db)):
    cases = db.query(Case).all()
    result = []
    for c in cases:
        # Lấy tất cả audio files của case
        audio_files = db.query(AudioFile).filter(AudioFile.case_id == c.id).all()
        # Tổng hợp transcript, summary, context_analysis từ các file
        transcripts = []
        summaries = []
        contexts = []
        for f in audio_files:
            task = f.task
            task_result = task.result if task and task.result else None
            if task_result:
                try:
                    task_result = TaskResult(**task_result).dict()
                except Exception:
                    task_result = TaskResult(
                        transcription="",
                        summary="",
                        context_analysis={},
                        confidence=0.0,
                        duration=0.0,
                        language="vi",
                        processing_time=0.0
                    ).dict()
                if task_result.get("transcription"):
                    transcripts.append(task_result["transcription"])
                if task_result.get("summary"):
                    summaries.append(task_result["summary"])
                if task_result.get("context_analysis"):
                    contexts.append(task_result["context_analysis"])
        result.append({
            "id": c.id,
            "case_code": c.case_code,
            "title": c.title,
            "description": c.description,
            "status_id": c.status_id,
            "priority_id": c.priority_id,
            "created_by": c.created_by,
            "transcripts": transcripts,
            "summaries": summaries,
            "contexts": contexts,
        })
    return result

@router.post("/", response_model=Dict[str, Any], status_code=201)
def create_case(data: Dict[str, Any], db: Session = Depends(get_db)):
    try:
        # Lấy id mặc định
        status = db.query(CaseStatus).filter(CaseStatus.status_name == "active").first()
        priority = db.query(CasePriority).filter(CasePriority.priority_name == "high").first()
        user = db.query(User).filter(User.username == "admin").first()
        if not status or not priority or not user:
            logger.error(f"Missing default: status={status}, priority={priority}, user={user}")
            raise HTTPException(status_code=500, detail="Missing default status, priority, or admin user")
        case = Case(
            title=data["title"],
            case_code=str(uuid.uuid4()),
            description=data.get("description"),
            status_id=status.id,
            priority_id=priority.id,
            created_by=user.id
        )
        db.add(case)
        db.commit()
        db.refresh(case)
        logger.info(f"Created case: {case.id} - {case.title}")
        return {
            "id": case.id,
            "case_code": case.case_code,
            "title": case.title,
            "description": case.description,
            "status_id": case.status_id,
            "priority_id": case.priority_id,
            "created_by": case.created_by
        }
    except Exception as e:
        logger.error(f"Error creating case: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{case_id}", response_model=Dict[str, Any])
def get_case(case_id: int, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case

@router.patch("/{case_id}", response_model=Dict[str, Any])
def update_case(case_id: int, data: Dict[str, Any], db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    for k, v in data.items():
        if hasattr(case, k):
            setattr(case, k, v)
    db.commit()
    db.refresh(case)
    return case

@router.delete("/{case_id}")
def delete_case(case_id: int, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    db.delete(case)
    db.commit()
    return {"detail": "Case deleted"}

@router.get("/{case_id}/files")
def get_case_files(case_id: int, request: Request, db: Session = Depends(get_db)):
    files = db.query(AudioFile).filter(AudioFile.case_id == case_id).all()
    base_url = str(request.base_url).rstrip('/')
    result = []
    for f in files:
        task = f.task
        task_result = task.result if task and task.result else None
        # Validate schema
        if task_result:
            try:
                task_result = TaskResult(**task_result).dict()
            except Exception:
                task_result = TaskResult(
                    transcription="",
                    summary="",
                    context_analysis={},
                    confidence=0.0,
                    duration=0.0,
                    language="vi",
                    processing_time=0.0
                ).dict()
        else:
            task_result = TaskResult(
                transcription="",
                summary="",
                context_analysis={},
                confidence=0.0,
                duration=0.0,
                language="vi",
                processing_time=0.0
            ).dict()
        # Đảm bảo luôn trả về task_id đúng
        result.append({
            "id": f.id,
            "filename": f.filename,
            "status": f.status,
            "url": f"{base_url}/audio/{f.id}/download",
            "task_id": f.task_id,  # Sử dụng trực tiếp AudioFile.task_id
            "transcript": task_result.get("transcription"),
            "summary": task_result.get("summary"),
            "context_analysis": task_result.get("context_analysis"),
            "result": task_result,
        })
    return result 