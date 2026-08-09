from __future__ import annotations

from src.services.investigation.canonicalization import canonicalize_supported_claims
from src.services.investigation.claim_semantics import extract_semantic_roles
from src.services.investigation.contracts import sha256_canonical_json
from src.services.investigation.contradictions import discover_contradictions
from src.services.investigation.run_contracts import DiscoveryCandidate
from src.services.investigation.verification_contracts import SemanticClaimFrame


def _candidate(candidate_id: str, statement: str, polarity: str):
    return DiscoveryCandidate(
        candidate_id=candidate_id,
        claim_type="event.arrival",
        statement=statement,
        polarity=polarity,
        evidence_refs=[f"ev-{candidate_id}"],
    )


def _frame(
    candidate,
    *,
    source_assertion: str,
    evidence_ref: str,
    raw_start: int,
    polarity: str | None = None,
):
    payload = {
        "semantic_policy_version": "investigation-semantic-policy-v1.2",
        "candidate_ref": candidate.candidate_id,
        "candidate_sha256": sha256_canonical_json(
            candidate.model_dump(mode="json", exclude_none=True)
        ),
        "source_revision_id": "srcv1:" + "a" * 64,
        "segment_id": f"segment-{raw_start}",
        "raw_char_start": raw_start,
        "raw_char_end": raw_start + len(source_assertion),
        "quote_sha256": sha256_canonical_json({"quote": source_assertion}),
        "claim_type": candidate.claim_type,
        "candidate_statement": candidate.statement,
        "source_assertion": source_assertion,
        "polarity": polarity or candidate.polarity,
        "source_modality": polarity or candidate.polarity,
        "atomicity": "atomic",
        "atomic_units": (source_assertion,),
        "evidence_refs": (evidence_ref,),
        "speaker_id": "SPEAKER_0",
        "exact_values": (),
        "source_roles": extract_semantic_roles(source_assertion).model_dump(
            mode="json",
            exclude_none=True,
        ),
        "safe_attributes": {
            "semantic_policy_version": "investigation-semantic-policy-v1.2"
        },
    }
    frame_hash = sha256_canonical_json(payload)
    return SemanticClaimFrame(
        frame_id=f"semv1:{frame_hash}",
        frame_sha256=frame_hash,
        **payload,
    )


def test_exact_duplicate_semantics_and_span_merge_deterministically():
    statement = "Minh đến lúc 09:00."
    left = _candidate("cand-left", statement, "affirmed")
    right = _candidate("cand-right", statement, "affirmed")
    left_frame = _frame(
        left,
        source_assertion=statement,
        evidence_ref="ev-left",
        raw_start=0,
    )
    right_frame = _frame(
        right,
        source_assertion=statement,
        evidence_ref="ev-right",
        raw_start=0,
    ).model_copy(update={"segment_id": left_frame.segment_id})
    right_payload = right_frame.model_dump(mode="python", exclude_none=True)
    right_payload.pop("frame_id")
    right_payload.pop("frame_sha256")
    right_hash = sha256_canonical_json(right_payload)
    right_frame = SemanticClaimFrame(
        frame_id=f"semv1:{right_hash}",
        frame_sha256=right_hash,
        **right_payload,
    )

    result = canonicalize_supported_claims(
        candidates={left.candidate_id: left, right.candidate_id: right},
        frames={left.candidate_id: left_frame, right.candidate_id: right_frame},
        supported_candidate_refs=(right.candidate_id, left.candidate_id),
    )

    assert len(result.claims) == 1
    assert result.claims[0].candidate_refs == ["cand-left", "cand-right"]
    assert result.claims[0].evidence_refs == ["ev-left", "ev-right"]
    assert result.merge_records[0].member_candidate_refs == (
        "cand-left",
        "cand-right",
    )


def test_same_statement_at_different_spans_does_not_hard_merge():
    statement = "Minh đến lúc 09:00."
    left = _candidate("cand-left", statement, "affirmed")
    right = _candidate("cand-right", statement, "affirmed")
    frames = {
        left.candidate_id: _frame(
            left,
            source_assertion=statement,
            evidence_ref="ev-left",
            raw_start=0,
        ),
        right.candidate_id: _frame(
            right,
            source_assertion=statement,
            evidence_ref="ev-right",
            raw_start=100,
        ),
    }

    result = canonicalize_supported_claims(
        candidates={left.candidate_id: left, right.candidate_id: right},
        frames=frames,
        supported_candidate_refs=(left.candidate_id, right.candidate_id),
    )

    assert len(result.claims) == 2
    assert len(result.merge_records) == 2


def test_opposite_polarity_is_never_merged_and_creates_conflict_record():
    affirmed = _candidate("cand-yes", "Minh đến lúc 09:00.", "affirmed")
    negated = _candidate("cand-no", "Minh không đến lúc 09:00.", "negated")
    frames = {
        affirmed.candidate_id: _frame(
            affirmed,
            source_assertion=affirmed.statement,
            evidence_ref="ev-yes",
            raw_start=0,
        ),
        negated.candidate_id: _frame(
            negated,
            source_assertion=negated.statement,
            evidence_ref="ev-no",
            raw_start=100,
        ),
    }
    result = canonicalize_supported_claims(
        candidates={
            affirmed.candidate_id: affirmed,
            negated.candidate_id: negated,
        },
        frames=frames,
        supported_candidate_refs=(affirmed.candidate_id, negated.candidate_id),
    )

    conflicts = discover_contradictions(
        frames=frames,
        candidate_to_claim=result.candidate_to_claim,
    )

    assert len(result.claims) == 2
    assert len(conflicts) == 1
    assert conflicts[0].assertions_preserved is True
    assert conflicts[0].status == "needs_review"
    assert set(conflicts[0].candidate_refs) == {"cand-yes", "cand-no"}


def test_candidate_order_does_not_change_claim_or_merge_ids():
    statement = "Minh đến lúc 09:00."
    left = _candidate("cand-left", statement, "affirmed")
    right = _candidate("cand-right", statement, "affirmed")
    left_frame = _frame(
        left,
        source_assertion=statement,
        evidence_ref="ev-left",
        raw_start=0,
    )
    right_frame = _frame(
        right,
        source_assertion=statement,
        evidence_ref="ev-right",
        raw_start=0,
    )
    right_payload = right_frame.model_dump(mode="python", exclude_none=True)
    right_payload["segment_id"] = left_frame.segment_id
    right_payload.pop("frame_id")
    right_payload.pop("frame_sha256")
    right_hash = sha256_canonical_json(right_payload)
    right_frame = SemanticClaimFrame(
        frame_id=f"semv1:{right_hash}",
        frame_sha256=right_hash,
        **right_payload,
    )
    candidates = {left.candidate_id: left, right.candidate_id: right}
    frames = {left.candidate_id: left_frame, right.candidate_id: right_frame}

    first = canonicalize_supported_claims(
        candidates=candidates,
        frames=frames,
        supported_candidate_refs=(left.candidate_id, right.candidate_id),
    )
    second = canonicalize_supported_claims(
        candidates=candidates,
        frames=frames,
        supported_candidate_refs=(right.candidate_id, left.candidate_id),
    )

    assert first.claims[0].claim_id == second.claims[0].claim_id
    assert first.merge_records[0].merge_id == second.merge_records[0].merge_id
