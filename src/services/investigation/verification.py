"""Deterministic-first T4 verification orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import JsonValue, ValidationError

from .canonicalization import (
    canonical_claim_sha256,
    canonicalize_entities,
    canonicalize_supported_claims,
)
from .claim_semantics import (
    SemanticAssessment,
    assess_semantic_frame,
    build_semantic_frame,
    candidate_sha256,
)
from .contracts import sha256_canonical_json
from .contradictions import discover_contradictions
from .discovery import verify_discovery_batch
from .discovery_contracts import DiscoveryBatch, VerifiedDiscoveryBatch
from .evidence_selector import (
    EvidenceSelectorArtifact,
    EvidenceSelectorRequest,
    EvidenceSelectorResolver,
)
from .run_contracts import CanonicalClaimLedger, VerificationDecision
from .source_revision import SourceRevision, _revalidate_source_revision
from .verification_contracts import (
    CandidateVerificationRecord,
    EligibilityArtifact,
    RiskAssessmentArtifact,
    SemanticClaimFrame,
    VerificationBatch,
    VerificationError,
    VerificationRunManifest,
    VerificationReplayResult,
    VerifierSignal,
    _verification_replay_result,
    canonical_id,
    verification_batch_sha256,
)


@dataclass(frozen=True)
class CheckerObservation:
    outcome: str
    score: float | None = None
    calibrated: bool = False
    calibration_artifact_ref: str | None = None


class VerifierAdapter(Protocol):
    def manifest(self) -> Mapping[str, JsonValue]:
        raise NotImplementedError

    def evaluate(
        self,
        *,
        premise: str,
        hypothesis: str,
        frame: SemanticClaimFrame,
    ) -> CheckerObservation:
        raise NotImplementedError


def _validate_checker_manifest(
    checker: VerifierAdapter,
) -> dict[str, JsonValue]:
    metadata = dict(checker.manifest())
    required = {
        "adapter_id",
        "adapter_version",
        "model_id",
        "model_revision",
        "runtime_id",
    }
    missing = required - set(metadata)
    if missing:
        raise VerificationError(
            "checker manifest missing fields: " + ", ".join(sorted(missing))
        )
    if any(
        not isinstance(metadata[key], str) or not str(metadata[key]).strip()
        for key in required
    ):
        raise VerificationError(
            "checker manifest identifiers must be non-blank strings"
        )
    if metadata.get("network_required", False) is not False:
        raise VerificationError("T4 checker adapters must be fully offline")
    metadata["network_required"] = False
    return metadata


def _build_signal(
    *,
    checker_metadata: Mapping[str, JsonValue],
    observation: CheckerObservation,
    frame: SemanticClaimFrame,
) -> VerifierSignal:
    if observation.outcome not in {
        "entails",
        "contradicts",
        "neutral",
        "error",
        "not_run",
    }:
        raise VerificationError("checker returned an unsupported outcome")
    payload: dict[str, Any] = {
        "subject_ref": frame.frame_id,
        "subject_sha256": frame.frame_sha256,
        "adapter_id": str(checker_metadata["adapter_id"]),
        "adapter_version": str(checker_metadata["adapter_version"]),
        "model_id": str(checker_metadata["model_id"]),
        "model_revision": str(checker_metadata["model_revision"]),
        "runtime_id": str(checker_metadata["runtime_id"]),
        "outcome": observation.outcome,
        "score": observation.score,
        "calibrated": observation.calibrated,
        "calibration_artifact_ref": observation.calibration_artifact_ref,
        "non_authoritative": True,
        "can_promote": False,
        "network_required": False,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    return VerifierSignal(
        signal_id=canonical_id("sigv1", payload),
        **payload,
    )


def build_verification_manifest(
    *,
    discovery_batch: DiscoveryBatch,
    checker_manifest: Mapping[str, JsonValue] | None,
    source_module_hashes: Mapping[str, str],
    git_revision: str,
    git_dirty: bool,
    git_untracked: bool,
) -> VerificationRunManifest:
    payload: dict[str, Any] = {
        "manifest_version": "investigation-verification-manifest-v1.0",
        "verification_version": "investigation-verification-v1.0",
        "semantic_policy_version": "investigation-semantic-policy-v1.2",
        "reconciliation_policy_version": "investigation-reconciliation-policy-v1.0",
        "contradiction_policy_version": "investigation-contradiction-policy-v1.0",
        "discovery_batch_id": discovery_batch.batch_id,
        "discovery_batch_sha256": discovery_batch.batch_sha256,
        "source_revision_id": discovery_batch.source_revision_id,
        "source_revision_sha256": discovery_batch.source_revision_sha256,
        "checker_profile": "signal_only" if checker_manifest else "deterministic_only",
        "checker_manifest": dict(checker_manifest) if checker_manifest else None,
        "source_module_hashes": dict(source_module_hashes),
        "git_revision": git_revision,
        "git_dirty": git_dirty,
        "git_untracked": git_untracked,
        "network_required": False,
        "quality_claim_status": ("not_claimed_without_locked_vietnamese_human_corpus"),
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    manifest_hash = sha256_canonical_json(payload)
    return VerificationRunManifest(
        manifest_id=f"vmanv1:{manifest_hash}",
        manifest_sha256=manifest_hash,
        **payload,
    )


def _verification_selector(
    *,
    resolver: EvidenceSelectorResolver,
    verification_id: str,
    source_artifact: EvidenceSelectorArtifact,
) -> EvidenceSelectorArtifact:
    requests = tuple(
        EvidenceSelectorRequest(
            evidence_id=selector.evidence_id,
            scope=selector.scope,
            source_revision_id=selector.source_revision_id,
            quote_exact=selector.quote_exact,
            segment_id=selector.segment_id,
            prefix=selector.prefix or None,
            suffix=selector.suffix or None,
            occurrence_index=selector.occurrence_index,
        )
        for selector in source_artifact.selectors
    )
    artifact = resolver.build_artifact(
        subject_kind="verification",
        subject_ref=verification_id,
        requests=requests,
    )
    return resolver.verify_artifact(artifact).artifact


def _disposition(
    assessment: SemanticAssessment,
    signal: VerifierSignal | None,
) -> tuple[str, tuple[str, ...], bool]:
    failures = set(assessment.failure_codes)
    reviews = set(assessment.review_codes)
    if signal and signal.outcome in {"contradicts", "neutral", "error"}:
        reviews.add("checker_disagreement")
    if failures:
        if failures & {"polarity_modality", "exact_values", "owner_unit_binding"}:
            return "contradicted", tuple(sorted(failures | reviews)), True
        return "unverifiable", tuple(sorted(failures | reviews)), True
    if reviews:
        return "partially_supported", tuple(sorted(reviews)), True
    return "supported", (), False


def _risk_artifact(claim: Any) -> RiskAssessmentArtifact:
    subject_digest = canonical_claim_sha256(claim)
    payload = {
        "subject_ref": claim.claim_id,
        "subject_sha256": subject_digest,
        "risk_tier": "ordinary",
        "basis": "verified_source_assertion_only",
    }
    return RiskAssessmentArtifact(
        artifact_id=canonical_id("riskv1", payload),
        subject_ref=claim.claim_id,
        subject_sha256=subject_digest,
        risk_tier="ordinary",
        basis="verified_source_assertion_only",
    )


def _candidate_kind(candidate: Any) -> str:
    value = (candidate.attributes or {}).get("candidate_kind")
    return str(value) if isinstance(value, str) else "claim"


def _is_non_claim_candidate(candidate: Any) -> bool:
    return _candidate_kind(candidate) == "entity_mention" or (
        candidate.claim_type.startswith("entity_mention.")
    )


def _eligibility_artifact(
    *,
    verification_id: str,
    candidate_ref: str,
    candidate_digest: str,
    frame: SemanticClaimFrame,
    claim: Any | None,
    disposition: str,
    eligibility: str,
) -> EligibilityArtifact:
    payload: dict[str, Any] = {
        "verification_ref": verification_id,
        "candidate_ref": candidate_ref,
        "candidate_sha256": candidate_digest,
        "semantic_frame_sha256": frame.frame_sha256,
        "canonical_claim_ref": claim.claim_id if claim is not None else None,
        "canonical_claim_sha256": (
            canonical_claim_sha256(claim) if claim is not None else None
        ),
        "eligibility": eligibility,
        "disposition": disposition,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    return EligibilityArtifact(
        artifact_id=canonical_id("eligv1", payload),
        **payload,
    )


def build_verification_batch(
    *,
    verified_discovery: VerifiedDiscoveryBatch,
    revision: SourceRevision,
    source_module_hashes: Mapping[str, str],
    git_revision: str,
    git_dirty: bool,
    git_untracked: bool,
    checker: VerifierAdapter | None = None,
) -> VerificationBatch:
    """Build a deterministic T4 artifact from an opaque replayed T3 batch."""

    if not isinstance(verified_discovery, VerifiedDiscoveryBatch):
        raise TypeError("T4 requires a VerifiedDiscoveryBatch")
    revision = _revalidate_source_revision(revision)
    discovery = verify_discovery_batch(verified_discovery.batch, revision).batch
    checker_metadata = _validate_checker_manifest(checker) if checker else None
    manifest = build_verification_manifest(
        discovery_batch=discovery,
        checker_manifest=checker_metadata,
        source_module_hashes=source_module_hashes,
        git_revision=git_revision,
        git_dirty=git_dirty,
        git_untracked=git_untracked,
    )

    if not discovery.candidate_records:
        payload: dict[str, Any] = {
            "verification_version": "investigation-verification-v1.0",
            "status": "no_claim_candidates",
            "scope": discovery.scope,
            "source_revision_id": discovery.source_revision_id,
            "source_revision_sha256": discovery.source_revision_sha256,
            "discovery_batch_id": discovery.batch_id,
            "discovery_batch_sha256": discovery.batch_sha256,
            "discovery_batch": discovery,
            "semantic_frames": (),
            "checks": (),
            "records": (),
            "selector_artifacts": (),
            "checker_signals": (),
            "merge_records": (),
            "entity_clusters": (),
            "contradictions": (),
            "eligibility_artifacts": (),
            "risk_artifacts": (),
            "manifest": manifest,
            "release_authority": False,
            "network_required": False,
        }
        batch_hash = verification_batch_sha256(payload)
        return VerificationBatch(
            batch_id=f"t4batchv1:{batch_hash}",
            batch_sha256=batch_hash,
            **payload,
        )

    resolver = EvidenceSelectorResolver(revision)
    candidates = {
        record.candidate.candidate_id: record.candidate
        for record in discovery.candidate_records
    }
    frames: dict[str, SemanticClaimFrame] = {}
    assessments: dict[str, SemanticAssessment] = {}
    dispositions: dict[str, str] = {}
    failures: dict[str, tuple[str, ...]] = {}
    review_flags: dict[str, bool] = {}
    verification_ids: dict[str, str] = {}
    selectors: dict[str, EvidenceSelectorArtifact] = {}
    signals: dict[str, VerifierSignal] = {}
    checks_by_candidate: dict[str, tuple[Any, ...]] = {}

    for source_record in sorted(
        discovery.candidate_records, key=lambda item: item.candidate.candidate_id
    ):
        candidate = source_record.candidate
        source_selector = source_record.selector_artifact.selectors[0]
        frame = build_semantic_frame(candidate, source_selector)
        digest = candidate_sha256(candidate)
        verification_id = canonical_id(
            "verv1",
            {
                "candidate_ref": candidate.candidate_id,
                "candidate_sha256": digest,
                "semantic_frame_ref": frame.frame_id,
                "semantic_frame_sha256": frame.frame_sha256,
            },
        )
        selector_artifact = _verification_selector(
            resolver=resolver,
            verification_id=verification_id,
            source_artifact=source_record.selector_artifact,
        )
        frame = build_semantic_frame(candidate, selector_artifact.selectors[0])
        assessment = assess_semantic_frame(candidate, frame)
        signal = None
        if checker is not None and checker_metadata is not None:
            try:
                observation = checker.evaluate(
                    premise=frame.source_assertion,
                    hypothesis=candidate.statement,
                    frame=frame,
                )
            except Exception:
                observation = CheckerObservation(outcome="error")
            signal = _build_signal(
                checker_metadata=checker_metadata,
                observation=observation,
                frame=frame,
            )
            signals[candidate.candidate_id] = signal
        disposition, failure_codes, needs_review = _disposition(assessment, signal)
        frames[candidate.candidate_id] = frame
        assessments[candidate.candidate_id] = assessment
        dispositions[candidate.candidate_id] = disposition
        failures[candidate.candidate_id] = failure_codes
        review_flags[candidate.candidate_id] = needs_review
        verification_ids[candidate.candidate_id] = verification_id
        selectors[candidate.candidate_id] = selector_artifact
        checks_by_candidate[candidate.candidate_id] = assessment.checks

    entity_result = canonicalize_entities(
        discovery.candidate_records,
        discovery.entity_challenger_records,
    )
    supported_refs = tuple(
        sorted(
            candidate_ref
            for candidate_ref, disposition in dispositions.items()
            if disposition == "supported"
            and not _is_non_claim_candidate(candidates[candidate_ref])
            and _candidate_kind(candidates[candidate_ref]) == "claim"
        )
    )
    claim_result = canonicalize_supported_claims(
        candidates=candidates,
        frames=frames,
        supported_candidate_refs=supported_refs,
        evidence_to_concepts=entity_result.evidence_to_concepts,
    )
    claims_by_id = {claim.claim_id: claim for claim in claim_result.claims}
    risk_artifacts = tuple(
        sorted(
            (_risk_artifact(claim) for claim in claim_result.claims),
            key=lambda item: item.artifact_id,
        )
    )
    risk_by_claim = {item.subject_ref: item for item in risk_artifacts}

    decisions: list[VerificationDecision] = []
    records: list[CandidateVerificationRecord] = []
    eligibility_artifacts: list[EligibilityArtifact] = []
    for candidate_ref in sorted(candidates):
        candidate = candidates[candidate_ref]
        frame = frames[candidate_ref]
        disposition = dispositions[candidate_ref]
        claim_ref = claim_result.candidate_to_claim.get(candidate_ref)
        claim = claims_by_id.get(claim_ref) if claim_ref else None
        eligibility = "withheld"
        if disposition == "supported" and claim is not None:
            eligibility = (
                "source_attributed"
                if claim.factual_scope == "verified_source_assertion"
                else "factual"
            )
        release_blocking = not _is_non_claim_candidate(candidate)
        eligibility_artifact = _eligibility_artifact(
            verification_id=verification_ids[candidate_ref],
            candidate_ref=candidate_ref,
            candidate_digest=candidate_sha256(candidate),
            frame=frame,
            claim=claim,
            disposition=disposition,
            eligibility=eligibility,
        )
        eligibility_artifacts.append(eligibility_artifact)
        selector_artifact = selectors[candidate_ref]
        decision_payload: dict[str, Any] = {
            "verification_id": verification_ids[candidate_ref],
            "candidate_ref": candidate_ref,
            "disposition": disposition,
            "evidence_resolution": "resolved",
            "source_revision_id": revision.source_revision_id,
            "resolution_authority": "t2-evidence-selector-v1",
            "resolution_artifact_ref": selector_artifact.artifact_id,
            "verified_evidence_refs": [
                selector.evidence_id for selector in selector_artifact.selectors
            ],
            "canonical_claim_ref": claim_ref,
            "projection_eligibility": eligibility,
            "eligibility_artifact_ref": (
                eligibility_artifact.artifact_id if eligibility != "withheld" else None
            ),
            "failure_codes": list(failures[candidate_ref]) or None,
        }
        decision_payload = {
            key: value for key, value in decision_payload.items() if value is not None
        }
        decisions.append(VerificationDecision(**decision_payload))
        record_payload: dict[str, Any] = {
            "verification_id": verification_ids[candidate_ref],
            "candidate_ref": candidate_ref,
            "candidate_sha256": candidate_sha256(candidate),
            "semantic_frame_ref": frame.frame_id,
            "semantic_frame_sha256": frame.frame_sha256,
            "selector_artifact_ref": selector_artifact.artifact_id,
            "verified_evidence_refs": tuple(
                selector.evidence_id for selector in selector_artifact.selectors
            ),
            "disposition": disposition,
            "projection_eligibility": eligibility,
            "canonical_claim_ref": claim_ref,
            "eligibility_artifact_ref": (
                eligibility_artifact.artifact_id if eligibility != "withheld" else None
            ),
            "risk_artifact_ref": (
                risk_by_claim[claim_ref].artifact_id if claim_ref else None
            ),
            "failure_codes": failures[candidate_ref],
            "check_refs": tuple(
                check.check_id for check in checks_by_candidate[candidate_ref]
            ),
            "checker_signal_ref": (
                signals[candidate_ref].signal_id if candidate_ref in signals else None
            ),
            "requires_human_review": review_flags[candidate_ref],
            "human_review_completed": False,
            "release_blocking": release_blocking,
        }
        record_payload = {
            key: value for key, value in record_payload.items() if value is not None
        }
        records.append(
            CandidateVerificationRecord(
                record_id=canonical_id("vrecv1", record_payload),
                **record_payload,
            )
        )

    evidence_by_id: dict[str, Any] = {}
    for artifact in (
        *selectors.values(),
        *(item.selector_artifact for item in discovery.entity_challenger_records),
    ):
        verified_artifact = resolver.verify_artifact(artifact).artifact
        for selector in verified_artifact.selectors:
            evidence = selector.to_evidence_span()
            previous = evidence_by_id.get(evidence.evidence_id)
            if previous is not None and previous != evidence:
                raise VerificationError("duplicate evidence ID has conflicting content")
            evidence_by_id[evidence.evidence_id] = evidence

    contradictions = discover_contradictions(
        frames=frames,
        candidate_to_claim=claim_result.candidate_to_claim,
    )
    ledger_payload: dict[str, Any] = {
        "candidates": [candidates[key] for key in sorted(candidates)],
        "verification_decisions": sorted(
            decisions, key=lambda item: item.verification_id
        ),
        "claims": list(claim_result.claims),
        "evidence": [evidence_by_id[key] for key in sorted(evidence_by_id)],
        "contradiction_count": len(contradictions),
    }
    attributed_assertion_refs = sorted(
        candidate_ref
        for candidate_ref, frame in frames.items()
        if not _is_non_claim_candidate(candidates[candidate_ref])
        and (frame.source_modality == "reported" or frame.polarity == "reported")
    )
    if attributed_assertion_refs:
        ledger_payload[
            "attributed_assertion_candidate_refs"
        ] = attributed_assertion_refs
    if contradictions:
        ledger_payload["contradiction_refs"] = [
            item.contradiction_id for item in contradictions
        ]
        ledger_payload["contradiction_set_sha256"] = sha256_canonical_json(
            [item.model_dump(mode="json", exclude_none=True) for item in contradictions]
        )
    if entity_result.concepts:
        ledger_payload["concepts"] = list(entity_result.concepts)
    ledger = CanonicalClaimLedger(**ledger_payload)
    has_withheld = any(
        record.release_blocking and record.projection_eligibility == "withheld"
        for record in records
    )
    status = "needs_review" if has_withheld or contradictions else "success"
    payload = {
        "verification_version": "investigation-verification-v1.0",
        "status": status,
        "scope": discovery.scope,
        "source_revision_id": discovery.source_revision_id,
        "source_revision_sha256": discovery.source_revision_sha256,
        "discovery_batch_id": discovery.batch_id,
        "discovery_batch_sha256": discovery.batch_sha256,
        "discovery_batch": discovery,
        "ledger": ledger,
        "semantic_frames": tuple(frames[key] for key in sorted(frames)),
        "checks": tuple(
            sorted(
                (
                    check
                    for candidate_checks in checks_by_candidate.values()
                    for check in candidate_checks
                ),
                key=lambda item: item.check_id,
            )
        ),
        "records": tuple(sorted(records, key=lambda item: item.verification_id)),
        "selector_artifacts": tuple(
            sorted(selectors.values(), key=lambda item: item.subject_ref)
        ),
        "checker_signals": tuple(
            sorted(signals.values(), key=lambda item: item.subject_ref)
        ),
        "merge_records": claim_result.merge_records,
        "entity_clusters": entity_result.clusters,
        "contradictions": contradictions,
        "eligibility_artifacts": tuple(
            sorted(eligibility_artifacts, key=lambda item: item.verification_ref)
        ),
        "risk_artifacts": risk_artifacts,
        "manifest": manifest,
        "release_authority": False,
        "network_required": False,
    }
    batch_hash = verification_batch_sha256(payload)
    return VerificationBatch(
        batch_id=f"t4batchv1:{batch_hash}",
        batch_sha256=batch_hash,
        **payload,
    )


class _RecordedSignalAdapter:
    def __init__(
        self,
        manifest: Mapping[str, JsonValue],
        signals: Sequence[VerifierSignal],
    ) -> None:
        self._manifest = dict(manifest)
        self._signals = {signal.subject_ref: signal for signal in signals}

    def manifest(self) -> Mapping[str, JsonValue]:
        return self._manifest

    def evaluate(
        self,
        *,
        premise: str,
        hypothesis: str,
        frame: SemanticClaimFrame,
    ) -> CheckerObservation:
        del premise, hypothesis
        signal = self._signals.get(frame.frame_id)
        if signal is None:
            raise VerificationError("recorded checker signal is missing")
        return CheckerObservation(
            outcome=signal.outcome,
            score=signal.score,
            calibrated=signal.calibrated,
            calibration_artifact_ref=signal.calibration_artifact_ref,
        )


def verify_verification_batch(
    batch: VerificationBatch | Mapping[str, Any],
    *,
    verified_discovery: VerifiedDiscoveryBatch,
    revision: SourceRevision,
) -> VerificationReplayResult:
    """Replay a T4 artifact and reject stale IDs, semantics, or source bindings."""

    if not isinstance(verified_discovery, VerifiedDiscoveryBatch):
        raise TypeError("T4 replay requires a VerifiedDiscoveryBatch")
    revision = _revalidate_source_revision(revision)
    try:
        resolved = (
            VerificationBatch.model_validate_json(
                batch.model_dump_json(exclude_none=True)
            )
            if isinstance(batch, VerificationBatch)
            else VerificationBatch.model_validate(batch)
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise VerificationError("invalid T4 verification artifact") from exc
    if resolved.discovery_batch_id != verified_discovery.batch.batch_id:
        raise VerificationError("T4 artifact is detached from the verified T3 batch")
    checker = None
    if resolved.manifest.checker_profile == "signal_only":
        checker = _RecordedSignalAdapter(
            resolved.manifest.checker_manifest or {},
            resolved.checker_signals,
        )
    expected = build_verification_batch(
        verified_discovery=verified_discovery,
        revision=revision,
        source_module_hashes=resolved.manifest.source_module_hashes,
        git_revision=resolved.manifest.git_revision,
        git_dirty=resolved.manifest.git_dirty,
        git_untracked=resolved.manifest.git_untracked,
        checker=checker,
    )
    if expected.model_dump_json(exclude_none=True) != resolved.model_dump_json(
        exclude_none=True
    ):
        raise VerificationError("T4 artifact does not match deterministic replay")
    return _verification_replay_result(resolved)


__all__ = [
    "CheckerObservation",
    "VerifierAdapter",
    "build_verification_batch",
    "build_verification_manifest",
    "verify_verification_batch",
]
