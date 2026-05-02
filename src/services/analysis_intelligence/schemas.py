from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


SCHEMA_VERSION = "analysis_intelligence.v2"

SourceKind = Literal[
    "audio_segment",
    "transcript_segment",
    "transcript_text",
    "summary_text",
    "report_text",
]
ReviewStatus = Literal["machine_suggested", "needs_review", "confirmed", "rejected"]
RelationType = Literal[
    "called",
    "owns_phone",
    "met_at",
    "located_at",
    "transferred_money",
    "planned_event",
    "mentions_object",
    "requested",
    "delivered",
    "threatened",
    "unknown",
]

SEGMENT_SOURCE_KINDS = {"audio_segment", "transcript_segment"}
TEXT_ONLY_SOURCE_KINDS = {"transcript_text", "summary_text", "report_text"}
HIGH_RISK_RELATIONS = {"owns_phone", "transferred_money", "threatened", "delivered", "requested"}
TIME_GROUNDED_RELATIONS = {"called", "met_at", "located_at", "planned_event"}
RESTRICTED_RELATIONS = HIGH_RISK_RELATIONS | TIME_GROUNDED_RELATIONS


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: Any) -> str:
    normalized = "|".join(str(p or "").strip().lower() for p in parts)
    return f"{prefix}_{sha256_text(normalized)[:16]}"


class EvidenceRef(BaseModel):
    source_kind: SourceKind
    source_text_sha256: str
    text_span: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    audio_id: int | None = None
    segment_id: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    speaker_id: str | None = None

    @model_validator(mode="after")
    def validate_source_requirements(self) -> "EvidenceRef":
        if not self.source_text_sha256:
            raise ValueError("source_text_sha256 is required")
        if not self.text_span:
            raise ValueError("text_span is required")
        if self.char_end <= self.char_start:
            raise ValueError("char_end must be greater than char_start")
        if self.source_kind in SEGMENT_SOURCE_KINDS:
            if self.audio_id is None:
                raise ValueError("audio_id is required for segment evidence")
            if not self.segment_id:
                raise ValueError("segment_id is required for segment evidence")
            if self.start_time is None or self.end_time is None:
                raise ValueError("start_time/end_time are required for segment evidence")
            if self.end_time <= self.start_time:
                raise ValueError("end_time must be greater than start_time")
        return self

    @property
    def has_time_grounding(self) -> bool:
        return (
            self.source_kind in SEGMENT_SOURCE_KINDS
            and self.start_time is not None
            and self.end_time is not None
            and self.end_time > self.start_time
        )

    @property
    def has_speaker_grounding(self) -> bool:
        return bool(self.speaker_id)


class SegmentUnit(BaseModel):
    id: str
    source_kind: SourceKind = "transcript_text"
    text: str
    source_text_sha256: str
    audio_id: int | None = None
    start_time: float | None = None
    end_time: float | None = None
    speaker_id: str | None = None
    words: list[dict[str, Any]] = Field(default_factory=list)


class ReviewFields(BaseModel):
    review_status: ReviewStatus = "machine_suggested"
    requires_review: bool = False
    reviewed_by: int | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
    original_label: str | None = None
    original_type: str | None = None
    source_item_ids: list[str] = Field(default_factory=list)


class EvidenceItem(ReviewFields):
    id: str
    type: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_reason: str
    source_method: str
    evidence_refs: list[EvidenceRef]

    @model_validator(mode="after")
    def validate_evidence(self) -> "EvidenceItem":
        if not self.evidence_refs:
            raise ValueError("evidence_refs must not be empty")
        if any(ref.source_kind in TEXT_ONLY_SOURCE_KINDS for ref in self.evidence_refs):
            self.requires_review = True
            if self.review_status == "machine_suggested":
                self.review_status = "needs_review"
        if any(ref.source_kind in SEGMENT_SOURCE_KINDS and not ref.speaker_id for ref in self.evidence_refs):
            self.requires_review = True
        return self


class EntityItem(EvidenceItem):
    value: str | None = None
    aliases: list[str] = Field(default_factory=list)


class RelationItem(EvidenceItem):
    type: RelationType
    source_entity_id: str
    target_entity_id: str

    @model_validator(mode="after")
    def validate_relation_grounding(self) -> "RelationItem":
        if self.type in RESTRICTED_RELATIONS:
            if not any(ref.has_time_grounding and ref.has_speaker_grounding for ref in self.evidence_refs):
                raise ValueError(f"{self.type} requires timestamp and speaker grounding")
        return self


class EventItem(EvidenceItem):
    start_time: float | None = None
    end_time: float | None = None
    entity_ids: list[str] = Field(default_factory=list)


class ClaimItem(EvidenceItem):
    entity_ids: list[str] = Field(default_factory=list)


class LegacyView(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    main_events: list[str] = Field(default_factory=list)
    entity_types: list[str] = Field(default_factory=list)


def to_legacy_view(
    entities: list[EntityItem],
    relations: list[RelationItem],
    events: list[EventItem],
    claims: list[ClaimItem],
) -> LegacyView:
    active_entities = [item for item in entities if item.review_status != "rejected"]
    active_entity_ids = {item.id for item in active_entities}
    active_relations = [
        item
        for item in relations
        if item.review_status != "rejected"
        and item.source_entity_id in active_entity_ids
        and item.target_entity_id in active_entity_ids
    ]
    active_events = [item for item in events if item.review_status != "rejected"]
    active_claims = [item for item in claims if item.review_status != "rejected"]

    nodes = [
        {
            "id": item.id,
            "label": item.label,
            "type": item.type,
            "confidence": item.confidence,
            "review_status": item.review_status,
            "requires_review": item.requires_review,
        }
        for item in active_entities
    ]
    edges = [
        {
            "id": item.id,
            "from": item.source_entity_id,
            "to": item.target_entity_id,
            "label": item.label,
            "type": item.type,
            "confidence": item.confidence,
            "review_status": item.review_status,
            "requires_review": item.requires_review,
        }
        for item in active_relations
    ]
    timeline = [
        {
            "id": item.id,
            "time": item.start_time if item.start_time is not None else "không xác định",
            "event": item.label,
            "entities_involved": item.entity_ids,
            "confidence": item.confidence,
            "review_status": item.review_status,
            "requires_review": item.requires_review,
        }
        for item in active_events
    ]
    main_events = [item.label for item in active_events] + [item.label for item in active_claims]
    entity_types = sorted({item.type for item in active_entities})
    return LegacyView(
        nodes=nodes,
        edges=edges,
        timeline=timeline,
        main_events=main_events,
        entity_types=entity_types,
    )


class AnalysisGraphV2(BaseModel):
    schema_version: str = SCHEMA_VERSION
    graph_revision: int = 1
    task_id: str | None = None
    audio_id: int | None = None
    source_file: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    model_info: dict[str, Any] = Field(default_factory=dict)
    segments: list[SegmentUnit] = Field(default_factory=list)
    entities: list[EntityItem] = Field(default_factory=list)
    relations: list[RelationItem] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)
    claims: list[ClaimItem] = Field(default_factory=list)
    legacy_view: LegacyView = Field(default_factory=LegacyView)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    main_events: list[str] = Field(default_factory=list)
    entity_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph_integrity(self) -> "AnalysisGraphV2":
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported schema_version")

        entity_ids = {item.id for item in self.entities}
        segment_ids = {segment.id for segment in self.segments}
        for relation in self.relations:
            if relation.source_entity_id not in entity_ids or relation.target_entity_id not in entity_ids:
                raise ValueError("Relation references missing entity")

        for item in [*self.entities, *self.relations, *self.events, *self.claims]:
            for ref in item.evidence_refs:
                if ref.segment_id and ref.segment_id not in segment_ids:
                    raise ValueError(f"Evidence references missing segment {ref.segment_id}")

        generated = to_legacy_view(self.entities, self.relations, self.events, self.claims)
        self.legacy_view = generated
        self.nodes = generated.nodes
        self.edges = generated.edges
        self.timeline = generated.timeline
        self.main_events = generated.main_events
        self.entity_types = generated.entity_types

        rejected_ids = {
            item.id
            for item in [*self.entities, *self.relations, *self.events, *self.claims]
            if item.review_status == "rejected"
        }
        legacy_ids = {
            *(node.get("id") for node in self.nodes),
            *(edge.get("id") for edge in self.edges),
            *(item.get("id") for item in self.timeline),
        }
        if rejected_ids.intersection(legacy_ids):
            raise ValueError("Rejected items must not appear in legacy aliases")
        return self

    def to_storage_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
