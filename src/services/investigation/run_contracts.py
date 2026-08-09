"""Release lifecycle, trusted registries, and projections for InvestigationRun."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from types import MappingProxyType
from typing import Any, Literal
from weakref import WeakKeyDictionary

from pydantic import (
    BaseModel,
    Field,
    JsonValue,
    ValidationError,
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
    NarrativeAttestationArtifact,
    NarrativeClaimClassification,
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
from .evidence_selector import VerifiedEvidenceSelectorArtifact
from .narrative_attestation import (
    CANONICAL_THEME_ID,
    CANONICAL_THEME_TITLE,
    NARRATIVE_PRODUCER_DIGEST,
    classify_released_claim,
    expected_narrative_evidence_refs,
    expected_narrative_sentence_kind,
    expected_narrative_sentence_text,
    narrative_subject_sha256,
)
from .reasoning_contracts import (
    EvidenceBackedInsight,
    Hypothesis,
    VerificationAction,
)


def _validate_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256")


def _freeze_trusted_snapshot(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return (
            value.__class__.__qualname__,
            _freeze_trusted_snapshot(
                value.model_dump(mode="json", exclude_none=True)
            ),
        )
    if is_dataclass(value) and not isinstance(value, type):
        return (
            value.__class__.__qualname__,
            tuple(
                (field.name, _freeze_trusted_snapshot(getattr(value, field.name)))
                for field in fields(value)
            ),
        )
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (
                    str(key),
                    _freeze_trusted_snapshot(item),
                )
                for key, item in value.items()
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_trusted_snapshot(item) for item in value)
    return value


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
    normalized_char_start: int | None = None
    normalized_char_end: int | None = None
    occurrence_index: int | None = None
    case_id: str | None = None
    file_id: str | None = None
    source_id: str | None = None
    source_revision_sha256: str | None = None
    raw_transcript_sha256: str | None = None
    segment_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("trusted evidence segment_id must be non-blank")
        _validate_sha256(self.quote_sha256, "trusted quote hash")
        _validate_sha256(self.source_sha256, "trusted source hash")
        for value, label in (
            (self.source_revision_sha256, "trusted source revision hash"),
            (self.raw_transcript_sha256, "trusted raw transcript hash"),
            (self.segment_sha256, "trusted segment hash"),
        ):
            if value is not None:
                _validate_sha256(value, label)
        if (
            self.segment_sha256 is not None
            and self.segment_sha256 != self.source_sha256
        ):
            raise ValueError("trusted EvidenceSpan source hash must match segment hash")


@dataclass(frozen=True)
class _TrustedSelectorAttestation:
    artifact_ref: str
    source_revision_id: str
    evidence: Mapping[str, _TrustedEvidenceFingerprint]
    source_provenance_verified: bool = False
    source_revision_sha256: str | None = None
    raw_transcript_sha256: str | None = None
    normalized_transcript_sha256: str | None = None
    audio_sha256: str | None = None
    segment_count: int | None = None

    def __post_init__(self) -> None:
        if not self.artifact_ref.strip() or not self.source_revision_id.strip():
            raise ValueError("trusted selector attestation fields must be non-blank")
        if not self.evidence:
            raise ValueError("trusted selector attestation requires evidence")
        if any(not evidence_id.strip() for evidence_id in self.evidence):
            raise ValueError("trusted selector evidence IDs must be non-blank")
        provenance_fields = (
            self.source_revision_sha256,
            self.raw_transcript_sha256,
            self.normalized_transcript_sha256,
            self.segment_count,
        )
        if self.source_provenance_verified:
            if any(value is None for value in provenance_fields):
                raise ValueError("verified selector source provenance is incomplete")
            _validate_sha256(
                self.source_revision_sha256 or "",
                "trusted source revision hash",
            )
            _validate_sha256(
                self.raw_transcript_sha256 or "",
                "trusted raw transcript hash",
            )
            _validate_sha256(
                self.normalized_transcript_sha256 or "",
                "trusted normalized transcript hash",
            )
            if self.audio_sha256 is not None:
                _validate_sha256(self.audio_sha256, "trusted audio hash")
            if self.segment_count is None or self.segment_count < 1:
                raise ValueError("trusted source segment count must be positive")
        elif any(value is not None for value in provenance_fields) or (
            self.audio_sha256 is not None
        ):
            raise ValueError("unverified selector cannot carry source provenance")
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


def _risk_subject_sha256(subject: BaseModel) -> str:
    """Hash risk-screened semantics without the circular attestation reference."""

    payload = subject.model_dump(mode="json", exclude_none=True)
    payload.pop("risk_screening_artifact_ref", None)
    return sha256_canonical_json(
        {
            "subject_class": subject.__class__.__name__,
            "subject": payload,
        }
    )


def _verification_subject_sha256(
    decision: "VerificationDecision",
    claim: GroundedClaim | None,
    candidate: "DiscoveryCandidate",
) -> str:
    return sha256_canonical_json(
        {
            "verification": decision.model_dump(mode="json", exclude_none=True),
            "candidate": candidate.model_dump(mode="json", exclude_none=True),
            "canonical_claim_sha256": (
                _semantic_subject_sha256(claim) if claim is not None else None
            ),
        }
    )


class _TrustedInvestigationValidationContext:
    """Opaque in-process trust boundary populated by future T2/T4 services."""

    selector_attestations: Mapping[str, _TrustedSelectorAttestation]
    relationship_attestations: Mapping[str, _TrustedSelectorAttestation]
    risk_assessments: Mapping[str, _TrustedRiskAssessment]
    verification_eligibility: Mapping[str, _TrustedEligibilityAssessment]
    relationship_eligibility: Mapping[str, _TrustedEligibilityAssessment]
    reasoning_eligibility: Mapping[str, _TrustedEligibilityAssessment]
    narrative_attestations: Mapping[str, NarrativeAttestationArtifact]
    manifest_sha256: str
    _sealed: bool
    __slots__ = (
        "selector_attestations",
        "relationship_attestations",
        "risk_assessments",
        "verification_eligibility",
        "relationship_eligibility",
        "reasoning_eligibility",
        "narrative_attestations",
        "manifest_sha256",
        "_sealed",
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
        narrative_attestations: Mapping[str, NarrativeAttestationArtifact],
        manifest_sha256: str,
        _authority: object,
    ) -> None:
        if _authority is not _TRUSTED_CONTEXT_AUTHORITY:
            raise TypeError("trusted validation context requires internal authority")
        object.__setattr__(
            self,
            "selector_attestations",
            MappingProxyType(dict(selector_attestations)),
        )
        object.__setattr__(
            self,
            "relationship_attestations",
            MappingProxyType(dict(relationship_attestations)),
        )
        object.__setattr__(
            self,
            "risk_assessments",
            MappingProxyType(dict(risk_assessments)),
        )
        object.__setattr__(
            self,
            "verification_eligibility",
            MappingProxyType(dict(verification_eligibility)),
        )
        object.__setattr__(
            self,
            "relationship_eligibility",
            MappingProxyType(dict(relationship_eligibility)),
        )
        object.__setattr__(
            self,
            "reasoning_eligibility",
            MappingProxyType(dict(reasoning_eligibility)),
        )
        object.__setattr__(
            self,
            "narrative_attestations",
            MappingProxyType(dict(narrative_attestations)),
        )
        _validate_sha256(manifest_sha256, "trusted manifest hash")
        object.__setattr__(self, "manifest_sha256", manifest_sha256)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("trusted validation context is immutable")
        object.__setattr__(self, name, value)

    def validate_source_provenance(self, provenance: SourceProvenance) -> None:
        """Bind run provenance to every replayed production T2 artifact."""

        try:
            provenance = SourceProvenance.model_validate_json(
                provenance.model_dump_json(exclude_none=True)
            )
        except ValidationError as exc:
            raise ValueError("invalid run source provenance") from exc
        attestations = (
            *self.selector_attestations.values(),
            *self.relationship_attestations.values(),
        )
        for attestation in attestations:
            if not attestation.source_provenance_verified:
                continue
            if attestation.source_revision_id != provenance.source_revision_id:
                raise ValueError("trusted selector source revision mismatch")
            if provenance.source_revision_id != (
                f"srcv1:{attestation.source_revision_sha256}"
            ):
                raise ValueError("trusted selector source revision ID is not canonical")
            if attestation.raw_transcript_sha256 != provenance.raw_transcript_sha256:
                raise ValueError(
                    "run raw transcript hash does not match trusted source"
                )
            if (
                attestation.normalized_transcript_sha256
                != provenance.normalized_transcript_sha256
            ):
                raise ValueError(
                    "run normalized transcript hash does not match trusted source"
                )
            if attestation.audio_sha256 != provenance.audio_sha256:
                raise ValueError("run audio hash does not match trusted source")
            if attestation.segment_count != provenance.segment_count:
                raise ValueError("run segment count does not match trusted source")


_TRUSTED_CONTEXT_AUTHORITY = object()
_VALIDATION_CONTEXT_KEY = "investigation_release_authority"


def _build_release_authority_bridge():
    minter_taken = False
    minted: WeakKeyDictionary[
        object,
        tuple[_TrustedInvestigationValidationContext, tuple[Any, ...]],
    ] = WeakKeyDictionary()

    class _OneShotReleaseAuthority:
        __slots__ = ("__weakref__",)

    def context_snapshot(
        trusted_context: _TrustedInvestigationValidationContext,
    ) -> tuple[Any, ...]:
        return (
            _freeze_trusted_snapshot(trusted_context.selector_attestations),
            _freeze_trusted_snapshot(trusted_context.relationship_attestations),
            _freeze_trusted_snapshot(trusted_context.risk_assessments),
            _freeze_trusted_snapshot(trusted_context.verification_eligibility),
            _freeze_trusted_snapshot(trusted_context.relationship_eligibility),
            _freeze_trusted_snapshot(trusted_context.reasoning_eligibility),
            _freeze_trusted_snapshot(trusted_context.narrative_attestations),
            trusted_context.manifest_sha256,
        )

    def take_minter():
        nonlocal minter_taken
        if minter_taken:
            raise RuntimeError("release authority minter is already installed")
        minter_taken = True

        def mint(
            trusted_context: _TrustedInvestigationValidationContext,
        ) -> object:
            if not isinstance(
                trusted_context,
                _TrustedInvestigationValidationContext,
            ):
                raise TypeError("release authority requires a trusted context")
            authority = _OneShotReleaseAuthority()
            minted[authority] = (trusted_context, context_snapshot(trusted_context))
            return authority

        return mint

    def consume(value: object) -> _TrustedInvestigationValidationContext:
        if type(value) is not _OneShotReleaseAuthority:
            raise ValueError(
                "success requires one-shot authority from the release adapter"
            )
        trusted = minted.pop(value, None)
        if trusted is None:
            raise ValueError(
                "success requires one-shot authority from the release adapter"
            )
        trusted_context, expected_snapshot = trusted
        if context_snapshot(trusted_context) != expected_snapshot:
            raise ValueError("trusted validation context changed after authority mint")
        return trusted_context

    return take_minter, consume


(
    _take_release_authority_minter,
    _consume_release_authority,
) = _build_release_authority_bridge()
del _build_release_authority_bridge


def _build_trusted_investigation_validation_context(
    *,
    selector_attestations: Mapping[str, _TrustedSelectorAttestation],
    relationship_attestations: Mapping[str, _TrustedSelectorAttestation],
    risk_assessments: Mapping[str, _TrustedRiskAssessment],
    verification_eligibility: Mapping[str, _TrustedEligibilityAssessment],
    relationship_eligibility: Mapping[str, _TrustedEligibilityAssessment],
    reasoning_eligibility: Mapping[str, _TrustedEligibilityAssessment] | None = None,
    narrative_attestations: Mapping[str, NarrativeAttestationArtifact] | None = None,
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
        narrative_attestations=narrative_attestations or {},
        manifest_sha256=manifest_sha256,
        _authority=_TRUSTED_CONTEXT_AUTHORITY,
    )


def _selector_attestations_from_verified_artifacts(
    artifacts: Mapping[str, VerifiedEvidenceSelectorArtifact],
    *,
    subject_kind: Literal["verification", "relationship"],
) -> dict[str, _TrustedSelectorAttestation]:
    attestations: dict[str, _TrustedSelectorAttestation] = {}
    for subject_ref, verified in artifacts.items():
        if not isinstance(verified, VerifiedEvidenceSelectorArtifact):
            raise TypeError("trusted selectors require a verified T2 artifact")
        artifact = verified.artifact
        if artifact.subject_ref != subject_ref:
            raise ValueError(
                "selector artifact subject_ref does not match registry key"
            )
        if artifact.subject_kind != subject_kind:
            raise ValueError("selector artifact subject kind mismatch")
        evidence = {
            selector.evidence_id: _TrustedEvidenceFingerprint(
                segment_id=selector.segment_id,
                quote_sha256=selector.quote_sha256,
                source_sha256=selector.source_sha256,
                quote_prefix=selector.prefix or None,
                quote_suffix=selector.suffix or None,
                raw_char_start=selector.raw_char_start,
                raw_char_end=selector.raw_char_end,
                start_seconds=selector.start_seconds,
                end_seconds=selector.end_seconds,
                speaker_id=selector.speaker_id,
                normalized_char_start=selector.normalized_char_start,
                normalized_char_end=selector.normalized_char_end,
                occurrence_index=selector.occurrence_index,
                case_id=selector.scope.case_id,
                file_id=selector.scope.file_id,
                source_id=selector.scope.source_id,
                source_revision_sha256=selector.source_revision_sha256,
                raw_transcript_sha256=selector.raw_transcript_sha256,
                segment_sha256=selector.segment_sha256,
            )
            for selector in artifact.selectors
        }
        attestations[subject_ref] = _TrustedSelectorAttestation(
            artifact_ref=artifact.artifact_id,
            source_revision_id=artifact.source_revision_id,
            evidence=evidence,
            source_provenance_verified=True,
            source_revision_sha256=artifact.source_revision_sha256,
            raw_transcript_sha256=artifact.raw_transcript_sha256,
            normalized_transcript_sha256=artifact.normalized_source_sha256,
            audio_sha256=artifact.audio_sha256,
            segment_count=artifact.segment_count,
        )
    return attestations


def _build_trusted_investigation_validation_context_from_artifacts(
    *,
    selector_artifacts: Mapping[str, VerifiedEvidenceSelectorArtifact],
    relationship_selector_artifacts: Mapping[str, VerifiedEvidenceSelectorArtifact],
    risk_assessments: Mapping[str, _TrustedRiskAssessment],
    verification_eligibility: Mapping[str, _TrustedEligibilityAssessment],
    relationship_eligibility: Mapping[str, _TrustedEligibilityAssessment],
    reasoning_eligibility: Mapping[str, _TrustedEligibilityAssessment] | None = None,
    narrative_attestations: Mapping[str, NarrativeAttestationArtifact] | None = None,
    manifest_sha256: str,
) -> _TrustedInvestigationValidationContext:
    """Build the production T2 trust portion only from replayed artifacts."""

    return _build_trusted_investigation_validation_context(
        selector_attestations=_selector_attestations_from_verified_artifacts(
            selector_artifacts,
            subject_kind="verification",
        ),
        relationship_attestations=_selector_attestations_from_verified_artifacts(
            relationship_selector_artifacts,
            subject_kind="relationship",
        ),
        risk_assessments=risk_assessments,
        verification_eligibility=verification_eligibility,
        relationship_eligibility=relationship_eligibility,
        reasoning_eligibility=reasoning_eligibility,
        narrative_attestations=narrative_attestations,
        manifest_sha256=manifest_sha256,
    )


def _trusted_release_context(
    info: ValidationInfo,
) -> _TrustedInvestigationValidationContext:
    context = info.context
    authority = (
        context.get(_VALIDATION_CONTEXT_KEY) if isinstance(context, Mapping) else None
    )
    return _consume_release_authority(authority)


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
        if self.projection_eligibility in {
            "source_attributed",
            "factual",
        } and self.disposition != "supported":
            raise ValueError(
                "source-attributed or factual eligibility requires supported evidence"
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
    attributed_assertion_candidate_refs: list[str] | None = None
    contradiction_refs: list[str] | None = None
    contradiction_set_sha256: Sha256Hex | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    contradiction_count: int = Field(default=0, ge=0)

    @classmethod
    def _allowed_sparse_empty_paths(cls, value: Any) -> frozenset[tuple[str, ...]]:
        return frozenset({("claims",)})

    @model_validator(mode="after")
    def validate_ledger_graph(self) -> "CanonicalClaimLedger":
        if self.contradiction_count == 0:
            if self.contradiction_refs is not None or (
                self.contradiction_set_sha256 is not None
            ):
                raise ValueError(
                    "empty contradiction state cannot carry refs or a digest"
                )
        else:
            if not self.contradiction_refs or self.contradiction_set_sha256 is None:
                raise ValueError(
                    "non-empty contradiction state requires refs and a digest"
                )
            if len(self.contradiction_refs) != self.contradiction_count:
                raise ValueError("contradiction count must match contradiction refs")
            _ensure_unique(self.contradiction_refs, "contradiction refs")

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
        if self.attributed_assertion_candidate_refs:
            _ensure_unique(
                self.attributed_assertion_candidate_refs,
                "attributed assertion candidate refs",
            )
            _require_refs(
                self.attributed_assertion_candidate_refs,
                candidate_ids,
                "attributed assertion candidate refs",
            )
            decisions_by_candidate = {
                decision.candidate_ref: decision
                for decision in self.verification_decisions
            }
            for candidate_ref in self.attributed_assertion_candidate_refs:
                decision = decisions_by_candidate[candidate_ref]
                if decision.projection_eligibility != "withheld" or (
                    "factual_modality" not in (decision.failure_codes or [])
                ):
                    raise ValueError(
                        "attributed assertions must remain explicitly withheld"
                    )

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
        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in self.candidates
        }
        linked_decisions: dict[str, list[VerificationDecision]] = {}
        for decision in self.verification_decisions:
            if decision.verified_evidence_refs:
                _require_refs(
                    decision.verified_evidence_refs,
                    evidence_ids,
                    "verification evidence refs",
                )
                candidate = candidate_by_id[decision.candidate_ref]
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
                if (
                    claim.claim_type != candidate.claim_type
                    or claim.statement != candidate.statement
                    or claim.polarity != candidate.polarity
                    or claim.epistemic_status != candidate.epistemic_status
                ):
                    raise ValueError(
                        "canonical claim semantics must match every source candidate"
                    )
                expected_eligibility = "non_factual"
                if claim.epistemic_status == "fact" and claim.disposition == "supported":
                    expected_eligibility = (
                        "source_attributed"
                        if claim.factual_scope == "verified_source_assertion"
                        else "factual"
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
            for candidate_ref in claim.candidate_refs:
                candidate = candidate_by_id[candidate_ref]
                if (
                    claim.claim_type != candidate.claim_type
                    or claim.statement != candidate.statement
                    or claim.polarity != candidate.polarity
                    or claim.epistemic_status != candidate.epistemic_status
                ):
                    raise ValueError(
                        "merged claims require identical candidate semantics"
                    )
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
    narrated_claim_refs: list[str] = Field(min_length=1)
    claim_classifications: list[NarrativeClaimClassification] = Field(min_length=1)
    insight_refs: list[str] | None = None
    hypothesis_refs: list[str] | None = None
    verification_action_refs: list[str] | None = None
    themes: list[AdaptiveTheme] = Field(min_length=1)
    narrative: NarrativeSynthesis
    narrative_attestations: list[NarrativeAttestationArtifact] = Field(min_length=1)

    @field_validator(
        "released_claim_refs",
        "narrated_claim_refs",
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
    source_attributed_claim_refs: list[str] | None = None
    fact_claim_refs: list[str] | None = None
    qualified_claim_refs: list[str] | None = None
    insight_refs: list[str] | None = None
    hypothesis_refs: list[str] | None = None
    verification_action_refs: list[str] | None = None
    relationship_refs: list[str] | None = None
    attributes: dict[str, JsonValue] | None = None

    @field_validator(
        "released_claim_refs",
        "source_attributed_claim_refs",
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
        trusted_context.validate_source_provenance(self.provenance)
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
        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in ledger.candidates
        }
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
                candidate_by_id[decision.candidate_ref],
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
            if claim.factual_scope not in {
                "verified_source_assertion",
                "corroborated_world_finding",
            }:
                raise ValueError("released facts require an explicit factual scope")
            if claim.factual_scope == "corroborated_world_finding":
                raise ValueError(
                    "production corroborated world findings are unsupported "
                    "without a trusted cross-source corroboration authority"
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
            if claim.disposition != "supported":
                raise ValueError(
                    "non-supported claims require a completed review attestation "
                    "and must remain withheld in this contract version"
                )

            expected_eligibility = (
                "source_attributed"
                if claim.factual_scope == "verified_source_assertion"
                else "factual"
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
            evidence_by_id,
            insight_by_id,
            summary_reasoning_refs,
            self.provenance,
            self.manifest,
            trusted_context,
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
        if assessment.subject_sha256 != _risk_subject_sha256(subject):
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
        evidence_by_id: dict[str, EvidenceSpan],
        insight_by_id: dict[str, EvidenceBackedInsight],
        reasoning_refs: dict[str, set[str]],
        provenance: SourceProvenance,
        manifest: InvestigationRunManifest,
        trusted_context: _TrustedInvestigationValidationContext,
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
        if len(summary.themes) != 1 or summary.themes[0].theme_id != CANONICAL_THEME_ID:
            raise ValueError("released narrative requires the canonical verified-facts theme")
        if summary.themes[0].title != CANONICAL_THEME_TITLE:
            raise ValueError("released theme title must be deterministically rendered")

        groups = summary.narrative.thematic_groups or []
        group_theme_refs = [group.theme_ref for group in groups]
        if len(group_theme_refs) != len(set(group_theme_refs)):
            raise ValueError("primary themes cannot have duplicate narrative groups")
        if groups and set(group_theme_refs) != theme_ids:
            raise ValueError("every primary theme requires one narrative group")

        overview_sentences = list(summary.narrative.overview)
        if any(sentence.placement_role != "overview" for sentence in overview_sentences):
            raise ValueError("overview sentences require overview placement")
        detail_sentences = []
        for group in groups:
            if any(sentence.placement_role == "overview" for sentence in group.sentences):
                raise ValueError("thematic sentences cannot claim overview placement")
            detail_sentences.extend(group.sentences)
        sentences = [*overview_sentences, *detail_sentences]
        sentence_ids = [sentence.sentence_id for sentence in sentences]
        if len(sentence_ids) != len(set(sentence_ids)):
            raise ValueError("released narrative sentence IDs must be unique")

        classification_by_ref = {
            classification.claim_ref: classification
            for classification in summary.claim_classifications
        }
        if len(classification_by_ref) != len(summary.claim_classifications):
            raise ValueError("released claim classifications must be unique")
        if set(classification_by_ref) != released_claim_ids:
            raise ValueError("claim classifications must cover exact released claims")
        for claim_ref, classification in classification_by_ref.items():
            expected = classify_released_claim(claim_by_id[claim_ref])
            if classification != expected:
                raise ValueError("released claim classification is not deterministic")

        public_attestation_by_id = {
            artifact.artifact_id: artifact
            for artifact in summary.narrative_attestations
        }
        if len(public_attestation_by_id) != len(summary.narrative_attestations):
            raise ValueError("narrative attestation artifact IDs must be unique")
        sentence_attestation_refs = {
            sentence.semantic_attestation_ref for sentence in sentences
        }
        if set(public_attestation_by_id) != sentence_attestation_refs:
            raise ValueError("narrative attestations must cover exact released sentences")
        if set(trusted_context.narrative_attestations) != sentence_attestation_refs:
            raise ValueError("trusted T5 attestations must cover exact released sentences")

        narrated_claim_refs: set[str] = set()
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
            expected_kind = expected_narrative_sentence_kind(
                claim_refs=sentence.claim_refs,
                insight_refs=sentence_insight_refs,
                claim_by_id=claim_by_id,
            )
            if sentence.sentence_kind != expected_kind:
                raise ValueError(
                    "released deterministic narrative kind conflicts with claim scope"
                )
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
            expected_text = expected_narrative_sentence_text(
                claim_refs=sentence.claim_refs,
                insight_refs=sentence_insight_refs,
                claim_by_id=claim_by_id,
                evidence_by_id=evidence_by_id,
                insight_by_id=insight_by_id,
            )
            if sentence.text != expected_text:
                raise ValueError(
                    "narrative sentence text is not exactly supported by referenced semantics"
                )
            expected_evidence_refs = expected_narrative_evidence_refs(
                claim_refs=sentence.claim_refs,
                insight_refs=sentence_insight_refs,
                claim_by_id=claim_by_id,
                insight_by_id=insight_by_id,
            )
            if sentence.evidence_refs != expected_evidence_refs:
                raise ValueError(
                    "narrative evidence refs must equal referenced claim and insight evidence"
                )

            public_artifact = public_attestation_by_id[
                sentence.semantic_attestation_ref
            ]
            trusted_artifact = trusted_context.narrative_attestations.get(
                sentence.semantic_attestation_ref
            )
            if public_artifact != trusted_artifact:
                raise ValueError("narrative attestation does not match trusted T5 context")
            if (
                public_artifact.sentence_id != sentence.sentence_id
                or public_artifact.sentence_kind != sentence.sentence_kind
                or public_artifact.placement_role != sentence.placement_role
                or public_artifact.content_sha256 != sentence.content_sha256
                or public_artifact.claim_refs != sentence.claim_refs
                or public_artifact.evidence_refs != sentence.evidence_refs
                or (public_artifact.insight_refs or []) != sentence_insight_refs
            ):
                raise ValueError("narrative sentence does not match its T5 attestation")
            if (
                public_artifact.source_revision_id != provenance.source_revision_id
                or public_artifact.source_provenance_sha256
                != narrative_subject_sha256(provenance)
                or public_artifact.generation_manifest_sha256
                != narrative_subject_sha256(manifest)
                or public_artifact.producer_digest != NARRATIVE_PRODUCER_DIGEST
            ):
                raise ValueError("narrative attestation provenance or producer mismatch")
            expected_claim_hashes = {
                ref: narrative_subject_sha256(claim_by_id[ref])
                for ref in sentence.claim_refs
            }
            expected_evidence_hashes = {
                ref: narrative_subject_sha256(evidence_by_id[ref])
                for ref in sentence.evidence_refs
            }
            expected_insight_hashes = {
                ref: narrative_subject_sha256(insight_by_id[ref])
                for ref in sentence_insight_refs
            }
            if (
                public_artifact.claim_sha256 != expected_claim_hashes
                or public_artifact.evidence_sha256 != expected_evidence_hashes
                or (public_artifact.insight_sha256 or {}) != expected_insight_hashes
            ):
                raise ValueError("narrative attestation semantic hashes mismatch")
            narrated_claim_refs.update(sentence.claim_refs)

        if narrated_claim_refs != released_claim_ids:
            raise ValueError("released claim narrative coverage must be 100 percent")
        if set(summary.narrated_claim_refs) != narrated_claim_refs or (
            summary.narrated_claim_refs != summary.released_claim_refs
        ):
            raise ValueError("narrated_claim_refs must equal exact released claim refs")

        critical_claim_refs = {
            claim_ref
            for claim_ref, classification in classification_by_ref.items()
            if classification.salience == "critical"
        }
        critically_placed_refs = {
            claim_ref
            for sentence in sentences
            if sentence.placement_role in {"overview", "critical_detail"}
            for claim_ref in sentence.claim_refs
        }
        if not critical_claim_refs.issubset(critically_placed_refs):
            raise ValueError("critical claims require overview or critical-detail placement")

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
            "source_attributed": analysis.source_attributed_claim_refs or [],
            "fact": analysis.fact_claim_refs or [],
            "qualified": analysis.qualified_claim_refs or [],
        }
        bucket_refs = [claim_ref for refs in buckets.values() for claim_ref in refs]
        if len(bucket_refs) != len(set(bucket_refs)):
            raise ValueError("analysis epistemic buckets cannot overlap")
        if set(bucket_refs) != released_claim_ids:
            raise ValueError("analysis epistemic buckets must cover released claims")
        if buckets["qualified"]:
            raise ValueError(
                "analysis qualified bucket requires a completed review attestation"
            )
        for claim_ref in buckets["source_attributed"]:
            claim = claim_by_id[claim_ref]
            if (
                claim.epistemic_status != "fact"
                or claim.disposition != "supported"
                or claim.factual_scope != "verified_source_assertion"
            ):
                raise ValueError(
                    "analysis source-attributed bucket requires supported "
                    "verified source assertions"
                )
        for claim_ref in buckets["fact"]:
            claim = claim_by_id[claim_ref]
            if (
                claim.epistemic_status != "fact"
                or claim.disposition != "supported"
                or claim.factual_scope != "corroborated_world_finding"
            ):
                raise ValueError(
                    "analysis fact bucket requires supported corroborated world findings"
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


def validate_investigation_run(value: Any) -> InvestigationRun:
    """Validate diagnostic/non-release runs without accepting caller authority.

    Successful factual publication must use ``release_investigation_run`` so the
    T3/T4/source and repository state are replayed inside one trusted boundary.
    """

    if isinstance(value, str):
        return InvestigationRun.model_validate_json(value)
    if isinstance(value, InvestigationRun):
        return InvestigationRun.model_validate_json(
            value.model_dump_json(exclude_none=True)
        )
    return InvestigationRun.model_validate(value)


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


# Complete the release-adapter handshake before a direct run_contracts import
# returns, closing the import-order window around the one-shot minter.
from . import release_adapter as _release_adapter  # noqa: E402

del _release_adapter
