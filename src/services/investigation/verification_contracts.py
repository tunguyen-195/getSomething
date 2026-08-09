"""Immutable T4 verification and reconciliation artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, JsonValue, ValidationError, field_validator, model_validator

from .contracts import (
    ProjectionEligibility,
    VerificationDisposition,
    sha256_canonical_json,
)
from .discovery_contracts import DiscoveryBatch
from .discovery_common import jsonable
from .evidence_selector import EvidenceSelectorArtifact
from .run_contracts import CanonicalClaimLedger
from .source_revision import ImmutableArtifact, SourceScope

VERIFICATION_VERSION: Literal[
    "investigation-verification-v1.0"
] = "investigation-verification-v1.0"
SEMANTIC_POLICY_VERSION: Literal[
    "investigation-semantic-policy-v1.2"
] = "investigation-semantic-policy-v1.2"
RECONCILIATION_POLICY_VERSION: Literal[
    "investigation-reconciliation-policy-v1.0"
] = "investigation-reconciliation-policy-v1.0"
CONTRADICTION_POLICY_VERSION: Literal[
    "investigation-contradiction-policy-v1.0"
] = "investigation-contradiction-policy-v1.0"
VERIFICATION_MANIFEST_VERSION: Literal[
    "investigation-verification-manifest-v1.0"
] = "investigation-verification-manifest-v1.0"

VERIFICATION_REQUIRED_SOURCE_MODULES = frozenset(
    {
        "verification.py",
        "verification_contracts.py",
        "claim_semantics.py",
        "canonicalization.py",
        "contradictions.py",
    }
)


class VerificationError(ValueError):
    """Raised when a T4 artifact cannot be built or replayed safely."""


def canonical_id(prefix: str, payload: Mapping[str, Any]) -> str:
    return f"{prefix}:{sha256_canonical_json(dict(payload))}"


class ExactValueBinding(ImmutableArtifact):
    kind: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    normalized: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    unit: str | None = Field(default=None, min_length=1)
    owner_cue: str | None = Field(default=None, min_length=1)
    ambiguous: bool = False


class SemanticRoleBinding(ImmutableArtifact):
    """Conservative ordered roles used to reject actor/object reversals."""

    actor: str | None = Field(default=None, min_length=1)
    action: str | None = Field(default=None, min_length=1)
    object: str | None = Field(default=None, min_length=1)
    recipient: str | None = Field(default=None, min_length=1)
    voice: Literal["active", "passive", "unknown"] = "unknown"
    complete: bool = False
    ambiguous: bool = True


class SemanticClaimFrame(ImmutableArtifact):
    frame_id: str = Field(min_length=1)
    frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_policy_version: Literal[
        "investigation-semantic-policy-v1.2"
    ] = SEMANTIC_POLICY_VERSION
    candidate_ref: str = Field(min_length=1)
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision_id: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    raw_char_start: int = Field(ge=0)
    raw_char_end: int = Field(gt=0)
    quote_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_type: str = Field(min_length=1)
    candidate_statement: str = Field(min_length=1)
    source_assertion: str = Field(min_length=1)
    polarity: Literal[
        "affirmed", "negated", "uncertain", "reported", "quoted_instruction"
    ]
    source_modality: Literal[
        "affirmed",
        "negated",
        "uncertain",
        "reported",
        "quoted_instruction",
        "conditional",
        "question",
        "explicit_unknown",
    ]
    atomicity: Literal["atomic", "compound", "ambiguous"]
    atomic_units: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    speaker_id: str | None = Field(default=None, min_length=1)
    exact_values: tuple[ExactValueBinding, ...] = ()
    source_roles: SemanticRoleBinding
    safe_attributes: dict[str, JsonValue] | None = None

    @field_validator("atomic_units", "evidence_refs")
    @classmethod
    def unique_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("semantic frame values must be unique")
        return values

    @model_validator(mode="after")
    def validate_identity(self) -> "SemanticClaimFrame":
        if self.raw_char_end <= self.raw_char_start:
            raise ValueError("semantic frame raw range must be increasing")
        payload = semantic_frame_payload(self)
        expected_hash = sha256_canonical_json(payload)
        if self.frame_sha256 != expected_hash:
            raise ValueError("semantic frame hash mismatch")
        if self.frame_id != f"semv1:{expected_hash}":
            raise ValueError("semantic frame ID is not canonical")
        return self


def semantic_frame_payload(
    frame: SemanticClaimFrame | Mapping[str, Any],
) -> dict[str, Any]:
    payload = (
        frame.model_dump(mode="json", exclude_none=True)
        if isinstance(frame, SemanticClaimFrame)
        else dict(frame)
    )
    payload.pop("frame_id", None)
    payload.pop("frame_sha256", None)
    return jsonable(payload)


class DeterministicCheckRecord(ImmutableArtifact):
    check_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    status: Literal["pass", "fail", "review", "not_applicable"]
    subject_ref: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    refs: tuple[str, ...] = ()

    @field_validator("refs")
    @classmethod
    def unique_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("check refs must be unique")
        return values

    @model_validator(mode="after")
    def validate_identity(self) -> "DeterministicCheckRecord":
        payload = self.model_dump(mode="json", exclude={"check_id"})
        if self.check_id != canonical_id("chkv1", payload):
            raise ValueError("deterministic check ID is not canonical")
        return self


class VerifierSignal(ImmutableArtifact):
    signal_id: str = Field(min_length=1)
    subject_ref: str = Field(min_length=1)
    subject_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_id: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    outcome: Literal["entails", "contradicts", "neutral", "error", "not_run"]
    score: float | None = Field(default=None, ge=0, le=1)
    calibrated: bool = False
    calibration_artifact_ref: str | None = Field(default=None, min_length=1)
    non_authoritative: Literal[True] = True
    can_promote: Literal[False] = False
    network_required: Literal[False] = False

    @model_validator(mode="after")
    def validate_signal(self) -> "VerifierSignal":
        if self.calibrated != (self.calibration_artifact_ref is not None):
            raise ValueError("checker calibration fields must be provided together")
        payload = self.model_dump(mode="json", exclude={"signal_id"}, exclude_none=True)
        if self.signal_id != canonical_id("sigv1", payload):
            raise ValueError("verifier signal ID is not canonical")
        return self


class CandidateVerificationRecord(ImmutableArtifact):
    record_id: str = Field(min_length=1)
    verification_id: str = Field(min_length=1)
    candidate_ref: str = Field(min_length=1)
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_frame_ref: str = Field(min_length=1)
    semantic_frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selector_artifact_ref: str = Field(min_length=1)
    verified_evidence_refs: tuple[str, ...] = Field(min_length=1)
    disposition: VerificationDisposition
    projection_eligibility: ProjectionEligibility
    canonical_claim_ref: str | None = Field(default=None, min_length=1)
    eligibility_artifact_ref: str | None = Field(default=None, min_length=1)
    risk_artifact_ref: str | None = Field(default=None, min_length=1)
    failure_codes: tuple[str, ...] = ()
    check_refs: tuple[str, ...] = Field(min_length=1)
    checker_signal_ref: str | None = Field(default=None, min_length=1)
    requires_human_review: bool = False
    human_review_completed: Literal[False] = False
    release_blocking: bool = True

    @field_validator("verified_evidence_refs", "failure_codes", "check_refs")
    @classmethod
    def unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("verification record values must be unique")
        return values

    @model_validator(mode="after")
    def validate_state(self) -> "CandidateVerificationRecord":
        expected_verification = canonical_id(
            "verv1",
            {
                "candidate_ref": self.candidate_ref,
                "candidate_sha256": self.candidate_sha256,
                "semantic_frame_ref": self.semantic_frame_ref,
                "semantic_frame_sha256": self.semantic_frame_sha256,
            },
        )
        if self.verification_id != expected_verification:
            raise ValueError("verification ID is not canonical")
        projectable = self.projection_eligibility != "withheld"
        if projectable != (self.canonical_claim_ref is not None):
            raise ValueError("projectable records require exactly one canonical claim")
        if projectable and (
            self.eligibility_artifact_ref is None or self.risk_artifact_ref is None
        ):
            raise ValueError(
                "projectable records require eligibility and risk artifacts"
            )
        if self.projection_eligibility in {
            "source_attributed",
            "factual",
        } and self.disposition != "supported":
            raise ValueError(
                "source-attributed or factual eligibility requires supported disposition"
            )
        if (
            self.disposition != "supported"
            and self.projection_eligibility != "withheld"
        ):
            raise ValueError("non-supported records must remain withheld in T4")
        if self.requires_human_review and self.projection_eligibility != "withheld":
            raise ValueError("unreviewed records must remain withheld")
        if not self.release_blocking and (
            self.disposition != "supported"
            or self.requires_human_review
            or self.failure_codes
        ):
            raise ValueError("only supported non-claim records may be non-blocking")
        payload = self.model_dump(mode="json", exclude={"record_id"}, exclude_none=True)
        if self.record_id != canonical_id("vrecv1", payload):
            raise ValueError("verification record ID is not canonical")
        return self


class ClaimMergeRecord(ImmutableArtifact):
    merge_id: str = Field(min_length=1)
    policy_version: Literal[
        "investigation-reconciliation-policy-v1.0"
    ] = RECONCILIATION_POLICY_VERSION
    canonical_claim_ref: str = Field(min_length=1)
    member_candidate_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    hard_merge: Literal[True] = True
    basis: Literal["exact_semantics_and_evidence"] = "exact_semantics_and_evidence"

    @field_validator("member_candidate_refs", "evidence_refs")
    @classmethod
    def canonical_sets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(values)) != values or len(values) != len(set(values)):
            raise ValueError("merge refs must be sorted and unique")
        return values

    @model_validator(mode="after")
    def validate_identity(self) -> "ClaimMergeRecord":
        payload = self.model_dump(mode="json", exclude={"merge_id"})
        if self.merge_id != canonical_id("mrgv1", payload):
            raise ValueError("merge ID is not canonical")
        return self


class EntityClusterRecord(ImmutableArtifact):
    cluster_id: str = Field(min_length=1)
    policy_version: Literal[
        "investigation-reconciliation-policy-v1.0"
    ] = RECONCILIATION_POLICY_VERSION
    concept_ref: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    normalized_surface: str = Field(min_length=1)
    mention_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    hard_identity_merge: Literal[False] = False
    basis: Literal[
        "exact_surface_type_and_evidence"
    ] = "exact_surface_type_and_evidence"

    @field_validator("mention_refs", "evidence_refs")
    @classmethod
    def canonical_sets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(values)) != values or len(values) != len(set(values)):
            raise ValueError("entity refs must be sorted and unique")
        return values

    @model_validator(mode="after")
    def validate_identity(self) -> "EntityClusterRecord":
        payload = self.model_dump(mode="json", exclude={"cluster_id"})
        if self.cluster_id != canonical_id("entclv1", payload):
            raise ValueError("entity cluster ID is not canonical")
        return self


class ContradictionRecord(ImmutableArtifact):
    contradiction_id: str = Field(min_length=1)
    policy_version: Literal[
        "investigation-contradiction-policy-v1.0"
    ] = CONTRADICTION_POLICY_VERSION
    proposition_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_refs: tuple[str, ...] = Field(min_length=2)
    affirmed_candidate_refs: tuple[str, ...] = Field(min_length=1)
    negated_candidate_refs: tuple[str, ...] = Field(min_length=1)
    claim_refs: tuple[str, ...] = Field(min_length=2)
    evidence_refs: tuple[str, ...] = Field(min_length=2)
    total_pair_count: int = Field(ge=1)
    materialized_pair_count: Literal[0] = 0
    omitted_pair_count: int = Field(ge=1)
    conflict_dimension: Literal["polarity"] = "polarity"
    status: Literal["needs_review"] = "needs_review"
    assertions_preserved: Literal[True] = True

    @field_validator(
        "candidate_refs",
        "affirmed_candidate_refs",
        "negated_candidate_refs",
        "claim_refs",
        "evidence_refs",
    )
    @classmethod
    def canonical_sets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(values)) != values or len(values) != len(set(values)):
            raise ValueError("contradiction refs must be sorted and unique")
        return values

    @model_validator(mode="after")
    def validate_identity(self) -> "ContradictionRecord":
        if set(self.affirmed_candidate_refs) & set(self.negated_candidate_refs):
            raise ValueError("contradiction polarity groups cannot overlap")
        if set(self.candidate_refs) != (
            set(self.affirmed_candidate_refs) | set(self.negated_candidate_refs)
        ):
            raise ValueError("contradiction candidate refs must cover polarity groups")
        expected_pairs = len(self.affirmed_candidate_refs) * len(
            self.negated_candidate_refs
        )
        if self.total_pair_count != expected_pairs:
            raise ValueError("contradiction pair count mismatch")
        if self.omitted_pair_count != expected_pairs:
            raise ValueError(
                "grouped contradictions must omit Cartesian pair materialization"
            )
        payload = self.model_dump(mode="json", exclude={"contradiction_id"})
        if self.contradiction_id != canonical_id("conflv1", payload):
            raise ValueError("contradiction ID is not canonical")
        return self


class EligibilityArtifact(ImmutableArtifact):
    artifact_id: str = Field(min_length=1)
    verification_ref: str = Field(min_length=1)
    candidate_ref: str = Field(min_length=1)
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_claim_ref: str | None = Field(default=None, min_length=1)
    canonical_claim_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    eligibility: ProjectionEligibility
    disposition: VerificationDisposition

    @model_validator(mode="after")
    def validate_identity(self) -> "EligibilityArtifact":
        if (self.canonical_claim_ref is None) != (self.canonical_claim_sha256 is None):
            raise ValueError("eligibility claim fields must be provided together")
        payload = self.model_dump(
            mode="json", exclude={"artifact_id"}, exclude_none=True
        )
        if self.artifact_id != canonical_id("eligv1", payload):
            raise ValueError("eligibility artifact ID is not canonical")
        return self


class RiskAssessmentArtifact(ImmutableArtifact):
    artifact_id: str = Field(min_length=1)
    subject_ref: str = Field(min_length=1)
    subject_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    risk_tier: Literal["ordinary"] = "ordinary"
    basis: Literal["verified_source_assertion_only"] = (
        "verified_source_assertion_only"
    )

    @model_validator(mode="after")
    def validate_identity(self) -> "RiskAssessmentArtifact":
        payload = self.model_dump(mode="json", exclude={"artifact_id"})
        if self.artifact_id != canonical_id("riskv1", payload):
            raise ValueError("risk artifact ID is not canonical")
        return self


class VerificationRunManifest(ImmutableArtifact):
    manifest_id: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_version: Literal[
        "investigation-verification-manifest-v1.0"
    ] = VERIFICATION_MANIFEST_VERSION
    verification_version: Literal[
        "investigation-verification-v1.0"
    ] = VERIFICATION_VERSION
    semantic_policy_version: Literal[
        "investigation-semantic-policy-v1.2"
    ] = SEMANTIC_POLICY_VERSION
    reconciliation_policy_version: Literal[
        "investigation-reconciliation-policy-v1.0"
    ] = RECONCILIATION_POLICY_VERSION
    contradiction_policy_version: Literal[
        "investigation-contradiction-policy-v1.0"
    ] = CONTRADICTION_POLICY_VERSION
    discovery_batch_id: str = Field(min_length=1)
    discovery_batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision_id: str = Field(min_length=1)
    source_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checker_profile: Literal["deterministic_only", "signal_only"]
    checker_manifest: dict[str, JsonValue] | None = None
    source_module_hashes: dict[str, str] = Field(min_length=1)
    git_revision: str = Field(min_length=1)
    git_dirty: bool
    git_untracked: bool
    network_required: Literal[False] = False
    quality_claim_status: Literal[
        "not_claimed_without_locked_vietnamese_human_corpus"
    ] = "not_claimed_without_locked_vietnamese_human_corpus"

    @field_validator("source_module_hashes")
    @classmethod
    def validate_source_hashes(cls, values: dict[str, str]) -> dict[str, str]:
        missing = VERIFICATION_REQUIRED_SOURCE_MODULES - set(values)
        if missing:
            raise ValueError(
                "verification manifest missing source hashes: "
                + ", ".join(sorted(missing))
            )
        for name, digest in values.items():
            if (
                not name.strip()
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise ValueError("invalid verification source module hash")
        return values

    @model_validator(mode="after")
    def validate_identity(self) -> "VerificationRunManifest":
        if self.checker_profile == "deterministic_only" and self.checker_manifest:
            raise ValueError("deterministic-only manifest cannot include a checker")
        if self.checker_profile == "signal_only" and not self.checker_manifest:
            raise ValueError("signal-only manifest requires checker metadata")
        payload = self.model_dump(
            mode="json", exclude={"manifest_id", "manifest_sha256"}, exclude_none=True
        )
        expected_hash = sha256_canonical_json(payload)
        if self.manifest_sha256 != expected_hash:
            raise ValueError("verification manifest hash mismatch")
        if self.manifest_id != f"vmanv1:{expected_hash}":
            raise ValueError("verification manifest ID is not canonical")
        return self


class VerificationBatch(ImmutableArtifact):
    verification_version: Literal[
        "investigation-verification-v1.0"
    ] = VERIFICATION_VERSION
    batch_id: str = Field(min_length=1)
    batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["success", "no_claim_candidates", "needs_review"]
    scope: SourceScope
    source_revision_id: str = Field(min_length=1)
    source_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    discovery_batch_id: str = Field(min_length=1)
    discovery_batch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    discovery_batch: DiscoveryBatch
    ledger: CanonicalClaimLedger | None = None
    semantic_frames: tuple[SemanticClaimFrame, ...] = ()
    checks: tuple[DeterministicCheckRecord, ...] = ()
    records: tuple[CandidateVerificationRecord, ...] = ()
    selector_artifacts: tuple[EvidenceSelectorArtifact, ...] = ()
    checker_signals: tuple[VerifierSignal, ...] = ()
    merge_records: tuple[ClaimMergeRecord, ...] = ()
    entity_clusters: tuple[EntityClusterRecord, ...] = ()
    contradictions: tuple[ContradictionRecord, ...] = ()
    eligibility_artifacts: tuple[EligibilityArtifact, ...] = ()
    risk_artifacts: tuple[RiskAssessmentArtifact, ...] = ()
    manifest: VerificationRunManifest
    release_authority: Literal[False] = False
    network_required: Literal[False] = False

    @model_validator(mode="after")
    def validate_batch(self) -> "VerificationBatch":
        if self.discovery_batch.batch_id != self.discovery_batch_id or (
            self.discovery_batch.batch_sha256 != self.discovery_batch_sha256
        ):
            raise ValueError("verification batch discovery binding mismatch")
        if self.discovery_batch.scope != self.scope:
            raise ValueError("verification batch scope mismatch")
        if self.discovery_batch.source_revision_id != self.source_revision_id or (
            self.discovery_batch.source_revision_sha256 != self.source_revision_sha256
        ):
            raise ValueError("verification batch source revision mismatch")
        if self.manifest.discovery_batch_id != self.discovery_batch_id or (
            self.manifest.discovery_batch_sha256 != self.discovery_batch_sha256
        ):
            raise ValueError("verification manifest discovery binding mismatch")
        if self.manifest.source_revision_id != self.source_revision_id or (
            self.manifest.source_revision_sha256 != self.source_revision_sha256
        ):
            raise ValueError("verification manifest source binding mismatch")
        if self.status == "no_claim_candidates":
            if self.ledger is not None or self.records or self.semantic_frames:
                raise ValueError("no-claim verification cannot include a claim ledger")
        elif self.ledger is None or not self.records or not self.semantic_frames:
            raise ValueError("claim verification requires a diagnostic ledger")
        if self.status == "success" and any(
            record.release_blocking and record.projection_eligibility == "withheld"
            for record in self.records
        ):
            raise ValueError(
                "success cannot contain release-blocking withheld decisions"
            )
        if self.status == "needs_review" and not (
            any(
                record.release_blocking and record.projection_eligibility == "withheld"
                for record in self.records
            )
            or self.contradictions
        ):
            raise ValueError(
                "needs_review requires a withheld decision or contradiction"
            )
        collections = (
            (self.semantic_frames, "frame_id"),
            (self.checks, "check_id"),
            (self.records, "record_id"),
            (self.selector_artifacts, "artifact_id"),
            (self.checker_signals, "signal_id"),
            (self.merge_records, "merge_id"),
            (self.entity_clusters, "cluster_id"),
            (self.contradictions, "contradiction_id"),
            (self.eligibility_artifacts, "artifact_id"),
            (self.risk_artifacts, "artifact_id"),
        )
        seen: set[str] = set()
        for items, field in collections:
            for item in items:
                identifier = str(getattr(item, field))
                if identifier in seen:
                    raise ValueError("duplicate ID across verification batch artifacts")
                seen.add(identifier)
        expected_hash = verification_batch_sha256(self)
        if self.batch_sha256 != expected_hash:
            raise ValueError("verification batch hash mismatch")
        if self.batch_id != f"t4batchv1:{expected_hash}":
            raise ValueError("verification batch ID is not canonical")
        return self


def verification_batch_payload(
    batch: VerificationBatch | Mapping[str, Any],
) -> dict[str, Any]:
    payload = (
        batch.model_dump(mode="json", exclude_none=True)
        if isinstance(batch, VerificationBatch)
        else dict(batch)
    )
    payload.pop("batch_id", None)
    payload.pop("batch_sha256", None)
    return jsonable(payload)


def verification_batch_sha256(
    batch: VerificationBatch | Mapping[str, Any],
) -> str:
    return sha256_canonical_json(verification_batch_payload(batch))


class VerificationReplayResult:
    """Immutable replay output container with no release authority."""

    __slots__ = ("_batch_json", "_sealed")
    _batch_json: str
    _sealed: bool

    def __init__(self, batch: VerificationBatch):
        resolved = VerificationBatch.model_validate_json(
            batch.model_dump_json(exclude_none=True)
        )
        object.__setattr__(
            self, "_batch_json", resolved.model_dump_json(exclude_none=True)
        )
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("verified T4 batch is immutable")
        object.__setattr__(self, name, value)

    @property
    def batch(self) -> VerificationBatch:
        try:
            return VerificationBatch.model_validate_json(self._batch_json)
        except (TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise VerificationError("verified T4 batch storage is invalid") from exc


def _verification_replay_result(
    batch: VerificationBatch,
) -> VerificationReplayResult:
    return VerificationReplayResult(batch)


__all__ = [
    "CONTRADICTION_POLICY_VERSION",
    "RECONCILIATION_POLICY_VERSION",
    "SEMANTIC_POLICY_VERSION",
    "VERIFICATION_MANIFEST_VERSION",
    "VERIFICATION_REQUIRED_SOURCE_MODULES",
    "VERIFICATION_VERSION",
    "CandidateVerificationRecord",
    "ClaimMergeRecord",
    "ContradictionRecord",
    "DeterministicCheckRecord",
    "EligibilityArtifact",
    "EntityClusterRecord",
    "ExactValueBinding",
    "RiskAssessmentArtifact",
    "SemanticRoleBinding",
    "SemanticClaimFrame",
    "VerificationBatch",
    "VerificationError",
    "VerificationRunManifest",
    "VerificationReplayResult",
    "VerifierSignal",
    "canonical_id",
    "semantic_frame_payload",
    "verification_batch_payload",
    "verification_batch_sha256",
]
