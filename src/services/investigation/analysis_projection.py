"""Strict reference-only contract for released investigative analysis views."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from .contracts import (
    ConceptMention,
    EvidenceSpan,
    GroundedClaim,
    GroundedRelationship,
    Sha256Hex,
    StrictEnvelope,
    _ensure_unique,
    sha256_canonical_json,
)
from .reasoning_contracts import EvidenceBackedInsight, Hypothesis, VerificationAction


ANALYSIS_PROJECTION_VERSION: Literal[
    "investigation-analysis-projection-v1.1"
] = "investigation-analysis-projection-v1.1"
RELEASED_ANALYSIS_VERSION: Literal[
    "released-investigation-analysis-v1"
] = "released-investigation-analysis-v1"
RELEASED_ANALYSIS_AUTHORITY: Literal[
    "released_investigation_run"
] = "released_investigation_run"

SpeakerAssignmentState = Literal[
    "anonymous_cluster",
    "self_identified",
    "third_party_attributed",
    "human_verified",
    "ambiguous",
    "degraded",
    "unavailable",
]
ExactValueRole = Literal[
    "identifier",
    "money",
    "quantity",
    "date",
    "time",
    "datetime",
    "location",
    "other",
]
EventState = Literal[
    "planned",
    "ongoing",
    "completed",
    "denied",
    "reported",
    "conditional",
    "unknown",
]


def _require_exact_refs(
    refs: list[str] | None,
    available: Mapping[str, Any],
    label: str,
) -> None:
    expected = set(available)
    actual = set(refs or [])
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if extra:
            details.append(f"extra={','.join(extra)}")
        raise ValueError(f"{label} must cover the exact released set: {'; '.join(details)}")


def _require_subset(
    refs: list[str] | tuple[str, ...] | None,
    available: set[str],
    label: str,
) -> None:
    missing = sorted(set(refs or []) - available)
    if missing:
        raise ValueError(f"dangling {label}: {', '.join(missing)}")


def _ensure_sorted_unique(values: list[str], label: str) -> list[str]:
    _ensure_unique(values, label)
    if values != sorted(values):
        raise ValueError(f"{label} must use canonical sorted order")
    return values


class HashBoundAnalysisArtifact(StrictEnvelope):
    """Base for immutable projection companion records."""

    content_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def bind(cls, **payload: Any) -> Self:
        data = dict(payload)
        data["content_sha256"] = sha256_canonical_json(data)
        return cls.model_validate(data)

    @model_validator(mode="after")
    def validate_content_hash(self) -> "HashBoundAnalysisArtifact":
        payload = self.model_dump(
            mode="json",
            exclude={"content_sha256"},
            exclude_none=True,
        )
        if self.content_sha256 != sha256_canonical_json(payload):
            raise ValueError("content_sha256 must bind the canonical artifact")
        return self


class SourceSetProvenance(HashBoundAnalysisArtifact):
    source_set_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    source_revision_refs: list[str] = Field(min_length=1)
    authorization_scope_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_revision_refs")
    @classmethod
    def unique_source_revisions(cls, values: list[str]) -> list[str]:
        return _ensure_sorted_unique(values, "source revision refs")


class AnalysisQualityArtifact(HashBoundAnalysisArtifact):
    quality_id: str = Field(min_length=1)
    source_set_ref: str = Field(min_length=1)
    coverage_manifest_ref: str = Field(min_length=1)
    source_coverage_complete: bool
    source_quality_refs: list[str] = Field(min_length=1)
    asr_state: Literal["verified", "degraded", "unavailable", "not_evaluated"]
    diarization_state: Literal[
        "verified", "degraded", "unavailable", "not_evaluated"
    ]
    deterministic_fallback_used: bool
    release_ready: bool
    unresolved_evidence_refs: list[str] | None = None
    ambiguous_speaker_refs: list[str] | None = None
    withheld_item_refs: list[str] | None = None
    blocking_codes: list[str] | None = None

    @field_validator(
        "source_quality_refs",
        "unresolved_evidence_refs",
        "ambiguous_speaker_refs",
        "withheld_item_refs",
        "blocking_codes",
    )
    @classmethod
    def unique_quality_refs(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return _ensure_sorted_unique(values, "analysis quality references")

    @model_validator(mode="after")
    def validate_release_readiness(self) -> "AnalysisQualityArtifact":
        blockers_present = bool(self.blocking_codes or self.unresolved_evidence_refs)
        if self.release_ready and (
            not self.source_coverage_complete or blockers_present
        ):
            raise ValueError(
                "release-ready quality requires complete coverage and no blockers"
            )
        if not self.source_coverage_complete and not self.blocking_codes:
            raise ValueError("incomplete source coverage requires a blocking code")
        return self


class SpeakerAssignmentRecord(HashBoundAnalysisArtifact):
    speaker_assignment_id: str = Field(min_length=1)
    source_revision_id: str = Field(min_length=1)
    file_id: str = Field(min_length=1)
    diarization_revision_id: str | None = Field(default=None, min_length=1)
    local_speaker_id: str | None = Field(default=None, min_length=1)
    assignment_state: SpeakerAssignmentState
    claimed_identity_ref: str | None = Field(default=None, min_length=1)
    verified_identity_ref: str | None = Field(default=None, min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    human_review_artifact_ref: str | None = Field(default=None, min_length=1)

    @field_validator("evidence_refs")
    @classmethod
    def unique_evidence_refs(cls, values: list[str]) -> list[str]:
        return _ensure_sorted_unique(values, "speaker evidence refs")

    @model_validator(mode="after")
    def validate_assignment_state(self) -> "SpeakerAssignmentRecord":
        if self.assignment_state == "unavailable":
            if self.local_speaker_id is not None:
                raise ValueError("unavailable diarization cannot declare a speaker")
        elif self.local_speaker_id is None:
            raise ValueError("speaker assignment requires a file-local speaker ID")

        if self.assignment_state in {"self_identified", "third_party_attributed"}:
            if self.claimed_identity_ref is None:
                raise ValueError("attributed speaker identity requires a claim ref")
            if self.verified_identity_ref is not None:
                raise ValueError("attributed identity cannot be marked verified")
        elif self.claimed_identity_ref is not None:
            raise ValueError("claimed identity is only valid for attributed states")

        if self.assignment_state == "human_verified":
            if (
                self.verified_identity_ref is None
                or self.human_review_artifact_ref is None
            ):
                raise ValueError(
                    "human-verified identity requires identity and review artifacts"
                )
        elif self.verified_identity_ref is not None:
            raise ValueError("only human-verified assignments may bind identity")
        return self


class ExactValueRecord(HashBoundAnalysisArtifact):
    exact_value_id: str = Field(min_length=1)
    value_type: str = Field(min_length=1)
    semantic_role: ExactValueRole
    surface_exact: str = Field(min_length=1)
    normalized_value: str | None = Field(default=None, min_length=1)
    owner_state: Literal["explicit", "not_stated", "ambiguous"]
    owner_ref: str | None = Field(default=None, min_length=1)
    unit_state: Literal["explicit", "not_applicable", "not_stated", "ambiguous"]
    unit: str | None = Field(default=None, min_length=1)
    claim_refs: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    speaker_assignment_ref: str | None = Field(default=None, min_length=1)
    sensitivity: Literal["ordinary", "sensitive", "high_impact"]
    verification_artifact_ref: str = Field(min_length=1)

    @field_validator("claim_refs", "evidence_refs")
    @classmethod
    def unique_exact_value_refs(cls, values: list[str]) -> list[str]:
        return _ensure_sorted_unique(values, "exact value refs")

    @model_validator(mode="after")
    def validate_owner_and_unit(self) -> "ExactValueRecord":
        if (self.owner_state == "explicit") != (self.owner_ref is not None):
            raise ValueError("explicit owner state must match owner_ref presence")
        if (self.unit_state == "explicit") != (self.unit is not None):
            raise ValueError("explicit unit state must match unit presence")
        return self


class EventParticipantBinding(StrictEnvelope):
    role: str = Field(min_length=1)
    participant_ref: str = Field(min_length=1)
    participant_kind: Literal["concept", "claim"]


class GroundedEventRecord(HashBoundAnalysisArtifact):
    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    event_state: EventState
    claim_refs: list[str] = Field(min_length=1)
    participant_bindings: list[EventParticipantBinding] = Field(min_length=1)
    location_refs: list[str] | None = None
    exact_value_refs: list[str] | None = None
    described_time_value_refs: list[str] | None = None
    evidence_refs: list[str] = Field(min_length=1)

    @field_validator(
        "claim_refs",
        "location_refs",
        "exact_value_refs",
        "described_time_value_refs",
        "evidence_refs",
    )
    @classmethod
    def unique_event_refs(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return _ensure_sorted_unique(values, "event refs")

    @model_validator(mode="after")
    def validate_described_time_refs(self) -> "GroundedEventRecord":
        if self.described_time_value_refs and not set(
            self.described_time_value_refs
        ).issubset(set(self.exact_value_refs or [])):
            raise ValueError(
                "described event time must reference an event exact-value binding"
            )
        participant_keys = [
            (binding.role, binding.participant_kind, binding.participant_ref)
            for binding in self.participant_bindings
        ]
        if len(participant_keys) != len(set(participant_keys)):
            raise ValueError("event participant bindings must be unique")
        return self


class GroundedFlowRecord(HashBoundAnalysisArtifact):
    flow_id: str = Field(min_length=1)
    flow_type: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    beneficiary_ref: str | None = Field(default=None, min_length=1)
    object_ref: str = Field(min_length=1)
    claim_refs: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    exact_value_refs: list[str] | None = None
    event_refs: list[str] | None = None
    relationship_ref: str | None = Field(default=None, min_length=1)

    @field_validator(
        "claim_refs", "evidence_refs", "exact_value_refs", "event_refs"
    )
    @classmethod
    def unique_flow_refs(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return _ensure_sorted_unique(values, "flow refs")

    @model_validator(mode="after")
    def validate_direction(self) -> "GroundedFlowRecord":
        if self.source_ref == self.target_ref:
            raise ValueError("flow source and target must differ")
        return self


class HypothesisSetRecord(HashBoundAnalysisArtifact):
    hypothesis_set_id: str = Field(min_length=1)
    comparison_question: str = Field(min_length=1)
    hypothesis_refs: list[str] = Field(min_length=2)
    mutually_exclusive: bool
    exhaustive: bool
    review_state: Literal["needs_review", "human_reviewed"]

    @field_validator("hypothesis_refs")
    @classmethod
    def unique_hypothesis_refs(cls, values: list[str]) -> list[str]:
        return _ensure_sorted_unique(values, "hypothesis set refs")


class ReleasedContradictionRecord(HashBoundAnalysisArtifact):
    contradiction_id: str = Field(min_length=1)
    proposition_key_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")
    claim_refs: list[str] = Field(min_length=2)
    evidence_refs: list[str] = Field(min_length=2)
    conflict_dimension: str = Field(min_length=1)
    status: Literal["unresolved", "human_reviewed"]
    assertions_preserved: Literal[True] = True
    resolution_artifact_ref: str | None = Field(default=None, min_length=1)

    @field_validator("claim_refs", "evidence_refs")
    @classmethod
    def unique_contradiction_refs(cls, values: list[str]) -> list[str]:
        return _ensure_sorted_unique(values, "contradiction refs")

    @model_validator(mode="after")
    def validate_resolution_state(self) -> "ReleasedContradictionRecord":
        if (self.status == "human_reviewed") != (
            self.resolution_artifact_ref is not None
        ):
            raise ValueError(
                "human-reviewed contradiction state must match resolution artifact"
            )
        return self


class AnalysisProjectionV1_1(StrictEnvelope):
    """Reference-only selection of released typed investigation artifacts."""

    projection_version: Literal[
        "investigation-analysis-projection-v1.1"
    ] = ANALYSIS_PROJECTION_VERSION
    source_set_ref: str = Field(min_length=1)
    quality_ref: str = Field(min_length=1)
    source_assertion_refs: list[str] | None = None
    world_finding_refs: list[str] | None = None
    concept_refs: list[str] | None = None
    exact_value_refs: list[str] | None = None
    speaker_assignment_refs: list[str] | None = None
    event_refs: list[str] | None = None
    relationship_refs: list[str] | None = None
    flow_refs: list[str] | None = None
    contradiction_refs: list[str] | None = None
    insight_refs: list[str] | None = None
    hypothesis_set_refs: list[str] | None = None
    verification_action_refs: list[str] | None = None
    briefing_claim_refs: list[str] | None = None
    briefing_insight_refs: list[str] | None = None

    @field_validator(
        "source_assertion_refs",
        "world_finding_refs",
        "concept_refs",
        "exact_value_refs",
        "speaker_assignment_refs",
        "event_refs",
        "relationship_refs",
        "flow_refs",
        "contradiction_refs",
        "insight_refs",
        "hypothesis_set_refs",
        "verification_action_refs",
    )
    @classmethod
    def unique_projection_refs(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return _ensure_sorted_unique(values, "analysis projection refs")

    @field_validator("briefing_claim_refs", "briefing_insight_refs")
    @classmethod
    def unique_briefing_refs(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return _ensure_unique(values, "analysis briefing refs")

    @model_validator(mode="after")
    def validate_projection_layers(self) -> "AnalysisProjectionV1_1":
        source_refs = set(self.source_assertion_refs or [])
        world_refs = set(self.world_finding_refs or [])
        if not source_refs and not world_refs:
            raise ValueError("released analysis requires at least one factual claim")
        if source_refs & world_refs:
            raise ValueError("source assertions and world findings must be disjoint")
        if not set(self.briefing_claim_refs or []).issubset(source_refs | world_refs):
            raise ValueError("briefing claims must reference released factual claims")
        if not set(self.briefing_insight_refs or []).issubset(
            set(self.insight_refs or [])
        ):
            raise ValueError("briefing insights must reference released insights")
        return self


class ReleasedAnalysisArtifact(StrictEnvelope):
    schema_version: Literal[
        "released-investigation-analysis-v1"
    ] = RELEASED_ANALYSIS_VERSION
    authority: Literal[
        "released_investigation_run"
    ] = RELEASED_ANALYSIS_AUTHORITY
    run_id: str = Field(min_length=1)
    release_subject_sha256: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")
    projection: AnalysisProjectionV1_1
    content_hash: Sha256Hex = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_content_hash(self) -> "ReleasedAnalysisArtifact":
        payload = self.model_dump(
            mode="json",
            exclude={"content_hash"},
            exclude_none=True,
        )
        if self.content_hash != sha256_canonical_json(payload):
            raise ValueError("content_hash must bind the canonical analysis artifact")
        return self


@dataclass(frozen=True)
class AnalysisProjectionRegistry:
    """Trusted released registries used to resolve projection references."""

    source_sets: Mapping[str, SourceSetProvenance]
    quality: Mapping[str, AnalysisQualityArtifact]
    claims: Mapping[str, GroundedClaim]
    source_assertions: Mapping[str, GroundedClaim]
    world_findings: Mapping[str, GroundedClaim]
    concepts: Mapping[str, ConceptMention]
    exact_values: Mapping[str, ExactValueRecord]
    speaker_assignments: Mapping[str, SpeakerAssignmentRecord]
    events: Mapping[str, GroundedEventRecord]
    relationships: Mapping[str, GroundedRelationship]
    flows: Mapping[str, GroundedFlowRecord]
    contradictions: Mapping[str, ReleasedContradictionRecord]
    evidence: Mapping[str, EvidenceSpan]
    insights: Mapping[str, EvidenceBackedInsight]
    hypotheses: Mapping[str, Hypothesis]
    hypothesis_sets: Mapping[str, HypothesisSetRecord]
    verification_actions: Mapping[str, VerificationAction]


def validate_analysis_projection_refs(
    projection: AnalysisProjectionV1_1,
    registry: AnalysisProjectionRegistry,
) -> None:
    """Fail closed unless every projection ref resolves to the exact released set."""

    if projection.source_set_ref not in registry.source_sets:
        raise ValueError("analysis projection source_set_ref is unresolved")
    if projection.quality_ref not in registry.quality:
        raise ValueError("analysis projection quality_ref is unresolved")
    source_set = registry.source_sets[projection.source_set_ref]
    quality = registry.quality[projection.quality_ref]
    if quality.source_set_ref != source_set.source_set_id:
        raise ValueError("analysis quality source set mismatch")
    if not quality.release_ready or quality.blocking_codes:
        raise ValueError("analysis quality is not release-ready")

    _require_exact_refs(
        projection.source_assertion_refs,
        registry.source_assertions,
        "source assertion refs",
    )
    _require_exact_refs(
        projection.world_finding_refs,
        registry.world_findings,
        "world finding refs",
    )
    _require_exact_refs(projection.concept_refs, registry.concepts, "concept refs")
    _require_exact_refs(
        projection.exact_value_refs,
        registry.exact_values,
        "exact value refs",
    )
    _require_exact_refs(
        projection.speaker_assignment_refs,
        registry.speaker_assignments,
        "speaker assignment refs",
    )
    _require_exact_refs(projection.event_refs, registry.events, "event refs")
    _require_exact_refs(
        projection.relationship_refs,
        registry.relationships,
        "relationship refs",
    )
    _require_exact_refs(projection.flow_refs, registry.flows, "flow refs")
    _require_exact_refs(
        projection.contradiction_refs,
        registry.contradictions,
        "contradiction refs",
    )
    _require_exact_refs(projection.insight_refs, registry.insights, "insight refs")
    _require_exact_refs(
        projection.hypothesis_set_refs,
        registry.hypothesis_sets,
        "hypothesis set refs",
    )
    _require_exact_refs(
        projection.verification_action_refs,
        registry.verification_actions,
        "verification action refs",
    )

    evidence_ids = set(registry.evidence)
    claim_ids = set(registry.claims)
    projected_claim_ids = set(registry.source_assertions) | set(registry.world_findings)
    concept_ids = set(registry.concepts)
    exact_value_ids = set(registry.exact_values)
    event_ids = set(registry.events)
    relationship_ids = set(registry.relationships)
    hypothesis_ids = set(registry.hypotheses)
    source_revision_ids = set(source_set.source_revision_refs)

    for claim in registry.source_assertions.values():
        if (
            claim.factual_scope != "verified_source_assertion"
            or claim.epistemic_status != "fact"
            or claim.disposition != "supported"
        ):
            raise ValueError("source assertion registry contains a non-source fact")
        _require_subset(claim.evidence_refs, evidence_ids, "claim evidence refs")

    for claim in registry.world_findings.values():
        if (
            claim.factual_scope != "corroborated_world_finding"
            or claim.epistemic_status != "fact"
            or claim.disposition != "supported"
        ):
            raise ValueError("world finding registry lacks corroborated fact authority")
        _require_subset(claim.evidence_refs, evidence_ids, "finding evidence refs")

    for assignment in registry.speaker_assignments.values():
        if assignment.source_revision_id not in source_revision_ids:
            raise ValueError("speaker assignment is outside the authorized source set")
        _require_subset(
            assignment.evidence_refs,
            evidence_ids,
            "speaker assignment evidence refs",
        )
        if assignment.local_speaker_id is not None:
            for evidence_ref in assignment.evidence_refs:
                evidence_speaker = registry.evidence[evidence_ref].speaker_id
                if evidence_speaker != assignment.local_speaker_id:
                    raise ValueError("speaker assignment conflicts with evidence speaker")

    for value in registry.exact_values.values():
        _require_subset(value.claim_refs, projected_claim_ids, "exact value claim refs")
        _require_subset(value.evidence_refs, evidence_ids, "exact value evidence refs")
        if value.owner_ref is not None and value.owner_ref not in (
            concept_ids | claim_ids
        ):
            raise ValueError("exact value owner_ref is unresolved")
        if value.speaker_assignment_ref is not None:
            assignment = registry.speaker_assignments.get(value.speaker_assignment_ref)
            if assignment is None:
                raise ValueError("exact value speaker assignment is unresolved")
            if value.sensitivity == "high_impact" and assignment.assignment_state in {
                "ambiguous",
                "degraded",
                "unavailable",
            }:
                raise ValueError(
                    "high-impact exact values cannot use uncertain speaker assignment"
                )

    for event in registry.events.values():
        _require_subset(event.claim_refs, projected_claim_ids, "event claim refs")
        _require_subset(event.evidence_refs, evidence_ids, "event evidence refs")
        _require_subset(event.location_refs, concept_ids, "event location refs")
        _require_subset(event.exact_value_refs, exact_value_ids, "event value refs")
        for binding in event.participant_bindings:
            available = concept_ids if binding.participant_kind == "concept" else claim_ids
            if binding.participant_ref not in available:
                raise ValueError("event participant ref is unresolved")
        for value_ref in event.described_time_value_refs or []:
            if registry.exact_values[value_ref].semantic_role not in {
                "date",
                "time",
                "datetime",
            }:
                raise ValueError("described event time must use a temporal exact value")

    for relationship in registry.relationships.values():
        if relationship.source_ref not in concept_ids | claim_ids:
            raise ValueError("relationship source_ref is unresolved")
        if relationship.target_ref not in concept_ids | claim_ids:
            raise ValueError("relationship target_ref is unresolved")
        _require_subset(
            relationship.evidence_refs,
            evidence_ids,
            "relationship evidence refs",
        )
        _require_subset(
            relationship.premise_claim_refs,
            projected_claim_ids,
            "relationship premise refs",
        )
        if (
            relationship.disposition != "supported"
            or relationship.evidence_resolution != "resolved"
            or relationship.projection_eligibility not in {
                "source_attributed",
                "factual",
            }
        ):
            raise ValueError("relationship registry contains a non-released relation")

    for flow in registry.flows.values():
        for endpoint in (flow.source_ref, flow.target_ref, flow.beneficiary_ref):
            if endpoint is not None and endpoint not in concept_ids | claim_ids:
                raise ValueError("flow endpoint is unresolved")
        if flow.object_ref not in concept_ids | exact_value_ids:
            raise ValueError("flow object_ref is unresolved")
        _require_subset(flow.claim_refs, projected_claim_ids, "flow claim refs")
        _require_subset(flow.evidence_refs, evidence_ids, "flow evidence refs")
        _require_subset(flow.exact_value_refs, exact_value_ids, "flow value refs")
        _require_subset(flow.event_refs, event_ids, "flow event refs")
        if flow.relationship_ref is not None and (
            flow.relationship_ref not in relationship_ids
        ):
            raise ValueError("flow relationship_ref is unresolved")

    for contradiction in registry.contradictions.values():
        _require_subset(
            contradiction.claim_refs,
            claim_ids,
            "contradiction claim refs",
        )
        _require_subset(
            contradiction.evidence_refs,
            evidence_ids,
            "contradiction evidence refs",
        )

    for insight in registry.insights.values():
        _require_subset(
            insight.premise_claim_refs,
            projected_claim_ids,
            "insight premise refs",
        )
        _require_subset(insight.evidence_refs, evidence_ids, "insight evidence refs")
        _require_subset(
            insight.counterevidence_claim_refs,
            claim_ids,
            "insight counterevidence refs",
        )

    covered_hypothesis_refs: set[str] = set()
    for hypothesis_set in registry.hypothesis_sets.values():
        _require_subset(
            hypothesis_set.hypothesis_refs,
            hypothesis_ids,
            "hypothesis set refs",
        )
        overlap = covered_hypothesis_refs & set(hypothesis_set.hypothesis_refs)
        if overlap:
            raise ValueError("hypotheses cannot appear in multiple competing sets")
        covered_hypothesis_refs.update(hypothesis_set.hypothesis_refs)
    if covered_hypothesis_refs != hypothesis_ids:
        raise ValueError("hypothesis sets must cover every released hypothesis")

    for action in registry.verification_actions.values():
        _require_subset(action.evidence_refs, evidence_ids, "action evidence refs")
        _require_subset(action.linked_claim_refs, claim_ids, "action claim refs")
        _require_subset(
            action.linked_hypothesis_refs,
            hypothesis_ids,
            "action hypothesis refs",
        )
        _require_subset(
            action.linked_concept_refs,
            concept_ids,
            "action concept refs",
        )


def analysis_projection_json_schema() -> dict[str, Any]:
    return ReleasedAnalysisArtifact.model_json_schema()


def analysis_projection_schema_sha256() -> str:
    return sha256_canonical_json(analysis_projection_json_schema())


def build_released_analysis_artifact(
    *,
    run_id: str,
    release_subject_sha256: str,
    projection: AnalysisProjectionV1_1,
) -> ReleasedAnalysisArtifact:
    payload = {
        "schema_version": RELEASED_ANALYSIS_VERSION,
        "authority": RELEASED_ANALYSIS_AUTHORITY,
        "run_id": run_id,
        "release_subject_sha256": release_subject_sha256,
        "projection": projection.model_dump(mode="json", exclude_none=True),
    }
    return ReleasedAnalysisArtifact.model_validate(
        {**payload, "content_hash": sha256_canonical_json(payload)}
    )


__all__ = [
    "ANALYSIS_PROJECTION_VERSION",
    "RELEASED_ANALYSIS_AUTHORITY",
    "RELEASED_ANALYSIS_VERSION",
    "AnalysisProjectionRegistry",
    "AnalysisProjectionV1_1",
    "AnalysisQualityArtifact",
    "ExactValueRecord",
    "GroundedEventRecord",
    "GroundedFlowRecord",
    "HypothesisSetRecord",
    "ReleasedAnalysisArtifact",
    "ReleasedContradictionRecord",
    "SourceSetProvenance",
    "SpeakerAssignmentRecord",
    "analysis_projection_json_schema",
    "analysis_projection_schema_sha256",
    "build_released_analysis_artifact",
    "validate_analysis_projection_refs",
]
