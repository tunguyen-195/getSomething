from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from src.services.investigation.discovery import (
    DISCOVERY_SYSTEM_PROMPT,
    ChunkPlannerConfig,
    EntityChallengerDraft,
    LLMAtomicCandidateDraft,
    LLMDiscoveryResponse,
    LLMEntityMentionDraft,
    RetryPolicy,
    build_chunk_plan,
    build_discovery_batch,
    build_discovery_manifest,
    materialize_entity_challenger_mentions,
    materialize_llm_candidates,
    verify_discovery_batch,
)
from src.services.investigation.discovery_contracts import DiscoveryBatch
from src.services.investigation.source_revision import (
    SourceScope,
    SourceSegmentDraft,
    build_source_revision,
)
from src.services.investigation.verification import (
    CheckerObservation,
    build_verification_batch,
    verify_verification_batch,
)
from src.services.investigation.verification_contracts import (
    CandidateVerificationRecord,
    VerificationError,
)


def _revision(texts: list[str], *, file_id: str = "file-1"):
    texts = [text.strip() for text in texts]
    return build_source_revision(
        scope=SourceScope(
            case_id="case-1",
            file_id=file_id,
            source_id=f"source-{file_id}",
        ),
        raw_transcript="\n".join(texts),
        segments=[
            SourceSegmentDraft(
                text=text,
                speaker_id=f"SPEAKER_{index}",
                start_seconds=float(index * 2),
                end_seconds=float(index * 2 + 1),
            )
            for index, text in enumerate(texts)
        ],
    )


def _config():
    return ChunkPlannerConfig(
        max_context_tokens=2048,
        reserved_output_tokens=256,
        target_chunk_tokens=256,
        overlap_turns=1,
        chars_per_token=2.8,
    )


def _manifest(plan):
    return build_discovery_manifest(
        chunk_plan=plan,
        transmitted_system_prompt=DISCOVERY_SYSTEM_PROMPT,
        model_id="fixture-model",
        model_digest="sha256:model",
        provider="fixture",
        quantization="none",
        tokenizer_revision="tokenizer-r1",
        tokenizer_sha256="0" * 64,
        chat_template_revision="template-r1",
        chat_template_sha256="1" * 64,
        runtime_id="fixture-runtime",
        runtime_digest="sha256:runtime",
        decoding_config={"temperature": 0, "seed": 0},
        retry_policy=RetryPolicy(),
        source_module_hashes={
            "chunk_planner.py": "2" * 64,
            "discovery.py": "3" * 64,
            "discovery_common.py": "4" * 64,
            "discovery_contracts.py": "5" * 64,
            "exact_detectors.py": "6" * 64,
        },
        git_revision="fixture",
        git_dirty=True,
        git_untracked=True,
    )


def _t4_hashes():
    return {
        "verification.py": "1" * 64,
        "verification_contracts.py": "2" * 64,
        "claim_semantics.py": "3" * 64,
        "canonicalization.py": "4" * 64,
        "contradictions.py": "5" * 64,
    }


def _verified_discovery(
    revision,
    *,
    candidates: tuple[LLMAtomicCandidateDraft, ...] = (),
    entity_mentions: tuple[LLMEntityMentionDraft, ...] = (),
    challenger_mentions: tuple[EntityChallengerDraft, ...] = (),
):
    plan = build_chunk_plan(revision, _config())
    response = LLMDiscoveryResponse(
        candidates=candidates,
        entity_mentions=entity_mentions,
    )
    candidate_records = materialize_llm_candidates(
        revision,
        plan.chunks[0],
        response,
    )
    challenger_records = materialize_entity_challenger_mentions(
        revision,
        plan.chunks[0],
        challenger_mentions,
        challenger_id="fixture-challenger",
        challenger_version="1",
    )
    batch = build_discovery_batch(
        revision=revision,
        chunk_plan=plan,
        manifest=_manifest(plan),
        candidate_records=candidate_records,
        entity_challenger_records=challenger_records,
    )
    return batch, verify_discovery_batch(batch, revision)


def _build_t4(verified, revision, *, checker=None):
    return build_verification_batch(
        verified_discovery=verified,
        revision=revision,
        source_module_hashes=_t4_hashes(),
        git_revision="fixture",
        git_dirty=True,
        git_untracked=True,
        checker=checker,
    )


class _Checker:
    def __init__(self, outcome: str):
        self.outcome = outcome

    def manifest(self):
        return {
            "adapter_id": "fixture-checker",
            "adapter_version": "1",
            "model_id": "fixture-nli",
            "model_revision": "revision-1",
            "runtime_id": "fixture-runtime",
            "network_required": False,
        }

    def evaluate(self, *, premise, hypothesis, frame):
        del premise, hypothesis, frame
        return CheckerObservation(outcome=self.outcome, score=0.9)


def test_supported_atomic_claim_replays_with_canonical_ids_and_exact_evidence():
    revision = _revision(["Minh chuyển 15 triệu đồng cho Lan lúc 09:00."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.transfer",
        statement=segment.text,
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))

    batch = _build_t4(verified, revision)
    replayed = verify_verification_batch(
        batch,
        verified_discovery=verified,
        revision=revision,
    )

    assert batch.status == "success"
    assert batch.batch_id.startswith("t4batchv1:")
    assert replayed.batch.batch_id == batch.batch_id
    assert batch.records[0].verification_id.startswith("verv1:")
    assert batch.ledger is not None
    claim = batch.ledger.claims[0]
    assert claim.claim_id.startswith("clmv1:")
    assert claim.statement == draft.statement
    assert claim.polarity == "affirmed"
    evidence = batch.ledger.evidence[0]
    assert evidence.quote_exact == segment.text
    assert evidence.speaker_id == "SPEAKER_0"
    assert evidence.start_seconds == 0.0
    assert batch.network_required is False
    assert batch.release_authority is False


def test_raw_or_detached_discovery_cannot_enter_t4():
    revision = _revision(["Lan có mặt lúc 10:00."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.presence",
        statement=segment.text,
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    raw, _ = _verified_discovery(revision, candidates=(draft,))

    with pytest.raises(TypeError, match="VerifiedDiscoveryBatch"):
        build_verification_batch(
            verified_discovery=raw,  # type: ignore[arg-type]
            revision=revision,
            source_module_hashes=_t4_hashes(),
            git_revision="fixture",
            git_dirty=True,
            git_untracked=True,
        )


def test_unrelated_candidate_statement_is_withheld_and_never_becomes_claim():
    revision = _revision(["Trời hôm nay có mưa nhẹ."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="criminal.accusation",
        statement="Lan đã nhận 50 triệu đồng.",
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))

    batch = _build_t4(verified, revision)

    assert batch.status == "needs_review"
    assert batch.ledger is not None
    assert batch.ledger.claims == []
    assert batch.records[0].projection_eligibility == "withheld"
    assert "statement_alignment" in batch.records[0].failure_codes
    assert "exact_values" in batch.records[0].failure_codes


def test_polarity_mismatch_is_contradicted_and_withheld():
    revision = _revision(["Minh không đến điểm hẹn lúc 09:00."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.arrival",
        statement=segment.text,
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))

    batch = _build_t4(verified, revision)

    assert batch.records[0].disposition == "contradicted"
    assert batch.records[0].projection_eligibility == "withheld"
    assert batch.ledger is not None and batch.ledger.claims == []


@pytest.mark.parametrize(
    ("source", "claim_type", "polarity"),
    [
        ("Lan nói Minh đã rời đi.", "reported.departure", "reported"),
        (
            "Theo lời Lan, Minh đã nhận 15 triệu đồng.",
            "event.transfer",
            "affirmed",
        ),
        (
            "Lan cáo buộc Minh đã nhận tiền.",
            "criminal.accusation",
            "affirmed",
        ),
        ("Theo Lan, Minh đã nhận tiền.", "event.transfer", "affirmed"),
        ("Theo nguồn tin, Minh đã nhận tiền.", "event.transfer", "affirmed"),
        ("Được cho là Minh đã nhận tiền.", "event.transfer", "affirmed"),
        ("Lan tố Minh đã nhận tiền.", "criminal.accusation", "affirmed"),
    ],
)
def test_reported_source_assertion_cannot_be_promoted_to_affirmed(
    source,
    claim_type,
    polarity,
):
    revision = _revision([source])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type=claim_type,
        statement=segment.text,
        polarity=polarity,
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))
    batch = _build_t4(verified, revision)

    assert batch.ledger is not None
    assert batch.status == "needs_review"
    assert batch.ledger.claims == []
    assert batch.ledger.attributed_assertion_candidate_refs == [
        batch.records[0].candidate_ref
    ]
    assert batch.records[0].projection_eligibility == "withheld"
    assert "factual_modality" in batch.records[0].failure_codes


def test_compound_candidate_is_split_for_diagnosis_but_not_projected():
    text = "Minh đến lúc 09:00; Lan rời đi lúc 10:00."
    revision = _revision([text])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.compound",
        statement=text,
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=text,
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))

    batch = _build_t4(verified, revision)

    assert batch.semantic_frames[0].atomicity == "compound"
    assert batch.semantic_frames[0].atomic_units == (
        "Minh đến lúc 09:00",
        "Lan rời đi lúc 10:00.",
    )
    assert batch.records[0].projection_eligibility == "withheld"
    assert batch.ledger is not None and batch.ledger.claims == []


def test_exact_value_and_unit_mutation_is_withheld():
    revision = _revision(["Minh giao 15 triệu đồng cho Lan."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.transfer",
        statement="Minh giao 50 tỷ đồng cho Lan.",
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
        attributes={"amount": "50 tỷ đồng", "owner": "Minh"},
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))

    batch = _build_t4(verified, revision)

    assert batch.records[0].disposition == "contradicted"
    assert "exact_values" in batch.records[0].failure_codes
    assert "owner_unit_binding" in batch.records[0].failure_codes


def test_checker_disagreement_is_retained_and_cannot_silently_promote():
    revision = _revision(["Lan có mặt lúc 10:00."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.presence",
        statement=segment.text,
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))

    batch = _build_t4(verified, revision, checker=_Checker("contradicts"))

    assert batch.status == "needs_review"
    assert batch.checker_signals[0].non_authoritative is True
    assert batch.checker_signals[0].can_promote is False
    assert batch.checker_signals[0].outcome == "contradicts"
    assert "checker_disagreement" in batch.records[0].failure_codes
    assert batch.records[0].projection_eligibility == "withheld"


def test_checker_entailment_cannot_override_missing_semantic_grounding():
    revision = _revision(["Lan gọi điện cho Minh."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.payment",
        statement="Lan chuyển 100 triệu đồng cho Minh.",
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))

    batch = _build_t4(verified, revision, checker=_Checker("entails"))

    assert batch.checker_signals[0].outcome == "entails"
    assert batch.records[0].projection_eligibility == "withheld"
    assert batch.ledger is not None and batch.ledger.claims == []


def test_arbitrary_verification_id_is_rejected_by_contract():
    revision = _revision(["Lan có mặt."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.presence",
        statement=segment.text,
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))
    batch = _build_t4(verified, revision)
    payload = batch.records[0].model_dump(mode="python", exclude_none=True)
    payload["verification_id"] = "arbitrary-id"
    payload["record_id"] = "arbitrary-record"

    with pytest.raises(ValidationError, match="verification ID is not canonical"):
        CandidateVerificationRecord.model_validate(payload)


def test_resealed_semantic_tamper_fails_deterministic_replay():
    revision = _revision(["Lan có mặt lúc 10:00."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.presence",
        statement=segment.text,
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))
    batch = _build_t4(verified, revision)
    forged = batch.model_copy(
        update={
            "semantic_frames": (
                batch.semantic_frames[0].model_copy(
                    update={"candidate_statement": "Nội dung đã bị đổi."}
                ),
            )
        }
    )

    with pytest.raises(VerificationError, match="invalid T4 verification artifact"):
        verify_verification_batch(
            forged,
            verified_discovery=verified,
            revision=revision,
        )


def test_no_claim_candidates_is_source_bound_and_has_no_ledger():
    revision = _revision(["Anh Minh đang nghe máy."])
    segment = revision.segments[0]
    challenger = EntityChallengerDraft(
        entity_type="person",
        surface="Minh",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    _, verified = _verified_discovery(
        revision,
        challenger_mentions=(challenger,),
    )

    batch = _build_t4(verified, revision)

    assert batch.status == "no_claim_candidates"
    assert batch.ledger is None
    assert batch.source_revision_id == revision.source_revision_id
    assert (
        verify_verification_batch(
            batch,
            verified_discovery=verified,
            revision=revision,
        ).batch.batch_id
        == batch.batch_id
    )


def test_cross_revision_replay_fails_closed():
    revision = _revision(["Lan có mặt."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.presence",
        statement=segment.text,
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))
    other = _revision(["Lan vắng mặt."], file_id="file-2")

    with pytest.raises(Exception, match="source|scope|revision"):
        _build_t4(verified, other)


def test_model_copy_batch_tamper_cannot_bypass_replay():
    revision = _revision(["Lan có mặt."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.presence",
        statement=segment.text,
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    _, verified = _verified_discovery(revision, candidates=(draft,))
    batch = _build_t4(verified, revision)
    forged_payload = copy.deepcopy(batch.model_dump(mode="json", exclude_none=True))
    forged_payload["records"][0]["projection_eligibility"] = "withheld"

    with pytest.raises(VerificationError, match="invalid T4 verification artifact"):
        verify_verification_batch(
            forged_payload,
            verified_discovery=verified,
            revision=revision,
        )


def test_verification_batch_embeds_the_exact_replayed_discovery_artifact():
    revision = _revision(["Lan có mặt."])
    segment = revision.segments[0]
    draft = LLMAtomicCandidateDraft(
        candidate_kind="claim",
        claim_type="event.presence",
        statement=segment.text,
        polarity="affirmed",
        segment_id=segment.segment_id,
        quote_exact=segment.text,
    )
    raw, verified = _verified_discovery(revision, candidates=(draft,))
    batch = _build_t4(verified, revision)

    assert isinstance(batch.discovery_batch, DiscoveryBatch)
    assert batch.discovery_batch.batch_id == raw.batch_id
    assert batch.discovery_batch.batch_sha256 == raw.batch_sha256
