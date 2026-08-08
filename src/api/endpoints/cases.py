from collections import defaultdict

from fastapi import APIRouter, HTTPException, Depends, Query, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, text
from sqlalchemy.orm import joinedload
from typing import List, Dict, Any
from src.database.models.models import Case, CaseStatus, CasePriority, User, AudioFile, CaseParticipant, ParticipantRole
from src.database.config.database import get_db
from src.core.auth import accessible_case_ids, assert_case_access, get_current_user
from src.services.audit_service import log_activity
import uuid
import logging
from src.core.time import LEGACY_DATABASE_TIMEZONE, utc_isoformat
from src.database.models.schemas import CaseUpdate, TaskResult

router = APIRouter()
logger = logging.getLogger(__name__)


def _case_to_dict(case: Case) -> Dict[str, Any]:
    return {
        "id": case.id,
        "case_code": case.case_code,
        "title": case.title,
        "description": case.description,
        "status_id": case.status_id,
        "priority_id": case.priority_id,
        "created_by": case.created_by,
        "created_at": utc_isoformat(
            case.created_at,
            naive_timezone=LEGACY_DATABASE_TIMEZONE,
        ),
        "is_archived": case.is_archived,
    }

@router.get("/", response_model=List[Dict[str, Any]])
def get_cases(
    response: Response,
    sort_by: str = "created_at",
    order: str = "desc",
    include_archived: bool = False,
    compact: bool = False,
    limit: int | None = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Case)
    if not include_archived:
        query = query.filter(Case.is_archived.is_(False))
    allowed_ids = accessible_case_ids(db, current_user)
    if allowed_ids is not None:
        query = query.filter(Case.id.in_(allowed_ids or {-1}))

    search_term = (search or "").strip()
    if search_term:
        pattern = f"%{search_term}%"
        query = query.filter(or_(Case.title.ilike(pattern), Case.case_code.ilike(pattern)))

    total = query.order_by(None).count()
    response.headers["X-Total-Count"] = str(total)

    # Sorting logic
    if sort_by == "title":
        # Case-insensitive sorting - Explicit SQL expression
        if order == "asc":
            query = query.order_by(text("lower(title) ASC"))
        else:
            query = query.order_by(text("lower(title) DESC"))
    else:  # default to created_at
        if order == "asc":
            query = query.order_by(
                Case.created_at.asc().nullslast(),
                Case.id.asc(),
            )
        else:
            query = query.order_by(
                Case.created_at.desc().nullslast(),
                Case.id.desc(),
            )

    if offset:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)

    cases = query.all()
    if compact:
        return [_case_to_dict(case) for case in cases]

    case_ids = [case.id for case in cases]
    audio_by_case: dict[int, list[AudioFile]] = defaultdict(list)
    if case_ids:
        audio_files = (
            db.query(AudioFile)
            .options(joinedload(AudioFile.task))
            .filter(AudioFile.case_id.in_(case_ids))
            .all()
        )
        for audio_file in audio_files:
            audio_by_case[audio_file.case_id].append(audio_file)

    result = []
    for c in cases:
        # Tổng hợp transcript, summary, context_analysis từ các file
        transcripts = []
        summaries = []
        contexts = []
        for f in audio_by_case.get(c.id, []):
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
            **_case_to_dict(c),
            "transcripts": transcripts,
            "summaries": summaries,
            "contexts": contexts,
        })
    return result

@router.post("/", response_model=Dict[str, Any], status_code=201)
def create_case(
    data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        # Lấy id mặc định
        status = db.query(CaseStatus).filter(CaseStatus.status_name == "active").first()
        priority = db.query(CasePriority).filter(CasePriority.priority_name == "high").first()
        if not status or not priority:
            logger.error(f"Missing default: status={status}, priority={priority}")
            raise HTTPException(status_code=500, detail="Missing default status or priority")
        case = Case(
            title=data["title"],
            case_code=str(uuid.uuid4()),
            description=data.get("description"),
            status_id=status.id,
            priority_id=priority.id,
            created_by=current_user.id
        )
        db.add(case)
        db.flush()
        owner_role = db.query(ParticipantRole).filter(ParticipantRole.role_name == "owner").first()
        if owner_role:
            db.add(CaseParticipant(case_id=case.id, user_id=current_user.id, role_id=owner_role.id, is_active=True))
        db.commit()
        db.refresh(case)
        logger.info(f"Created case: {case.id} - {case.title}")
        return _case_to_dict(case)
    except Exception as e:
        logger.error(f"Error creating case: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{case_id}", response_model=Dict[str, Any])
def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_case_access(db, current_user, case_id, "read")
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case or case.is_archived:
        raise HTTPException(status_code=404, detail="Case not found")
    return _case_to_dict(case)

@router.patch("/{case_id}", response_model=Dict[str, Any])
def update_case(
    case_id: int,
    data: CaseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_case_access(db, current_user, case_id, "write")
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    updates = data.model_dump(exclude_unset=True)
    if "status_id" in updates:
        status = db.query(CaseStatus).filter(
            CaseStatus.id == updates["status_id"],
            CaseStatus.is_active.is_(True),
        ).first()
        if not status:
            raise HTTPException(status_code=422, detail="Invalid case status")
    if "priority_id" in updates:
        priority = db.query(CasePriority).filter(
            CasePriority.id == updates["priority_id"]
        ).first()
        if not priority:
            raise HTTPException(status_code=422, detail="Invalid case priority")
    for field, value in updates.items():
        setattr(case, field, value)
    db.commit()
    db.refresh(case)
    return _case_to_dict(case)

@router.delete("/{case_id}")
def delete_case(
    case_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_case_access(db, current_user, case_id, "archive")
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    case.is_archived = True
    case.archive_reason = "Archived by user"
    for audio in db.query(AudioFile).filter(AudioFile.case_id == case_id).all():
        audio.is_archived = True
        audio.archive_reason = "Parent case archived"
    log_activity(
        db,
        "archive",
        current_user.id,
        request=request,
        case_id=case_id,
        detail={"resource": "case"},
    )
    db.commit()
    return {"detail": "Case archived"}

@router.get("/{case_id}/files")
def get_case_files(
    case_id: int,
    request: Request,
    sort_by: str = "created_at",
    order: str = "desc",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_case_access(db, current_user, case_id, "read")
    query = (
        db.query(AudioFile)
        .options(joinedload(AudioFile.task))
        .filter(AudioFile.case_id == case_id)
    )
    query = query.filter(AudioFile.is_archived.is_(False))

    # Sorting logic
    if sort_by == "filename":
        field = AudioFile.filename
    else:  # default to created_at
        field = AudioFile.created_at

    if order == "asc":
        query = query.order_by(field.asc(), AudioFile.id.asc())
    else:
        query = query.order_by(field.desc(), AudioFile.id.desc())

    files = query.all()
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
            "audio_id": f.id,
            "filename": f.filename,
            "status": f.status,
            "url": f"{base_url}/api/v1/audio/{f.id}/download",
            "download_url": f"/api/v1/audio/{f.id}/download",
            "task_id": f.task_id,  # Sử dụng trực tiếp AudioFile.task_id
            "transcript": task_result.get("transcription"),
            "summary": task_result.get("summary"),
            "context_analysis": task_result.get("context_analysis"),
            "result": task_result,
            "created_at": utc_isoformat(
                f.created_at,
                naive_timezone=LEGACY_DATABASE_TIMEZONE,
            ),
            "uploaded_at": utc_isoformat(
                f.uploaded_at,
                naive_timezone=LEGACY_DATABASE_TIMEZONE,
            ),
        })
    return result
