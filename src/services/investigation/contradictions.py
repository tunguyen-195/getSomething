"""Polarity-aware contradiction preservation for verified source assertions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from .claim_semantics import proposition_core
from .contracts import sha256_canonical_json
from .verification_contracts import (
    ContradictionRecord,
    SemanticClaimFrame,
    canonical_id,
)

_OPPOSING_POLARITIES = frozenset({"affirmed", "negated"})


def discover_contradictions(
    *,
    frames: Mapping[str, SemanticClaimFrame],
    candidate_to_claim: Mapping[str, str],
) -> tuple[ContradictionRecord, ...]:
    """Keep supported source assertions separate and record compatible conflicts."""

    blocks: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for candidate_ref in sorted(candidate_to_claim):
        frame = frames[candidate_ref]
        core = proposition_core(frame)
        if core and frame.polarity in _OPPOSING_POLARITIES:
            blocks[(frame.claim_type, core)][frame.polarity].append(candidate_ref)

    records: list[ContradictionRecord] = []
    for block in sorted(blocks, key=repr):
        polarities = blocks[block]
        affirmed_refs = tuple(sorted(set(polarities.get("affirmed", ()))))
        negated_refs = tuple(sorted(set(polarities.get("negated", ()))))
        if not affirmed_refs or not negated_refs:
            continue
        candidate_refs = tuple(sorted((*affirmed_refs, *negated_refs)))
        claim_refs = tuple(
            sorted({candidate_to_claim[item] for item in candidate_refs})
        )
        if len(claim_refs) < 2:
            continue
        evidence_refs = tuple(
            sorted(
                {
                    evidence_ref
                    for candidate_ref in candidate_refs
                    for evidence_ref in frames[candidate_ref].evidence_refs
                }
            )
        )
        if len(evidence_refs) < 2:
            continue
        proposition_key_sha256 = sha256_canonical_json(
            {"claim_type": block[0], "proposition_core": block[1]}
        )
        total_pair_count = len(affirmed_refs) * len(negated_refs)
        payload = {
            "policy_version": "investigation-contradiction-policy-v1.0",
            "proposition_key_sha256": proposition_key_sha256,
            "candidate_refs": candidate_refs,
            "affirmed_candidate_refs": affirmed_refs,
            "negated_candidate_refs": negated_refs,
            "claim_refs": claim_refs,
            "evidence_refs": evidence_refs,
            "total_pair_count": total_pair_count,
            "materialized_pair_count": 0,
            "omitted_pair_count": total_pair_count,
            "conflict_dimension": "polarity",
            "status": "needs_review",
            "assertions_preserved": True,
        }
        records.append(
            ContradictionRecord(
                contradiction_id=canonical_id("conflv1", payload),
                **payload,
            )
        )
    return tuple(sorted(records, key=lambda item: item.contradiction_id))


__all__ = ["discover_contradictions"]
