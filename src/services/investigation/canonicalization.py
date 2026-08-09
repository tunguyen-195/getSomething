"""Conservative, provenance-preserving T4 claim and entity reconciliation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .claim_semantics import semantic_merge_key
from .contracts import ConceptMention, GroundedClaim, sha256_canonical_json
from .discovery_contracts import DiscoveryCandidateRecord, EntityChallengerRecord
from .verification_contracts import (
    ClaimMergeRecord,
    EntityClusterRecord,
    SemanticClaimFrame,
    canonical_id,
)


@dataclass(frozen=True)
class CanonicalClaimResult:
    claims: tuple[GroundedClaim, ...]
    merge_records: tuple[ClaimMergeRecord, ...]
    candidate_to_claim: Mapping[str, str]


@dataclass(frozen=True)
class CanonicalEntityResult:
    concepts: tuple[ConceptMention, ...]
    clusters: tuple[EntityClusterRecord, ...]
    evidence_to_concepts: Mapping[str, tuple[str, ...]]


def _semantic_subject_sha256(subject: GroundedClaim) -> str:
    semantic_payload = subject.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"risk_screening_artifact_ref"},
    )
    return sha256_canonical_json(
        {
            "subject_class": subject.__class__.__name__,
            "subject": semantic_payload,
        }
    )


def canonical_claim_sha256(claim: GroundedClaim) -> str:
    return _semantic_subject_sha256(
        GroundedClaim.model_validate_json(claim.model_dump_json(exclude_none=True))
    )


def canonicalize_entities(
    candidate_records: Sequence[DiscoveryCandidateRecord],
    challenger_records: Sequence[EntityChallengerRecord],
) -> CanonicalEntityResult:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in candidate_records:
        candidate = record.candidate
        candidate_attributes = candidate.attributes or {}
        surface = candidate_attributes.get("surface")
        entity_type = candidate_attributes.get("entity_type")
        if not (
            candidate.claim_type.startswith("entity_mention.")
            and isinstance(surface, str)
            and isinstance(entity_type, str)
        ):
            continue
        selector = record.selector_artifact.selectors[0]
        grouped[
            (
                entity_type.casefold(),
                surface.casefold(),
                selector.segment_id,
                selector.raw_char_start,
                selector.raw_char_end,
                selector.quote_sha256,
            )
        ].append(
            {
                "mention_ref": candidate.candidate_id,
                "entity_type": entity_type,
                "surface": surface,
                "role": candidate_attributes.get("role"),
                "evidence_ref": selector.evidence_id,
            }
        )
    for challenger_record in challenger_records:
        selector = challenger_record.selector_artifact.selectors[0]
        grouped[
            (
                challenger_record.entity_type.casefold(),
                challenger_record.surface.casefold(),
                selector.segment_id,
                selector.raw_char_start,
                selector.raw_char_end,
                selector.quote_sha256,
            )
        ].append(
            {
                "mention_ref": challenger_record.mention_id,
                "entity_type": challenger_record.entity_type,
                "surface": challenger_record.surface,
                "role": challenger_record.role,
                "evidence_ref": selector.evidence_id,
            }
        )

    concepts: list[ConceptMention] = []
    clusters: list[EntityClusterRecord] = []
    evidence_to_concepts: dict[str, list[str]] = defaultdict(list)
    for key in sorted(grouped, key=repr):
        members = grouped[key]
        mention_refs = tuple(sorted({str(item["mention_ref"]) for item in members}))
        evidence_refs = tuple(sorted({str(item["evidence_ref"]) for item in members}))
        first = sorted(members, key=lambda item: str(item["mention_ref"]))[0]
        concept_payload = {
            "entity_type": str(first["entity_type"]),
            "normalized_surface": key[1],
            "mention_refs": mention_refs,
            "evidence_refs": evidence_refs,
            "identity_policy": "same_exact_span_only",
        }
        concept_id = canonical_id("concv1", concept_payload)
        concept_attributes: dict[str, Any] = {
            "identity_status": "mention_only",
            "identity_policy": "same_exact_span_only",
            "mention_refs": list(mention_refs),
        }
        roles = sorted(
            {
                str(item["role"])
                for item in members
                if isinstance(item.get("role"), str) and str(item["role"]).strip()
            }
        )
        if roles:
            concept_attributes["source_roles"] = roles
        concepts.append(
            ConceptMention(
                concept_id=concept_id,
                concept_type=str(first["entity_type"]),
                surface=str(first["surface"]),
                role=roles[0] if len(roles) == 1 else None,
                evidence_refs=list(evidence_refs),
                attributes=concept_attributes,
            )
        )
        cluster_payload = {
            "policy_version": "investigation-reconciliation-policy-v1.0",
            "concept_ref": concept_id,
            "entity_type": str(first["entity_type"]),
            "normalized_surface": key[1],
            "mention_refs": mention_refs,
            "evidence_refs": evidence_refs,
            "hard_identity_merge": False,
            "basis": "exact_surface_type_and_evidence",
        }
        clusters.append(
            EntityClusterRecord(
                cluster_id=canonical_id("entclv1", cluster_payload),
                **cluster_payload,
            )
        )
        for evidence_ref in evidence_refs:
            evidence_to_concepts[evidence_ref].append(concept_id)

    return CanonicalEntityResult(
        concepts=tuple(sorted(concepts, key=lambda item: item.concept_id)),
        clusters=tuple(sorted(clusters, key=lambda item: item.cluster_id)),
        evidence_to_concepts={
            key: tuple(sorted(set(values)))
            for key, values in sorted(evidence_to_concepts.items())
        },
    )


def canonicalize_supported_claims(
    *,
    candidates: Mapping[str, Any],
    frames: Mapping[str, SemanticClaimFrame],
    supported_candidate_refs: Sequence[str],
    evidence_to_concepts: Mapping[str, tuple[str, ...]] | None = None,
) -> CanonicalClaimResult:
    groups: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for candidate_ref in sorted(set(supported_candidate_refs)):
        groups[semantic_merge_key(frames[candidate_ref])].append(candidate_ref)

    claims: list[GroundedClaim] = []
    merge_records: list[ClaimMergeRecord] = []
    candidate_to_claim: dict[str, str] = {}
    concept_map = evidence_to_concepts or {}
    for key in sorted(groups, key=repr):
        candidate_refs = tuple(sorted(groups[key]))
        representative_ref = candidate_refs[0]
        candidate = candidates[representative_ref]
        frame = frames[representative_ref]
        evidence_refs = tuple(
            sorted(
                {
                    evidence_ref
                    for candidate_ref in candidate_refs
                    for evidence_ref in frames[candidate_ref].evidence_refs
                }
            )
        )
        concept_refs = tuple(
            sorted(
                {
                    concept_ref
                    for evidence_ref in evidence_refs
                    for concept_ref in concept_map.get(evidence_ref, ())
                }
            )
        )
        claim_payload = {
            "claim_type": candidate.claim_type,
            "statement": candidate.statement,
            "polarity": candidate.polarity,
            "source_revision_id": frame.source_revision_id,
            "candidate_refs": candidate_refs,
            "semantic_frame_refs": tuple(
                sorted(frames[item].frame_id for item in candidate_refs)
            ),
            "evidence_refs": evidence_refs,
            "concept_refs": concept_refs,
        }
        claim_id = canonical_id("clmv1", claim_payload)
        attributes: dict[str, Any] = {
            "t4_semantic_frame_refs": list(claim_payload["semantic_frame_refs"]),
            "source_assertion": frame.source_assertion,
            "source_assertion_sha256": sha256_canonical_json(
                {"source_assertion": frame.source_assertion}
            ),
            "source_modality": frame.source_modality,
            "semantic_policy_version": frame.semantic_policy_version,
        }
        if frame.safe_attributes:
            attributes["safe_candidate_attributes"] = frame.safe_attributes
        grounded_payload: dict[str, Any] = {
            "claim_id": claim_id,
            "claim_type": candidate.claim_type,
            "statement": candidate.statement,
            "polarity": candidate.polarity,
            "disposition": "supported",
            "epistemic_status": "fact",
            "factual_scope": "verified_source_assertion",
            "risk_tier": "ordinary",
            "requires_human_verification": False,
            "evidence_refs": list(evidence_refs),
            "candidate_refs": list(candidate_refs),
            "attributes": attributes,
        }
        if concept_refs:
            grounded_payload["concept_refs"] = list(concept_refs)
        provisional_claim = GroundedClaim(**grounded_payload)
        risk_subject_sha256 = canonical_claim_sha256(provisional_claim)
        risk_artifact_ref = canonical_id(
            "riskv1",
            {
                "subject_ref": claim_id,
                "subject_sha256": risk_subject_sha256,
                "risk_tier": "ordinary",
                "basis": "verified_source_assertion_only",
            },
        )
        claim = GroundedClaim(
            **grounded_payload,
            risk_screening_artifact_ref=risk_artifact_ref,
        )
        claims.append(claim)
        for candidate_ref in candidate_refs:
            candidate_to_claim[candidate_ref] = claim_id
        merge_payload = {
            "policy_version": "investigation-reconciliation-policy-v1.0",
            "canonical_claim_ref": claim_id,
            "member_candidate_refs": candidate_refs,
            "evidence_refs": evidence_refs,
            "hard_merge": True,
            "basis": "exact_semantics_and_evidence",
        }
        merge_records.append(
            ClaimMergeRecord(
                merge_id=canonical_id("mrgv1", merge_payload),
                policy_version="investigation-reconciliation-policy-v1.0",
                canonical_claim_ref=claim_id,
                member_candidate_refs=candidate_refs,
                evidence_refs=evidence_refs,
                hard_merge=True,
                basis="exact_semantics_and_evidence",
            )
        )
    return CanonicalClaimResult(
        claims=tuple(sorted(claims, key=lambda item: item.claim_id)),
        merge_records=tuple(
            sorted(merge_records, key=lambda item: item.canonical_claim_ref)
        ),
        candidate_to_claim=dict(sorted(candidate_to_claim.items())),
    )


__all__ = [
    "CanonicalClaimResult",
    "CanonicalEntityResult",
    "canonical_claim_sha256",
    "canonicalize_entities",
    "canonicalize_supported_claims",
]
