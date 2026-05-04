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
AnalysisMode = Literal["general", "selected"]
RiskSeverity = Literal["low", "medium", "high", "critical"]
SlotType = Literal[
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
    label_vi: str | None = None
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


class FactItem(EvidenceItem):
    value: Any = None
    normalized_value: Any = None

    @model_validator(mode="after")
    def default_vietnamese_label(self) -> "FactItem":
        if not self.label_vi:
            self.label_vi = self.label
        return self


class RiskFlag(EvidenceItem):
    value: Any = None
    normalized_value: Any = None
    severity: RiskSeverity = "medium"
    category: str
    reason_vi: str

    @model_validator(mode="after")
    def default_risk_label(self) -> "RiskFlag":
        if not self.label_vi:
            self.label_vi = self.label
        self.requires_review = True
        if self.review_status == "machine_suggested":
            self.review_status = "needs_review"
        return self


class SlotItem(EvidenceItem):
    template_slot_name: str
    slot_type: SlotType
    value: Any = None
    normalized_value: Any = None
    required: bool = False
    source_fact_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_slot_label(self) -> "SlotItem":
        if not self.label_vi:
            self.label_vi = self.label
        return self


class DomainFrame(BaseModel):
    id: str
    domain: str
    label_vi: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    source_method: str = "deterministic"
    domain_template_id: int | None = None
    domain_template_key: str | None = None
    domain_template_version: int | None = None
    schema_hash: str | None = None
    slot_ids: list[str] = Field(default_factory=list)
    source_fact_ids: list[str] = Field(default_factory=list)
    requires_review: bool = False
    review_status: ReviewStatus = "machine_suggested"


class DisplaySection(BaseModel):
    id: str
    title_vi: str
    kind: str
    item_ids: list[str] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)


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


def _active_items(items: list[Any]) -> list[Any]:
    return [item for item in items if getattr(item, "review_status", None) != "rejected"]


def build_display_sections_vi(
    facts: list[FactItem],
    risk_flags: list[RiskFlag],
    slots: list[SlotItem],
    domain_frames: list[DomainFrame],
) -> list[DisplaySection]:
    active_facts = _active_items(facts)
    active_risks = _active_items(risk_flags)
    active_slots = _active_items(slots)
    fact_by_id = {item.id: item for item in active_facts}
    slot_by_id = {item.id: item for item in active_slots}

    sections: list[DisplaySection] = []
    if active_facts:
        contact_types = {"phone", "email_candidate", "id_number_candidate", "email"}
        booking_types = {
            "person_name",
            "organization",
            "date",
            "date_range",
            "money",
            "money_range",
            "quantity",
            "purpose",
            "payment_method",
        }
        action_types = {"request", "offer", "decision", "obligation", "action", "policy"}

        def fact_payload(item: FactItem) -> dict[str, Any]:
            return {
                "id": item.id,
                "type": item.type,
                "label_vi": item.label_vi or item.label,
                "value": item.value,
                "normalized_value": item.normalized_value,
                "confidence": item.confidence,
                "requires_review": item.requires_review,
                "review_status": item.review_status,
                "evidence_count": len(item.evidence_refs),
            }

        for section_id, title, allowed in [
            ("core_contact_vi", "Thông tin liên hệ và định danh", contact_types),
            ("core_business_vi", "Thông tin nghiệp vụ chính", booking_types),
            ("core_actions_vi", "Yêu cầu, cam kết và hành động", action_types),
        ]:
            section_facts = [item for item in active_facts if item.type in allowed]
            if section_facts:
                sections.append(
                    DisplaySection(
                        id=section_id,
                        title_vi=title,
                        kind="facts",
                        item_ids=[item.id for item in section_facts],
                        items=[fact_payload(item) for item in section_facts],
                    )
                )

        other_facts = [
            item
            for item in active_facts
            if item.type not in contact_types | booking_types | action_types
        ]
        if other_facts:
            sections.append(
                DisplaySection(
                    id="core_other_vi",
                    title_vi="Thông tin khác",
                    kind="facts",
                    item_ids=[item.id for item in other_facts],
                    items=[fact_payload(item) for item in other_facts],
                )
            )

    for frame in _active_items(domain_frames):
        frame_slots = [slot_by_id[slot_id] for slot_id in frame.slot_ids if slot_id in slot_by_id]
        frame_facts = [fact_by_id[fact_id] for fact_id in frame.source_fact_ids if fact_id in fact_by_id]
        items = [
            {
                "id": slot.id,
                "type": "slot",
                "slot_type": slot.slot_type,
                "template_slot_name": slot.template_slot_name,
                "label_vi": slot.label_vi or slot.label,
                "value": slot.value,
                "normalized_value": slot.normalized_value,
                "confidence": slot.confidence,
                "requires_review": slot.requires_review,
                "review_status": slot.review_status,
                "evidence_count": len(slot.evidence_refs),
            }
            for slot in frame_slots
        ] + [
            {
                "id": fact.id,
                "type": fact.type,
                "label_vi": fact.label_vi or fact.label,
                "value": fact.value,
                "normalized_value": fact.normalized_value,
                "confidence": fact.confidence,
                "requires_review": fact.requires_review,
                "review_status": fact.review_status,
                "evidence_count": len(fact.evidence_refs),
            }
            for fact in frame_facts
        ]
        if items:
            sections.append(
                DisplaySection(
                    id=f"display_{frame.id}",
                    title_vi=frame.label_vi,
                    kind="domain_frame",
                    item_ids=[item["id"] for item in items],
                    items=items,
                )
            )

    if active_risks:
        sections.append(
            DisplaySection(
                id="risk_flags_vi",
                title_vi="Điểm cần kiểm tra",
                kind="risk_flags",
                item_ids=[item.id for item in active_risks],
                items=[
                    {
                        "id": item.id,
                        "type": item.type,
                        "label_vi": item.label_vi or item.label,
                        "severity": item.severity,
                        "category": item.category,
                        "reason_vi": item.reason_vi,
                        "value": item.value,
                        "confidence": item.confidence,
                        "review_status": item.review_status,
                        "evidence_count": len(item.evidence_refs),
                    }
                    for item in active_risks
                ],
            )
        )
    return sections


class AnalysisGraphV2(BaseModel):
    schema_version: str = SCHEMA_VERSION
    graph_revision: int = 1
    task_id: str | None = None
    audio_id: int | None = None
    source_file: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    analysis_mode: AnalysisMode = "general"
    extractor_versions: dict[str, str] = Field(default_factory=dict)
    selected_template_ids: list[int] = Field(default_factory=list)
    template_version_refs: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    model_info: dict[str, Any] = Field(default_factory=dict)
    segments: list[SegmentUnit] = Field(default_factory=list)
    entities: list[EntityItem] = Field(default_factory=list)
    relations: list[RelationItem] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)
    claims: list[ClaimItem] = Field(default_factory=list)
    facts: list[FactItem] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    slots: list[SlotItem] = Field(default_factory=list)
    domain_frames: list[DomainFrame] = Field(default_factory=list)
    display_sections_vi: list[DisplaySection] = Field(default_factory=list)
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

        fact_ids = {item.id for item in self.facts}
        slot_ids = {item.id for item in self.slots}

        for slot in self.slots:
            for fact_id in slot.source_fact_ids:
                if fact_id not in fact_ids:
                    raise ValueError("Slot references missing fact")
        for frame in self.domain_frames:
            for slot_id in frame.slot_ids:
                if slot_id not in slot_ids:
                    raise ValueError("Domain frame references missing slot")
            for fact_id in frame.source_fact_ids:
                if fact_id not in fact_ids:
                    raise ValueError("Domain frame references missing fact")

        for item in [
            *self.entities,
            *self.relations,
            *self.events,
            *self.claims,
            *self.facts,
            *self.risk_flags,
            *self.slots,
        ]:
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
        self.display_sections_vi = build_display_sections_vi(
            self.facts,
            self.risk_flags,
            self.slots,
            self.domain_frames,
        )

        rejected_ids = {
            item.id
            for item in [
                *self.entities,
                *self.relations,
                *self.events,
                *self.claims,
                *self.facts,
                *self.risk_flags,
                *self.slots,
            ]
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
