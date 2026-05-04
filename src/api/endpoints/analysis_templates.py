from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.core.auth import check_rate_limit, get_current_user
from src.core.config import settings
from src.database.config.database import get_db
from src.database.models.models import User
from src.services.audit_service import log_activity
from src.services.analysis_intelligence.domain_templates import (
    TemplatePayload,
    archive_template,
    create_template,
    edit_template,
    get_template,
    list_templates,
    publish_template,
    serialize_template,
)
from src.services.analysis_intelligence.extractor import extract_core_analysis
from src.services.analysis_intelligence.schemas import SegmentUnit, sha256_text, stable_id


router = APIRouter()


class TemplateTestRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=12000)


def _audit_template_change(
    db: Session,
    request: Request,
    current_user: User,
    *,
    action: str,
    template: Any,
) -> None:
    log_activity(
        db,
        "create" if action == "create" else "update",
        current_user.id,
        request=request,
        case_id=template.case_id,
        detail={
            "resource": "analysis_domain_template",
            "action": action,
            "template_id": template.id,
            "template_key": template.template_key,
            "version": template.version,
            "status": template.status,
            "scope": template.scope,
        },
    )


@router.get("")
def list_analysis_templates(
    scope: str | None = Query(default=None, pattern="^(global|user|case)$"),
    case_id: int | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    templates = list_templates(
        db,
        current_user,
        scope=scope,
        case_id=case_id,
        include_archived=include_archived,
    )
    return {"templates": [serialize_template(template) for template in templates]}


@router.post("")
def create_analysis_template(
    payload: TemplatePayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_rate_limit(f"rl:analysis-template:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    template = create_template(db, current_user, payload)
    _audit_template_change(db, request, current_user, action="create", template=template)
    db.commit()
    return serialize_template(template)


@router.post("/validate")
def validate_analysis_template(
    payload: TemplatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_rate_limit(f"rl:analysis-template:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    return {
        "valid": True,
        "slot_count": len(payload.domain_schema.slots),
        "example_count": len(payload.examples_json),
    }


@router.get("/{template_id}")
def get_analysis_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = get_template(db, current_user, template_id, action="read")
    return serialize_template(template)


@router.patch("/{template_id}")
def edit_analysis_template(
    template_id: int,
    payload: TemplatePayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_rate_limit(f"rl:analysis-template:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    template = edit_template(db, current_user, template_id, payload)
    _audit_template_change(db, request, current_user, action="edit", template=template)
    db.commit()
    return serialize_template(template)


@router.post("/{template_id}/publish")
def publish_analysis_template(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_rate_limit(f"rl:analysis-template:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    template = publish_template(db, current_user, template_id)
    _audit_template_change(db, request, current_user, action="publish", template=template)
    db.commit()
    return serialize_template(template)


@router.post("/{template_id}/archive")
def archive_analysis_template(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_rate_limit(f"rl:analysis-template:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    template = archive_template(db, current_user, template_id)
    _audit_template_change(db, request, current_user, action="archive", template=template)
    db.commit()
    return serialize_template(template)


@router.post("/{template_id}/test")
def test_analysis_template(
    template_id: int,
    payload: TemplateTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    check_rate_limit(f"rl:analysis-template:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    template = get_template(db, current_user, template_id, action="read")
    text = payload.transcript.strip()
    segment = SegmentUnit(
        id=stable_id("seg", "template_test", template.id, text[:120]),
        source_kind="transcript_text",
        text=text,
        source_text_sha256=sha256_text(text),
    )
    core = extract_core_analysis([segment])
    return {
        "template_id": template.id,
        "template_key": template.template_key,
        "version": template.version,
        "mode": "deterministic_core_preview",
        "facts": [item.model_dump(mode="json") for item in core.facts],
        "entities": [item.model_dump(mode="json") for item in core.entities],
        "risk_flags": [item.model_dump(mode="json") for item in core.risk_flags],
        "note": "LLM slot extraction is not executed in template test unless analysis LLM is enabled in a later flow.",
    }
