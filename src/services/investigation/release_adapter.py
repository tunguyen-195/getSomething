"""Single trusted release boundary for factual InvestigationRun publication."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from . import narrative_attestation as _narrative_attestation
from . import run_contracts as _run_contracts
from .contracts import SourceProvenance, sha256_canonical_json
from .discovery_common import DISCOVERY_REQUIRED_SOURCE_MODULES
from .evidence_selector import EvidenceSelectorResolver
from .run_contracts import (
    CanonicalClaimLedger,
    InvestigationRun,
    InvestigationRunManifest,
    SummaryProjection,
    _TrustedEligibilityAssessment,
    _TrustedRiskAssessment,
    _build_trusted_investigation_validation_context,
    _selector_attestations_from_verified_artifacts,
    _semantic_subject_sha256,
    _verification_subject_sha256,
)
from .narrative_attestation import (
    NarrativeReleaseBundle,
    ReleasedNarrativeProjection,
    build_deterministic_narrative_release,
)
from .source_revision import SourceRevision, _revalidate_source_revision

if TYPE_CHECKING:
    from .discovery_contracts import DiscoveryBatch
    from .verification_contracts import VerificationBatch

RELEASE_REQUIRED_SOURCE_MODULES = frozenset(
    {
        "canonicalization.py",
        "claim_semantics.py",
        "contracts.py",
        "contradictions.py",
        "discovery.py",
        "discovery_contracts.py",
        "evidence_selector.py",
        "__init__.py",
        "narrative_attestation.py",
        "reasoning_contracts.py",
        "release_adapter.py",
        "run_contracts.py",
        "source_revision.py",
        "verification.py",
        "verification_contracts.py",
    }
)

_mint_released_narrative_projection = (
    _narrative_attestation._take_released_narrative_minter()
)
delattr(_narrative_attestation, "_take_released_narrative_minter")


class InvestigationReleaseError(ValueError):
    """Raised when an artifact cannot cross the factual release boundary."""


@dataclass(frozen=True)
class RepositoryState:
    git_revision: str
    git_dirty: bool
    git_untracked: bool
    git_status_sha256: str
    discovery_source_hashes: Mapping[str, str]
    verification_source_hashes: Mapping[str, str]
    release_source_hashes: Mapping[str, str]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_hashes(source_dir: Path, names: frozenset[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in sorted(names):
        path = source_dir / name
        if not path.is_file():
            raise InvestigationReleaseError(
                f"required release source module is missing: {path}"
            )
        hashes[name] = _sha256_file(path)
    return hashes


def _git_output(repository_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-c", f"safe.directory={repository_root}", *args],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InvestigationReleaseError("cannot measure repository Git state") from exc
    return completed.stdout.strip()


def capture_repository_state(repository_root: str | Path) -> RepositoryState:
    """Measure exact source bytes and Git state inside the trusted boundary."""

    from .verification_contracts import VERIFICATION_REQUIRED_SOURCE_MODULES

    root = Path(repository_root).resolve()
    source_dir = root / "src" / "services" / "investigation"
    if not source_dir.is_dir():
        raise InvestigationReleaseError(
            "repository root does not contain src/services/investigation"
        )
    status = _git_output(root, "status", "--porcelain=v1", "--untracked-files=normal")
    return RepositoryState(
        git_revision=_git_output(root, "rev-parse", "HEAD"),
        git_dirty=bool(status),
        git_untracked=any(line.startswith("??") for line in status.splitlines()),
        git_status_sha256=hashlib.sha256(status.encode("utf-8")).hexdigest(),
        discovery_source_hashes=_source_hashes(
            source_dir,
            DISCOVERY_REQUIRED_SOURCE_MODULES,
        ),
        verification_source_hashes=_source_hashes(
            source_dir,
            VERIFICATION_REQUIRED_SOURCE_MODULES,
        ),
        release_source_hashes=_source_hashes(
            source_dir,
            RELEASE_REQUIRED_SOURCE_MODULES,
        ),
    )


def _mapping_payload(value: Any, *, label: str) -> dict[str, Any]:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvestigationReleaseError(f"{label} is not UTF-8 JSON") from exc
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise InvestigationReleaseError(f"{label} is not valid JSON") from exc
        if not isinstance(decoded, dict):
            raise InvestigationReleaseError(f"{label} must be a JSON object")
        return decoded
    if isinstance(value, BaseModel):
        return value.model_dump(
            mode="python",
            exclude_none=True,
            round_trip=True,
        )
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"{label} must be raw JSON, a mapping, or its canonical model")


def _require_recorded_environment(
    *,
    label: str,
    source_hashes: Mapping[str, str],
    git_revision: str,
    git_dirty: bool,
    git_untracked: bool,
    expected_hashes: Mapping[str, str],
    state: RepositoryState,
) -> None:
    if dict(source_hashes) != dict(expected_hashes):
        raise InvestigationReleaseError(
            f"{label} source hashes do not match measured repository bytes"
        )
    if git_revision != state.git_revision:
        raise InvestigationReleaseError(f"{label} Git revision mismatch")
    if git_dirty != state.git_dirty or git_untracked != state.git_untracked:
        raise InvestigationReleaseError(f"{label} Git worktree state mismatch")


def _validate_source_provenance(
    provenance: SourceProvenance,
    revision: SourceRevision,
) -> None:
    expected = {
        "source_revision_id": revision.source_revision_id,
        "audio_sha256": revision.audio_sha256,
        "raw_transcript_sha256": revision.raw_transcript_sha256,
        "normalized_transcript_sha256": revision.normalized_transcript_sha256,
        "segment_count": revision.segment_count,
    }
    actual = provenance.model_dump(mode="json", exclude_none=False)
    for field, value in expected.items():
        if actual[field] != value:
            raise InvestigationReleaseError(
                f"run provenance {field} does not match the sealed source revision"
            )


def _validate_contradiction_binding(batch: VerificationBatch) -> None:
    ledger = batch.ledger
    if ledger is None:
        raise InvestigationReleaseError("successful T4 release requires a ledger")
    refs = [item.contradiction_id for item in batch.contradictions]
    expected_digest = (
        sha256_canonical_json(
            [
                item.model_dump(mode="json", exclude_none=True)
                for item in batch.contradictions
            ]
        )
        if batch.contradictions
        else None
    )
    if ledger.contradiction_count != len(batch.contradictions):
        raise InvestigationReleaseError("T4 contradiction count was dropped")
    if (ledger.contradiction_refs or []) != refs:
        raise InvestigationReleaseError("T4 contradiction refs were dropped")
    if ledger.contradiction_set_sha256 != expected_digest:
        raise InvestigationReleaseError("T4 contradiction digest mismatch")


def _validation_context_from_replayed_t4(
    *,
    batch: VerificationBatch,
    revision: SourceRevision,
    manifest: InvestigationRunManifest,
    narrative_release: NarrativeReleaseBundle,
):
    from .canonicalization import canonical_claim_sha256

    if batch.ledger is None:
        raise InvestigationReleaseError("T4 ledger is required for factual release")
    resolver = EvidenceSelectorResolver(revision)
    selector_artifacts = {
        artifact.subject_ref: resolver.verify_artifact(artifact)
        for artifact in batch.selector_artifacts
    }
    decisions = {
        decision.verification_id: decision
        for decision in batch.ledger.verification_decisions
    }
    candidates = {
        candidate.candidate_id: candidate for candidate in batch.ledger.candidates
    }
    claims = {claim.claim_id: claim for claim in batch.ledger.claims}
    eligibility_artifacts = {
        artifact.verification_ref: artifact for artifact in batch.eligibility_artifacts
    }
    if set(eligibility_artifacts) != set(decisions):
        raise InvestigationReleaseError(
            "T4 eligibility artifacts must cover the exact decision ledger"
        )
    verification_eligibility: dict[str, _TrustedEligibilityAssessment] = {}
    for decision_id, decision in decisions.items():
        artifact = eligibility_artifacts[decision_id]
        claim = claims.get(decision.canonical_claim_ref or "")
        if artifact.eligibility != decision.projection_eligibility:
            raise InvestigationReleaseError("T4 eligibility decision mismatch")
        if decision.eligibility_artifact_ref is not None and (
            decision.eligibility_artifact_ref != artifact.artifact_id
        ):
            raise InvestigationReleaseError("T4 eligibility artifact ref mismatch")
        verification_eligibility[decision_id] = _TrustedEligibilityAssessment(
            eligibility=artifact.eligibility,
            artifact_ref=artifact.artifact_id,
            subject_sha256=_verification_subject_sha256(
                decision,
                claim,
                candidates[decision.candidate_ref],
            ),
        )

    risk_artifacts = {
        artifact.subject_ref: artifact for artifact in batch.risk_artifacts
    }
    if set(risk_artifacts) != set(claims):
        raise InvestigationReleaseError(
            "T4 risk artifacts must cover the exact canonical claim ledger"
        )
    risk_assessments: dict[str, _TrustedRiskAssessment] = {}
    for claim_id, claim in claims.items():
        artifact = risk_artifacts[claim_id]
        expected_digest = canonical_claim_sha256(claim)
        if artifact.subject_sha256 != expected_digest:
            raise InvestigationReleaseError("T4 risk subject digest mismatch")
        if claim.risk_screening_artifact_ref != artifact.artifact_id:
            raise InvestigationReleaseError("T4 risk artifact ref mismatch")
        risk_assessments[claim_id] = _TrustedRiskAssessment(
            risk_tier=artifact.risk_tier,
            artifact_ref=artifact.artifact_id,
            subject_sha256=artifact.subject_sha256,
        )

    return _build_trusted_investigation_validation_context(
        selector_attestations=_selector_attestations_from_verified_artifacts(
            selector_artifacts,
            subject_kind="verification",
        ),
        relationship_attestations={},
        risk_assessments=risk_assessments,
        verification_eligibility=verification_eligibility,
        relationship_eligibility={},
        reasoning_eligibility={},
        narrative_attestations={
            artifact.artifact_id: artifact
            for artifact in narrative_release.narrative_attestations
        },
        manifest_sha256=_semantic_subject_sha256(manifest),
    )


def _release_investigation_run_impl(
    *,
    discovery_batch: DiscoveryBatch | Mapping[str, Any] | str | bytes,
    verification_batch: VerificationBatch | Mapping[str, Any] | str | bytes,
    source_revision: SourceRevision,
    proposed_run: InvestigationRun | Mapping[str, Any] | str | bytes,
    repository_root: str | Path,
    _mint_release_authority,
    _context_builder,
) -> InvestigationRun:
    """Replay every upstream artifact and publish only an exact factual run."""

    # Keep service imports lazy so run_contracts can finish installing this
    # boundary even when discovery or verification initiated the import cycle.
    from .discovery import verify_discovery_batch
    from .discovery_contracts import DiscoveryBatch, VerifiedDiscoveryBatch
    from .verification import verify_verification_batch
    from .verification_contracts import (
        VerificationBatch,
        VerificationError,
        VerificationReplayResult,
    )

    if isinstance(discovery_batch, VerifiedDiscoveryBatch):
        raise TypeError("release requires the raw T3 artifact, not a wrapper")
    if isinstance(verification_batch, VerificationReplayResult):
        raise TypeError("release requires the raw T4 artifact, not a wrapper")
    revision = _revalidate_source_revision(source_revision)
    state = capture_repository_state(repository_root)

    try:
        raw_discovery = DiscoveryBatch.model_validate_json(
            json.dumps(
                _mapping_payload(discovery_batch, label="T3 discovery artifact"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        raw_verification = VerificationBatch.model_validate_json(
            json.dumps(
                _mapping_payload(verification_batch, label="T4 verification artifact"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    except (ValidationError, ValueError) as exc:
        raise InvestigationReleaseError("invalid T3 or T4 release artifact") from exc

    _require_recorded_environment(
        label="T3",
        source_hashes=raw_discovery.manifest.source_module_hashes,
        git_revision=raw_discovery.manifest.git_revision,
        git_dirty=raw_discovery.manifest.git_dirty,
        git_untracked=raw_discovery.manifest.git_untracked,
        expected_hashes=state.discovery_source_hashes,
        state=state,
    )
    _require_recorded_environment(
        label="T4",
        source_hashes=raw_verification.manifest.source_module_hashes,
        git_revision=raw_verification.manifest.git_revision,
        git_dirty=raw_verification.manifest.git_dirty,
        git_untracked=raw_verification.manifest.git_untracked,
        expected_hashes=state.verification_source_hashes,
        state=state,
    )

    try:
        verified_discovery = verify_discovery_batch(raw_discovery, revision)
        replayed = verify_verification_batch(
            raw_verification,
            verified_discovery=verified_discovery,
            revision=revision,
        ).batch
    except (TypeError, ValueError, VerificationError) as exc:
        raise InvestigationReleaseError("T3/T4 deterministic replay failed") from exc
    if replayed.status != "success":
        raise InvestigationReleaseError("factual release requires T4 status=success")
    if replayed.contradictions:
        raise InvestigationReleaseError("contradictions block factual release")
    _validate_contradiction_binding(replayed)
    if any(
        (
            replayed.ledger.insights,
            replayed.ledger.hypotheses,
            replayed.ledger.verification_actions,
        )
    ):
        raise InvestigationReleaseError(
            "production T4 reasoning attestations are unsupported"
        )

    run_payload = _mapping_payload(proposed_run, label="proposed InvestigationRun")
    try:
        if run_payload.get("run_status") != "success":
            raise InvestigationReleaseError(
                "trusted release adapter publishes only successful factual runs"
            )
        proposed_ledger = CanonicalClaimLedger.model_validate_json(
            json.dumps(
                run_payload.get("ledger"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        manifest = InvestigationRunManifest.model_validate_json(
            json.dumps(
                run_payload.get("manifest"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        provenance = SourceProvenance.model_validate_json(
            json.dumps(
                run_payload.get("provenance"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    except (TypeError, ValueError, ValidationError) as exc:
        if isinstance(exc, InvestigationReleaseError):
            raise
        raise InvestigationReleaseError("proposed InvestigationRun is invalid") from exc

    if replayed.ledger is None or (
        proposed_ledger.model_dump_json(exclude_none=True)
        != replayed.ledger.model_dump_json(exclude_none=True)
    ):
        raise InvestigationReleaseError(
            "proposed run ledger must equal the exact replayed T4 ledger"
        )
    _validate_source_provenance(provenance, revision)
    _require_recorded_environment(
        label="InvestigationRun",
        source_hashes=manifest.source_module_hashes,
        git_revision=manifest.git_revision,
        git_dirty=manifest.git_dirty,
        git_untracked=manifest.git_untracked,
        expected_hashes=state.release_source_hashes,
        state=state,
    )
    released_claim_ids = {
        decision.canonical_claim_ref
        for decision in replayed.ledger.verification_decisions
        if decision.canonical_claim_ref is not None
        and decision.projection_eligibility in {"source_attributed", "factual"}
    }
    released_claims = [
        claim
        for claim in replayed.ledger.claims
        if claim.claim_id in released_claim_ids
    ]
    narrative_release = build_deterministic_narrative_release(
        released_claims=released_claims,
        evidence=replayed.ledger.evidence,
        source_provenance=provenance,
        generation_manifest=manifest,
    )
    try:
        projection_payload = run_payload.get("projections")
        proposed_summary = SummaryProjection.model_validate(
            projection_payload.get("summary")
            if isinstance(projection_payload, Mapping)
            else None
        )
        expected_summary = SummaryProjection.model_validate(
            narrative_release.model_dump(mode="json", exclude_none=True)
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise InvestigationReleaseError(
            "proposed narrative release is malformed"
        ) from exc
    if proposed_summary != expected_summary:
        raise InvestigationReleaseError(
            "proposed narrative must equal deterministic T5 replay"
        )
    trusted_context = _context_builder(
        batch=replayed,
        revision=revision,
        manifest=manifest,
        narrative_release=narrative_release,
    )
    release_authority = _mint_release_authority(trusted_context)
    try:
        released = InvestigationRun.model_validate(
            run_payload,
            context={
                _run_contracts._VALIDATION_CONTEXT_KEY: release_authority,
            },
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise InvestigationReleaseError(
            "proposed InvestigationRun failed trusted release validation"
        ) from exc
    if capture_repository_state(repository_root) != state:
        raise InvestigationReleaseError(
            "repository state changed during trusted release validation"
        )
    return released


def _bind_release_entrypoint(implementation, context_builder, minter):
    def release_investigation_run(
        *,
        discovery_batch: DiscoveryBatch | Mapping[str, Any] | str | bytes,
        verification_batch: VerificationBatch | Mapping[str, Any] | str | bytes,
        source_revision: SourceRevision,
        proposed_run: InvestigationRun | Mapping[str, Any] | str | bytes,
        repository_root: str | Path,
    ) -> InvestigationRun:
        return implementation(
            discovery_batch=discovery_batch,
            verification_batch=verification_batch,
            source_revision=source_revision,
            proposed_run=proposed_run,
            repository_root=repository_root,
            _mint_release_authority=minter,
            _context_builder=context_builder,
        )

    return release_investigation_run


release_investigation_run = _bind_release_entrypoint(
    _release_investigation_run_impl,
    _validation_context_from_replayed_t4,
    _run_contracts._take_release_authority_minter(),
)
delattr(_run_contracts, "_take_release_authority_minter")
del _bind_release_entrypoint
del _release_investigation_run_impl
del _validation_context_from_replayed_t4


def release_investigation_narrative(
    *,
    discovery_batch: DiscoveryBatch | Mapping[str, Any] | str | bytes,
    verification_batch: VerificationBatch | Mapping[str, Any] | str | bytes,
    source_revision: SourceRevision,
    proposed_run: InvestigationRun | Mapping[str, Any] | str | bytes,
    repository_root: str | Path,
) -> ReleasedNarrativeProjection:
    """Replay the full release boundary and return only a sealed narrative view."""

    released_run = release_investigation_run(
        discovery_batch=discovery_batch,
        verification_batch=verification_batch,
        source_revision=source_revision,
        proposed_run=proposed_run,
        repository_root=repository_root,
    )
    return _mint_released_narrative_projection(released_run)


__all__ = [
    "InvestigationReleaseError",
    "RELEASE_REQUIRED_SOURCE_MODULES",
    "RepositoryState",
    "capture_repository_state",
    "release_investigation_narrative",
    "release_investigation_run",
]
