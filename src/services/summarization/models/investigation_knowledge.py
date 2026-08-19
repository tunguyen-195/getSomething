"""Ground strict context output in transcript evidence and validate its graph."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.services.investigation.claim_semantics import (
    extract_semantic_action_sequence,
    extract_semantic_roles,
)

from src.core.config import settings

from .context_analysis import (
    CONTEXT_PROMPT_VERSION,
    ContextAnalysisPayload,
    EpistemicStatus,
    SummarySentenceDraft,
)


KNOWLEDGE_SCHEMA_VERSION = "investigation-knowledge-v1.2"
GROUNDED_CONTEXT_SCHEMA_VERSION = "grounded-context-v1.1"


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


ParticipantIdentityBasis = Literal[
    "self_identified",
    "source_attributed",
    "conversation_role",
    "anonymous",
]
SpeakerBindingState = Literal[
    "verified_cluster",
    "degraded_unresolved",
    "unavailable",
    "not_applicable",
]
DiarizationStatus = Literal[
    "success",
    "degraded",
    "failed",
    "unavailable",
    "disabled",
]


class GroundedParticipantRole(EvidenceReferencedModel):
    role_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    role_type: Literal[
        "occupation",
        "organization_affiliation",
        "conversation_role",
        "relationship",
        "other",
    ] = "other"
    basis: Literal[
        "explicit_self_statement",
        "explicit_named_relation",
        "source_attributed",
        "trusted_channel_metadata",
    ]


class ParticipantReference(EvidenceReferencedModel):
    participant_id: str = Field(min_length=1)
    participant_kind: Literal["speaker", "mentioned_person"]
    source_speaker_ids: list[str] = Field(default_factory=list)
    speaker_binding_state: SpeakerBindingState
    entity_id: str | None = Field(default=None, min_length=1)
    display_name: str | None = Field(default=None, min_length=1)
    grounded_roles: list[GroundedParticipantRole] = Field(default_factory=list)
    identity_basis: ParticipantIdentityBasis
    public_actor_label: str = Field(min_length=1)
    allowed_reference_forms: list[str] = Field(min_length=1)
    withheld_identity_reason: Literal[
        "diarization_degraded",
        "diarization_unavailable",
        "identity_conflict",
        "insufficient_relation_evidence",
    ] | None = None
    attribution_required: bool = False
    verification_status: Literal["unverified", "human_verified"] = "unverified"

    @field_validator("source_speaker_ids")
    @classmethod
    def require_unique_speaker_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.casefold() for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("participant reference values must be unique")
        return value

    @field_validator("allowed_reference_forms")
    @classmethod
    def require_public_reference_forms(cls, value: list[str]) -> list[str]:
        normalized = [item.casefold() for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("participant reference values must be unique")
        if any(
            re.fullmatch(
                r"(?:tôi|tao|mình|em|anh|chị|bên\s+em)",
                item,
                re.IGNORECASE,
            )
            or re.search(r"\bSPEAKER[_\s-]*\d+\b", item, re.IGNORECASE)
            for item in value
        ):
            raise ValueError("participant reference forms cannot expose conversation labels")
        return value

    @model_validator(mode="after")
    def validate_identity_release(self) -> "ParticipantReference":
        allowed = {item.casefold() for item in self.allowed_reference_forms}
        if self.public_actor_label.casefold() not in allowed:
            raise ValueError("public actor label must be an allowed reference form")
        if (
            self.attribution_required
            and self.display_name is not None
            and self.display_name.casefold() in allowed
        ):
            raise ValueError(
                "attribution-required participant cannot release a bare identity"
            )
        if self.identity_basis == "anonymous":
            if self.entity_id is not None or self.display_name is not None:
                raise ValueError("anonymous participant cannot release an identity")
        elif self.display_name is None or self.entity_id is None:
            raise ValueError("named participant requires entity_id and display_name")
        if self.speaker_binding_state == "verified_cluster":
            if not self.source_speaker_ids:
                raise ValueError("verified speaker binding requires a source speaker ID")
        elif self.source_speaker_ids:
            raise ValueError("unverified speaker binding cannot release speaker IDs")
        role_ids = [item.role_id for item in self.grounded_roles]
        if len(role_ids) != len(set(role_ids)):
            raise ValueError("participant grounded role IDs must be unique")
        return self


class ParticipantRegistry(KnowledgeModel):
    source_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diarization_status: DiarizationStatus
    speaker_count_release_status: Literal["verified", "withheld"]
    verified_speaker_count: int | None = Field(default=None, ge=1)
    degraded_reasons: list[str] = Field(default_factory=list)
    participants: list[ParticipantReference] = Field(min_length=1)

    @field_validator("degraded_reasons")
    @classmethod
    def require_unique_degraded_reasons(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("participant registry degraded reasons must be unique")
        return value

    @model_validator(mode="after")
    def validate_count_release(self) -> "ParticipantRegistry":
        if self.speaker_count_release_status == "verified":
            if self.diarization_status != "success":
                raise ValueError("speaker count requires successful diarization")
            if self.verified_speaker_count is None:
                raise ValueError("verified speaker count is required")
        elif self.verified_speaker_count is not None:
            raise ValueError("withheld speaker count cannot expose a value")
        participant_ids = [item.participant_id for item in self.participants]
        if len(participant_ids) != len(set(participant_ids)):
            raise ValueError("participant IDs must be unique")
        public_labels = [
            item.public_actor_label.casefold()
            for item in self.participants
            if item.identity_basis != "anonymous"
            or item.speaker_binding_state == "verified_cluster"
        ]
        if len(public_labels) != len(set(public_labels)):
            raise ValueError("participant public actor labels must be unique")
        return self


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
    actor: str | None = Field(default=None, min_length=1)
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
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    speaker_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_segment_coordinates(self) -> "SegmentSourceHash":
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("segment manifest timestamps must be paired")
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds < self.start_seconds
        ):
            raise ValueError("segment manifest end precedes start")
        return self


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
    participant_registry: ParticipantRegistry
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
            self.participant_registry.participants,
        ]
        for collection in referenced_collections:
            for item in collection:
                for evidence_id in item.evidence_ids:
                    if evidence_id not in evidence_by_id:
                        raise ValueError(f"dangling evidence reference: {evidence_id}")
                    referenced_evidence_ids.add(evidence_id)

        for participant in self.participant_registry.participants:
            for role in participant.grounded_roles:
                for evidence_id in role.evidence_ids:
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
        entities_by_id = _unique_by_id(self.entities, "entity_id", "entity")
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

        manifest_speaker_ids = {
            item.speaker_id
            for item in self.provenance.segment_source_hashes
            if item.speaker_id is not None
        }
        bound_speaker_ids: list[str] = []
        for participant in self.participant_registry.participants:
            if participant.entity_id is not None:
                entity = entities_by_id.get(participant.entity_id)
                if entity is None or entity.entity_type != "person":
                    raise ValueError("participant entity_id must resolve to a person")
                if participant.display_name != entity.value:
                    raise ValueError("participant display name must match its person entity")
            for role in participant.grounded_roles:
                if not set(role.evidence_ids).issubset(participant.evidence_ids):
                    raise ValueError("participant role evidence must belong to participant")
            if participant.identity_basis == "self_identified":
                direct_self_evidence = [
                    evidence_by_id[evidence_id]
                    for evidence_id in participant.evidence_ids
                    if participant.display_name is not None
                    and _is_self_identification(
                        evidence_by_id[evidence_id].quote,
                        participant.display_name,
                    )
                ]
                if participant.display_name is None or not direct_self_evidence:
                    raise ValueError(
                        "self-identified participant lacks direct identification evidence"
                    )
                if participant.source_speaker_ids:
                    self_identification_speaker_ids = {
                        evidence.speaker_id
                        for evidence in direct_self_evidence
                        if evidence.speaker_id is not None
                    }
                    if set(participant.source_speaker_ids) != (
                        self_identification_speaker_ids
                    ):
                        raise ValueError(
                            "self-identification evidence speaker does not match "
                            "participant binding"
                        )
            for speaker_id in participant.source_speaker_ids:
                if speaker_id not in manifest_speaker_ids:
                    raise ValueError("participant speaker ID is absent from source manifest")
                if not any(
                    evidence_by_id[evidence_id].speaker_id == speaker_id
                    for evidence_id in participant.evidence_ids
                ):
                    raise ValueError("participant speaker ID lacks participant evidence")
                bound_speaker_ids.append(speaker_id)
        if len(bound_speaker_ids) != len(set(bound_speaker_ids)):
            raise ValueError("a speaker cluster cannot map to multiple participants")
        registry = self.participant_registry
        if registry.speaker_count_release_status == "verified":
            if set(bound_speaker_ids) != manifest_speaker_ids:
                raise ValueError("verified participant registry must bind every speaker cluster")
            if registry.verified_speaker_count != len(manifest_speaker_ids):
                raise ValueError("verified speaker count does not match source manifest")

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

        segment_manifest: dict[int, SegmentSourceHash] = {}
        for item in self.provenance.segment_source_hashes:
            if item.segment_index in segment_manifest:
                raise ValueError("duplicate segment source hash index")
            segment_manifest[item.segment_index] = item
        if set(segment_manifest) != set(
            range(self.provenance.transcript_segment_count)
        ):
            raise ValueError("segment source hash manifest is incomplete")
        for span in self.evidence_spans:
            if span.source_type != "transcript_segment" or span.segment_index is None:
                continue
            manifest = segment_manifest[span.segment_index]
            if span.source_sha256 != manifest.source_sha256:
                raise ValueError(
                    "segment evidence source_sha256 does not match provenance manifest"
                )
            if (
                span.start_seconds != manifest.start_seconds
                or span.end_seconds != manifest.end_seconds
                or span.speaker_id != manifest.speaker_id
            ):
                raise ValueError("segment evidence metadata does not match provenance manifest")

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
    summary_source: Literal["grounded_summary_sentence_text"] = (
        "grounded_summary_sentence_text"
    )
    raw_model_summary_released: Literal[False] = False
    projection_version: Literal["summary-projection-v2"] = "summary-projection-v2"
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
    summary_projection_source: Literal["grounded_summary_sentence_text"] = (
        "grounded_summary_sentence_text"
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


_CONVERSATIONAL_REFERENCE = re.compile(
    r"\b(?:tôi|tao|mình|em|anh|chị|bên\s+em)\b",
    re.IGNORECASE,
)
_GENERIC_PERSON_VALUES = {
    "anh",
    "chị",
    "em",
    "khách",
    "mình",
    "người gọi",
    "người nói",
    "người tham gia",
    "nhân viên",
    "số",
    "tôi",
}
_GENERIC_PARTICIPANT_ROLES = {
    "person",
    "participant",
    "speaker",
    "người nói",
    "người tham gia",
}
_SPEAKER_ORDINALS = (
    "thứ nhất",
    "thứ hai",
    "thứ ba",
    "thứ tư",
    "thứ năm",
    "thứ sáu",
    "thứ bảy",
    "thứ tám",
    "thứ chín",
    "thứ mười",
)


def _normalized_diarization_status(value: object) -> DiarizationStatus:
    normalized = str(value or "unavailable").strip().casefold()
    if normalized in {"success", "degraded", "failed", "unavailable", "disabled"}:
        return normalized  # type: ignore[return-value]
    return "unavailable"


def _normalized_reason_list(value: object) -> list[str]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = [str(item) for item in value]
    else:
        candidates = []
    return list(
        dict.fromkeys(
            normalized
            for item in candidates
            for normalized in [_normalize_text(item)]
            if normalized
        )
    )


def participant_source_metadata_sha256(source_metadata: dict[str, Any] | None) -> str:
    metadata = source_metadata or {}
    material = {
        "diarization_status": metadata.get("diarization_status"),
        "num_speakers": metadata.get("num_speakers"),
        "diarization_method_used": metadata.get("diarization_method_used"),
        "diarization_fallback_reason": metadata.get("diarization_fallback_reason"),
        "diarization_degraded_reasons": metadata.get(
            "diarization_degraded_reasons"
        ),
        "has_diarization": metadata.get("has_diarization"),
        "degraded": metadata.get("degraded"),
        "audio_integrity_status": metadata.get("audio_integrity_status"),
        "speaker_provenance": metadata.get("speaker_provenance"),
    }
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return _sha256(canonical)


def _phrase_pattern(value: str) -> str:
    return r"\s+".join(re.escape(token) for token in _normalize_text(value).split())


_SELF_IDENTIFICATION_QUESTION_PREFIX = re.compile(
    r"\b(?:có\s+phải|phải\s+chăng)\b[^.!?]{0,120}$",
    re.IGNORECASE,
)
_SELF_IDENTIFICATION_QUESTION_TAIL = re.compile(
    r"^(?:\s|[,;:])*(?:hả|sao|à|ư|nhỉ|chứ|"
    r"(?:có\s+)?(?:phải|đúng)\s+(?:không|chứ)|(?:hay\s+)?không)\b",
    re.IGNORECASE,
)
_SELF_IDENTIFICATION_NEGATION = re.compile(
    r"\b(?:không|chẳng|chưa)\s+(?:phải\s+)?(?:tên\s+|họ\s+tên\s+)?(?:là\s+)?$",
    re.IGNORECASE,
)
_SELF_IDENTIFICATION_REPORTED = re.compile(
    r"\b(?:theo\s+(?:lời|tin\s+nhắn)|nói|cho\s+biết|kể|bảo|"
    r"khẳng\s+định|nhắc|nhắn(?:\s+tin)?|viết(?:\s+rằng)?|"
    r"ghi(?:\s+rằng)?|thuật\s+lại|trích\s+lời|hỏi)\b"
    r"[^.!?]{0,120}$",
    re.IGNORECASE,
)
_SELF_IDENTIFICATION_DENIAL_TAIL = re.compile(
    r"^(?:\s|[,;:])*(?:đâu|không\s+phải|không\s+đúng|"
    r"chẳng\s+đúng|sai(?:\s+rồi)?)\b",
    re.IGNORECASE,
)

_DIGIT_ENTITY_TYPES = {"phone", "bank_account", "identity_document"}
_DIGIT_ENTITY_LENGTHS = {
    "phone": (7, 15),
    "bank_account": (6, 19),
    "identity_document": (6, 20),
}
_DIGIT_SURFACE = re.compile(r"(?<!\w)\+?\d(?:[\d\s()./-]*\d)?(?!\w)")
_CLOCK_SURFACE = re.compile(
    r"(?<!\d)(?P<hour>[01]?\d|2[0-3])\s*"
    r"(?P<separator>:|h|giờ)\s*(?P<minute>[0-5]?\d)?(?!\d)",
    re.IGNORECASE,
)


def _exact_entity_surface_occurs(value: str, quote: str) -> bool:
    normalized_value = _normalize_text(value)
    normalized_quote = _normalize_text(quote)
    if not normalized_value or not normalized_quote:
        return False
    pattern = r"(?<!\w)" + _phrase_pattern(normalized_value) + r"(?!\w)"
    return re.search(pattern, normalized_quote, re.IGNORECASE) is not None


def _canonical_digit_surfaces(value: str) -> set[str]:
    return {
        "".join(char for char in match.group(0) if char.isdigit())
        for match in _DIGIT_SURFACE.finditer(value)
    }


def _canonical_clock_surfaces(value: str) -> set[tuple[int, int]]:
    surfaces: set[tuple[int, int]] = set()
    for match in _CLOCK_SURFACE.finditer(value):
        minute_text = match.group("minute")
        if match.group("separator") == ":" and minute_text is None:
            continue
        surfaces.add((int(match.group("hour")), int(minute_text or "0")))
    return surfaces


def _entity_value_is_supported(entity_type: str, value: str, quote: str) -> bool:
    normalized_value = _normalize_text(value)
    if not normalized_value:
        return False
    if entity_type == "person":
        return (
            normalized_value.casefold() not in _GENERIC_PERSON_VALUES
            and _exact_entity_surface_occurs(normalized_value, quote)
        )
    if entity_type in _DIGIT_ENTITY_TYPES:
        value_digits = "".join(char for char in normalized_value if char.isdigit())
        minimum, maximum = _DIGIT_ENTITY_LENGTHS[entity_type]
        return (
            minimum <= len(value_digits) <= maximum
            and value_digits in _canonical_digit_surfaces(quote)
        )
    if entity_type == "time":
        if _exact_entity_surface_occurs(normalized_value, quote):
            return True
        value_clocks = _canonical_clock_surfaces(normalized_value)
        return bool(value_clocks and value_clocks & _canonical_clock_surfaces(quote))
    return _exact_entity_surface_occurs(normalized_value, quote)


def _is_self_identification(quote: str, display_name: str) -> bool:
    normalized_quote = _normalize_text(quote)
    escaped_name = _phrase_pattern(display_name)
    match = re.search(
        rf"\b(?:"
        rf"(?:tôi|tao|mình|em)\s+"
        rf"(?:(?:tên|họ\s+tên)(?:\s+là)?|là)"
        rf"|(?:anh|chị)\s+(?:tên|họ\s+tên)(?:\s+là)?"
        rf")\s+{escaped_name}(?!\w)",
        normalized_quote,
        re.IGNORECASE,
    )
    if match is None:
        return False
    prefix = normalized_quote[: match.start()]
    tail = normalized_quote[match.end() :]
    if _SELF_IDENTIFICATION_QUESTION_PREFIX.search(prefix):
        return False
    if "?" in tail or _SELF_IDENTIFICATION_QUESTION_TAIL.search(tail):
        return False
    if _SELF_IDENTIFICATION_DENIAL_TAIL.search(tail):
        return False
    if _SELF_IDENTIFICATION_NEGATION.search(prefix):
        return False
    if _SELF_IDENTIFICATION_REPORTED.search(prefix):
        return False
    return True


def _explicit_role_surfaces(quote: str, display_name: str, role: str) -> list[str]:
    normalized_quote = _normalize_text(quote)
    name_pattern = _phrase_pattern(display_name)
    role_pattern = _phrase_pattern(role)
    patterns = (
        rf"(?<!\w){role_pattern}\s+(?:là\s+)?{name_pattern}(?!\w)",
        rf"(?<!\w){name_pattern}\s*,\s*{role_pattern}(?!\w)",
        rf"(?<!\w){name_pattern}\s+(?:là|giữ\s+chức\s+vụ|làm|"
        rf"đảm\s+nhiệm\s+vai\s+trò)\s+{role_pattern}(?!\w)",
    )
    return list(
        dict.fromkeys(
            match.group(0)
            for pattern in patterns
            for match in re.finditer(pattern, normalized_quote, re.IGNORECASE)
        )
    )


def _participant_role_type(role: str) -> Literal[
    "occupation",
    "organization_affiliation",
    "conversation_role",
    "relationship",
    "other",
]:
    lowered = role.casefold()
    if any(marker in lowered for marker in ("nhân viên", "cán bộ", "giám đốc", "chức vụ")):
        return "occupation"
    if any(marker in lowered for marker in ("đơn vị", "công ty", "tổ chức")):
        return "organization_affiliation"
    if any(
        marker in lowered
        for marker in (
            "người gọi",
            "người nghe",
            "người tiếp nhận",
            "người trả lời",
            "người liên hệ",
            "bên gọi",
            "bên nhận cuộc gọi",
        )
    ):
        return "conversation_role"
    if any(marker in lowered for marker in ("cha", "mẹ", "anh trai", "chị gái", "vợ", "chồng")):
        return "relationship"
    return "other"


def _anonymous_actor_label(index: int) -> str:
    if index < len(_SPEAKER_ORDINALS):
        return f"người tham gia {_SPEAKER_ORDINALS[index]}"
    suffix = chr(ord("A") + (index % 26))
    return f"người tham gia chưa định danh {suffix}"


def _build_participant_registry(
    *,
    entities: list[KnowledgeEntity],
    evidence_spans: list[EvidenceSpan],
    segment_rows: list[dict[str, Any]],
    source_metadata: dict[str, Any],
) -> ParticipantRegistry:
    evidence_by_id = {item.evidence_id: item for item in evidence_spans}
    requested_status = _normalized_diarization_status(
        source_metadata.get("diarization_status")
    )
    provenance_value = source_metadata.get("speaker_provenance")
    provenance = provenance_value if isinstance(provenance_value, dict) else {}
    provenance_status = str(provenance.get("status") or "").strip().casefold()
    reported_count_value = source_metadata.get("num_speakers")
    reported_count = (
        reported_count_value
        if isinstance(reported_count_value, int)
        and not isinstance(reported_count_value, bool)
        and reported_count_value > 0
        else None
    )
    source_speakers = list(
        dict.fromkeys(
            str(row["speaker"])
            for row in segment_rows
            if row.get("speaker") is not None
        )
    )
    degraded_reasons = _normalized_reason_list(
        source_metadata.get("diarization_degraded_reasons")
    )
    fallback_reason = _normalize_text(
        str(source_metadata.get("diarization_fallback_reason") or "")
    )
    if fallback_reason:
        degraded_reasons.append(fallback_reason)

    artifact_verified = provenance.get("artifact_verified") is True
    model_revision = str(provenance.get("model_revision") or "").strip().casefold()
    revision_verified = re.fullmatch(r"[0-9a-f]{40}", model_revision) is not None
    provenance_count = provenance.get("speaker_count")
    assignment_method = str(provenance.get("assignment_method") or "").strip().casefold()
    method_used = str(
        provenance.get("method_used")
        or source_metadata.get("diarization_method_used")
        or ""
    ).strip().casefold()
    audio_integrity_status = str(
        source_metadata.get("audio_integrity_status") or ""
    ).strip().casefold()
    degraded_flag = source_metadata.get("degraded") is True
    has_diarization = source_metadata.get("has_diarization")
    trusted_diarization = (
        requested_status == "success"
        and provenance_status == "success"
        and reported_count == len(source_speakers)
        and reported_count is not None
        and provenance_count == reported_count
        and artifact_verified
        and revision_verified
        and not provenance.get("load_error")
        and assignment_method not in {"", "none"}
        and method_used not in {"", "none"}
        and audio_integrity_status == "verified"
        and not degraded_flag
        and not degraded_reasons
        and has_diarization is not False
    )
    effective_status = requested_status
    if requested_status == "success" and not trusted_diarization:
        effective_status = "degraded"
        if provenance_status != "success":
            degraded_reasons.append("speaker provenance did not confirm success")
        if reported_count != len(source_speakers) or reported_count is None:
            degraded_reasons.append("reported speaker count does not match source clusters")
        if provenance_count != reported_count:
            degraded_reasons.append("speaker provenance count does not match reported count")
        if not artifact_verified:
            degraded_reasons.append("diarization artifact was not verified")
        if not revision_verified:
            degraded_reasons.append("diarization model revision was not verified")
        if provenance.get("load_error"):
            degraded_reasons.append("diarization provenance contains a load error")
        if assignment_method in {"", "none"}:
            degraded_reasons.append("speaker assignment method was not verified")
        if method_used in {"", "none"}:
            degraded_reasons.append("diarization method was not verified")
        if audio_integrity_status != "verified":
            degraded_reasons.append("audio integrity was not verified")
        if degraded_flag:
            degraded_reasons.append("transcription result marked diarization degraded")
        if has_diarization is False:
            degraded_reasons.append("transcription result did not confirm diarization")
    degraded_reasons = list(dict.fromkeys(degraded_reasons))

    person_records: list[dict[str, Any]] = []
    self_names_by_speaker: dict[str, set[str]] = {}
    for entity in entities:
        if entity.entity_type != "person" or entity.verification_status == "rejected":
            continue
        display_name = _normalize_text(entity.value)
        if not display_name or display_name.casefold() in _GENERIC_PERSON_VALUES:
            continue
        entity_evidence = [
            evidence_by_id[evidence_id]
            for evidence_id in entity.evidence_ids
            if evidence_id in evidence_by_id
        ]
        self_evidence = [
            evidence
            for evidence in entity_evidence
            if _is_self_identification(evidence.quote, display_name)
        ]
        self_speakers = {
            evidence.speaker_id
            for evidence in self_evidence
            if evidence.speaker_id is not None
        }
        for speaker_id in self_speakers:
            self_names_by_speaker.setdefault(speaker_id, set()).add(
                display_name.casefold()
            )
        person_records.append(
            {
                "entity": entity,
                "display_name": display_name,
                "entity_evidence": entity_evidence,
                "self_evidence": self_evidence,
                "self_speakers": self_speakers,
            }
        )

    participants: list[ParticipantReference] = []
    bound_speakers: set[str] = set()
    for record in person_records:
        entity = record["entity"]
        display_name = record["display_name"]
        self_evidence = record["self_evidence"]
        self_speakers = record["self_speakers"]
        identity_basis: ParticipantIdentityBasis = (
            "self_identified"
            if self_evidence and trusted_diarization
            else "source_attributed"
        )
        conflict = any(
            len(self_names_by_speaker.get(speaker_id, set())) > 1
            for speaker_id in self_speakers
        ) or len(self_speakers) > 1
        can_bind_speaker = (
            trusted_diarization
            and identity_basis == "self_identified"
            and len(self_speakers) == 1
            and not conflict
        )
        source_speaker_ids = sorted(self_speakers) if can_bind_speaker else []
        bound_speakers.update(source_speaker_ids)
        if self_evidence and trusted_diarization and not can_bind_speaker:
            public_actor_label = f"người tự giới thiệu là {display_name}"
            allowed_reference_forms = [public_actor_label]
            withheld_reason = (
                "identity_conflict"
                if conflict
                else "diarization_degraded"
                if effective_status == "degraded"
                else "diarization_unavailable"
            )
            binding_state: SpeakerBindingState = (
                "degraded_unresolved"
                if effective_status == "degraded"
                else "unavailable"
            )
        elif identity_basis == "source_attributed":
            public_actor_label = f"người được nhắc đến là {display_name}"
            allowed_reference_forms = [public_actor_label]
            withheld_reason = None
            binding_state = "not_applicable"
        else:
            public_actor_label = display_name
            allowed_reference_forms = [display_name]
            withheld_reason = None
            binding_state = (
                "verified_cluster" if can_bind_speaker else "not_applicable"
            )

        grounded_roles: list[GroundedParticipantRole] = []
        role = _normalize_text(entity.role or "")
        if role and role.casefold() not in _GENERIC_PARTICIPANT_ROLES:
            role_matches = [
                (evidence.evidence_id, surfaces)
                for evidence in record["entity_evidence"]
                if not can_bind_speaker
                or evidence.speaker_id in source_speaker_ids
                for surfaces in [
                    _explicit_role_surfaces(evidence.quote, display_name, role)
                ]
                if surfaces
            ]
            role_evidence_ids = [evidence_id for evidence_id, _ in role_matches]
            if role_evidence_ids:
                grounded_roles.append(
                    GroundedParticipantRole(
                        role_id=_stable_id("role", entity.entity_id, role),
                        label=role,
                        role_type=_participant_role_type(role),
                        basis="explicit_named_relation",
                        evidence_ids=role_evidence_ids,
                    )
                )
                allowed_reference_forms.extend(
                    surface
                    for _evidence_id, surfaces in role_matches
                    for surface in surfaces
                )
        if identity_basis == "source_attributed" and any(
            item.role_type == "conversation_role" for item in grounded_roles
        ):
            identity_basis = "conversation_role"

        participant_evidence_ids = list(entity.evidence_ids)
        if can_bind_speaker:
            participant_evidence_ids = [
                evidence.evidence_id
                for evidence in evidence_spans
                if evidence.speaker_id in source_speaker_ids
            ]
        participants.append(
            ParticipantReference(
                participant_id=_stable_id(
                    "participant",
                    entity.entity_id,
                    identity_basis,
                    *source_speaker_ids,
                ),
                participant_kind=(
                    "speaker"
                    if identity_basis == "self_identified"
                    else "mentioned_person"
                ),
                source_speaker_ids=source_speaker_ids,
                speaker_binding_state=binding_state,
                entity_id=entity.entity_id,
                display_name=display_name,
                grounded_roles=grounded_roles,
                identity_basis=identity_basis,
                public_actor_label=public_actor_label,
                allowed_reference_forms=list(dict.fromkeys(allowed_reference_forms)),
                withheld_identity_reason=withheld_reason,
                attribution_required=(
                    identity_basis in {"source_attributed", "conversation_role"}
                    or not can_bind_speaker
                ),
                verification_status=(
                    "human_verified"
                    if entity.verification_status == "human_verified"
                    else "unverified"
                ),
                evidence_ids=participant_evidence_ids,
            )
        )

    if trusted_diarization:
        for speaker_index, speaker_id in enumerate(source_speakers):
            if speaker_id in bound_speakers:
                continue
            evidence_ids = [
                evidence.evidence_id
                for evidence in evidence_spans
                if evidence.speaker_id == speaker_id
            ]
            public_actor_label = _anonymous_actor_label(speaker_index)
            participants.append(
                ParticipantReference(
                    participant_id=_stable_id("participant", "speaker", speaker_id),
                    participant_kind="speaker",
                    source_speaker_ids=[speaker_id],
                    speaker_binding_state="verified_cluster",
                    identity_basis="anonymous",
                    public_actor_label=public_actor_label,
                    allowed_reference_forms=[public_actor_label],
                    withheld_identity_reason="insufficient_relation_evidence",
                    evidence_ids=evidence_ids,
                )
            )
    else:
        unresolved_groups: dict[tuple[Any, ...], list[str]] = {}
        for evidence in evidence_spans:
            group_key = (
                ("segment", evidence.segment_index)
                if evidence.source_type == "transcript_segment"
                else (
                    "transcript",
                    evidence.char_start,
                    evidence.char_end,
                )
            )
            unresolved_groups.setdefault(group_key, []).append(evidence.evidence_id)
        for group_key, unresolved_evidence_ids in unresolved_groups.items():
            participants.append(
                ParticipantReference(
                    participant_id=_stable_id(
                        "participant",
                        "unresolved",
                        effective_status,
                        *group_key,
                    ),
                    participant_kind="speaker",
                    source_speaker_ids=[],
                    speaker_binding_state=(
                        "degraded_unresolved"
                        if effective_status == "degraded"
                        else "unavailable"
                    ),
                    identity_basis="anonymous",
                    public_actor_label="một người tham gia",
                    allowed_reference_forms=["một người tham gia"],
                    withheld_identity_reason=(
                        "diarization_degraded"
                        if effective_status == "degraded"
                        else "diarization_unavailable"
                    ),
                    evidence_ids=unresolved_evidence_ids,
                )
            )

    return ParticipantRegistry(
        source_metadata_sha256=participant_source_metadata_sha256(source_metadata),
        diarization_status=effective_status,
        speaker_count_release_status=(
            "verified" if trusted_diarization else "withheld"
        ),
        verified_speaker_count=(len(source_speakers) if trusted_diarization else None),
        degraded_reasons=degraded_reasons,
        participants=participants,
    )


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
    """Render the verified sentence drafts without exposing their source bindings."""

    rendered = []
    for sentence in sentences:
        text = (
            sentence.text
            if isinstance(sentence, GroundedSummarySentence)
            else str(sentence["text"])
        )
        normalized_text = _normalize_text(text)
        if normalized_text and normalized_text not in rendered:
            rendered.append(normalized_text)
    return " ".join(rendered).strip()


_SUMMARY_TOKEN_PATTERN = re.compile(
    r"https?://\S+|[\w.+%-]+@[\w.-]+|[\wÀ-ỹ]+(?:[-_/.:][\wÀ-ỹ]+)*",
    re.IGNORECASE,
)
_SUMMARY_CONNECTIVE_TOKENS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "các",
    "cho",
    "có",
    "của",
    "đề",
    "đã",
    "đồng",
    "được",
    "file",
    "ghi",
    "giữa",
    "gồm",
    "là",
    "liên",
    "lại",
    "một",
    "nên",
    "này",
    "những",
    "nội",
    "nêu",
    "quan",
    "qua",
    "sau",
    "thời",
    "theo",
    "thể",
    "thông",
    "tin",
    "trao",
    "trình",
    "trong",
    "trên",
    "từ",
    "tại",
    "và",
    "về",
    "báo",
    "bên",
    "cáo",
    "cập",
    "cụ",
    "cuộc",
    "dung",
    "đó",
    "đổi",
    "hiện",
    "mô",
    "nghe",
    "ngoài",
    "nhắc",
    "rằng",
    "ra",
    "tiếp",
    "tục",
    "việc",
    "còn",
    "cũng",
    "như",
    "nhiên",
    "để",
    "nhằm",
    "đơn",
    "vị",
    "phòng",
    "lực",
    "lượng",
    "đặc",
    "biệt",
    "mặc",
    "dù",
    "nhưng",
    "đều",
    "chung",
    "phận",
    "mảng",
    "từng",
    "tuy",
    "trước",
    "hướng",
    "tới",
}
_FUTURE_MARKERS = {
    "sẽ",
    "dự kiến",
    "dự tính",
    "dự định",
    "định",
    "chuẩn bị",
    "sắp",
}
_COMPLETED_MARKERS = {"đã", "vừa", "xong", "hoàn tất", "completed"}
_NEGATION_MARKERS = {"không", "chưa", "chẳng", "không có", "not", "never"}
_UNCERTAINTY_MARKERS = {
    "có thể",
    "có lẽ",
    "dường như",
    "nghi",
    "chưa rõ",
    "possibly",
    "maybe",
    "uncertain",
}
_UNCERTAINTY_DISCOURSE = re.compile(r"\bcó\s+thể\s+nói\b", re.IGNORECASE)
_REPORTING_MARKERS = {
    "cáo buộc",
    "cho biết",
    "cho rằng",
    "khẳng định",
    "khai",
    "kể",
    "nghi ngờ",
    "nhắn",
    "nói",
    "phản ánh",
    "phủ nhận",
    "thông báo",
    "thừa nhận",
    "theo lời",
    "tiết lộ",
    "trình bày",
    "tố cáo",
    "tố giác",
}
_CONDITIONAL_MARKERS = {"nếu", "giả sử", "trong trường hợp"}
_SUMMARY_CLAUSE_SPLIT = re.compile(
    r"\s*;\s*|(?<=[.!?])\s+|,\s+|"
    r"\s+(?:và|nhưng(?:\s+mà)?|còn)\s+"
    r"(?=(?:không|chưa|chẳng|chả|đừng|đã|vừa|sẽ|sắp)\b)|"
    r"\s+(?=(?:vậy\s+thì|theo\s+quy\s+định|ngay\s+sau)\b)|"
    r"\s+(?=(?:rồi\s+)?(?:chị|anh|em|bên\s+\w+|khách\s+sạn)\s+"
    r"(?:không|chưa)\b)",
    re.IGNORECASE,
)
_SUMMARY_COORDINATED_PREDICATE = re.compile(
    r"\s+(?:và|nhưng(?:\s+mà)?|còn|sau\s+đó|đồng\s+thời)\s+(\S+)",
    re.IGNORECASE,
)
_SUMMARY_LOW_VALUE_COURTESY_CLAUSE = re.compile(
    r"\b(?:cảm\s+ơn|chúc\s+.+(?:tốt\s+lành|vui\s+vẻ))\b",
    re.IGNORECASE,
)
_SUMMARY_ACTOR_STARTS = {
    "anh",
    "bên",
    "chị",
    "em",
    "họ",
    "khách",
    "mình",
    "người",
    "nhân viên",
    "tôi",
    "ta",
    "đối tượng",
}
_SUMMARY_ALIGNMENT_GENERIC_TOKENS = {
    "ạ",
    "bên",
    "dạ",
    "gia",
    "hai",
    "khách",
    "người",
    "nhất",
    "sạn",
    "tham",
    "thứ",
    "vâng",
}
_SUMMARY_PREDICATE_MARKER = re.compile(
    r"\b(?:là|có|còn|gồm|bao\s+gồm|được|bị|phải|muốn|cần|"
    r"lưu\s+ý|đọc|giữ|sử\s+dụng|ở|lưu\s+trú)\b",
    re.IGNORECASE,
)
_SUMMARY_FORBIDDEN_METADATA = re.compile(
    r"(?:\[(?:audio[\s_-]*offset|offset[\s_-]+(?:âm|am)[\s_-]+thanh)[^\]]*\])"
    r"|(?:\b(?:evidence(?:_ids?)?|fact_id|entity_id|event_id|relationship_id|"
    r"segment(?:_id|_index)?|speaker(?:_id)?|source_sha256|quote_sha256|"
    r"content_sha256|model_id|prompt_version)\s*:)",
    re.IGNORECASE,
)
_SUMMARY_PHONE_SURFACE = re.compile(
    r"(?<!\d)(?:\+?84|0)(?:[\s.\-]*\d){8,10}(?!\d)",
    re.IGNORECASE,
)
_SAFE_PARAPHRASE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\btrong\s+khoảng\s+thời\s+gian\b", re.IGNORECASE),
        "",
    ),
    (re.compile(r"\bcung\s+cấp\b", re.IGNORECASE), ""),
    (re.compile(r"\btrùng\s+với\b", re.IGNORECASE), "đúng"),
    (re.compile(r"\bmiễn\s+phí\b", re.IGNORECASE), "free"),
    (re.compile(r"\bdùng\b", re.IGNORECASE), "sử dụng"),
    (
        re.compile(r"\bđể\s+(chị|anh|em|khách)\s+chuyển\s+khoản\b", re.IGNORECASE),
        r"\1 sẽ chuyển khoản",
    ),
    (re.compile(r"\bsẽ\s+phục\s+vụ\b", re.IGNORECASE), "được phục vụ"),
    (
        re.compile(r"\bcăn\s+cước(?:\s+công\s+dân)?\b", re.IGNORECASE),
        "căn cứ công dân",
    ),
    (re.compile(r"\bquy\s+trả\b", re.IGNORECASE), "quỷ trả"),
    (
        re.compile(
            r"\bmột(?=\s+(?:người|phòng|suất|vé|đêm|ngày|tháng|năm|giờ|phút|lần|cuộc)\b)",
            re.IGNORECASE,
        ),
        "1",
    ),
    (re.compile(r"\bc[oó]\s+k[eế]\s+ho[aạ]ch\b", re.IGNORECASE), "sẽ"),
    (re.compile(r"\bdự\s+(?:kiến|tính|định)\b", re.IGNORECASE), "sẽ"),
    (re.compile(r"\bcho\s+biết\b", re.IGNORECASE), "nói"),
    (re.compile(r"\bnhất\s+trí\b", re.IGNORECASE), "đồng ý"),
    (re.compile(r"\bbao\s+gồm\b", re.IGNORECASE), "gồm"),
    (re.compile(r"\bcũng\s+như\b", re.IGNORECASE), "và"),
    (
        re.compile(r"\b(?:quanh|doanh)\s+nghiệp\b", re.IGNORECASE),
        "doanh nghiệp",
    ),
    (
        re.compile(r"\bhướng\s+(?:vận|vẫn|dẫn)\b", re.IGNORECASE),
        "hướng dẫn",
    ),
    (re.compile(r"\btoàn\s+(?:vân|dân)\b", re.IGNORECASE), "toàn dân"),
    (re.compile(r"\bnguyện\s+(?:dọng|vọng)\b", re.IGNORECASE), "nguyện vọng"),
    (re.compile(r"\b(?:chịp|kịp)\s+thời\b", re.IGNORECASE), "kịp thời"),
    (
        re.compile(r"\bkinh\s+tế\s+(?:đến\s+|-\s*)?xã\s+hội\b", re.IGNORECASE),
        "kinh tế xã hội",
    ),
    (re.compile(r"\bbám\s+sát\b", re.IGNORECASE), "bám"),
    (re.compile(r"\b(?:gian|văn)\s+bản\b", re.IGNORECASE), "văn bản"),
    (re.compile(r"\b(?:ký|kiến)\s+nghị\b", re.IGNORECASE), "kiến nghị"),
    (re.compile(r"\bcấp\s+(?:quỹ|ủy)\b", re.IGNORECASE), "cấp ủy"),
    (re.compile(r"\b(?:tinh\s+quanh|tình\s+hình)\b", re.IGNORECASE), "tình hình"),
    (
        re.compile(r"\b(?:sông\s+sông\s+như|song\s+song\s+với)\s+đó\b", re.IGNORECASE),
        "song song với đó",
    ),
    (re.compile(r"\bgiữ\s+giữ\b", re.IGNORECASE), "giữ vững"),
    (re.compile(r"\bgiữ\s+dưỡng\b", re.IGNORECASE), "giữ vững"),
    (re.compile(r"\bdưỡng\s+mạnh\b", re.IGNORECASE), "vững mạnh"),
    (re.compile(r"\btheo\s+dõi\s+tình\s+hình\b", re.IGNORECASE), "nắm tình hình"),
    (re.compile(r"\bcác\s+loại\s+tội\s+phạm\b", re.IGNORECASE), "tội phạm"),
    (re.compile(r"\bduy\s+trì\b", re.IGNORECASE), "giữ"),
    (
        re.compile(r"\bcác\s+hoạt\s+động\s+(?:trên|của\s+phòng)\b", re.IGNORECASE),
        "phòng",
    ),
)


def _summary_tokens(value: str) -> list[str]:
    return [token.casefold() for token in _SUMMARY_TOKEN_PATTERN.findall(value)]


def _canonicalize_safe_paraphrase(value: str) -> str:
    canonical = _normalize_text(value)
    for pattern, replacement in _SAFE_PARAPHRASE_PATTERNS:
        canonical = pattern.sub(replacement, canonical)
    return canonical


def _contains_marker(value: str, markers: set[str]) -> bool:
    normalized = _normalize_text(value).casefold()
    return any(
        re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", normalized) is not None
        for marker in markers
    )


def _contains_uncertainty_marker(value: str) -> bool:
    normalized = _UNCERTAINTY_DISCOURSE.sub("", _normalize_text(value))
    return _contains_marker(normalized, _UNCERTAINTY_MARKERS)


def _contains_reporting_marker(value: str) -> bool:
    normalized = _UNCERTAINTY_DISCOURSE.sub("", _normalize_text(value)).casefold()
    if re.search(r"(?<!đảm )(?<!\w)bảo(?!\s+(?:đảm|vệ))(?!\w)", normalized):
        return True
    return _contains_marker(normalized, _REPORTING_MARKERS)


def _contains_future_marker(value: str) -> bool:
    normalized = re.sub(
        r"\b(?:(?:ổn|quy|nhận|xác)\s+định|sắp\s+(?:xếp|đặt|hàng))\b",
        "",
        _normalize_text(value),
        flags=re.IGNORECASE,
    )
    return _contains_marker(normalized, _FUTURE_MARKERS)


def _contains_completed_marker(value: str) -> bool:
    normalized = re.sub(
        r"\bvừa\s+(?:đủ|phải|vặn|tầm|lúc)\b",
        "",
        _normalize_text(value),
        flags=re.IGNORECASE,
    )
    return _contains_marker(normalized, _COMPLETED_MARKERS)


def _contains_negation_marker(value: str) -> bool:
    normalized = re.sub(
        r"\b(?:không\s+(?:gian|khí|quân)|chưa\s+chắc)\b",
        "",
        _normalize_text(value),
        flags=re.IGNORECASE,
    )
    return _contains_marker(normalized, _NEGATION_MARKERS)


def _capability_paraphrase_matches(source: str, candidate: str) -> bool:
    combined = f"{source} {candidate}"
    if re.search(
        r"\b(?:miễn\s+phí|free|wifi|dịch\s+vụ|tiện\s+ích|cho\s+phép)\b",
        combined,
        re.IGNORECASE,
    ) is None:
        return False
    source_match = re.search(
        r"\bcó\s+thể\s+([\wÀ-ỹ]+)",
        source,
        re.IGNORECASE,
    )
    candidate_match = re.search(
        r"\b(?:được(?:\s+phép)?)\s+([\wÀ-ỹ]+)",
        candidate,
        re.IGNORECASE,
    )
    return bool(
        source_match
        and candidate_match
        and source_match.group(1).casefold() == candidate_match.group(1).casefold()
    )


def _split_coordinated_predicates(value: str) -> list[str]:
    boundaries: list[int] = []
    for match in _SUMMARY_COORDINATED_PREDICATE.finditer(value):
        actor = match.group(1).strip(".,;:!?()[]{}\"'")
        if not actor:
            continue
        if actor[0].isupper() or actor.casefold() in _SUMMARY_ACTOR_STARTS:
            boundaries.append(match.start())
    if not boundaries:
        return [value]
    result: list[str] = []
    cursor = 0
    for boundary in boundaries:
        result.append(value[cursor:boundary])
        cursor = boundary
    result.append(value[cursor:])
    return result


def _summary_clauses(value: str) -> list[str]:
    protected_value = re.sub(
        r"\b(?:[A-ZĐ]\.){2,}",
        lambda match: match.group(0).replace(".", "__abbr_dot__"),
        value,
    )
    clauses = []
    for item in _SUMMARY_CLAUSE_SPLIT.split(protected_value):
        clauses.extend(
            _normalize_text(part.replace("__abbr_dot__", ".")).strip(" ,;:.!?")
            for part in _split_coordinated_predicates(item)
        )
    return [item for item in clauses if item]


def _summary_content_tokens(value: str) -> set[str]:
    return {
        token
        for token in _summary_tokens(value)
        if len(token) > 1 and token not in _SUMMARY_CONNECTIVE_TOKENS
    }


def aligned_summary_clause(text: str, source_text: str) -> str:
    """Return the candidate clause with the strongest lexical source alignment."""

    clauses = _summary_clauses(text) or [_normalize_text(text)]
    source_tokens = _summary_content_tokens(source_text)
    source_informative_tokens = source_tokens.difference(
        _SUMMARY_ALIGNMENT_GENERIC_TOKENS
    )
    source_actions = set(extract_semantic_action_sequence(source_text))
    source_roles = extract_semantic_roles(source_text)

    def role_tokens(value: str | None) -> set[str]:
        if not value:
            return set()
        return _summary_content_tokens(value).difference(
            {
                "có",
                "dự",
                "giả",
                "không",
                "nếu",
                "sẽ",
                "sắp",
                "tính",
                "định",
                "kiến",
                "trường",
                "hợp",
            }
        )

    source_actor_tokens = role_tokens(source_roles.actor)
    source_target_tokens = role_tokens(source_roles.object).union(
        role_tokens(source_roles.recipient)
    )

    def alignment_key(clause: str) -> tuple[int, int, int, int, int, int]:
        candidate_tokens = _summary_content_tokens(clause)
        candidate_actions = set(extract_semantic_action_sequence(clause))
        candidate_roles = extract_semantic_roles(clause)
        candidate_actor_tokens = role_tokens(candidate_roles.actor)
        candidate_target_tokens = role_tokens(candidate_roles.object).union(
            role_tokens(candidate_roles.recipient)
        )
        actor_overlap = len(source_actor_tokens.intersection(candidate_actor_tokens))
        target_overlap = len(source_target_tokens.intersection(candidate_target_tokens))
        return (
            int(bool(actor_overlap) and bool(target_overlap)),
            actor_overlap + target_overlap,
            len(source_actions.intersection(candidate_actions)),
            len(
                source_informative_tokens.intersection(
                    candidate_tokens.difference(_SUMMARY_ALIGNMENT_GENERIC_TOKENS)
                )
            ),
            len(source_tokens.intersection(candidate_tokens)),
            -len(_summary_tokens(clause)),
        )

    return max(
        clauses,
        key=alignment_key,
    )


def _clauses_materially_align(candidate_clause: str, source_clause: str) -> bool:
    source_tokens = _summary_content_tokens(source_clause)
    if not source_tokens:
        return True
    required_overlap = min(3 if len(source_tokens) >= 4 else 2, len(source_tokens))
    return (
        len(source_tokens.intersection(_summary_content_tokens(candidate_clause)))
        >= required_overlap
    )


def _clauses_strongly_align(candidate_clause: str, source_clause: str) -> bool:
    source_tokens = _summary_content_tokens(source_clause).difference(
        _SUMMARY_ALIGNMENT_GENERIC_TOKENS
    )
    candidate_tokens = _summary_content_tokens(candidate_clause).difference(
        _SUMMARY_ALIGNMENT_GENERIC_TOKENS
    )
    if not source_tokens:
        return False
    source_actions = set(extract_semantic_action_sequence(source_clause))
    candidate_actions = set(extract_semantic_action_sequence(candidate_clause))
    if source_actions.intersection(candidate_actions):
        source_roles = extract_semantic_roles(source_clause)
        candidate_roles = extract_semantic_roles(candidate_clause)

        def comparable_role_tokens(value: str | None) -> set[str]:
            if not value:
                return set()
            return _summary_content_tokens(value).difference(
                {
                    "có",
                    "dự",
                    "giả",
                    "không",
                    "nếu",
                    "sẽ",
                    "sắp",
                    "tính",
                    "định",
                    "kiến",
                    "trường",
                    "hợp",
                }
            )

        source_actor = comparable_role_tokens(source_roles.actor)
        candidate_actor = comparable_role_tokens(candidate_roles.actor)
        source_target = comparable_role_tokens(source_roles.object).union(
            comparable_role_tokens(source_roles.recipient)
        )
        candidate_target = comparable_role_tokens(candidate_roles.object).union(
            comparable_role_tokens(candidate_roles.recipient)
        )
        actor_aligned = bool(source_actor.intersection(candidate_actor))
        target_aligned = not source_target or bool(
            source_target.intersection(candidate_target)
        )
        if actor_aligned and target_aligned:
            return True
    overlap = len(source_tokens.intersection(candidate_tokens))
    required_overlap = min(3 if len(source_tokens) >= 4 else 2, len(source_tokens))
    return overlap >= required_overlap and overlap * 3 >= len(source_tokens) * 2


_REPORTING_PREFIX = re.compile(
    r"^(?:qua|theo)\s+(?:nội\s+dung|thông\s+tin)(?:\s+(?:nghe|ghi)\s+được)?\s*[:,]\s*",
    re.IGNORECASE,
)
_ACTOR_REPORTING_VERB = re.compile(
    r"^(?P<actor>.+?)\s+(?:cho\s+biết|nêu|xác\s+nhận|khẳng\s+định|nói)\s+",
    re.IGNORECASE,
)


def _strip_reporting_prefix(value: str) -> str:
    return _REPORTING_PREFIX.sub("", _normalize_text(value), count=1)


def _strip_added_actor_reporting_verb(value: str) -> str:
    return _ACTOR_REPORTING_VERB.sub(r"\g<actor> ", value, count=1)


def _is_ordered_subsequence(source: tuple[str, ...], candidate: tuple[str, ...]) -> bool:
    if not source:
        return True
    cursor = 0
    for token in candidate:
        if token == source[cursor]:
            cursor += 1
            if cursor == len(source):
                return True
    return False


def _validate_source_relation_alignment(
    text: str,
    evidence_quotes: list[str],
    *,
    owner: str,
) -> None:
    for evidence_quote in evidence_quotes:
        for source_clause in _summary_clauses(evidence_quote) or [evidence_quote]:
            candidate_clause = aligned_summary_clause(text, source_clause)
            if not _clauses_materially_align(candidate_clause, source_clause):
                continue
            normalized_source = _strip_reporting_prefix(source_clause)
            normalized_candidate = _strip_reporting_prefix(candidate_clause)
            if (
                _contains_reporting_marker(candidate_clause)
                and not _contains_reporting_marker(source_clause)
            ):
                normalized_candidate = _strip_added_actor_reporting_verb(
                    normalized_candidate
                )
            source_roles = extract_semantic_roles(normalized_source)
            source_actions = extract_semantic_action_sequence(normalized_source)
            candidate_actions = extract_semantic_action_sequence(normalized_candidate)
            if (
                source_actions
                and source_roles.complete
                and not source_roles.ambiguous
                and not _is_ordered_subsequence(
                source_actions,
                candidate_actions,
                )
            ):
                raise KnowledgeGroundingError(f"{owner} changes or drops source actions")

            if not source_roles.complete or source_roles.ambiguous:
                continue
            candidate_roles = extract_semantic_roles(normalized_candidate)
            if not candidate_roles.complete or candidate_roles.ambiguous:
                raise KnowledgeGroundingError(f"{owner} drops source semantic roles")
            for field in ("actor", "action", "object", "recipient"):
                source_value = getattr(source_roles, field)
                candidate_value = getattr(candidate_roles, field)
                if field == "action":
                    compatible = source_value == candidate_value
                elif source_value is None:
                    compatible = True
                elif candidate_value is None:
                    compatible = False
                else:
                    source_tokens = set(str(source_value).split())
                    candidate_tokens = set(str(candidate_value).split())
                    compatible = source_tokens.issubset(candidate_tokens) or (
                        candidate_tokens.issubset(source_tokens)
                    )
                if not compatible:
                    raise KnowledgeGroundingError(
                        f"{owner} changes source {field} binding"
                    )


def _validate_source_modality_alignment(
    text: str,
    evidence_quotes: list[str],
    *,
    owner: str,
) -> None:
    for evidence_quote in evidence_quotes:
        for source_clause in _summary_clauses(evidence_quote) or [evidence_quote]:
            if _SUMMARY_LOW_VALUE_COURTESY_CLAUSE.search(source_clause):
                continue
            if not _summary_content_tokens(source_clause):
                continue
            candidate_clause = aligned_summary_clause(text, source_clause)
            if not _clauses_materially_align(candidate_clause, source_clause):
                continue
            source_future = _contains_future_marker(source_clause)
            source_completed = _contains_completed_marker(source_clause)
            source_negated = _contains_negation_marker(source_clause)
            source_uncertain = _contains_uncertainty_marker(source_clause)
            source_reported = _contains_reporting_marker(source_clause)
            source_conditional = _contains_marker(source_clause, _CONDITIONAL_MARKERS)

            candidate_future = _contains_future_marker(candidate_clause)
            candidate_completed = _contains_completed_marker(candidate_clause)
            candidate_negated = _contains_negation_marker(candidate_clause)
            candidate_uncertain = _contains_uncertainty_marker(candidate_clause)
            candidate_reported = _contains_reporting_marker(candidate_clause)
            candidate_conditional = _contains_marker(
                candidate_clause,
                _CONDITIONAL_MARKERS,
            )
            modality_changed = (
                source_future != candidate_future
                or source_completed != candidate_completed
                or source_negated != candidate_negated
                or source_uncertain != candidate_uncertain
                or source_reported and not candidate_reported
                or source_conditional != candidate_conditional
            )
            source_has_predicate = bool(
                extract_semantic_action_sequence(source_clause)
                or _SUMMARY_PREDICATE_MARKER.search(source_clause)
            )
            if not any(
                (
                    source_future,
                    source_completed,
                    source_negated,
                    source_uncertain,
                    source_reported,
                    source_conditional,
                )
            ) and not source_has_predicate:
                continue
            if modality_changed and not _clauses_strongly_align(
                candidate_clause,
                source_clause,
            ):
                continue

            if source_future != candidate_future or (
                source_future and candidate_completed
            ):
                raise KnowledgeGroundingError(
                    f"{owner} changes planned action modality"
                )
            if source_completed != candidate_completed or (
                source_completed and candidate_future
            ):
                raise KnowledgeGroundingError(
                    f"{owner} changes completed action modality"
                )
            if source_negated != candidate_negated:
                raise KnowledgeGroundingError(f"{owner} changes source negation")
            if source_uncertain != candidate_uncertain and not (
                source_uncertain
                and not candidate_uncertain
                and _capability_paraphrase_matches(source_clause, candidate_clause)
            ):
                raise KnowledgeGroundingError(f"{owner} changes source uncertainty")
            # Turning a direct utterance into attributed third-person prose is a
            # safe reporting transformation. Dropping attribution from an already
            # reported claim is not: that would promote hearsay into world truth.
            if source_reported and not candidate_reported:
                raise KnowledgeGroundingError(f"{owner} changes source attribution")
            if source_conditional != candidate_conditional:
                raise KnowledgeGroundingError(f"{owner} changes source conditionality")


def validate_grounded_summary_text(
    text: str,
    evidence_quotes: list[str],
    *,
    owner: str,
    allow_safe_paraphrase: bool = False,
    allowed_context_surfaces: list[str] | None = None,
) -> str:
    """Reject invented values, unsupported content, and modality-changing prose."""

    normalized_text = _normalize_text(text)
    evidence_text = _normalize_text(" ".join(evidence_quotes))
    if not normalized_text or not evidence_text:
        raise KnowledgeGroundingError(f"{owner} requires text and evidence")
    if _SUMMARY_FORBIDDEN_METADATA.search(normalized_text):
        raise KnowledgeGroundingError(f"{owner} exposes technical evidence metadata")

    alignment_text = (
        _canonicalize_safe_paraphrase(normalized_text)
        if allow_safe_paraphrase
        else normalized_text
    )
    alignment_quotes = (
        [_canonicalize_safe_paraphrase(quote) for quote in evidence_quotes]
        if allow_safe_paraphrase
        else evidence_quotes
    )
    alignment_evidence_text = _normalize_text(" ".join(alignment_quotes))
    evidence_tokens = set(_summary_tokens(alignment_evidence_text))
    candidate_tokens = _summary_tokens(alignment_text)
    allowed_context_tokens: set[str] = set()
    if allow_safe_paraphrase and allowed_context_surfaces:
        allowed_context = _canonicalize_safe_paraphrase(
            " ".join(allowed_context_surfaces)
        )
        allowed_context_tokens.update(_summary_tokens(allowed_context))
    protected_values = {
        token for token in candidate_tokens if any(char.isdigit() for char in token)
    }
    missing_value_set = protected_values - evidence_tokens - allowed_context_tokens
    evidence_phones = {
        "".join(char for char in match.group(0) if char.isdigit())
        for match in _SUMMARY_PHONE_SURFACE.finditer(alignment_evidence_text)
    }
    matched_phone_tokens: set[str] = set()
    for match in _SUMMARY_PHONE_SURFACE.finditer(alignment_text):
        digits = "".join(char for char in match.group(0) if char.isdigit())
        if digits in evidence_phones:
            phone_tokens = set(_summary_tokens(match.group(0)))
            matched_phone_tokens.update(phone_tokens)
            missing_value_set.difference_update(phone_tokens)
    missing_values = sorted(missing_value_set)
    if missing_values:
        raise KnowledgeGroundingError(
            f"{owner} contains identifiers or quantities absent from evidence"
        )

    allowed_tokens = set(evidence_tokens).union(
        matched_phone_tokens,
        allowed_context_tokens,
    )
    unsupported = sorted(
        {
            token
            for token in candidate_tokens
            if token not in allowed_tokens
            and token not in _SUMMARY_CONNECTIVE_TOKENS
            and len(token) > 1
        }
    )
    if unsupported:
        raise KnowledgeGroundingError(
            f"{owner} contains unsupported synthesis tokens: {', '.join(unsupported[:8])}"
        )

    _validate_source_modality_alignment(
        alignment_text,
        alignment_quotes,
        owner=owner,
    )
    _validate_source_relation_alignment(
        alignment_text,
        alignment_quotes,
        owner=owner,
    )
    return normalized_text


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
        speaker_value = _normalize_text(
            str(segment.get("speaker") or segment.get("speaker_id") or "")
        ) or None
        start_value = segment.get("start")
        end_value = segment.get("end")
        segment_source_hashes.append(
            SegmentSourceHash(
                segment_index=index,
                source_sha256=_sha256(text_value),
                start_seconds=start_value,
                end_seconds=end_value,
                speaker_id=speaker_value,
            )
        )
        if not text_value:
            continue
        segment_rows.append(
            {
                "index": index,
                "text": text_value,
                "start": start_value,
                "end": end_value,
                "speaker": speaker_value,
            }
        )

    evidence_by_key: dict[tuple[Any, ...], EvidenceSpan] = {}

    def segment_evidence(segment: dict[str, Any], quote: str) -> EvidenceSpan:
        folded_quote = quote.casefold()
        key = ("segment", segment["index"], folded_quote)
        if key not in evidence_by_key:
            evidence_by_key[key] = EvidenceSpan(
                evidence_id=_stable_id("ev", *key),
                source_type="transcript_segment",
                segment_index=segment["index"],
                start_seconds=segment["start"],
                end_seconds=segment["end"],
                speaker_id=segment["speaker"],
                quote=quote,
                quote_sha256=_sha256(quote),
                source_sha256=_sha256(segment["text"]),
            )
        return evidence_by_key[key]

    def transcript_evidence(quote: str) -> EvidenceSpan | None:
        folded_quote = quote.casefold()
        char_start = normalized_transcript.casefold().find(folded_quote)
        if char_start == -1:
            return None
        char_end = char_start + len(quote)
        key = ("transcript", char_start, char_end, folded_quote)
        if key not in evidence_by_key:
            evidence_by_key[key] = EvidenceSpan(
                evidence_id=_stable_id("ev", *key),
                source_type="transcript_text",
                char_start=char_start,
                char_end=char_end,
                quote=quote,
                quote_sha256=_sha256(quote),
                source_sha256=_sha256(normalized_transcript),
            )
        return evidence_by_key[key]

    def resolve_evidence(quote: str) -> list[str] | None:
        normalized_quote = _normalize_text(quote)
        if len(normalized_quote) < 1:
            return None
        folded_quote = normalized_quote.casefold()

        matching_segments = [
            segment
            for segment in segment_rows
            if folded_quote in segment["text"].casefold()
        ]
        if len(matching_segments) == 1:
            return [segment_evidence(matching_segments[0], normalized_quote).evidence_id]
        if len(matching_segments) > 1:
            evidence = transcript_evidence(normalized_quote)
            return [evidence.evidence_id] if evidence is not None else None

        for window_size in range(2, len(segment_rows) + 1):
            for start_index in range(0, len(segment_rows) - window_size + 1):
                end_index = start_index + window_size
                candidates = segment_rows[start_index:end_index]
                combined = _normalize_text(" ".join(item["text"] for item in candidates))
                if folded_quote not in combined.casefold():
                    continue
                return [
                    segment_evidence(segment, segment["text"]).evidence_id
                    for segment in candidates
                ]

        evidence = transcript_evidence(normalized_quote)
        return [evidence.evidence_id] if evidence is not None else None

    def require_evidence(quote: str, owner: str) -> list[str]:
        evidence_ids = resolve_evidence(quote)
        if evidence_ids is None:
            raise KnowledgeGroundingError(
                f"{owner} evidence quote is absent from transcript"
            )
        return evidence_ids

    def require_evidence_many(quotes: list[str], owner: str) -> list[str]:
        evidence_ids = [
            evidence_id
            for quote in quotes
            for evidence_id in require_evidence(quote, owner)
        ]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise KnowledgeGroundingError(
                f"{owner} evidence quotes resolve to duplicate evidence"
            )
        return evidence_ids

    summary_sentences: list[GroundedSummarySentence] = []
    for sentence in payload.summary_sentences:
        evidence_ids = require_evidence_many(
            sentence.evidence_quotes,
            f"summary sentence {sentence.draft_id}",
        )
        summary_sentences.append(
            GroundedSummarySentence(
                draft_id=sentence.draft_id,
                text=validate_grounded_summary_text(
                    sentence.text,
                    sentence.evidence_quotes,
                    owner=f"summary sentence {sentence.draft_id}",
                ),
                sentence_role=sentence.sentence_role,
                evidence_quotes=[
                    next(
                        span.quote
                        for span in evidence_by_key.values()
                        if span.evidence_id == evidence_id
                    )
                    for evidence_id in evidence_ids
                ],
                evidence_ids=evidence_ids,
            )
        )

    facts: list[KnowledgeFact] = []
    entities: list[KnowledgeEntity] = []
    events: list[KnowledgeEvent] = []
    relationships: list[KnowledgeRelationship] = []
    hypotheses: list[InvestigationHypothesis] = []
    seen_fact_ids: set[str] = set()
    seen_entity_ids: set[str] = set()
    entities_by_id: dict[str, KnowledgeEntity] = {}

    def add_fact(
        category: str,
        statement: str,
        evidence_quotes: list[str],
        *,
        actor: str | None = None,
        status: EpistemicStatus = "reported",
    ) -> None:
        normalized_statement = _normalize_text(statement)
        normalized_actor = _normalize_text(actor or "") or None
        if normalized_actor and not any(
            normalized_actor.casefold() in _normalize_text(quote).casefold()
            for quote in evidence_quotes
        ):
            raise KnowledgeGroundingError(
                f"fact {category} actor is absent from evidence"
            )
        evidence_ids = require_evidence_many(evidence_quotes, f"fact {category}")
        fact_id = _stable_id(
            "fact",
            category,
            normalized_actor,
            normalized_statement,
            status,
        )
        if fact_id in seen_fact_ids:
            return
        seen_fact_ids.add(fact_id)
        facts.append(
            KnowledgeFact(
                fact_id=fact_id,
                category=category,
                statement=normalized_statement,
                actor=normalized_actor,
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
        add_fact(
            "action",
            item.action,
            [item.evidence_quote],
            actor=item.actor,
            status=item.status,
        )
    for item in payload.decisions:
        add_fact(
            "decision",
            item.decision,
            [item.evidence_quote],
            actor=item.actor,
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
        if value is None:
            raise KnowledgeGroundingError(f"entity {entity_type} has no value")
        if (
            entity_type == "person"
            and _normalize_text(value).casefold() in _GENERIC_PERSON_VALUES
        ):
            return
        evidence_ids = require_evidence(item.evidence_quote, f"entity {entity_type}")
        if not _entity_value_is_supported(entity_type, value, item.evidence_quote):
            raise KnowledgeGroundingError(
                f"entity {entity_type} value is not supported by its evidence quote"
            )
        entity_id = _stable_id("entity", entity_type, value)
        if entity_id in seen_entity_ids:
            existing = entities_by_id[entity_id]
            existing.evidence_ids = list(
                dict.fromkeys([*existing.evidence_ids, *evidence_ids])
            )
            if existing.role != item.role:
                existing.role = None
            return
        seen_entity_ids.add(entity_id)
        entity = KnowledgeEntity(
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
            evidence_ids=evidence_ids,
        )
        entities.append(entity)
        entities_by_id[entity_id] = entity

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
        evidence_ids = require_evidence(item.evidence_quote, f"event {index}")
        events.append(
            KnowledgeEvent(
                event_id=_stable_id("event", index, item.description),
                description=item.description,
                time_text=item.time,
                actors=item.actors,
                location=item.location,
                status=item.status,
                evidence_ids=evidence_ids,
            )
        )

    for index, item in enumerate(payload.relationships):
        evidence_ids = require_evidence(item.evidence_quote, f"relationship {index}")
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
                evidence_ids=evidence_ids,
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
            evidence_ids = resolve_evidence(candidate["evidence_quote"])
            if evidence_ids is None:
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
                    evidence_ids=evidence_ids,
                )
            )
    else:
        withheld_high_risk = len(high_risk_candidates)

    # Evidence is materialized on demand by claims, entities, events and
    # participant references. Keep one source segment per speaker so a trusted
    # diarization registry can prove each cluster without registering unrelated
    # low-confidence/no-speech segments.
    referenced_speakers = {
        evidence.speaker_id
        for evidence in evidence_by_key.values()
        if evidence.speaker_id is not None
    }
    for segment in segment_rows:
        speaker_id = segment.get("speaker")
        if speaker_id is not None and speaker_id not in referenced_speakers:
            segment_evidence(segment, segment["text"])
            referenced_speakers.add(speaker_id)
    evidence_spans = list(evidence_by_key.values())
    participant_registry = _build_participant_registry(
        entities=entities,
        evidence_spans=evidence_spans,
        segment_rows=segment_rows,
        source_metadata=source_metadata,
    )

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
        evidence_spans=evidence_spans,
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
        participant_registry=participant_registry,
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
            "summary_projection_source": "grounded_summary_sentence_text",
            "compatibility": {
                "summary_source": "grounded_summary_sentence_text",
                "raw_model_summary_released": False,
                "projection_version": "summary-projection-v2",
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
            "grounded_model_sentence_text_released": True,
            "grounded_model_sentence_text_requires_grounding_gate": True,
            "final_envelope_revalidated": True,
            "legacy_coercion_in_provider_path": False,
            "per_claim_semantic_attestation_complete": False,
            "summary_release_authority": "withheld_pending_claim_attestation",
        },
    }
