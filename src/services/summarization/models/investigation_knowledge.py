"""Ground strict context output in transcript evidence and validate its graph."""

from __future__ import annotations

import copy
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.config import settings

from .context_analysis import (
    CONTEXT_PROMPT_VERSION,
    ContextAnalysisPayload,
    EpistemicStatus,
    SummarySentenceDraft,
)


KNOWLEDGE_SCHEMA_VERSION = "investigation-knowledge-v1.1"
GROUNDED_CONTEXT_SCHEMA_VERSION = "grounded-context-v1.0"


class KnowledgeGroundingError(ValueError):
    """Raised when a typed item cannot be resolved to transcript evidence."""


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        protected_namespaces=(),
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class EvidenceSpan(KnowledgeModel):
    evidence_id: str = Field(min_length=1)
    source_type: Literal["transcript_segment", "transcript_text"]
    segment_index: int | None = Field(default=None, ge=0)
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    speaker_id: str | None = Field(default=None, min_length=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, gt=0)
    quote: str = Field(min_length=1)
    quote_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_source_coordinates_and_quote_hash(self) -> "EvidenceSpan":
        if self.quote_sha256 != _sha256(self.quote):
            raise ValueError("evidence quote_sha256 does not match quote")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("evidence end_seconds precedes start_seconds")
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("evidence start_seconds and end_seconds must be paired")
        if self.source_type == "transcript_segment":
            if self.segment_index is None:
                raise ValueError("segment evidence requires segment_index")
            if self.char_start is not None or self.char_end is not None:
                raise ValueError("segment evidence cannot contain transcript char offsets")
        else:
            if self.char_start is None or self.char_end is None:
                raise ValueError("transcript evidence requires char_start and char_end")
            if self.char_end <= self.char_start:
                raise ValueError("transcript evidence char range must be non-empty")
            if self.char_end - self.char_start != len(self.quote):
                raise ValueError("transcript evidence char range does not match quote")
            if any(
                value is not None
                for value in (
                    self.segment_index,
                    self.start_seconds,
                    self.end_seconds,
                    self.speaker_id,
                )
            ):
                raise ValueError("transcript evidence cannot contain segment coordinates")
        return self


class EvidenceReferencedModel(KnowledgeModel):
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def require_unique_evidence_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_ids must be unique")
        return value


class GroundedSummarySentence(SummarySentenceDraft):
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def require_unique_summary_evidence_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("summary sentence evidence_ids must be unique")
        return value


class KnowledgeFact(EvidenceReferencedModel):
    fact_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    status: EpistemicStatus = "reported"
    model_generated: Literal[True] = True
    verification_status: Literal["unverified", "human_verified", "rejected"] = (
        "unverified"
    )


class KnowledgeEntityAttributes(KnowledgeModel):
    account_number: str | None = Field(default=None, min_length=1)
    address: str | None = Field(default=None, min_length=1)
    alias: str | None = Field(default=None, min_length=1)
    normalized_value: str | None = Field(default=None, min_length=1)


class KnowledgeEntity(EvidenceReferencedModel):
    entity_id: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    value: str = Field(min_length=1)
    role: str | None = Field(default=None, min_length=1)
    attributes: KnowledgeEntityAttributes = Field(
        default_factory=KnowledgeEntityAttributes
    )
    model_generated: Literal[True] = True
    verification_status: Literal["unverified", "human_verified", "rejected"] = (
        "unverified"
    )


class KnowledgeEvent(EvidenceReferencedModel):
    event_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    time_text: str | None = Field(default=None, min_length=1)
    actors: list[str] = Field(default_factory=list)
    location: str | None = Field(default=None, min_length=1)
    status: EpistemicStatus = "reported"
    model_generated: Literal[True] = True
    verification_status: Literal["unverified", "human_verified", "rejected"] = (
        "unverified"
    )


class KnowledgeRelationship(EvidenceReferencedModel):
    relationship_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: EpistemicStatus = "reported"
    model_generated: Literal[True] = True
    verification_status: Literal["unverified", "human_verified", "rejected"] = (
        "unverified"
    )


class InvestigationHypothesis(EvidenceReferencedModel):
    hypothesis_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    confidence: Literal["low", "medium", "high", "unknown"] = "unknown"
    verification_question: str = Field(min_length=1)
    model_generated: Literal[True] = True
    requires_human_verification: Literal[True] = True
    verification_status: Literal["unverified", "human_verified", "rejected"] = (
        "unverified"
    )


class KnowledgeTimelineEntry(EvidenceReferencedModel):
    event_id: str = Field(min_length=1)
    time: str | None = Field(default=None, min_length=1)
    description: str = Field(min_length=1)


class SegmentSourceHash(KnowledgeModel):
    segment_index: int = Field(ge=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeProvenance(KnowledgeModel):
    source_task_id: str | None = Field(default=None, min_length=1)
    source_audio_id: int | str | None = None
    audio_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    audio_integrity_status: str | None = Field(default=None, min_length=1)
    transcript_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transcript_segment_count: int = Field(ge=0)
    segment_source_hashes: list[SegmentSourceHash]
    prompt_version: Literal[CONTEXT_PROMPT_VERSION] = CONTEXT_PROMPT_VERSION
    model_id: str = Field(min_length=1)
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def require_timezone_aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value


class KnowledgeQuality(KnowledgeModel):
    total_items: int = Field(ge=0)
    grounded_items: int = Field(ge=0)
    evidence_coverage: float = Field(ge=0, le=1)
    high_risk_candidate_count: int = Field(ge=0)
    released_high_risk_count: int = Field(ge=0)
    withheld_high_risk_count: int = Field(ge=0)


class KnowledgeRetention(KnowledgeModel):
    policy_version: Literal["ai-investigation-retention-v1"] = (
        "ai-investigation-retention-v1"
    )
    data_classification: Literal["law_enforcement_sensitive"] = (
        "law_enforcement_sensitive"
    )
    generated_at: datetime
    expires_at: datetime | None
    legal_hold: bool
    raw_model_response_stored: Literal[False] = False

    @field_validator("generated_at", "expires_at")
    @classmethod
    def require_timezone_aware_retention_time(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("retention timestamps must be timezone-aware")
        return value


class KnowledgeSafety(KnowledgeModel):
    high_risk_fields_enabled: bool
    notice: str = Field(min_length=1)
    unsupported_high_risk_claims_released: Literal[False] = False


class InvestigationKnowledge(KnowledgeModel):
    schema_version: Literal[KNOWLEDGE_SCHEMA_VERSION] = KNOWLEDGE_SCHEMA_VERSION
    evidence_spans: list[EvidenceSpan]
    summary_sentences: list[GroundedSummarySentence] = Field(min_length=1)
    facts: list[KnowledgeFact]
    entities: list[KnowledgeEntity]
    events: list[KnowledgeEvent]
    relationships: list[KnowledgeRelationship]
    timeline: list[KnowledgeTimelineEntry]
    hypotheses: list[InvestigationHypothesis]
    provenance: KnowledgeProvenance
    quality: KnowledgeQuality
    retention: KnowledgeRetention
    safety: KnowledgeSafety

    @model_validator(mode="after")
    def validate_graph(self) -> "InvestigationKnowledge":
        evidence_by_id = _unique_by_id(
            self.evidence_spans,
            "evidence_id",
            "evidence span",
        )
        referenced_evidence_ids: set[str] = set()

        referenced_collections: list[list[Any]] = [
            self.summary_sentences,
            self.facts,
            self.entities,
            self.events,
            self.relationships,
            self.timeline,
            self.hypotheses,
        ]
        for collection in referenced_collections:
            for item in collection:
                for evidence_id in item.evidence_ids:
                    if evidence_id not in evidence_by_id:
                        raise ValueError(f"dangling evidence reference: {evidence_id}")
                    referenced_evidence_ids.add(evidence_id)

        if referenced_evidence_ids != set(evidence_by_id):
            raise ValueError("evidence_spans contains an unreferenced evidence item")

        for sentence in self.summary_sentences:
            resolved_quotes = [
                evidence_by_id[evidence_id].quote for evidence_id in sentence.evidence_ids
            ]
            if resolved_quotes != sentence.evidence_quotes:
                raise ValueError(
                    "summary sentence evidence_quotes do not match evidence_ids"
                )

        _unique_by_id(self.summary_sentences, "draft_id", "summary sentence")
        _unique_by_id(self.facts, "fact_id", "fact")
        _unique_by_id(self.entities, "entity_id", "entity")
        events_by_id = _unique_by_id(self.events, "event_id", "event")
        _unique_by_id(self.relationships, "relationship_id", "relationship")
        hypotheses_by_id = _unique_by_id(
            self.hypotheses,
            "hypothesis_id",
            "hypothesis",
        )
        domain_ids = [
            *[item.fact_id for item in self.facts],
            *[item.entity_id for item in self.entities],
            *events_by_id,
            *[item.relationship_id for item in self.relationships],
            *hypotheses_by_id,
        ]
        if len(domain_ids) != len(set(domain_ids)):
            raise ValueError("domain item IDs must be globally unique")

        if len(self.timeline) != len(self.events):
            raise ValueError("timeline must contain exactly one entry per event")
        for event, timeline_entry in zip(self.events, self.timeline, strict=True):
            if timeline_entry.event_id not in events_by_id:
                raise ValueError(
                    f"dangling timeline event reference: {timeline_entry.event_id}"
                )
            if (
                timeline_entry.event_id != event.event_id
                or timeline_entry.time != event.time_text
                or timeline_entry.description != event.description
                or timeline_entry.evidence_ids != event.evidence_ids
            ):
                raise ValueError("timeline entry does not match its event")

        for span in self.evidence_spans:
            if span.source_type == "transcript_segment":
                if (
                    span.segment_index is None
                    or span.segment_index >= self.provenance.transcript_segment_count
                ):
                    raise ValueError("segment evidence index exceeds provenance count")
            elif span.source_sha256 != self.provenance.transcript_sha256:
                raise ValueError(
                    "transcript evidence source_sha256 does not match provenance"
                )

        segment_hashes: dict[int, str] = {}
        for item in self.provenance.segment_source_hashes:
            if item.segment_index in segment_hashes:
                raise ValueError("duplicate segment source hash index")
            segment_hashes[item.segment_index] = item.source_sha256
        if set(segment_hashes) != set(
            range(self.provenance.transcript_segment_count)
        ):
            raise ValueError("segment source hash manifest is incomplete")
        for span in self.evidence_spans:
            if (
                span.source_type == "transcript_segment"
                and span.segment_index is not None
                and span.source_sha256 != segment_hashes[span.segment_index]
            ):
                raise ValueError(
                    "segment evidence source_sha256 does not match provenance manifest"
                )

        grounded_items = (
            len(self.facts)
            + len(self.entities)
            + len(self.events)
            + len(self.relationships)
            + len(self.hypotheses)
        )
        if self.quality.grounded_items != grounded_items:
            raise ValueError("quality grounded_items does not match graph")
        if self.quality.released_high_risk_count != len(self.hypotheses):
            raise ValueError("quality released_high_risk_count does not match graph")
        if self.quality.high_risk_candidate_count != (
            self.quality.released_high_risk_count
            + self.quality.withheld_high_risk_count
        ):
            raise ValueError("quality high-risk counts are inconsistent")
        if self.quality.total_items != (
            grounded_items + self.quality.withheld_high_risk_count
        ):
            raise ValueError("quality total_items does not match graph")
        expected_coverage = (
            round(grounded_items / self.quality.total_items, 4)
            if self.quality.total_items
            else 1.0
        )
        if abs(self.quality.evidence_coverage - expected_coverage) > 0.00001:
            raise ValueError("quality evidence_coverage does not match graph")
        if self.retention.generated_at != self.provenance.generated_at:
            raise ValueError("retention and provenance generated_at must match")
        if self.retention.legal_hold and self.retention.expires_at is not None:
            raise ValueError("legal hold retention cannot expire automatically")
        if not self.retention.legal_hold and self.retention.expires_at is None:
            raise ValueError("non-legal-hold retention requires expires_at")
        if (
            self.retention.expires_at is not None
            and self.retention.expires_at <= self.retention.generated_at
        ):
            raise ValueError("retention expires_at must follow generated_at")
        return self


class CompatibilityProjection(KnowledgeModel):
    summary_source: Literal["summary_sentence_evidence_quotes"] = (
        "summary_sentence_evidence_quotes"
    )
    raw_model_summary_released: Literal[False] = False
    projection_version: Literal["summary-projection-v1"] = "summary-projection-v1"
    release_authority: Literal["withheld_pending_claim_attestation"] = (
        "withheld_pending_claim_attestation"
    )


class GroundedContextAnalysisPayload(ContextAnalysisPayload):
    """Final typed envelope returned after deterministic grounding and projection."""

    schema_version: Literal[GROUNDED_CONTEXT_SCHEMA_VERSION] = (
        GROUNDED_CONTEXT_SCHEMA_VERSION
    )
    summary_sentences: list[GroundedSummarySentence] = Field(min_length=1)
    investigation_knowledge: InvestigationKnowledge
    summary_projection_source: Literal["summary_sentence_evidence_quotes"] = (
        "summary_sentence_evidence_quotes"
    )
    compatibility: CompatibilityProjection = Field(
        default_factory=CompatibilityProjection
    )

    @model_validator(mode="after")
    def validate_final_projection(self) -> "GroundedContextAnalysisPayload":
        expected_summary = render_summary_projection(self.summary_sentences)
        if self.summary != expected_summary:
            raise ValueError("summary must be projected from summary_sentences")
        if self.summary_sentences != self.investigation_knowledge.summary_sentences:
            raise ValueError(
                "top-level summary_sentences must match investigation knowledge"
            )
        if self.hypotheses:
            raise ValueError("raw model hypotheses cannot be released at top level")
        if (
            self.risk_assessment.crime_indicators
            or self.risk_assessment.recommended_actions
        ):
            raise ValueError("raw high-risk fields cannot be released at top level")
        return self


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    material = "|".join(str(part) for part in parts)
    return f"{prefix}-{_sha256(material)[:16]}"


def _unique_by_id(items: list[Any], field_name: str, label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        item_id = str(getattr(item, field_name))
        if item_id in result:
            raise ValueError(f"duplicate {label} id: {item_id}")
        result[item_id] = item
    return result


def render_summary_projection(
    sentences: list[GroundedSummarySentence] | list[dict[str, Any]],
) -> str:
    """Render a fail-safe compatibility summary from source quotes only."""

    rendered = []
    for sentence in sentences:
        quotes = (
            sentence.evidence_quotes
            if isinstance(sentence, GroundedSummarySentence)
            else sentence["evidence_quotes"]
        )
        for quote in quotes:
            normalized_quote = _normalize_text(str(quote))
            if normalized_quote and normalized_quote not in rendered:
                rendered.append(normalized_quote)
    return " ".join(rendered).strip()


def remove_ungrounded_high_risk_fields(analysis: dict[str, Any]) -> dict[str, Any]:
    """Remove raw high-risk candidates from the flat compatibility projection."""

    payload = ContextAnalysisPayload.model_validate(copy.deepcopy(analysis))
    sanitized = payload.model_dump(mode="json", exclude_none=True)
    sanitized["hypotheses"] = []
    sanitized["risk_assessment"] = {
        "overall_risk": "unverified",
        "crime_indicators": [],
        "recommended_actions": [],
    }
    return ContextAnalysisPayload.model_validate(sanitized).model_dump(
        mode="json",
        exclude_none=True,
    )


def build_investigation_knowledge(
    analysis: dict[str, Any],
    transcript: str,
    segments: list[dict[str, Any]] | None = None,
    *,
    model_id: str,
    source_metadata: dict[str, Any] | None = None,
    high_risk_enabled: bool | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a strict graph; unsupported ordinary facts fail the whole operation."""

    payload = ContextAnalysisPayload.model_validate(analysis)
    source_metadata = source_metadata or {}
    high_risk_enabled = (
        settings.ENABLE_HIGH_RISK_AI_FIELDS
        if high_risk_enabled is None
        else high_risk_enabled
    )
    generated_at = generated_at or datetime.now(timezone.utc)
    normalized_transcript = _normalize_text(transcript)
    segment_rows: list[dict[str, Any]] = []
    segment_source_hashes: list[SegmentSourceHash] = []
    for index, segment in enumerate(segments or []):
        text_value = _normalize_text(str(segment.get("text") or ""))
        segment_source_hashes.append(
            SegmentSourceHash(
                segment_index=index,
                source_sha256=_sha256(text_value),
            )
        )
        if not text_value:
            continue
        segment_rows.append(
            {
                "index": index,
                "text": text_value,
                "start": segment.get("start"),
                "end": segment.get("end"),
                "speaker": segment.get("speaker"),
            }
        )

    evidence_by_key: dict[tuple[Any, ...], EvidenceSpan] = {}

    def resolve_evidence(quote: str) -> str | None:
        normalized_quote = _normalize_text(quote)
        if len(normalized_quote) < 1:
            return None
        folded_quote = normalized_quote.casefold()

        for segment in segment_rows:
            if folded_quote not in segment["text"].casefold():
                continue
            key = ("segment", segment["index"], folded_quote)
            if key not in evidence_by_key:
                evidence_by_key[key] = EvidenceSpan(
                    evidence_id=_stable_id("ev", *key),
                    source_type="transcript_segment",
                    segment_index=segment["index"],
                    start_seconds=segment["start"],
                    end_seconds=segment["end"],
                    speaker_id=segment["speaker"],
                    quote=normalized_quote,
                    quote_sha256=_sha256(normalized_quote),
                    source_sha256=_sha256(segment["text"]),
                )
            return evidence_by_key[key].evidence_id

        char_start = normalized_transcript.casefold().find(folded_quote)
        if char_start == -1:
            return None
        char_end = char_start + len(normalized_quote)
        key = ("transcript", char_start, char_end, folded_quote)
        if key not in evidence_by_key:
            evidence_by_key[key] = EvidenceSpan(
                evidence_id=_stable_id("ev", *key),
                source_type="transcript_text",
                char_start=char_start,
                char_end=char_end,
                quote=normalized_quote,
                quote_sha256=_sha256(normalized_quote),
                source_sha256=_sha256(normalized_transcript),
            )
        return evidence_by_key[key].evidence_id

    def require_evidence(quote: str, owner: str) -> str:
        evidence_id = resolve_evidence(quote)
        if evidence_id is None:
            raise KnowledgeGroundingError(
                f"{owner} evidence quote is absent from transcript"
            )
        return evidence_id

    def require_evidence_many(quotes: list[str], owner: str) -> list[str]:
        evidence_ids = [require_evidence(quote, owner) for quote in quotes]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise KnowledgeGroundingError(
                f"{owner} evidence quotes resolve to duplicate evidence"
            )
        return evidence_ids

    summary_sentences = [
        GroundedSummarySentence(
            draft_id=sentence.draft_id,
            text=" ".join(sentence.evidence_quotes),
            sentence_role=sentence.sentence_role,
            evidence_quotes=sentence.evidence_quotes,
            evidence_ids=require_evidence_many(
                sentence.evidence_quotes,
                f"summary sentence {sentence.draft_id}",
            ),
        )
        for sentence in payload.summary_sentences
    ]

    facts: list[KnowledgeFact] = []
    entities: list[KnowledgeEntity] = []
    events: list[KnowledgeEvent] = []
    relationships: list[KnowledgeRelationship] = []
    hypotheses: list[InvestigationHypothesis] = []
    seen_fact_ids: set[str] = set()
    seen_entity_ids: set[str] = set()

    def add_fact(
        category: str,
        statement: str,
        evidence_quotes: list[str],
        *,
        status: EpistemicStatus = "reported",
    ) -> None:
        normalized_statement = _normalize_text(statement)
        evidence_ids = require_evidence_many(evidence_quotes, f"fact {category}")
        fact_id = _stable_id("fact", category, normalized_statement, status)
        if fact_id in seen_fact_ids:
            return
        seen_fact_ids.add(fact_id)
        facts.append(
            KnowledgeFact(
                fact_id=fact_id,
                category=category,
                statement=normalized_statement,
                status=status,
                evidence_ids=evidence_ids,
            )
        )

    for point in payload.key_points:
        add_fact("key_point", point.statement, [point.evidence_quote])
    for item in payload.facts:
        add_fact(
            item.category,
            item.statement,
            [item.evidence_quote],
            status=item.status,
        )
    for item in payload.topics:
        add_fact("topic", item.synthesis, [item.evidence_quote])
    for item in payload.actions:
        add_fact("action", item.action, [item.evidence_quote], status=item.status)
    for item in payload.decisions:
        add_fact(
            "decision",
            item.decision,
            [item.evidence_quote],
            status=item.status,
        )
    for item in payload.contradictions:
        add_fact(
            "contradiction",
            item.statement,
            [item.evidence_quote, item.conflicting_evidence_quote],
            status="conflicting",
        )

    def add_entity(entity_type: str, item: Any) -> None:
        value = item.name or item.value or item.account_number or item.address
        evidence_id = require_evidence(item.evidence_quote, f"entity {entity_type}")
        entity_id = _stable_id("entity", entity_type, value)
        if entity_id in seen_entity_ids:
            return
        seen_entity_ids.add(entity_id)
        entities.append(
            KnowledgeEntity(
                entity_id=entity_id,
                entity_type=entity_type,
                value=value,
                role=item.role,
                attributes=KnowledgeEntityAttributes(
                    account_number=item.account_number,
                    address=item.address,
                    alias=item.alias,
                    normalized_value=item.normalized_value,
                ),
                evidence_ids=[evidence_id],
            )
        )

    for group_name, entity_type in (
        ("people", "person"),
        ("locations", "location"),
        ("time", "time"),
        ("organizations", "organization"),
    ):
        for item in getattr(payload.entities, group_name):
            add_entity(entity_type, item)

    if payload.entities.contact_info is not None:
        for group_name, entity_type in (
            ("phones", "phone"),
            ("emails", "email"),
            ("ids", "identity_document"),
            ("bank_accounts", "bank_account"),
            ("addresses", "address"),
        ):
            for item in getattr(payload.entities.contact_info, group_name):
                add_entity(entity_type, item)

    for index, item in enumerate(payload.events):
        evidence_id = require_evidence(item.evidence_quote, f"event {index}")
        events.append(
            KnowledgeEvent(
                event_id=_stable_id("event", index, item.description),
                description=item.description,
                time_text=item.time,
                actors=item.actors,
                location=item.location,
                status=item.status,
                evidence_ids=[evidence_id],
            )
        )

    for index, item in enumerate(payload.relationships):
        evidence_id = require_evidence(item.evidence_quote, f"relationship {index}")
        relationships.append(
            KnowledgeRelationship(
                relationship_id=_stable_id(
                    "rel",
                    index,
                    item.source,
                    item.target,
                    item.label,
                ),
                source=item.source,
                target=item.target,
                label=item.label,
                status=item.status,
                evidence_ids=[evidence_id],
            )
        )

    high_risk_candidates: list[dict[str, str]] = []
    for item in payload.hypotheses:
        high_risk_candidates.append(
            {
                "category": item.category,
                "statement": item.statement,
                "evidence_quote": item.evidence_quote,
                "confidence": item.confidence,
                "verification_question": item.verification_question,
            }
        )
    for item in payload.risk_assessment.crime_indicators:
        high_risk_candidates.append(
            {
                "category": item.crime_type or "crime_indicator",
                "statement": item.statement,
                "evidence_quote": item.evidence_quote,
                "confidence": item.confidence,
                "verification_question": (
                    "What independent evidence verifies this crime indicator?"
                ),
            }
        )

    withheld_high_risk = 0
    if high_risk_enabled:
        for index, candidate in enumerate(high_risk_candidates):
            evidence_id = resolve_evidence(candidate["evidence_quote"])
            if evidence_id is None:
                withheld_high_risk += 1
                continue
            hypotheses.append(
                InvestigationHypothesis(
                    hypothesis_id=_stable_id(
                        "hyp",
                        index,
                        candidate["category"],
                        candidate["statement"],
                    ),
                    category=candidate["category"],
                    statement=candidate["statement"],
                    confidence=candidate["confidence"],
                    verification_question=candidate["verification_question"],
                    evidence_ids=[evidence_id],
                )
            )
    else:
        withheld_high_risk = len(high_risk_candidates)

    grounded_items = (
        len(facts)
        + len(entities)
        + len(events)
        + len(relationships)
        + len(hypotheses)
    )
    total_items = grounded_items + withheld_high_risk
    evidence_coverage = round(grounded_items / total_items, 4) if total_items else 1.0

    generated_iso = generated_at
    legal_hold = bool(source_metadata.get("legal_hold", False))
    expires_at = None
    if not legal_hold:
        expires_at = generated_at + timedelta(
            days=max(1, settings.AI_CONTEXT_RETENTION_DAYS)
        )

    knowledge = InvestigationKnowledge(
        evidence_spans=list(evidence_by_key.values()),
        summary_sentences=summary_sentences,
        facts=facts,
        entities=entities,
        events=events,
        relationships=relationships,
        timeline=[
            KnowledgeTimelineEntry(
                event_id=event.event_id,
                time=event.time_text,
                description=event.description,
                evidence_ids=event.evidence_ids,
            )
            for event in events
        ],
        hypotheses=hypotheses,
        provenance=KnowledgeProvenance(
            source_task_id=source_metadata.get("task_id"),
            source_audio_id=source_metadata.get("audio_id"),
            audio_sha256=source_metadata.get("audio_sha256"),
            audio_integrity_status=source_metadata.get("audio_integrity_status"),
            transcript_sha256=_sha256(normalized_transcript),
            transcript_segment_count=len(segments or []),
            segment_source_hashes=segment_source_hashes,
            model_id=model_id,
            generated_at=generated_iso,
        ),
        quality=KnowledgeQuality(
            total_items=total_items,
            grounded_items=grounded_items,
            evidence_coverage=evidence_coverage,
            high_risk_candidate_count=len(high_risk_candidates),
            released_high_risk_count=len(hypotheses),
            withheld_high_risk_count=withheld_high_risk,
        ),
        retention=KnowledgeRetention(
            generated_at=generated_iso,
            expires_at=expires_at,
            legal_hold=legal_hold,
        ),
        safety=KnowledgeSafety(
            high_risk_fields_enabled=high_risk_enabled,
            notice=(
                "AI-generated investigative leads require comparison with the source "
                "audio and human verification before operational use."
            ),
        ),
    )
    return knowledge.model_dump(mode="json", exclude_none=True)


def build_grounded_context_analysis(
    analysis: dict[str, Any],
    transcript: str,
    segments: list[dict[str, Any]] | None = None,
    *,
    model_id: str,
    source_metadata: dict[str, Any] | None = None,
    high_risk_enabled: bool | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble and revalidate the final envelope after all derived fields exist."""

    draft = ContextAnalysisPayload.model_validate(analysis).model_dump(
        mode="json",
        exclude_none=True,
    )
    knowledge = build_investigation_knowledge(
        draft,
        transcript,
        segments,
        model_id=model_id,
        source_metadata=source_metadata,
        high_risk_enabled=high_risk_enabled,
        generated_at=generated_at,
    )
    sanitized = remove_ungrounded_high_risk_fields(draft)
    sanitized.update(
        {
            "schema_version": GROUNDED_CONTEXT_SCHEMA_VERSION,
            "summary": render_summary_projection(knowledge["summary_sentences"]),
            "summary_sentences": knowledge["summary_sentences"],
            "investigation_knowledge": knowledge,
            "summary_projection_source": "summary_sentence_evidence_quotes",
            "compatibility": {
                "summary_source": "summary_sentence_evidence_quotes",
                "raw_model_summary_released": False,
                "projection_version": "summary-projection-v1",
                "release_authority": "withheld_pending_claim_attestation",
            },
        }
    )
    return GroundedContextAnalysisPayload.model_validate(sanitized).model_dump(
        mode="json",
        exclude_none=True,
    )


def build_s1_schema_artifact() -> dict[str, Any]:
    """Return the deterministic schema artifact committed with the S1 package."""

    return {
        "artifact_version": "s1-summary-schema-v1",
        "context_prompt_version": CONTEXT_PROMPT_VERSION,
        "knowledge_schema_version": KNOWLEDGE_SCHEMA_VERSION,
        "grounded_context_schema_version": GROUNDED_CONTEXT_SCHEMA_VERSION,
        "provider_schema": ContextAnalysisPayload.model_json_schema(),
        "knowledge_schema": InvestigationKnowledge.model_json_schema(),
        "final_envelope_schema": GroundedContextAnalysisPayload.model_json_schema(),
        "gates": {
            "nested_objects_forbid_unknown_fields": True,
            "summary_sentences_require_evidence_quotes": True,
            "grounded_references_must_resolve": True,
            "source_hash_manifest_bound": True,
            "raw_model_summary_is_release_authority": False,
            "raw_model_sentence_text_released": False,
            "final_envelope_revalidated": True,
            "legacy_coercion_in_provider_path": False,
            "per_claim_semantic_attestation_complete": False,
            "summary_release_authority": "withheld_pending_claim_attestation",
        },
    }
