from fastapi import Request
from sqlalchemy.orm import Session

from src.database.models.models import ActivityLog, ActivityType


SENSITIVE_KEYS = {
    "password",
    "token",
    "transcript",
    "transcription",
    "summary",
    "context_analysis",
    "prompt",
    "model_output",
    "file_path",
}


def _sanitize_detail(detail: dict | None) -> dict:
    clean = {}
    for key, value in (detail or {}).items():
        if key in SENSITIVE_KEYS:
            continue
        clean[key] = value
    return clean


def log_activity(
    db: Session,
    action: str,
    user_id: int,
    request: Request | None = None,
    case_id: int | None = None,
    audio_id: int | None = None,
    task_id: str | None = None,
    detail: dict | None = None,
) -> None:
    activity_type = db.query(ActivityType).filter(ActivityType.type_name == action).first()
    if not activity_type:
        return
    db.add(
        ActivityLog(
            user_id=user_id,
            case_id=case_id,
            audio_id=audio_id,
            task_id=task_id,
            activity_type_id=activity_type.id,
            action_detail=_sanitize_detail(detail),
            ip_address=(request.client.host if request and request.client else None),
            user_agent=(request.headers.get("user-agent", "")[:500] if request else None),
        )
    )
