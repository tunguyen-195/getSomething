from __future__ import annotations

import hashlib
import json
import re
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
    trigger_text: str | None = None
    source_fact_ids: list[str] = Field(default_factory=list)
    semantic_time: dict[str, Any] | None = None
    risk_context: dict[str, Any] | None = None


class ClaimItem(EvidenceItem):
    entity_ids: list[str] = Field(default_factory=list)
    source_fact_ids: list[str] = Field(default_factory=list)


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


class InsightItem(ReviewFields):
    id: str
    type: str
    severity: RiskSeverity = "medium"
    title_vi: str
    description_vi: str
    supporting_item_ids: list[str] = Field(default_factory=list)
    source_fact_ids: list[str] = Field(default_factory=list)
    domain_frame_id: str | None = None
    template_slot_name: str | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    recommended_action_vi: str | None = None
    source_method: str = "deterministic_insight"

    @model_validator(mode="after")
    def validate_insight_grounding(self) -> "InsightItem":
        if self.requires_review and self.review_status == "machine_suggested":
            self.review_status = "needs_review"
        if self.type == "missing_required_slot":
            if not self.domain_frame_id or not self.template_slot_name:
                raise ValueError("missing_required_slot requires domain_frame_id and template_slot_name")
            self.requires_review = True
            if self.review_status == "machine_suggested":
                self.review_status = "needs_review"
            return self
        if not self.evidence_refs and not self.supporting_item_ids:
            raise ValueError("Insight requires evidence_refs or supporting_item_ids")
        return self


class DisplaySection(BaseModel):
    id: str
    title_vi: str
    kind: str
    item_ids: list[str] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)


class HallucinationSpan(BaseModel):
    id: str
    text: str
    filtered_text: str | None = None
    status: Literal["filtered", "flagged", "kept_for_review"] = "flagged"
    source: str
    reason_codes: list[str] = Field(default_factory=list)
    reason_vi: str
    confidence: float = Field(ge=0.0, le=1.0)
    start_time: float | None = None
    end_time: float | None = None
    segment_id: str | None = None
    word_index: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    llm_review: dict[str, Any] | None = None


class HallucinationAnalysis(BaseModel):
    enabled: bool = True
    source: str = "phoguard_boh_deloop"
    research_basis_vi: list[str] = Field(default_factory=list)
    raw_transcript: str | None = None
    filtered_transcript: str | None = None
    removed_count: int = 0
    flagged_count: int = 0
    review_required: bool = False
    spans: list[HallucinationSpan] = Field(default_factory=list)
    llm_status: str = "disabled"
    summary_vi: str | None = None


class LegacyView(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    main_events: list[str] = Field(default_factory=list)
    entity_types: list[str] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    extracted_entities: list[dict[str, Any]] = Field(default_factory=list)


class VisibilityState(BaseModel):
    visible_item_ids: list[str] = Field(default_factory=list)
    blocked_item_ids: list[str] = Field(default_factory=list)
    blocked_reasons: dict[str, list[str]] = Field(default_factory=dict)


KEY_ITEM_TYPES = {
    "phone",
    "email",
    "email_candidate",
    "id_number_candidate",
    "money",
    "money_range",
    "date",
    "date_range",
    "date_time",
    "time",
    "quantity",
    "payment_method",
    "purpose",
    "person",
    "person_name",
    "organization",
    "location",
    "address",
}


def _analysis_value_key(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip().lower()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).lower()


def _numeric_string(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        return int(value.strip())
    return None


def _canonical_date_key(value: Any) -> str:
    if isinstance(value, dict):
        day = value.get("day")
        month = value.get("month")
        year = value.get("year") or "yyyy"
        if day and month:
            return f"{year}-{int(month):02d}-{int(day):02d}"
    if isinstance(value, str):
        match = re.fullmatch(r"(?P<year>\d{4}|yyyy)-(?P<month>\d{2})-(?P<day>\d{2})", value.strip().lower())
        if match:
            return f"{match.group('year')}-{match.group('month')}-{match.group('day')}"
    return _analysis_value_key(value)


def _canonical_item_key(semantic_type: str, normalized_value: Any, raw_value: Any, label: Any) -> str:
    if semantic_type == "money":
        amount = normalized_value.get("amount_vnd") if isinstance(normalized_value, dict) else _numeric_string(normalized_value)
        amount = amount if amount is not None else _numeric_string(raw_value)
        if amount is not None:
            return f"money:{amount}"
    if semantic_type == "money_range" and isinstance(normalized_value, dict):
        start = normalized_value.get("from") or {}
        end = normalized_value.get("to") or {}
        return f"money_range:{start.get('amount_vnd')}:{end.get('amount_vnd')}"
    if semantic_type == "date":
        key = _canonical_date_key(normalized_value) or _canonical_date_key(raw_value)
        if key:
            return f"date:{key}"
    if semantic_type == "date_range" and isinstance(normalized_value, dict):
        start = _canonical_date_key(normalized_value.get("start"))
        end = _canonical_date_key(normalized_value.get("end"))
        if start or end:
            return f"date_range:{start}:{end}"
    if semantic_type == "date_time":
        if isinstance(normalized_value, dict) and ("start" in normalized_value or "end" in normalized_value):
            start = _canonical_date_key(normalized_value.get("start"))
            end = _canonical_date_key(normalized_value.get("end"))
            if start or end:
                return f"date_time_range:{start}:{end}"
        key = _canonical_date_key(normalized_value) or _canonical_date_key(raw_value)
        if key:
            return f"date_time:{key}"
    if semantic_type == "quantity" and isinstance(normalized_value, dict):
        return f"quantity:{normalized_value.get('unit')}:{normalized_value.get('quantity')}"
    return _analysis_value_key(normalized_value) or _analysis_value_key(raw_value) or _analysis_value_key(label)


def _semantic_suppression_key(semantic_type: str, normalized_value: Any, raw_value: Any, label: Any) -> str:
    key = _canonical_item_key(semantic_type, normalized_value, raw_value, label)
    if not key:
        return ""
    family = {
        "email_candidate": "email",
        "person_name": "person",
    }.get(semantic_type, semantic_type)
    if semantic_type in {"date", "date_time"}:
        family = "date"
        key = key.split(":", 1)[1] if ":" in key else key
    elif semantic_type in {"date_range"}:
        family = "date_range"
        key = key.split(":", 1)[1] if ":" in key else key
    elif semantic_type in {"money", "money_range", "phone", "email", "email_candidate", "person", "person_name", "organization", "location", "address", "quantity"}:
        key = key.split(":", 1)[1] if ":" in key else key
    return f"{family}:{key}"


def _date_label(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    day = value.get("day")
    month = value.get("month")
    year = value.get("year")
    if not day or not month:
        return None
    suffix = f"/{year}" if year else ""
    return f"{day}/{month}{suffix}"


def _semantic_time_label(value: dict[str, Any] | None) -> str | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    if kind == "compound":
        labels = [
            label
            for item in value.get("items", [])
            if isinstance(item, dict)
            for label in [_semantic_time_label(item)]
            if label
        ]
        if labels:
            return ", ".join(dict.fromkeys(labels))
    if kind == "date_range":
        start = _date_label(value.get("start"))
        end = _date_label(value.get("end"))
        if start and end:
            return f"{start} - {end}"
    if kind == "date":
        return _date_label(value.get("value"))
    if kind == "time" and value.get("value"):
        return str(value.get("value"))
    return None


def _display_value(value: Any) -> Any:
    return value


def _canonical_key_items(
    entities: list[EntityItem],
    facts: list[FactItem],
    slots: list[SlotItem],
    visibility: VisibilityState | None = None,
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, str, str, dict[str, Any]]] = []
    visible_ids = set(visibility.visible_item_ids) if visibility else None

    def add_candidate(priority: int, semantic_type: str, item: Any, *, item_kind: str) -> None:
        if getattr(item, "review_status", None) == "rejected":
            return
        if visible_ids is not None and item.id not in visible_ids:
            return
        normalized_value = getattr(item, "normalized_value", None)
        raw_value = getattr(item, "value", None)
        label = getattr(item, "label_vi", None) or getattr(item, "label", None)
        key_value = _canonical_item_key(semantic_type, normalized_value, raw_value, label)
        if not key_value:
            return
        if semantic_type not in KEY_ITEM_TYPES:
            return
        candidates.append(
            (
                priority,
                semantic_type,
                key_value,
                {
                    "id": item.id,
                    "type": semantic_type,
                    "source_item_type": item_kind,
                    "label": label or semantic_type,
                    "label_vi": getattr(item, "label_vi", None) or label or semantic_type,
                    "value": _display_value(raw_value if raw_value is not None else normalized_value),
                    "normalized_value": normalized_value if normalized_value is not None else raw_value,
                    "canonical_value": key_value,
                    "confidence": getattr(item, "confidence", None),
                    "review_status": getattr(item, "review_status", None),
                    "requires_review": getattr(item, "requires_review", False),
                    "context": getattr(item, "source_method", None) or getattr(item, "confidence_reason", None),
                },
            )
        )

    for slot in slots:
        add_candidate(0, slot.slot_type, slot, item_kind="slot")
    for fact in facts:
        add_candidate(1, fact.type, fact, item_kind="fact")
    for entity in entities:
        add_candidate(2, entity.type, entity, item_kind="entity")

    selected: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
    for priority, semantic_type, key_value, payload in candidates:
        key = (semantic_type, key_value)
        existing = selected.get(key)
        if existing is None or priority < existing[0]:
            selected[key] = (priority, payload)
    return [payload for _, payload in sorted(selected.values(), key=lambda item: (item[0], item[1]["type"], item[1]["id"]))]


def _add_blocked_reason(blocked_reasons: dict[str, list[str]], item_id: str, reason: str) -> None:
    reasons = blocked_reasons.setdefault(item_id, [])
    if reason not in reasons:
        reasons.append(reason)


def _compute_visibility(
    *,
    entities: list[EntityItem],
    relations: list[RelationItem],
    events: list[EventItem],
    claims: list[ClaimItem],
    facts: list[FactItem],
    risk_flags: list[RiskFlag],
    slots: list[SlotItem],
    domain_frames: list[DomainFrame],
    insight_items: list[InsightItem],
) -> VisibilityState:
    visible: set[str] = set()
    blocked_reasons: dict[str, list[str]] = {}

    def is_visible(item_id: str | None) -> bool:
        return bool(item_id and item_id in visible)

    def add_reason(item_id: str, reason: str) -> bool:
        before = set(blocked_reasons.get(item_id, []))
        _add_blocked_reason(blocked_reasons, item_id, reason)
        return set(blocked_reasons.get(item_id, [])) != before

    def block_item(item_id: str, reason: str) -> bool:
        changed = False
        if item_id in visible:
            visible.remove(item_id)
            changed = True
        return add_reason(item_id, reason) or changed

    def mark_own_status(items: list[Any]) -> None:
        for item in items:
            if item.review_status == "rejected":
                add_reason(item.id, "own_rejected")
            else:
                visible.add(item.id)

    mark_own_status(entities)
    mark_own_status(facts)
    mark_own_status(risk_flags)

    for relation in relations:
        if relation.review_status == "rejected":
            add_reason(relation.id, "own_rejected")
            continue
        if not is_visible(relation.source_entity_id):
            add_reason(relation.id, f"relation_endpoint_blocked:{relation.source_entity_id}")
        if not is_visible(relation.target_entity_id):
            add_reason(relation.id, f"relation_endpoint_blocked:{relation.target_entity_id}")
        if relation.id not in blocked_reasons:
            visible.add(relation.id)

    for slot in slots:
        if slot.review_status == "rejected":
            add_reason(slot.id, "own_rejected")
            continue
        for fact_id in slot.source_fact_ids:
            if not is_visible(fact_id):
                add_reason(slot.id, f"source_fact_blocked:{fact_id}")
        if slot.id not in blocked_reasons:
            visible.add(slot.id)

    for event in events:
        if event.review_status == "rejected":
            add_reason(event.id, "own_rejected")
            continue
        for fact_id in event.source_fact_ids:
            if not is_visible(fact_id):
                add_reason(event.id, f"source_fact_blocked:{fact_id}")
        for entity_id in event.entity_ids:
            if not is_visible(entity_id):
                add_reason(event.id, f"entity_blocked:{entity_id}")
        if event.id not in blocked_reasons:
            visible.add(event.id)

    for claim in claims:
        if claim.review_status == "rejected":
            add_reason(claim.id, "own_rejected")
            continue
        for entity_id in claim.entity_ids:
            if not is_visible(entity_id):
                add_reason(claim.id, f"entity_blocked:{entity_id}")
        for fact_id in claim.source_fact_ids:
            if not is_visible(fact_id):
                add_reason(claim.id, f"source_fact_blocked:{fact_id}")
        if claim.id not in blocked_reasons:
            visible.add(claim.id)

    frame_own_visible = {frame.id for frame in domain_frames if frame.review_status != "rejected"}
    preliminary_missing_insights: set[str] = set()
    for insight in insight_items:
        if insight.type != "missing_required_slot":
            continue
        if insight.review_status == "rejected":
            add_reason(insight.id, "own_rejected")
            continue
        if not insight.domain_frame_id or insight.domain_frame_id not in frame_own_visible:
            add_reason(insight.id, f"domain_frame_blocked:{insight.domain_frame_id}")
            continue
        preliminary_missing_insights.add(insight.id)

    for frame in domain_frames:
        if frame.review_status == "rejected":
            add_reason(frame.id, "own_rejected")
            continue
        visible_slot = any(is_visible(slot_id) for slot_id in frame.slot_ids)
        visible_fact = any(is_visible(fact_id) for fact_id in frame.source_fact_ids)
        visible_missing = any(
            insight.id in preliminary_missing_insights and insight.domain_frame_id == frame.id
            for insight in insight_items
        )
        if visible_slot or visible_fact or visible_missing:
            visible.add(frame.id)
            continue
        for slot_id in frame.slot_ids:
            if not is_visible(slot_id):
                add_reason(frame.id, f"slot_blocked:{slot_id}")
        for fact_id in frame.source_fact_ids:
            if not is_visible(fact_id):
                add_reason(frame.id, f"source_fact_blocked:{fact_id}")
        if frame.id not in blocked_reasons:
            add_reason(frame.id, "domain_frame_blocked:no_visible_source")

    for insight in insight_items:
        if insight.id in preliminary_missing_insights:
            visible.add(insight.id)
            continue
        if insight.review_status == "rejected":
            add_reason(insight.id, "own_rejected")
            continue
        for fact_id in insight.source_fact_ids:
            if not is_visible(fact_id):
                add_reason(insight.id, f"source_fact_blocked:{fact_id}")
        for item_id in insight.supporting_item_ids:
            if not is_visible(item_id):
                add_reason(insight.id, f"supporting_item_blocked:{item_id}")
        if insight.domain_frame_id and not is_visible(insight.domain_frame_id):
            add_reason(insight.id, f"domain_frame_blocked:{insight.domain_frame_id}")
        if insight.id not in blocked_reasons:
            visible.add(insight.id)

    semantic_items: list[tuple[str, Any]] = []
    for item in entities:
        key = _semantic_suppression_key(item.type, None, item.value, item.label)
        if key:
            semantic_items.append((key, item))
    for item in facts:
        key = _semantic_suppression_key(item.type, item.normalized_value, item.value, item.label_vi or item.label)
        if key:
            semantic_items.append((key, item))
    for item in slots:
        key = _semantic_suppression_key(item.slot_type, item.normalized_value, item.value, item.label_vi or item.label)
        if key:
            semantic_items.append((key, item))

    def apply_semantic_suppression() -> bool:
        changed = False
        blocked_by_key: dict[str, list[str]] = {}
        for key, item in semantic_items:
            if item.id not in visible:
                blocked_by_key.setdefault(key, []).append(item.id)
        for key, item in semantic_items:
            if item.id not in visible or item.review_status == "confirmed":
                continue
            source_ids = [source_id for source_id in blocked_by_key.get(key, []) if source_id != item.id]
            if not source_ids:
                continue
            for source_id in source_ids:
                changed = block_item(item.id, f"semantic_key_blocked:{source_id}") or changed
        return changed

    def cascade_dependency_blocks() -> bool:
        changed = apply_semantic_suppression()
        for relation in relations:
            if relation.id not in visible:
                continue
            if not is_visible(relation.source_entity_id):
                changed = block_item(relation.id, f"relation_endpoint_blocked:{relation.source_entity_id}") or changed
            if not is_visible(relation.target_entity_id):
                changed = block_item(relation.id, f"relation_endpoint_blocked:{relation.target_entity_id}") or changed
        for slot in slots:
            if slot.id not in visible:
                continue
            for fact_id in slot.source_fact_ids:
                if not is_visible(fact_id):
                    changed = block_item(slot.id, f"source_fact_blocked:{fact_id}") or changed
        for event in events:
            if event.id not in visible:
                continue
            for fact_id in event.source_fact_ids:
                if not is_visible(fact_id):
                    changed = block_item(event.id, f"source_fact_blocked:{fact_id}") or changed
            for entity_id in event.entity_ids:
                if not is_visible(entity_id):
                    changed = block_item(event.id, f"entity_blocked:{entity_id}") or changed
        for claim in claims:
            if claim.id not in visible:
                continue
            for entity_id in claim.entity_ids:
                if not is_visible(entity_id):
                    changed = block_item(claim.id, f"entity_blocked:{entity_id}") or changed
            for fact_id in claim.source_fact_ids:
                if not is_visible(fact_id):
                    changed = block_item(claim.id, f"source_fact_blocked:{fact_id}") or changed
        visible_missing_insights = {
            insight.id for insight in insight_items if insight.type == "missing_required_slot" and insight.id in visible
        }
        for frame in domain_frames:
            if frame.id not in visible:
                continue
            visible_slot = any(is_visible(slot_id) for slot_id in frame.slot_ids)
            visible_fact = any(is_visible(fact_id) for fact_id in frame.source_fact_ids)
            visible_missing = any(
                insight.id in visible_missing_insights and insight.domain_frame_id == frame.id
                for insight in insight_items
            )
            if visible_slot or visible_fact or visible_missing:
                continue
            changed = block_item(frame.id, "domain_frame_blocked:no_visible_source") or changed
        for insight in insight_items:
            if insight.id not in visible or insight.type == "missing_required_slot":
                continue
            for fact_id in insight.source_fact_ids:
                if not is_visible(fact_id):
                    changed = block_item(insight.id, f"source_fact_blocked:{fact_id}") or changed
            for item_id in insight.supporting_item_ids:
                if not is_visible(item_id):
                    changed = block_item(insight.id, f"supporting_item_blocked:{item_id}") or changed
            if insight.domain_frame_id and not is_visible(insight.domain_frame_id):
                changed = block_item(insight.id, f"domain_frame_blocked:{insight.domain_frame_id}") or changed
        changed = apply_semantic_suppression() or changed
        return changed

    while cascade_dependency_blocks():
        pass

    all_ids = {
        item.id
        for item in [
            *entities,
            *relations,
            *events,
            *claims,
            *facts,
            *risk_flags,
            *slots,
            *domain_frames,
            *insight_items,
        ]
    }
    for item_id in all_ids - visible - set(blocked_reasons):
        add_reason(item_id, "not_effectively_visible")

    return VisibilityState(
        visible_item_ids=sorted(visible & all_ids),
        blocked_item_ids=sorted(all_ids - visible),
        blocked_reasons={item_id: sorted(reasons) for item_id, reasons in sorted(blocked_reasons.items())},
    )


def to_legacy_view(
    *,
    entities: list[EntityItem],
    relations: list[RelationItem],
    events: list[EventItem],
    claims: list[ClaimItem],
    facts: list[FactItem],
    slots: list[SlotItem],
    domain_frames: list[DomainFrame],
    insight_items: list[InsightItem],
    visibility: VisibilityState,
) -> LegacyView:
    visible_ids = set(visibility.visible_item_ids)
    active_entities = [item for item in entities if item.id in visible_ids]
    active_entity_ids = {item.id for item in active_entities}
    active_relations = [
        item
        for item in relations
        if item.id in visible_ids
        and item.source_entity_id in active_entity_ids
        and item.target_entity_id in active_entity_ids
    ]
    active_events = [item for item in events if item.id in visible_ids]
    active_claims = [item for item in claims if item.id in visible_ids]
    active_insights = [item for item in insight_items if item.id in visible_ids]

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
            "time": _semantic_time_label(item.semantic_time)
            or (item.start_time if item.start_time is not None else "không xác định"),
            "event": item.label,
            "type": item.type,
            "semantic_time": item.semantic_time,
            "start_time": item.start_time,
            "end_time": item.end_time,
            "source_fact_ids": item.source_fact_ids,
            "entities_involved": item.entity_ids,
            "confidence": item.confidence,
            "review_status": item.review_status,
            "requires_review": item.requires_review,
        }
        for item in active_events
    ]
    main_events = [item.label for item in active_events] + [item.label for item in active_claims]
    entity_types = sorted({item.type for item in active_entities})
    insights = [item.title_vi for item in active_insights]
    extracted_entities = _canonical_key_items(entities, facts, slots, visibility)
    return LegacyView(
        nodes=nodes,
        edges=edges,
        timeline=timeline,
        main_events=main_events,
        entity_types=entity_types,
        insights=insights,
        extracted_entities=extracted_entities,
    )


def _active_items(items: list[Any], visibility: VisibilityState | None = None) -> list[Any]:
    visible_ids = set(visibility.visible_item_ids) if visibility else None
    return [
        item
        for item in items
        if getattr(item, "review_status", None) != "rejected"
        and (visible_ids is None or item.id in visible_ids)
    ]


def build_display_sections_vi(
    facts: list[FactItem],
    risk_flags: list[RiskFlag],
    slots: list[SlotItem],
    domain_frames: list[DomainFrame],
    visibility: VisibilityState | None = None,
) -> list[DisplaySection]:
    active_facts = _active_items(facts, visibility)
    active_risks = _active_items(risk_flags, visibility)
    active_slots = _active_items(slots, visibility)
    fact_by_id = {item.id: item for item in active_facts}
    slot_by_id = {item.id: item for item in active_slots}

    sections: list[DisplaySection] = []
    if active_facts:
        contact_types = {"phone", "email_candidate", "id_number_candidate", "email"}
        booking_types = {
            "person_name",
            "organization",
            "location",
            "address",
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

    for frame in _active_items(domain_frames, visibility):
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
    hallucination_analysis: HallucinationAnalysis | None = None
    segments: list[SegmentUnit] = Field(default_factory=list)
    entities: list[EntityItem] = Field(default_factory=list)
    relations: list[RelationItem] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)
    claims: list[ClaimItem] = Field(default_factory=list)
    facts: list[FactItem] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    slots: list[SlotItem] = Field(default_factory=list)
    domain_frames: list[DomainFrame] = Field(default_factory=list)
    insight_items: list[InsightItem] = Field(default_factory=list)
    display_sections_vi: list[DisplaySection] = Field(default_factory=list)
    legacy_view: LegacyView = Field(default_factory=LegacyView)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    main_events: list[str] = Field(default_factory=list)
    entity_types: list[str] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    key_items: list[dict[str, Any]] = Field(default_factory=list)
    visibility: VisibilityState = Field(default_factory=VisibilityState)

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
        event_ids = {item.id for item in self.events}
        risk_ids = {item.id for item in self.risk_flags}
        frame_ids = {item.id for item in self.domain_frames}

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
        for event in self.events:
            for fact_id in event.source_fact_ids:
                if fact_id not in fact_ids:
                    raise ValueError("Event references missing fact")
            for entity_id in event.entity_ids:
                if entity_id not in entity_ids:
                    raise ValueError("Event references missing entity")
        for claim in self.claims:
            for fact_id in claim.source_fact_ids:
                if fact_id not in fact_ids:
                    raise ValueError("Claim references missing fact")
            for entity_id in claim.entity_ids:
                if entity_id not in entity_ids:
                    raise ValueError("Claim references missing entity")
        valid_supporting_ids = fact_ids | event_ids | slot_ids | risk_ids
        for insight in self.insight_items:
            for fact_id in insight.source_fact_ids:
                if fact_id not in fact_ids:
                    raise ValueError("Insight references missing fact")
            for item_id in insight.supporting_item_ids:
                if item_id not in valid_supporting_ids:
                    raise ValueError("Insight references missing supporting item")
            if insight.domain_frame_id and insight.domain_frame_id not in frame_ids:
                raise ValueError("Insight references missing domain frame")

        for item in [
            *self.entities,
            *self.relations,
            *self.events,
            *self.claims,
            *self.facts,
            *self.risk_flags,
            *self.slots,
            *self.insight_items,
        ]:
            for ref in item.evidence_refs:
                if ref.segment_id and ref.segment_id not in segment_ids:
                    raise ValueError(f"Evidence references missing segment {ref.segment_id}")

        generated_visibility = _compute_visibility(
            entities=self.entities,
            relations=self.relations,
            events=self.events,
            claims=self.claims,
            facts=self.facts,
            risk_flags=self.risk_flags,
            slots=self.slots,
            domain_frames=self.domain_frames,
            insight_items=self.insight_items,
        )
        self.visibility = generated_visibility

        generated = to_legacy_view(
            entities=self.entities,
            relations=self.relations,
            events=self.events,
            claims=self.claims,
            facts=self.facts,
            slots=self.slots,
            domain_frames=self.domain_frames,
            insight_items=self.insight_items,
            visibility=generated_visibility,
        )
        self.legacy_view = generated
        self.nodes = generated.nodes
        self.edges = generated.edges
        self.timeline = generated.timeline
        self.main_events = generated.main_events
        self.entity_types = generated.entity_types
        self.insights = generated.insights
        self.key_items = generated.extracted_entities
        self.display_sections_vi = build_display_sections_vi(
            self.facts,
            self.risk_flags,
            self.slots,
            self.domain_frames,
            generated_visibility,
        )

        blocked_ids = set(generated_visibility.blocked_item_ids)
        all_item_ids = set(generated_visibility.visible_item_ids) | blocked_ids
        legacy_ids = {
            *(node.get("id") for node in self.nodes),
            *(edge.get("id") for edge in self.edges),
            *(item.get("id") for item in self.timeline),
            *(item.get("id") for item in self.key_items),
            *(item.get("id") for item in self.legacy_view.extracted_entities),
        }
        if blocked_ids.intersection(legacy_ids):
            raise ValueError("Blocked items must not appear in legacy aliases")
        if all_item_ids and all_item_ids != {
            item.id
            for item in [
                *self.entities,
                *self.relations,
                *self.events,
                *self.claims,
                *self.facts,
                *self.risk_flags,
                *self.slots,
                *self.domain_frames,
                *self.insight_items,
            ]
        }:
            raise ValueError("Visibility state must cover all analysis items")
        return self

    def to_storage_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
