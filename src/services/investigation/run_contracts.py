"""Release lifecycle, trusted registries, and projections for InvestigationRun."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    JsonValue,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .contracts import (
    ANALYSIS_PROJECTION_VERSION,
    INVESTIGATION_RUN_VERSION,
    SUMMARY_PROJECTION_VERSION,
    AdaptiveTheme,
    ConceptMention,
    EpistemicKind,
    EvidenceResolutionStatus,
    EvidenceSpan,
    GroundedClaim,
    GroundedRelationship,
    ManifestEnvelope,
    NarrativeSynthesis,
    ProjectionEligibility,
    RiskTier,
    SafetyEnvelope,
    Sha256Hex,
    SourceProvenance,
    StrictEnvelope,
    VerificationDisposition,
    _ensure_unique,
    _require_refs,
    sha256_canonical_json,
    sha256_utf8,
)
from .reasoning_contracts import (
    EvidenceBackedInsight,
    Hypothesis,
    VerificationAction,
)


def _validate_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256")


@dataclass(frozen=True)
class _TrustedEvidenceFingerprint:
    segment_id: str
    quote_sha256: str
    source_sha256: str
    quote_prefix: str | None
    quote_suffix: str | None
    raw_char_start: int | None
    raw_char_end: int | None
    start_seconds: float | None
    end_seconds: float | None
    speaker_id: str | None

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("trusted evidence segment_id must be non-blank")
        _validate_sha256(self.quote_sha256, "trusted quote hash")
        _validate_sha256(self.source_sha256, "trusted source hash")


@dataclass(frozen=True)
class _TrustedSelectorAttestation:
    artifact_ref: str
    source_revision_id: str
    evidence: Mapping[str, _TrustedEvidenceFingerprint]

    def __post_init__(self) -> None:
        if not self.artifact_ref.strip() or not self.source_revision_id.strip():
            raise ValueError("trusted selector attestation fields must be non-blank")
        if not self.evidence:
            raise ValueError("trusted selector attestation requires evidence")
        if any(not evidence_id.strip() for evidence_id in self.evidence):
            raise ValueError("trusted selector evidence IDs must be non-blank")
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))


@dataclass(frozen=True)
class _TrustedRiskAssessment:
    risk_tier: RiskTier
    artifact_ref: str
    subject_sha256: str

    def __post_init__(self) -> None:
        if not self.artifact_ref.strip():
            raise ValueError("trusted risk assessment artifact_ref must be non-blank")
        _validate_sha256(self.subject_sha256, "trusted risk subject hash")


@dataclass(frozen=True)
class _TrustedEligibilityAssessment:
    eligibility: ProjectionEligibility
    artifact_ref: str
    subject_sha256: str

    def __post_init__(self) -> None:
        if not self.artifact_ref.strip():
            raise ValueError("trusted eligibility artifact_ref must be non-blank")
        _validate_sha256(self.subject_sha256, "trusted eligibility subject hash")


def _semantic_subject_sha256(subject: BaseModel) -> str:
    """Bind trusted decisions to the exact validated semantic object."""

    return sha256_canonical_json(
        {
            "subject_class": subject.__class__.__name__,
            "subject": subject.model_dump(mode="json", exclude_none=True),
        }
    )


def _verification_subject_sha256(
    decision: "VerificationDecision",
    claim: GroundedClaim | None,
) -> str:
    return sha256_canonical_json(
        {
            "verification": decision.model_dump(mode="json", exclude_none=True),
            "canonical_claim_sha256": (
                _semantic_subject_sha256(claim) if claim is not None else None
            ),
        }
    )


class _TrustedInvestigationValidationContext:
    """Opaque in-process trust boundary populated by future T2/T4 services."""

    __slots__ = (
        "selector_attestations",
        "relationship_attestations",
        "risk_assessments",
        "verification_eligibility",
        "relationship_eligibility",
        "reasoning_eligibility",
        "manifest_sha256",
    )

    def __init__(
        self,
        *,
        selector_attestations: Mapping[str, _TrustedSelectorAttestation],
        relationship_attestations: Mapping[str, _TrustedSelectorAttestation],
        risk_assessments: Mapping[str, _TrustedRiskAssessment],
        verification_eligibility: Mapping[str, _TrustedEligibilityAssessment],
        relationship_eligibility: Mapping[str, _TrustedEligibilityAssessment],
        reasoning_eligibility: Mapping[str, _TrustedEligibilityAssessment],
        manifest_sha256: str,
        _authority: object,
    ) -> None:
        if _authority is not _TRUSTED_CONTEXT_AUTHORITY:
            raise TypeError("trusted validation context requires internal authority")
        self.selector_attestations = MappingProxyType(dict(selector_attestations))
        self.relationship_attestations = MappingProxyType(
            dict(relationship_attestations)
        )
        self.risk_assessments = MappingProxyType(dict(risk_assessments))
        self.verification_eligibility = MappingProxyType(dict(verification_eligibility))
        self.relationship_eligibility = MappingProxyType(dict(relationship_eligibility))
        self.reasoning_eligibility = MappingProxyType(dict(reasoning_eligibility))
        _validate_sha256(manifest_sha256, "trusted manifest hash")
        self.manifest_sha256 = manifest_sha256


_TRUSTED_CONTEXT_AUTHORITY = object()
_VALIDATION_CONTEXT_KEY = "investigation_release_authority"


def _build_trusted_investigation_validation_context(
    *,
    selector_attestations: Mapping[str, _TrustedSelectorAttestation],
    relationship_attestations: Mapping[str, _TrustedSelectorAttestation],
    risk_assessments: Mapping[str, _TrustedRiskAssessment],
    verification_eligibility: Mapping[str, _TrustedEligibilityAssessment],
    relationship_eligibility: Mapping[str, _TrustedEligibilityAssessment],
    reasoning_eligibility: Mapping[str, _TrustedEligibilityAssessment] | None = None,
    manifest_sha256: str,
) -> _TrustedInvestigationValidationContext:
    """Internal adapter seam for trusted T2 selector and T4 safety registries."""

    return _TrustedInvestigationValidationContext(
        selector_attestations=selector_attestations,
        relationship_attestations=relationship_attestations,
        risk_assessments=risk_assessments,
        verification_eligibility=verification_eligibility,
        relationship_eligibility=relationship_eligibility,
        reasoning_eligibility=reasoning_eligibility or {},
        manifest_sha256=manifest_sha256,
        _authority=_TRUSTED_CONTEXT_AUTHORITY,
    )


def _trusted_release_context(
    info: ValidationInfo,
) -> _TrustedInvestigationValidationContext:
    context = info.context
    authority = (
        context.get(_VALIDATION_CONTEXT_KEY) if isinstance(context, Mapping) else None
    )
    if not isinstance(authority, _TrustedInvestigationValidationContext):
        raise ValueError(
            "success requires trusted T2 selector and T4 risk validation context"
        )
    return authority


class InvestigationRunManifest(ManifestEnvelope):
    """Manifest discriminator for the release-safe InvestigationRun schema."""

    contract_version: Literal["investigation-run-v1.0"] = INVESTIGATION_RUN_VERSION
    source_module_hashes: dict[str, Sha256Hex] = Field(min_length=1)
    git_revision: str = Field(min_length=1)


class DiscoveryCandidate(StrictEnvelope):
    """Open-schema discovery output before verification and release."""

    candidate_id: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    polarity: Literal[
        "affirmed", "negated", "uncertain", "reported", "quoted_instruction"
    ]
    epistemic_status: EpistemicKind = "fact"
    risk_tier: RiskTier | None = None
    requires_human_verification: bool = False
    evidence_refs: list[str] = Field(min_length=1)
    concept_refs: list[str] | None = None
    premise_candidate_refs: list[str] | None = None
    attributes: dict[str, JsonValue] | None = None

    @field_validator("evidence_refs", "concept_refs", "premise_candidate_refs")
    @classmethod
    def unique_candidate_refs(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return _ensure_unique(values, "candidate references")

    @model_validator(mode="after")
    def protect_candidate_epistemics(self) -> "DiscoveryCandidate":
        if self.epistemic_status != "fact" and not self.requires_human_verification:
            raise ValueError("non-factual candidates require human verification")
        if self.risk_tier == "high_risk":
            if self.epistemic_status != "hypothesis":
                raise ValueError(
                    "high-risk candidates must be represented as hypotheses"
                )
            if not self.requires_human_verification:
                raise ValueError(
                    "high-risk candidate hypotheses require human verification"
                )
        return self


class VerificationDecision(StrictEnvelope):
    """Verifier result linking a discovery candidate to the canonical ledger.

    T1.1 validates lifecycle state only. A resolved decision must reference the
    future T2 selector artifact; this contract does not resolve source bytes.
    """

    verification_id: str = Field(min_length=1)
    candidate_ref: str = Field(min_length=1)
    disposition: VerificationDisposition
    evidence_resolution: EvidenceResolutionStatus
    source_revision_id: str = Field(min_length=1)
    resolution_authority: Literal["t2-evidence-selector-v1"] | None = None
    resolution_artifact_ref: str | None = Field(default=None, min_length=1)
    verified_evidence_refs: list[str] | None = None
    canonical_claim_ref: str | None = Field(default=None, min_length=1)
    projection_eligibility: ProjectionEligibility = "withheld"
    eligibility_artifact_ref: str | None = Field(default=None, min_length=1)
    failure_codes: list[str] | None = None

    @field_validator("verified_evidence_refs", "failure_codes")
    @classmethod
    def unique_verification_values(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return _ensure_unique(values, "verification values")

    @model_validator(mode="after")
    def validate_release_attestation(self) -> "VerificationDecision":
        if self.evidence_resolution == "resolved" and (
            self.resolution_authority is None or self.resolution_artifact_ref is None
        ):
            raise ValueError("resolved evidence requires a T2 selector attestation")
        if self.evidence_resolution != "resolved":
            if self.projection_eligibility != "withheld":
                raise ValueError(
                    "unresolved or revision-mismatch evidence must be withheld"
                )
            if self.verified_evidence_refs is not None:
                raise ValueError(
                    "unresolved evidence cannot declare verified evidence refs"
                )
        if self.projection_eligibility != "withheld":
            if self.canonical_claim_ref is None:
                raise ValueError("projectable decisions require canonical_claim_ref")
            if not self.verified_evidence_refs:
                raise ValueError("projectable decisions require verified evidence")
            if self.eligibility_artifact_ref is None:
                raise ValueError("projectable decisions require eligibility artifact")
        if self.projection_eligibility == "factual" and self.disposition != "supported":
            raise ValueError(
                "factual projection eligibility requires supported evidence"
            )
        if (
            self.projection_eligibility == "non_factual"
            and self.disposition == "unverifiable"
        ):
            raise ValueError("unverifiable candidates must remain withheld")
        return self


class CanonicalClaimLedger(StrictEnvelope):
    """Versioned candidate, verification, evidence, and canonical-claim ledger."""

    candidates: list[DiscoveryCandidate] = Field(min_length=1)
    verification_decisions: list[VerificationDecision] = Field(min_length=1)
    claims: list[GroundedClaim]
    evidence: list[EvidenceSpan] = Field(min_length=1)
    concepts: list[ConceptMention] | None = None
    relationships: list[GroundedRelationship] | None = None
    insights: list[EvidenceBackedInsight] | None = None
    hypotheses: list[Hypothesis] | None = None
    verification_actions: list[VerificationAction] | None = None

    @classmethod
    def _allowed_sparse_empty_paths(cls, value: Any) -> frozenset[tuple[str, ...]]:
        return frozenset({("claims",)})

    @model_validator(mode="after")
    def validate_ledger_graph(self) -> "CanonicalClaimLedger":
        collections: tuple[tuple[str, list[Any], str], ...] = (
            ("candidate", self.candidates, "candidate_id"),
            ("verification", self.verification_decisions, "verification_id"),
            ("claim", self.claims, "claim_id"),
            ("evidence", self.evidence, "evidence_id"),
            ("concept", self.concepts or [], "concept_id"),
            ("relationship", self.relationships or [], "relationship_id"),
            ("insight", self.insights or [], "insight_id"),
            ("hypothesis", self.hypotheses or [], "hypothesis_id"),
            ("verification_action", self.verification_actions or [], "action_id"),
        )
        seen_ids: dict[str, str] = {}
        for label, items, field_name in collections:
            for item in items:
                identifier = str(getattr(item, field_name))
                if identifier in seen_ids:
                    raise ValueError(
                        f"duplicate ID {identifier!r} in {label}; already used by "
                        f"{seen_ids[identifier]}"
                    )
                seen_ids[identifier] = label

        candidate_ids = {item.candidate_id for item in self.candidates}
        claim_ids = {item.claim_id for item in self.claims}
        evidence_ids = {item.evidence_id for item in self.evidence}
        concept_ids = {item.concept_id for item in self.concepts or []}
        node_ids = claim_ids | concept_ids

        decision_candidate_refs = [
            decision.candidate_ref for decision in self.verification_decisions
        ]
        if len(decision_candidate_refs) != len(set(decision_candidate_refs)):
            raise ValueError("each discovery candidate requires exactly one decision")
        if set(decision_candidate_refs) != candidate_ids:
            raise ValueError("every discovery candidate requires exactly one decision")

        for candidate in self.candidates:
            _require_refs(
                candidate.evidence_refs, evidence_ids, "candidate evidence_refs"
            )
            if candidate.concept_refs:
                _require_refs(
                    candidate.concept_refs, concept_ids, "candidate concept_refs"
                )
            if candidate.premise_candidate_refs:
                _require_refs(
                    candidate.premise_candidate_refs,
                    candidate_ids,
                    "candidate premise refs",
                )
                if candidate.candidate_id in candidate.premise_candidate_refs:
                    raise ValueError("candidate cannot use itself as a premise")

        claim_by_id = {claim.claim_id: claim for claim in self.claims}
        linked_decisions: dict[str, list[VerificationDecision]] = {}
        for decision in self.verification_decisions:
            if decision.verified_evidence_refs:
                _require_refs(
                    decision.verified_evidence_refs,
                    evidence_ids,
                    "verification evidence refs",
                )
                candidate = next(
                    item
                    for item in self.candidates
                    if item.candidate_id == decision.candidate_ref
                )
                if not set(decision.verified_evidence_refs).issubset(
                    candidate.evidence_refs
                ):
                    raise ValueError(
                        "verified evidence refs must originate from the candidate"
                    )
            if decision.canonical_claim_ref:
                _require_refs(
                    [decision.canonical_claim_ref],
                    claim_ids,
                    "verification canonical claim refs",
                )
                claim = claim_by_id[decision.canonical_claim_ref]
                if not claim.candidate_refs or decision.candidate_ref not in (
                    claim.candidate_refs
                ):
                    raise ValueError(
                        "canonical claims must retain their source candidate refs"
                    )
                if decision.disposition != claim.disposition:
                    raise ValueError(
                        "verification disposition must match the canonical claim"
                    )
                expected_eligibility = (
                    "factual"
                    if claim.epistemic_status == "fact"
                    and claim.disposition == "supported"
                    else "non_factual"
                )
                if claim.disposition == "unverifiable":
                    expected_eligibility = "withheld"
                if (
                    decision.projection_eligibility != "withheld"
                    and decision.projection_eligibility != expected_eligibility
                ):
                    raise ValueError(
                        "verification eligibility conflicts with claim epistemics"
                    )
                linked_decisions.setdefault(claim.claim_id, []).append(decision)

        for claim in self.claims:
            _require_refs(claim.evidence_refs, evidence_ids, "claim evidence_refs")
            if claim.concept_refs:
                _require_refs(claim.concept_refs, concept_ids, "claim concept_refs")
            if not claim.candidate_refs:
                raise ValueError("canonical claims require source candidate refs")
            _require_refs(claim.candidate_refs, candidate_ids, "claim candidate_refs")
            if claim.premise_claim_refs:
                _require_refs(
                    claim.premise_claim_refs,
                    claim_ids,
                    "claim premise refs",
                )
                if claim.claim_id in claim.premise_claim_refs:
                    raise ValueError("claim cannot use itself as a premise")
            decisions = linked_decisions.get(claim.claim_id, [])
            if not decisions:
                raise ValueError(
                    "every canonical claim requires a linked verification decision"
                )
            verified_evidence = {
                evidence_ref
                for decision in decisions
                if decision.evidence_resolution == "resolved"
                for evidence_ref in decision.verified_evidence_refs or []
            }
            if not set(claim.evidence_refs).issubset(verified_evidence):
                raise ValueError(
                    "canonical claim evidence requires a resolved verification"
                )

        for concept in self.concepts or []:
            _require_refs(concept.evidence_refs, evidence_ids, "concept evidence_refs")
        for relationship in self.relationships or []:
            _require_refs(
                [relationship.source_ref, relationship.target_ref],
                node_ids,
                "relationship node refs",
            )
            _require_refs(
                relationship.evidence_refs,
                evidence_ids,
                "relationship evidence_refs",
            )
            if relationship.premise_claim_refs:
                _require_refs(
                    relationship.premise_claim_refs,
                    claim_ids,
                    "relationship premise refs",
                )

        for insight in self.insights or []:
            _require_refs(
                insight.premise_claim_refs,
                claim_ids,
                "insight premise refs",
            )
            _require_refs(insight.evidence_refs, evidence_ids, "insight evidence refs")
            if insight.counterevidence_claim_refs:
                _require_refs(
                    insight.counterevidence_claim_refs,
                    claim_ids,
                    "insight counterevidence refs",
                )

        hypothesis_ids = {
            hypothesis.hypothesis_id for hypothesis in self.hypotheses or []
        }
        for hypothesis in self.hypotheses or []:
            _require_refs(
                hypothesis.premise_claim_refs,
                claim_ids,
                "hypothesis premise refs",
            )
            _require_refs(
                hypothesis.evidence_refs,
                evidence_ids,
                "hypothesis evidence refs",
            )
            if hypothesis.counterevidence_claim_refs:
                _require_refs(
                    hypothesis.counterevidence_claim_refs,
                    claim_ids,
                    "hypothesis counterevidence refs",
                )

        resolvable_action_targets = claim_ids | hypothesis_ids | concept_ids
        for action in self.verification_actions or []:
            _require_refs(
                action.evidence_refs,
                evidence_ids,
                "verification action evidence refs",
            )
            _require_refs(
                [action.target_ref],
                resolvable_action_targets,
                "verification action target refs",
            )
            if action.linked_claim_refs:
                _require_refs(
                    action.linked_claim_refs,
                    claim_ids,
                    "verification action claim refs",
                )
            if action.linked_hypothesis_refs:
                _require_refs(
                    action.linked_hypothesis_refs,
                    hypothesis_ids,
                    "verification action hypothesis refs",
                )
            if action.linked_concept_refs:
                _require_refs(
                    action.linked_concept_refs,
                    concept_ids,
                    "verification action concept refs",
                )
        return self


class SummaryProjection(StrictEnvelope):
    projection_version: Literal[
        "investigation-summary-projection-v1.0"
    ] = SUMMARY_PROJECTION_VERSION
    released_claim_refs: list[str] = Field(min_length=1)
    insight_refs: list[str] | None = None
    hypothesis_refs: list[str] | None = None
    verification_action_refs: list[str] | None = None
    themes: list[AdaptiveTheme] = Field(min_length=1)
    narrative: NarrativeSynthesis

    @field_validator(
        "released_claim_refs",
        "insight_refs",
        "hypothesis_refs",
        "verification_action_refs",
    )
    @classmethod
    def unique_released_claim_refs(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return _ensure_unique(values, "summary released claim refs")


class AnalysisProjection(StrictEnvelope):
    projection_version: Literal[
        "investigation-analysis-projection-v1.0"
    ] = ANALYSIS_PROJECTION_VERSION
    released_claim_refs: list[str] = Field(min_length=1)
    fact_claim_refs: list[str] | None = None
    qualified_claim_refs: list[str] | None = None
    insight_refs: list[str] | None = None
    hypothesis_refs: list[str] | None = None
    verification_action_refs: list[str] | None = None
    relationship_refs: list[str] | None = None
    attributes: dict[str, JsonValue] | None = None

    @field_validator(
        "released_claim_refs",
        "fact_claim_refs",
        "qualified_claim_refs",
        "insight_refs",
        "hypothesis_refs",
        "verification_action_refs",
        "relationship_refs",
    )
    @classmethod
    def unique_analysis_refs(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is None:
            return None
        return _ensure_unique(values, "analysis references")


class InvestigationProjections(StrictEnvelope):
    summary: SummaryProjection
    analysis: AnalysisProjection


class GateFailure(StrictEnvelope):
    code: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    severity: Literal["error", "warning"] = "error"
    message: str = Field(min_length=1)
    refs: list[str] | None = None

    @field_validator("refs")
    @classmethod
    def unique_gate_refs(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return _ensure_unique(values, "gate failure refs")


class InvestigationRun(StrictEnvelope):
    """Canonical lifecycle owner from candidates through released projections."""

    schema_version: Literal["investigation-run-v1.0"] = INVESTIGATION_RUN_VERSION
    run_id: str = Field(min_length=1)
    run_status: Literal["success", "no_extractable_claims", "needs_review", "failed"]
    ledger: CanonicalClaimLedger | None = None
    projections: InvestigationProjections | None = None
    gate_failures: list[GateFailure] | None = None
    provenance: SourceProvenance
    safety: SafetyEnvelope
    manifest: InvestigationRunManifest

    @classmethod
    def _allowed_sparse_empty_paths(cls, value: Any) -> frozenset[tuple[str, ...]]:
        if isinstance(value, Mapping) and value.get("run_status") == "needs_review":
            return frozenset({("ledger", "claims")})
        return frozenset()

    @model_validator(mode="after")
    def validate_lifecycle_and_release(
        self,
        info: ValidationInfo,
    ) -> "InvestigationRun":
        if self.manifest.contract_version != INVESTIGATION_RUN_VERSION:
            raise ValueError("investigation run manifest contract_version mismatch")
        if self.manifest.json_schema_sha256 != investigation_run_schema_sha256():
            raise ValueError("investigation run manifest schema hash mismatch")

        blocking_failures = [
            failure
            for failure in self.gate_failures or []
            if failure.severity == "error"
        ]
        if self.run_status == "no_extractable_claims":
            if self.ledger is not None or self.projections is not None:
                raise ValueError(
                    "no_extractable_claims cannot include ledger or projections"
                )
            if self.gate_failures is not None:
                raise ValueError("no_extractable_claims cannot include gate failures")
            return self

        if self.run_status == "failed":
            if self.projections is not None:
                raise ValueError("failed runs cannot include released projections")
            if not blocking_failures:
                raise ValueError("failed runs require a blocking gate failure")
            return self

        if self.run_status == "needs_review":
            if self.ledger is None:
                raise ValueError("needs_review requires a diagnostic ledger")
            if self.projections is not None:
                raise ValueError("needs_review cannot include released projections")
            if not blocking_failures:
                raise ValueError("needs_review requires a blocking gate failure")
            self._validate_source_revision(self.ledger)
            return self

        if self.ledger is None or self.projections is None:
            raise ValueError("success requires ledger and released projections")
        if self.gate_failures is not None:
            raise ValueError("success cannot include gate failures")
        trusted_context = _trusted_release_context(info)
        if trusted_context.manifest_sha256 != _semantic_subject_sha256(self.manifest):
            raise ValueError("run manifest changed after trusted preflight")
        self._validate_source_revision(self.ledger)
        self._validate_released_projections(
            self.ledger,
            self.projections,
            trusted_context,
        )
        return self

    def _validate_source_revision(self, ledger: CanonicalClaimLedger) -> None:
        for decision in ledger.verification_decisions:
            if decision.source_revision_id != self.provenance.source_revision_id:
                raise ValueError("verification source revision mismatch")
        for relationship in ledger.relationships or []:
            if (
                relationship.evidence_resolution == "resolved"
                and relationship.source_revision_id
                != self.provenance.source_revision_id
            ):
                raise ValueError("relationship source revision mismatch")

    def _validate_released_projections(
        self,
        ledger: CanonicalClaimLedger,
        projections: InvestigationProjections,
        trusted_context: _TrustedInvestigationValidationContext,
    ) -> None:
        summary = projections.summary
        analysis = projections.analysis
        summary_claim_ids = set(summary.released_claim_refs)
        analysis_claim_ids = set(analysis.released_claim_refs)
        if summary_claim_ids != analysis_claim_ids:
            raise ValueError(
                "Summary and Analysis must project the same released claims"
            )

        claim_by_id = {claim.claim_id: claim for claim in ledger.claims}
        concept_by_id = {
            concept.concept_id: concept for concept in ledger.concepts or []
        }
        evidence_by_id = {
            evidence.evidence_id: evidence for evidence in ledger.evidence
        }
        _require_refs(
            list(summary_claim_ids),
            set(claim_by_id),
            "released claim refs",
        )

        decision_by_id = {
            decision.verification_id: decision
            for decision in ledger.verification_decisions
        }
        if set(trusted_context.verification_eligibility) != set(decision_by_id):
            raise ValueError(
                "trusted verifier registry must cover the exact verification ledger"
            )
        resolved_decision_ids = {
            decision.verification_id
            for decision in ledger.verification_decisions
            if decision.evidence_resolution == "resolved"
        }
        if set(trusted_context.selector_attestations) != resolved_decision_ids:
            raise ValueError(
                "trusted selector registry must cover every resolved decision"
            )
        for decision_id, decision in decision_by_id.items():
            claim = (
                claim_by_id.get(decision.canonical_claim_ref)
                if decision.canonical_claim_ref
                else None
            )
            assessment = trusted_context.verification_eligibility[decision_id]
            if assessment.eligibility != decision.projection_eligibility:
                raise ValueError(
                    "verification eligibility requires trusted verifier context"
                )
            if (
                decision.eligibility_artifact_ref is not None
                and assessment.artifact_ref != decision.eligibility_artifact_ref
            ):
                raise ValueError(
                    "verification eligibility artifact does not match trusted context"
                )
            if assessment.subject_sha256 != _verification_subject_sha256(
                decision,
                claim,
            ):
                raise ValueError(
                    "verification semantics do not match trusted verifier context"
                )
            if decision.evidence_resolution == "resolved":
                self._validate_selector_attestation(
                    decision_id,
                    decision.resolution_artifact_ref,
                    decision.source_revision_id,
                    decision.verified_evidence_refs or [],
                    evidence_by_id,
                    trusted_context.selector_attestations,
                )

        decisions_by_claim: dict[str, list[VerificationDecision]] = {}
        for decision in ledger.verification_decisions:
            if (
                decision.canonical_claim_ref
                and decision.projection_eligibility != "withheld"
            ):
                decisions_by_claim.setdefault(
                    decision.canonical_claim_ref,
                    [],
                ).append(decision)

        if summary_claim_ids != set(decisions_by_claim):
            raise ValueError(
                "released projections must include every non-withheld verified claim"
            )

        for claim_id in summary_claim_ids:
            claim = claim_by_id[claim_id]
            decisions = decisions_by_claim.get(claim_id, [])
            if not decisions:
                raise ValueError("released claims require an eligible verification")
            if claim.epistemic_status != "fact":
                raise ValueError(
                    "non-factual intelligence requires its dedicated typed contract"
                )
            if any(
                decision.evidence_resolution != "resolved"
                or decision.source_revision_id != self.provenance.source_revision_id
                for decision in decisions
            ):
                raise ValueError(
                    "released claim evidence must resolve on this revision"
                )
            verified_refs = {
                evidence_ref
                for decision in decisions
                for evidence_ref in decision.verified_evidence_refs or []
            }
            if not set(claim.evidence_refs).issubset(verified_refs):
                raise ValueError("released claim evidence must be verifier-attested")
            if not claim.candidate_refs:
                raise ValueError("released claims must retain source candidate refs")
            if claim.disposition == "unverifiable":
                raise ValueError("unverifiable claims cannot be released")
            if claim.disposition != "supported" and not (
                claim.requires_human_verification
            ):
                raise ValueError("qualified claims require human verification")

            expected_eligibility = (
                "factual" if claim.disposition == "supported" else "non_factual"
            )
            if not all(
                decision.projection_eligibility == expected_eligibility
                for decision in decisions
            ):
                raise ValueError("claim epistemics do not match projection eligibility")

            self._validate_risk_assessment(
                claim_id,
                claim,
                claim.risk_tier,
                claim.risk_screening_artifact_ref,
                trusted_context,
            )
            if claim.risk_tier == "high_risk":
                raise ValueError("high-risk assertions must remain typed hypotheses")
            if claim.premise_claim_refs:
                self._require_released_supported_premises(
                    claim.premise_claim_refs,
                    summary_claim_ids,
                    claim_by_id,
                    "released claim premise refs",
                )

        insight_by_id = {
            insight.insight_id: insight for insight in ledger.insights or []
        }
        hypothesis_by_id = {
            hypothesis.hypothesis_id: hypothesis
            for hypothesis in ledger.hypotheses or []
        }
        action_by_id = {
            action.action_id: action for action in ledger.verification_actions or []
        }
        reasoning_ids = set(insight_by_id) | set(hypothesis_by_id) | set(action_by_id)
        if set(trusted_context.reasoning_eligibility) != reasoning_ids:
            raise ValueError(
                "trusted reasoning registry must cover the exact reasoning ledger"
            )

        summary_reasoning_refs = {
            "insight": set(summary.insight_refs or []),
            "hypothesis": set(summary.hypothesis_refs or []),
            "verification_action": set(summary.verification_action_refs or []),
        }
        analysis_reasoning_refs = {
            "insight": set(analysis.insight_refs or []),
            "hypothesis": set(analysis.hypothesis_refs or []),
            "verification_action": set(analysis.verification_action_refs or []),
        }
        if summary_reasoning_refs != analysis_reasoning_refs:
            raise ValueError(
                "Summary and Analysis must project the same typed reasoning set"
            )

        typed_collections: tuple[
            tuple[str, dict[str, Any], ProjectionEligibility], ...
        ] = (
            ("insight", insight_by_id, "factual"),
            ("hypothesis", hypothesis_by_id, "non_factual"),
            ("verification_action", action_by_id, "non_factual"),
        )
        for label, items, required_eligibility in typed_collections:
            for item_ref, item in items.items():
                assessment = trusted_context.reasoning_eligibility[item_ref]
                if assessment.eligibility != item.projection_eligibility:
                    raise ValueError(
                        f"released {label} eligibility lacks trusted binding"
                    )
                if assessment.artifact_ref != item.eligibility_artifact_ref:
                    raise ValueError(f"released {label} eligibility artifact mismatch")
                if assessment.subject_sha256 != _semantic_subject_sha256(item):
                    raise ValueError(
                        f"released {label} semantics changed after trusted review"
                    )
            projected_refs = summary_reasoning_refs[label]
            _require_refs(
                list(projected_refs),
                set(items),
                f"released {label} refs",
            )
            expected_refs = {
                item_ref
                for item_ref, item in items.items()
                if item.projection_eligibility != "withheld"
            }
            if projected_refs != expected_refs:
                raise ValueError(
                    f"released {label} refs must match trusted reasoning eligibility"
                )
            if any(
                items[item_ref].projection_eligibility != required_eligibility
                for item_ref in projected_refs
            ):
                raise ValueError(f"released {label} has invalid trusted eligibility")

        for insight_ref in summary_reasoning_refs["insight"]:
            insight = insight_by_id[insight_ref]
            if insight.counterevidence_status == "not_evaluated":
                raise ValueError(
                    "released insight requires completed counterevidence review"
                )
            self._require_released_supported_premises(
                insight.premise_claim_refs,
                summary_claim_ids,
                claim_by_id,
                "released insight premise refs",
            )
            premise_evidence = {
                evidence_ref
                for claim_ref in insight.premise_claim_refs
                for evidence_ref in claim_by_id[claim_ref].evidence_refs
            }
            if not set(insight.evidence_refs).issubset(premise_evidence):
                raise ValueError("insight evidence must originate from its premises")
            if insight.counterevidence_claim_refs:
                _require_refs(
                    insight.counterevidence_claim_refs,
                    summary_claim_ids,
                    "released insight counterevidence refs",
                )
            self._validate_risk_assessment(
                insight_ref,
                insight,
                insight.risk_tier,
                insight.risk_screening_artifact_ref,
                trusted_context,
            )

        for hypothesis_ref in summary_reasoning_refs["hypothesis"]:
            hypothesis = hypothesis_by_id[hypothesis_ref]
            self._require_released_supported_premises(
                hypothesis.premise_claim_refs,
                summary_claim_ids,
                claim_by_id,
                "released hypothesis premise refs",
            )
            if hypothesis.counterevidence_claim_refs:
                _require_refs(
                    hypothesis.counterevidence_claim_refs,
                    summary_claim_ids,
                    "released hypothesis counterevidence refs",
                )
            hypothesis_evidence = {
                evidence_ref
                for claim_ref in (
                    hypothesis.premise_claim_refs
                    + (hypothesis.counterevidence_claim_refs or [])
                )
                for evidence_ref in claim_by_id[claim_ref].evidence_refs
            }
            if not set(hypothesis.evidence_refs).issubset(hypothesis_evidence):
                raise ValueError(
                    "hypothesis evidence must originate from premise or "
                    "counterevidence claims"
                )
            self._validate_risk_assessment(
                hypothesis_ref,
                hypothesis,
                hypothesis.risk_tier,
                hypothesis.risk_screening_artifact_ref,
                trusted_context,
            )

        for action_ref in summary_reasoning_refs["verification_action"]:
            action = action_by_id[action_ref]
            if action.linked_claim_refs:
                _require_refs(
                    action.linked_claim_refs,
                    summary_claim_ids,
                    "released verification action claim refs",
                )
            if action.linked_hypothesis_refs:
                _require_refs(
                    action.linked_hypothesis_refs,
                    summary_reasoning_refs["hypothesis"],
                    "released verification action hypothesis refs",
                )
            if action.linked_concept_refs:
                _require_refs(
                    action.linked_concept_refs,
                    set(concept_by_id),
                    "released verification action concept refs",
                )
            released_targets = (
                summary_claim_ids
                | summary_reasoning_refs["hypothesis"]
                | set(concept_by_id)
            )
            _require_refs(
                [action.target_ref],
                released_targets,
                "released verification action target refs",
            )
            action_evidence = {
                evidence_ref
                for claim_ref in action.linked_claim_refs or []
                for evidence_ref in claim_by_id[claim_ref].evidence_refs
            }
            action_evidence.update(
                evidence_ref
                for hypothesis_ref in action.linked_hypothesis_refs or []
                for evidence_ref in hypothesis_by_id[hypothesis_ref].evidence_refs
            )
            action_evidence.update(
                evidence_ref
                for concept_ref in action.linked_concept_refs or []
                for evidence_ref in concept_by_id[concept_ref].evidence_refs
            )
            if not set(action.evidence_refs).issubset(action_evidence):
                raise ValueError(
                    "verification action evidence must originate from linked items"
                )

        self._validate_theme_and_narrative_projection(
            summary,
            summary_claim_ids,
            claim_by_id,
            insight_by_id,
            summary_reasoning_refs,
        )
        self._validate_analysis_projection(analysis, summary_claim_ids, claim_by_id)
        self._validate_relationship_projection(
            analysis,
            ledger,
            summary_claim_ids,
            claim_by_id,
            evidence_by_id,
            trusted_context,
        )

    @staticmethod
    def _validate_selector_attestation(
        subject_ref: str,
        artifact_ref: str | None,
        source_revision_id: str,
        evidence_refs: list[str],
        evidence_by_id: dict[str, EvidenceSpan],
        registry: Mapping[str, _TrustedSelectorAttestation],
    ) -> None:
        attestation = registry.get(subject_ref)
        if attestation is None:
            raise ValueError("released evidence requires trusted T2 attestation")
        if artifact_ref != attestation.artifact_ref:
            raise ValueError("selector artifact ref does not match trusted T2 context")
        if source_revision_id != attestation.source_revision_id:
            raise ValueError("selector source revision does not match trusted context")
        if set(evidence_refs) != set(attestation.evidence):
            raise ValueError("selector evidence refs do not match trusted context")
        for evidence_ref in evidence_refs:
            evidence = evidence_by_id[evidence_ref]
            fingerprint = attestation.evidence[evidence_ref]
            if sha256_utf8(evidence.quote_exact) != evidence.quote_sha256:
                raise ValueError("evidence quote bytes do not match quote_sha256")
            if (
                evidence.segment_id != fingerprint.segment_id
                or evidence.quote_sha256 != fingerprint.quote_sha256
                or evidence.source_sha256 != fingerprint.source_sha256
                or evidence.quote_prefix != fingerprint.quote_prefix
                or evidence.quote_suffix != fingerprint.quote_suffix
                or evidence.raw_char_start != fingerprint.raw_char_start
                or evidence.raw_char_end != fingerprint.raw_char_end
                or evidence.start_seconds != fingerprint.start_seconds
                or evidence.end_seconds != fingerprint.end_seconds
                or evidence.speaker_id != fingerprint.speaker_id
            ):
                raise ValueError(
                    "evidence selector fields do not match trusted T2 context"
                )

    @staticmethod
    def _validate_risk_assessment(
        subject_ref: str,
        subject: BaseModel,
        declared_risk_tier: RiskTier | None,
        artifact_ref: str | None,
        trusted_context: _TrustedInvestigationValidationContext,
    ) -> None:
        assessment = trusted_context.risk_assessments.get(subject_ref)
        if assessment is None:
            raise ValueError("released assertions require trusted risk screening")
        if declared_risk_tier is None:
            raise ValueError("release-safe assertions require an explicit risk tier")
        if declared_risk_tier != assessment.risk_tier:
            raise ValueError("declared risk tier does not match trusted screening")
        if artifact_ref is None or artifact_ref != assessment.artifact_ref:
            raise ValueError("risk screening artifact does not match trusted context")
        if assessment.subject_sha256 != _semantic_subject_sha256(subject):
            raise ValueError("risk-screened semantics changed after trusted review")

    @staticmethod
    def _require_released_supported_premises(
        premise_refs: list[str],
        released_claim_ids: set[str],
        claim_by_id: dict[str, GroundedClaim],
        label: str,
    ) -> None:
        _require_refs(premise_refs, released_claim_ids, label)
        for premise_ref in premise_refs:
            premise = claim_by_id[premise_ref]
            if premise.epistemic_status != "fact" or premise.disposition != "supported":
                raise ValueError(f"{label} require supported fact premises")

    @staticmethod
    def _validate_theme_and_narrative_projection(
        summary: SummaryProjection,
        released_claim_ids: set[str],
        claim_by_id: dict[str, GroundedClaim],
        insight_by_id: dict[str, EvidenceBackedInsight],
        reasoning_refs: dict[str, set[str]],
    ) -> None:
        theme_ids: set[str] = set()
        primary_claim_ids: set[str] = set()
        primary_reasoning_ids: dict[str, set[str]] = {
            "insight": set(),
            "hypothesis": set(),
            "verification_action": set(),
        }
        for theme in summary.themes:
            if theme.theme_id in theme_ids:
                raise ValueError("duplicate primary theme ID")
            theme_ids.add(theme.theme_id)
            _require_refs(
                theme.claim_refs,
                released_claim_ids,
                "summary theme claim refs",
            )
            overlap = primary_claim_ids & set(theme.claim_refs)
            if overlap:
                raise ValueError(
                    "released claims cannot belong to multiple primary themes: "
                    + ", ".join(sorted(overlap))
                )
            primary_claim_ids.update(theme.claim_refs)
            theme_reasoning_refs = {
                "insight": set(theme.insight_refs or []),
                "hypothesis": set(theme.hypothesis_refs or []),
                "verification_action": set(theme.verification_action_refs or []),
            }
            for label, refs in theme_reasoning_refs.items():
                _require_refs(
                    refs=list(refs),
                    available=reasoning_refs[label],
                    label=f"theme {label} refs",
                )
                overlap = primary_reasoning_ids[label] & refs
                if overlap:
                    raise ValueError(
                        f"released {label} cannot belong to multiple primary themes"
                    )
                primary_reasoning_ids[label].update(refs)
        if primary_claim_ids != released_claim_ids:
            raise ValueError("every released claim requires exactly one primary theme")
        for label, refs in reasoning_refs.items():
            if primary_reasoning_ids[label] != refs:
                raise ValueError(
                    f"every released {label} requires exactly one primary theme"
                )

        groups = summary.narrative.thematic_groups
        if not groups:
            raise ValueError("released summary requires thematic narrative groups")
        group_theme_refs = [group.theme_ref for group in groups]
        if len(group_theme_refs) != len(set(group_theme_refs)):
            raise ValueError("primary themes cannot have duplicate narrative groups")
        if set(group_theme_refs) != theme_ids:
            raise ValueError("every primary theme requires one narrative group")

        sentences = list(summary.narrative.overview)
        for group in groups:
            sentences.extend(group.sentences)
        for sentence in sentences:
            _require_refs(
                sentence.claim_refs,
                released_claim_ids,
                "released narrative claim refs",
            )
            sentence_insight_refs = sentence.insight_refs or []
            _require_refs(
                sentence_insight_refs,
                reasoning_refs["insight"],
                "released narrative insight refs",
            )
            if sentence.sentence_kind != "factual" and sentence_insight_refs:
                raise ValueError("evidence-backed insights require factual synthesis")
            if sentence.sentence_kind != "factual":
                continue
            for claim_ref in sentence.claim_refs:
                claim = claim_by_id[claim_ref]
                if claim.epistemic_status != "fact" or claim.disposition != "supported":
                    raise ValueError(
                        "factual narrative requires fact + supported claims"
                    )
            for insight_ref in sentence_insight_refs:
                insight = insight_by_id[insight_ref]
                if not set(insight.premise_claim_refs).issubset(sentence.claim_refs):
                    raise ValueError(
                        "factual insight sentence must map every premise claim"
                    )

        narrated_insight_refs = {
            insight_ref
            for sentence in sentences
            for insight_ref in sentence.insight_refs or []
        }
        if narrated_insight_refs != reasoning_refs["insight"]:
            raise ValueError(
                "every released insight requires a factual sentence mapping"
            )

    @staticmethod
    def _validate_analysis_projection(
        analysis: AnalysisProjection,
        released_claim_ids: set[str],
        claim_by_id: dict[str, GroundedClaim],
    ) -> None:
        buckets: dict[str, list[str]] = {
            "fact": analysis.fact_claim_refs or [],
            "qualified": analysis.qualified_claim_refs or [],
        }
        bucket_refs = [claim_ref for refs in buckets.values() for claim_ref in refs]
        if len(bucket_refs) != len(set(bucket_refs)):
            raise ValueError("analysis epistemic buckets cannot overlap")
        if set(bucket_refs) != released_claim_ids:
            raise ValueError("analysis epistemic buckets must cover released claims")
        for claim_ref in buckets["fact"]:
            claim = claim_by_id[claim_ref]
            if claim.epistemic_status != "fact" or claim.disposition != "supported":
                raise ValueError("analysis fact bucket requires supported facts")
        for claim_ref in buckets["qualified"]:
            claim = claim_by_id[claim_ref]
            if claim.disposition == "supported" or not (
                claim.requires_human_verification
            ):
                raise ValueError(
                    "analysis qualified bucket requires visible human review"
                )

    def _validate_relationship_projection(
        self,
        analysis: AnalysisProjection,
        ledger: CanonicalClaimLedger,
        released_claim_ids: set[str],
        claim_by_id: dict[str, GroundedClaim],
        evidence_by_id: dict[str, EvidenceSpan],
        trusted_context: _TrustedInvestigationValidationContext,
    ) -> None:
        relationship_by_id = {
            relationship.relationship_id: relationship
            for relationship in ledger.relationships or []
        }
        if set(trusted_context.relationship_eligibility) != set(relationship_by_id):
            raise ValueError(
                "trusted relationship registry must cover the exact relationship ledger"
            )
        resolved_relationship_ids = {
            relationship_id
            for relationship_id, relationship in relationship_by_id.items()
            if relationship.evidence_resolution == "resolved"
        }
        if set(trusted_context.relationship_attestations) != resolved_relationship_ids:
            raise ValueError(
                "trusted selector registry must cover every resolved relationship"
            )
        for relationship_id, relationship in relationship_by_id.items():
            assessment = trusted_context.relationship_eligibility[relationship_id]
            if assessment.eligibility != relationship.projection_eligibility:
                raise ValueError(
                    "relationship eligibility requires trusted verifier context"
                )
            if (
                relationship.eligibility_artifact_ref is not None
                and assessment.artifact_ref != relationship.eligibility_artifact_ref
            ):
                raise ValueError("relationship eligibility artifact mismatch")
            if assessment.subject_sha256 != _semantic_subject_sha256(relationship):
                raise ValueError("relationship semantics changed after trusted review")
            if relationship.evidence_resolution == "resolved":
                self._validate_selector_attestation(
                    relationship_id,
                    relationship.resolution_artifact_ref,
                    relationship.source_revision_id or "",
                    relationship.evidence_refs,
                    evidence_by_id,
                    trusted_context.relationship_attestations,
                )
        relationship_refs = analysis.relationship_refs or []
        _require_refs(
            relationship_refs,
            set(relationship_by_id),
            "analysis relationship refs",
        )
        expected_relationship_refs = {
            relationship_id
            for relationship_id, relationship in relationship_by_id.items()
            if relationship.projection_eligibility != "withheld"
        }
        if set(relationship_refs) != expected_relationship_refs:
            raise ValueError(
                "released relationship refs must match trusted eligibility"
            )
        for relationship_ref in relationship_refs:
            relationship = relationship_by_id[relationship_ref]
            expected_eligibility = (
                "factual"
                if relationship.epistemic_status == "fact"
                and relationship.disposition == "supported"
                else "non_factual"
            )
            if relationship.projection_eligibility != expected_eligibility:
                raise ValueError(
                    "relationship epistemics do not match projection eligibility"
                )
            if relationship.evidence_resolution != "resolved":
                raise ValueError("released relationship evidence must be resolved")
            if relationship.source_revision_id != self.provenance.source_revision_id:
                raise ValueError("released relationship revision mismatch")
            if relationship.disposition == "unverifiable":
                raise ValueError("unverifiable relationships cannot be released")
            if relationship.disposition != "supported" and not (
                relationship.requires_human_verification
            ):
                raise ValueError(
                    "non-supported relationships require human verification"
                )
            if relationship.epistemic_status != "fact":
                if not relationship.requires_human_verification:
                    raise ValueError(
                        "non-factual relationships require human verification"
                    )
                if not relationship.premise_claim_refs:
                    raise ValueError(
                        "non-factual relationships require premise claim refs"
                    )
                _require_refs(
                    relationship.premise_claim_refs,
                    released_claim_ids,
                    "released relationship premise refs",
                )
                self._require_released_supported_premises(
                    relationship.premise_claim_refs,
                    released_claim_ids,
                    claim_by_id,
                    "released relationship premise refs",
                )
            self._validate_risk_assessment(
                relationship_ref,
                relationship,
                relationship.risk_tier,
                relationship.risk_screening_artifact_ref,
                trusted_context,
            )


InvestigationSummaryProjection = SummaryProjection
InvestigationAnalysisProjection = AnalysisProjection


def investigation_run_json_schema() -> dict[str, Any]:
    """Return the release-safe lifecycle schema owned by InvestigationRun."""

    return InvestigationRun.model_json_schema()


def investigation_run_schema_sha256() -> str:
    """Return the stable canonical hash for the InvestigationRun schema."""

    return sha256_canonical_json(investigation_run_json_schema())


def build_investigation_run_manifest(
    *,
    prompt: str,
    prompt_version: str,
    model_id: str,
    model_digest: str,
    provider: str,
    decoding_config: Mapping[str, Any],
    source_module_hashes: Mapping[str, str],
    git_revision: str,
    git_dirty: bool,
    git_untracked: bool,
) -> InvestigationRunManifest:
    """Build the discriminated manifest for a release-safe InvestigationRun."""

    return InvestigationRunManifest(
        prompt_version=prompt_version,
        prompt_sha256=sha256_utf8(prompt),
        json_schema_sha256=investigation_run_schema_sha256(),
        model_id=model_id,
        model_digest=model_digest,
        provider=provider,
        decoding_config=dict(decoding_config),
        source_module_hashes=dict(source_module_hashes),
        git_revision=git_revision,
        git_dirty=git_dirty,
        git_untracked=git_untracked,
    )


def validate_investigation_run(
    value: Any,
    *,
    trusted_context: _TrustedInvestigationValidationContext | None = None,
) -> InvestigationRun:
    """Validate a release-safe lifecycle run and all shared projections."""

    context = (
        {_VALIDATION_CONTEXT_KEY: trusted_context}
        if trusted_context is not None
        else None
    )
    if isinstance(value, str):
        return InvestigationRun.model_validate_json(value, context=context)
    return InvestigationRun.model_validate(value, context=context)


__all__ = [
    "AnalysisProjection",
    "CanonicalClaimLedger",
    "DiscoveryCandidate",
    "GateFailure",
    "InvestigationAnalysisProjection",
    "InvestigationProjections",
    "InvestigationRun",
    "InvestigationRunManifest",
    "InvestigationSummaryProjection",
    "SummaryProjection",
    "VerificationDecision",
    "build_investigation_run_manifest",
    "investigation_run_json_schema",
    "investigation_run_schema_sha256",
    "validate_investigation_run",
]
