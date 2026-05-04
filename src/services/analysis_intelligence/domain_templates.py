from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.core.auth import assert_case_access, has_role_permission
from src.database.models.models import AnalysisDomainTemplate, User


TemplateScope = Literal["global", "user", "case"]
TemplateStatus = Literal["draft", "published", "archived"]
TemplateSlotType = Literal[
    "text",
    "person",
    "organization",
    "location",
    "phone",
    "email",
    "id_number",
    "date_time",
    "money",
    "quantity",
    "enum",
    "boolean",
]

MAX_SLOTS = 80
MAX_EXAMPLES = 12
MAX_SYNONYMS_PER_SLOT = 30
MAX_DESCRIPTION_CHARS = 3000
MAX_HINT_CHARS = 2000
MAX_EXAMPLE_TRANSCRIPT_CHARS = 12000


class SlotDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    label_vi: str = Field(min_length=1, max_length=160)
    type: TemplateSlotType
    required: bool = False
    synonyms: list[str] = Field(default_factory=list)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_CHARS)
    enum_values: list[str] = Field(default_factory=list)
    extraction_hints: str = Field(default="", max_length=MAX_HINT_CHARS)

    @field_validator("synonyms")
    @classmethod
    def validate_synonyms(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_SYNONYMS_PER_SLOT:
            raise ValueError(f"synonyms must have at most {MAX_SYNONYMS_PER_SLOT} items")
        return [item.strip() for item in value if item and item.strip()]

    @field_validator("enum_values")
    @classmethod
    def validate_enum_values(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]

    @model_validator(mode="after")
    def validate_enum_slot(self) -> "SlotDefinition":
        if self.type == "enum" and not self.enum_values:
            raise ValueError("enum slots require enum_values")
        return self


class TemplateExample(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    transcript: str = Field(min_length=1, max_length=MAX_EXAMPLE_TRANSCRIPT_CHARS)
    expected_slots: dict[str, Any] = Field(default_factory=dict)
    negative: bool = False


class TemplateSchema(BaseModel):
    domain_key: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    label_vi: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_CHARS)
    language: str = Field(default="vi", max_length=10)
    slots: list[SlotDefinition] = Field(min_length=1, max_length=MAX_SLOTS)
    extraction_hints: str = Field(default="", max_length=MAX_HINT_CHARS)

    @model_validator(mode="after")
    def validate_unique_slots(self) -> "TemplateSchema":
        names = [slot.name for slot in self.slots]
        if len(names) != len(set(names)):
            raise ValueError("slot names must be unique")
        return self


class TemplatePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    template_key: str | None = Field(default=None, max_length=120, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_CHARS)
    language: str = Field(default="vi", max_length=10)
    scope: TemplateScope = "user"
    case_id: int | None = None
    domain_schema: TemplateSchema = Field(alias="schema_json")
    examples_json: list[TemplateExample] = Field(default_factory=list, max_length=MAX_EXAMPLES)

    @model_validator(mode="after")
    def validate_scope(self) -> "TemplatePayload":
        if self.scope == "case" and self.case_id is None:
            raise ValueError("case_id is required for case-scoped templates")
        if self.scope != "case" and self.case_id is not None:
            raise ValueError("case_id is only allowed for case-scoped templates")
        return self


def template_schema_hash(schema_json: dict[str, Any], examples_json: list[dict[str, Any]] | None = None) -> str:
    payload = {
        "schema_json": schema_json,
        "examples_json": examples_json or [],
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _slugify_template_key(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip().lower()).strip("_")
    if not safe:
        safe = "analysis_template"
    if not re.match(r"^[a-zA-Z]", safe):
        safe = f"template_{safe}"
    return safe[:120]


def serialize_template(template: AnalysisDomainTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "template_key": template.template_key,
        "version": template.version,
        "schema_hash": template.schema_hash,
        "parent_template_id": template.parent_template_id,
        "name": template.name,
        "description": template.description,
        "language": template.language,
        "status": template.status,
        "scope": template.scope,
        "owner_user_id": template.owner_user_id,
        "case_id": template.case_id,
        "schema_json": template.schema_json,
        "examples_json": template.examples_json,
        "published_at": template.published_at.isoformat() if template.published_at else None,
        "archived_at": template.archived_at.isoformat() if template.archived_at else None,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
    }


def _assert_global_template_permission(user: User) -> None:
    if not has_role_permission(user, "analysis_template:manage_global"):
        raise HTTPException(status_code=403, detail="Missing analysis_template:manage_global permission")


def assert_template_access(db: Session, user: User, template: AnalysisDomainTemplate, action: str) -> None:
    if template.scope == "global":
        if action != "read":
            _assert_global_template_permission(user)
        return
    if template.scope == "user":
        if template.owner_user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
        return
    if template.scope == "case":
        if template.case_id is None:
            raise HTTPException(status_code=400, detail="Case-scoped template missing case_id")
        assert_case_access(db, user, template.case_id, "read" if action == "read" else "write")
        return
    raise HTTPException(status_code=400, detail="Unsupported template scope")


def list_templates(
    db: Session,
    user: User,
    *,
    scope: str | None = None,
    case_id: int | None = None,
    include_archived: bool = False,
) -> list[AnalysisDomainTemplate]:
    query = db.query(AnalysisDomainTemplate)
    if not include_archived:
        query = query.filter(AnalysisDomainTemplate.status != "archived")
    if scope:
        query = query.filter(AnalysisDomainTemplate.scope == scope)
    if case_id is not None:
        assert_case_access(db, user, case_id, "read")
        query = query.filter(
            or_(
                AnalysisDomainTemplate.scope == "global",
                AnalysisDomainTemplate.owner_user_id == user.id,
                AnalysisDomainTemplate.case_id == case_id,
            )
        )
    else:
        query = query.filter(
            or_(
                AnalysisDomainTemplate.scope == "global",
                AnalysisDomainTemplate.owner_user_id == user.id,
            )
        )
    return query.order_by(AnalysisDomainTemplate.template_key, AnalysisDomainTemplate.version.desc()).all()


def get_template(db: Session, user: User, template_id: int, action: str = "read") -> AnalysisDomainTemplate:
    template = db.query(AnalysisDomainTemplate).filter(AnalysisDomainTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Analysis template not found")
    assert_template_access(db, user, template, action)
    return template


def create_template(db: Session, user: User, payload: TemplatePayload) -> AnalysisDomainTemplate:
    if payload.scope == "global":
        _assert_global_template_permission(user)
    if payload.scope == "case":
        assert_case_access(db, user, int(payload.case_id), "write")

    schema_dict = payload.domain_schema.model_dump(mode="json")
    examples = [example.model_dump(mode="json") for example in payload.examples_json]
    template_key = payload.template_key or _slugify_template_key(payload.domain_schema.domain_key)
    latest = (
        db.query(AnalysisDomainTemplate)
        .filter(AnalysisDomainTemplate.template_key == template_key)
        .order_by(AnalysisDomainTemplate.version.desc())
        .first()
    )
    if latest:
        raise HTTPException(status_code=409, detail="template_key already exists; edit the existing template")
    template = AnalysisDomainTemplate(
        template_key=template_key,
        version=1,
        schema_hash=template_schema_hash(schema_dict, examples),
        name=payload.name,
        description=payload.description,
        language=payload.language,
        status="draft",
        scope=payload.scope,
        owner_user_id=user.id if payload.scope != "global" else None,
        case_id=payload.case_id,
        schema_json=schema_dict,
        examples_json=examples,
    )
    db.add(template)
    db.flush()
    return template


def edit_template(db: Session, user: User, template_id: int, payload: TemplatePayload) -> AnalysisDomainTemplate:
    template = get_template(db, user, template_id, action="write")
    if payload.scope == "global":
        _assert_global_template_permission(user)
    if payload.scope == "case":
        assert_case_access(db, user, int(payload.case_id), "write")
    schema_dict = payload.domain_schema.model_dump(mode="json")
    examples = [example.model_dump(mode="json") for example in payload.examples_json]
    if template.status == "published":
        latest_version = (
            db.query(AnalysisDomainTemplate.version)
            .filter(AnalysisDomainTemplate.template_key == template.template_key)
            .order_by(AnalysisDomainTemplate.version.desc())
            .first()
        )
        next_version = int(latest_version[0]) + 1 if latest_version else template.version + 1
        draft = AnalysisDomainTemplate(
            template_key=template.template_key,
            version=next_version,
            schema_hash=template_schema_hash(schema_dict, examples),
            parent_template_id=template.id,
            name=payload.name,
            description=payload.description,
            language=payload.language,
            status="draft",
            scope=template.scope,
            owner_user_id=template.owner_user_id,
            case_id=template.case_id,
            schema_json=schema_dict,
            examples_json=examples,
        )
        db.add(draft)
        db.flush()
        return draft

    template.name = payload.name
    template.description = payload.description
    template.language = payload.language
    template.scope = payload.scope
    template.case_id = payload.case_id
    template.owner_user_id = user.id if payload.scope != "global" else None
    template.schema_json = schema_dict
    template.examples_json = examples
    template.schema_hash = template_schema_hash(schema_dict, examples)
    return template


def publish_template(db: Session, user: User, template_id: int) -> AnalysisDomainTemplate:
    template = get_template(db, user, template_id, action="write")
    if template.status == "archived":
        raise HTTPException(status_code=400, detail="Archived templates cannot be published")
    if template.status != "published":
        template.status = "published"
        template.published_at = datetime.now(timezone.utc)
    return template


def archive_template(db: Session, user: User, template_id: int) -> AnalysisDomainTemplate:
    template = get_template(db, user, template_id, action="write")
    template.status = "archived"
    template.archived_at = datetime.now(timezone.utc)
    return template


def resolve_published_template_refs(db: Session, user: User, template_ids: list[int]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for template_id in template_ids:
        template = get_template(db, user, template_id, action="read")
        if template.status != "published":
            raise HTTPException(status_code=400, detail=f"Template {template_id} is not published")
        refs.append(
            {
                "id": template.id,
                "template_key": template.template_key,
                "version": template.version,
                "schema_hash": template.schema_hash,
                "name": template.name,
                "language": template.language,
            }
        )
    return refs
