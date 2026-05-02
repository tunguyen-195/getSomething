import copy
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.database.config.database import SessionLocal
from src.database.models.models import (
    AudioFile,
    Case,
    CaseParticipant,
    CasePriority,
    CaseStatus,
    ParticipantRole,
    Task as DBTask,
    User,
)

logger = logging.getLogger(__name__)

CANONICAL_STATUSES = {
    "uploaded",
    "transcribing",
    "transcribed",
    "summarizing",
    "summarized",
    "visualizing",
    "visualized",
    "failed",
}

LEGACY_STATUS_ALIASES = {
    "pending": "uploaded",
    "processing": "transcribing",
}

RESULT_FIELD_ALIASES = {
    "transcript": "transcription",
    "context": "context_analysis",
    "visualization": "visualization_data",
}

RESULT_FIELDS = {
    "transcription",
    "summary",
    "segments",
    "duration",
    "context_analysis",
    "visualization_data",
    "has_visualization",
    "audio_id",
    "download_url",
    "language",
    "confidence",
    "processing_time",
    "formatted_transcript",
    "transcript_file",
    "has_diarization",
    "num_speakers",
    "speed_factor",
    "diarization_method",
    "transcription_time",
    "diarization_time",
    "fast_mode",
    "caption",
    "model_name",
    "summary_model",
    "summary_type",
}


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    return {}


def extract_visualization_payload(value: Any) -> Any:
    """Return the raw visualization graph/timeline payload from wrapper-shaped results."""
    if not isinstance(value, dict):
        return value
    if "visualization_data" in value:
        return extract_visualization_payload(value["visualization_data"])
    if "data" in value and (
        "visualization_type" in value
        or value.get("status") in {"visualization_ready", "visualized", "success"}
        or "task_id" in value
    ):
        return extract_visualization_payload(value["data"])
    if "result" in value and value.get("status") == "success":
        return extract_visualization_payload(value["result"])
    return value


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if key == "visualization_data":
            merged[key] = extract_visualization_payload(value)
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def canonical_status(status: str | None, result: Dict[str, Any] | None = None) -> str | None:
    if not status:
        return status
    if status in CANONICAL_STATUSES:
        return status
    if status == "completed":
        result = result or {}
        if result.get("has_visualization") or result.get("visualization_data"):
            return "visualized"
        if result.get("summary"):
            return "summarized"
        if result.get("transcription") or result.get("transcript") or result.get("text"):
            return "transcribed"
        return "transcribed"
    return LEGACY_STATUS_ALIASES.get(status, status)


def effective_task_status(task_status: str | None, audio_status: str | None = None, result: Dict[str, Any] | None = None) -> str | None:
    status = canonical_status(task_status, result)
    if status:
        return status
    return canonical_status(audio_status, result)


def _sync_audio_status(db: Session, task: DBTask, status: str | None) -> None:
    if not status:
        return
    normalized = canonical_status(status, _as_dict(task.result))
    audio_files = list(task.audio_files or [])
    if not audio_files:
        audio_files = db.query(AudioFile).filter(AudioFile.task_id == task.id).all()
    for audio in audio_files:
        audio.status = normalized
        audio.updated_at = datetime.utcnow()


def _task_to_dict(task: DBTask) -> Dict[str, Any]:
    result = _as_dict(task.result)
    audio = task.audio_files[0] if task.audio_files else None
    if audio:
        result.setdefault("audio_id", audio.id)
        result.setdefault("download_url", f"/api/v1/audio/{audio.id}/download")

    data = {
        "id": task.id,
        "filename": task.filename,
        "status": effective_task_status(task.status, audio.status if audio else None, result),
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "result": result,
        "error": task.error,
        "case_id": task.case_id,
        "user_id": task.user_id,
    }
    for key, value in result.items():
        data.setdefault(key, value)
    data.setdefault("transcript", result.get("transcription"))
    return data


def _get_actor(db: Session, user_id: int | None) -> User | None:
    if user_id:
        return db.query(User).filter(User.id == user_id).first()
    return db.query(User).filter(User.username == "admin").first()


def create_task(
    filename: str,
    case_id: int | None = None,
    db: Session | None = None,
    user_id: int | None = None,
    commit: bool = True,
) -> Optional[Dict[str, Any]]:
    own_session = db is None
    db = db or SessionLocal()
    try:
        actor = _get_actor(db, user_id)
        if not actor:
            logger.error("Cannot create task without a valid actor/admin user")
            return None

        if case_id is not None:
            case = db.query(Case).filter(Case.id == case_id).first()
            if not case:
                logger.error("Case with id %s does not exist", case_id)
                return None
        else:
            status = db.query(CaseStatus).filter(CaseStatus.status_name == "active").first()
            priority = db.query(CasePriority).filter(CasePriority.priority_name == "high").first()
            if not status or not priority:
                logger.error("Missing default case status or priority")
                return None
            case = Case(
                title=filename,
                case_code=str(uuid.uuid4()),
                description=None,
                status_id=status.id,
                priority_id=priority.id,
                created_by=actor.id,
            )
            db.add(case)
            db.flush()
            owner_role = db.query(ParticipantRole).filter(ParticipantRole.role_name == "owner").first()
            if owner_role:
                db.add(
                    CaseParticipant(
                        case_id=case.id,
                        user_id=actor.id,
                        role_id=owner_role.id,
                        is_active=True,
                    )
                )

        now = datetime.utcnow()
        task = DBTask(
            id=str(uuid.uuid4()),
            filename=filename,
            status="pending",
            case_id=case.id,
            user_id=actor.id,
            created_at=now,
            updated_at=now,
            result={},
        )
        db.add(task)
        db.flush()
        if own_session or commit:
            db.commit()
            db.refresh(task)
        return _task_to_dict(task)
    except Exception:
        if own_session or commit:
            db.rollback()
        logger.exception("Error creating task")
        return None
    finally:
        if own_session:
            db.close()


def get_task(task_id: str, db: Session | None = None) -> Optional[Dict[str, Any]]:
    own_session = db is None
    db = db or SessionLocal()
    try:
        task = db.query(DBTask).filter(DBTask.id == task_id).first()
        if not task:
            return None
        return _task_to_dict(task)
    except Exception:
        logger.exception("Error getting task %s", task_id)
        return None
    finally:
        if own_session:
            db.close()


def update_task(task_id: str, data: Dict[str, Any], db: Session | None = None) -> bool:
    own_session = db is None
    db = db or SessionLocal()
    try:
        query = db.query(DBTask).filter(DBTask.id == task_id)
        if db.bind and db.bind.dialect.name != "sqlite":
            query = query.with_for_update()
        task = query.first()
        if not task:
            logger.warning("Task %s not found", task_id)
            return False

        result_patch: Dict[str, Any] = {}
        status_update: str | None = None
        for key, value in data.items():
            normalized_key = RESULT_FIELD_ALIASES.get(key, key)
            if normalized_key == "result":
                if not isinstance(value, dict):
                    logger.error("Task result update must be a dict")
                    return False
                result_patch = _deep_merge(result_patch, value)
            elif hasattr(task, normalized_key):
                if normalized_key == "status":
                    status_update = value
                else:
                    setattr(task, normalized_key, value)
            elif normalized_key in RESULT_FIELDS:
                if normalized_key == "visualization_data":
                    result_patch[normalized_key] = extract_visualization_payload(value)
                    result_patch["has_visualization"] = bool(result_patch[normalized_key])
                else:
                    result_patch[normalized_key] = value
            else:
                result_patch[normalized_key] = value

        if result_patch:
            task.result = _deep_merge(_as_dict(task.result), result_patch)
        if status_update:
            task.status = canonical_status(status_update, _as_dict(task.result))
            _sync_audio_status(db, task, task.status)
        task.updated_at = datetime.utcnow()
        if own_session:
            db.commit()
        else:
            db.flush()
        return True
    except Exception:
        if own_session:
            db.rollback()
        logger.exception("Error updating task %s", task_id)
        return False
    finally:
        if own_session:
            db.close()


def delete_task(task_id: str) -> bool:
    db = SessionLocal()
    try:
        task = db.query(DBTask).filter(DBTask.id == task_id).first()
        if not task:
            return False
        db.delete(task)
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("Error deleting task %s", task_id)
        return False
    finally:
        db.close()


def list_tasks(case_id: str | None = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        query = db.query(DBTask)
        if case_id:
            query = query.filter(DBTask.case_id == case_id)
        return [_task_to_dict(task) for task in query.order_by(desc(DBTask.created_at)).all()]
    except Exception:
        logger.exception("Error listing tasks")
        return []
    finally:
        db.close()
