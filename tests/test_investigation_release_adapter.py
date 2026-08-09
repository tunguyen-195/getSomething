from __future__ import annotations

import builtins
import copy
import json
import socket
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from pydantic import ValidationError

import src.services.investigation.run_contracts as run_contracts_module
import src.services.investigation.verification as verification_module
from src.services.investigation.contracts import ADAPTIVE_DISCOVERY_PROMPT_VERSION
from src.services.investigation.contracts import sha256_canonical_json, sha256_utf8
from src.services.investigation.discovery import (
    DISCOVERY_SYSTEM_PROMPT,
    ChunkPlannerConfig,
    LLMAtomicCandidateDraft,
    LLMDiscoveryResponse,
    RetryPolicy,
    build_chunk_plan,
    build_discovery_batch,
    build_discovery_manifest,
    materialize_llm_candidates,
    verify_discovery_batch,
)
from src.services.investigation.discovery_contracts import discovery_batch_sha256
from src.services.investigation.narrative_attestation import (
    ReleasedNarrativeProjection,
    build_s2_contract_snapshot,
    build_deterministic_narrative_release,
    classify_released_claim,
    released_narrative_metadata,
    render_released_narrative_text,
    verify_s2_contract_snapshot,
)
from src.services.investigation.release_adapter import (
    InvestigationReleaseError,
    capture_repository_state,
    release_investigation_narrative,
    release_investigation_run,
)
from src.services.investigation.run_contracts import (
    InvestigationRun,
    build_investigation_run_manifest,
)
from src.services.investigation.source_revision import (
    SourceScope,
    SourceSegmentDraft,
    build_source_revision,
)
from src.services.investigation.verification import build_verification_batch
from src.services.investigation.verification_contracts import (
    RiskAssessmentArtifact,
    VerificationBatch,
    VerificationReplayResult,
    canonical_id,
    verification_batch_sha256,
)
from src.services.visualization import (
    InvestigationVisualization,
    VisualizationProjectionError,
    project_released_investigation_run,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _revision(texts: list[str]):
    return build_source_revision(
        scope=SourceScope(
            case_id="release-case",
            file_id="release-file",
            source_id="release-source",
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


def _artifacts(
    texts: list[str],
    specs: list[dict[str, str | int]],
):
    revision = _revision(texts)
    state = capture_repository_state(PROJECT_ROOT)
    plan = build_chunk_plan(
        revision,
        ChunkPlannerConfig(
            max_context_tokens=2048,
            reserved_output_tokens=256,
            target_chunk_tokens=512,
            overlap_turns=1,
            chars_per_token=2.8,
        ),
    )
    chunk = plan.chunks[0]
    drafts = []
    for spec in specs:
        segment = revision.segments[int(spec["segment_index"])]
        drafts.append(
            LLMAtomicCandidateDraft(
                candidate_kind="claim",
                claim_type=str(spec["claim_type"]),
                statement=str(spec.get("statement") or segment.text),
                polarity=str(spec.get("polarity") or "affirmed"),
                segment_id=segment.segment_id,
                quote_exact=segment.text,
            )
        )
    records = materialize_llm_candidates(
        revision,
        chunk,
        LLMDiscoveryResponse(candidates=tuple(drafts)),
    )
    manifest = build_discovery_manifest(
        chunk_plan=plan,
        transmitted_system_prompt=DISCOVERY_SYSTEM_PROMPT,
        model_id="release-fixture-model",
        model_digest="sha256:" + "1" * 64,
        provider="deterministic-fixture",
        quantization="none",
        tokenizer_revision="fixture-tokenizer-v1",
        tokenizer_sha256="2" * 64,
        chat_template_revision="fixture-template-v1",
        chat_template_sha256="3" * 64,
        runtime_id="fixture-runtime",
        runtime_digest="sha256:" + "4" * 64,
        decoding_config={"temperature": 0, "seed": 0},
        retry_policy=RetryPolicy(),
        source_module_hashes=state.discovery_source_hashes,
        git_revision=state.git_revision,
        git_dirty=state.git_dirty,
        git_untracked=state.git_untracked,
    )
    discovery = build_discovery_batch(
        revision=revision,
        chunk_plan=plan,
        manifest=manifest,
        candidate_records=records,
    )
    verified = verify_discovery_batch(discovery, revision)
    verification = build_verification_batch(
        verified_discovery=verified,
        revision=revision,
        source_module_hashes=state.verification_source_hashes,
        git_revision=state.git_revision,
        git_dirty=state.git_dirty,
        git_untracked=state.git_untracked,
    )
    return revision, discovery, verified, verification, state


def _direct_fact_artifacts():
    text = "Minh chuyển 15 triệu đồng cho Lan lúc 09:00."
    return _artifacts(
        [text],
        [
            {
                "segment_index": 0,
                "claim_type": "event.transfer",
                "statement": text,
                "polarity": "affirmed",
            }
        ],
    )


def _general_fact_artifacts():
    texts = [
        "Hùng đưa gói hàng cho Lan.",
        "Chiếc túi màu đen thuộc về Minh.",
    ]
    return _artifacts(
        texts,
        [
            {
                "segment_index": 0,
                "claim_type": "exchange.handover",
                "statement": texts[0],
            },
            {
                "segment_index": 1,
                "claim_type": "possession.ownership",
                "statement": texts[1],
            },
        ],
    )


def _proposed_run(revision, verification, state):
    assert verification.status == "success"
    assert verification.ledger is not None
    claim_refs = [claim.claim_id for claim in verification.ledger.claims]
    assert claim_refs
    manifest = build_investigation_run_manifest(
        prompt="Release exact T4 facts only.",
        prompt_version=ADAPTIVE_DISCOVERY_PROMPT_VERSION,
        model_id="release-fixture-model",
        model_digest="sha256:" + "1" * 64,
        provider="deterministic-fixture",
        decoding_config={"temperature": 0, "seed": 0},
        source_module_hashes=state.release_source_hashes,
        git_revision=state.git_revision,
        git_dirty=state.git_dirty,
        git_untracked=state.git_untracked,
    )
    narrative_release = build_deterministic_narrative_release(
        released_claims=verification.ledger.claims,
        evidence=verification.ledger.evidence,
        source_provenance={
            "source_revision_id": revision.source_revision_id,
            "raw_transcript_sha256": revision.raw_transcript_sha256,
            "normalized_transcript_sha256": revision.normalized_transcript_sha256,
            "segment_count": revision.segment_count,
            **(
                {"audio_sha256": revision.audio_sha256}
                if revision.audio_sha256 is not None
                else {}
            ),
        },
        generation_manifest=manifest,
    )
    return {
        "schema_version": "investigation-run-v1.0",
        "run_id": "release-fixture-run",
        "run_status": "success",
        "ledger": verification.ledger.model_dump(mode="json", exclude_none=True),
        "projections": {
            "summary": narrative_release.model_dump(mode="json", exclude_none=True),
            "analysis": {
                "released_claim_refs": claim_refs,
                "source_attributed_claim_refs": claim_refs,
            },
        },
        "provenance": {
            "source_revision_id": revision.source_revision_id,
            "raw_transcript_sha256": revision.raw_transcript_sha256,
            "normalized_transcript_sha256": revision.normalized_transcript_sha256,
            "segment_count": revision.segment_count,
            **(
                {"audio_sha256": revision.audio_sha256}
                if revision.audio_sha256 is not None
                else {}
            ),
        },
        "safety": {
            "transcript_is_untrusted_data": True,
            "evidence_required_for_released_claims": True,
            "high_risk_requires_human_verification": True,
            "unsupported_high_risk_claims_released": False,
        },
        "manifest": manifest.model_dump(mode="json", exclude_none=True),
    }


def _different_sha256(value: str) -> str:
    replacement = "0" if value[0] != "0" else "1"
    return replacement + value[1:]


def _reseal_discovery(discovery, manifest_updates):
    payload = discovery.model_dump(mode="json", exclude_none=True)
    payload["manifest"].update(manifest_updates)
    payload["batch_sha256"] = discovery_batch_sha256(payload)
    payload["batch_id"] = f"discv1:{payload['batch_sha256']}"
    return type(discovery).model_validate_json(
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    )


def _exception_chain_messages(error: BaseException) -> str:
    messages: list[str] = []
    current: BaseException | None = error
    while current is not None:
        messages.append(str(current))
        current = current.__cause__ or current.__context__
    return " | ".join(messages)


def _release(revision, discovery, verification, proposed):
    return release_investigation_run(
        discovery_batch=discovery,
        verification_batch=verification,
        source_revision=revision,
        proposed_run=proposed,
        repository_root=PROJECT_ROOT,
    )


def _reseal_sentence_attestation(summary: dict, sentence: dict, **updates) -> None:
    artifact_ref = sentence["semantic_attestation_ref"]
    artifact = next(
        item
        for item in summary["narrative_attestations"]
        if item["artifact_id"] == artifact_ref
    )
    artifact_payload = copy.deepcopy(artifact)
    artifact_payload.pop("artifact_id")
    artifact_payload.update(updates)
    artifact_payload["artifact_id"] = (
        f"t5attv1:{sha256_canonical_json(artifact_payload)}"
    )
    artifact.clear()
    artifact.update(artifact_payload)
    sentence["semantic_attestation_ref"] = artifact_payload["artifact_id"]


def _replace_sentence_text(summary: dict, sentence: dict, text: str) -> None:
    content_sha256 = sha256_utf8(text)
    sentence["text"] = text
    sentence["content_sha256"] = content_sha256
    _reseal_sentence_attestation(
        summary,
        sentence,
        content_sha256=content_sha256,
    )


@pytest.mark.parametrize("wire_format", ["model", "mapping", "json", "bytes"])
def test_trusted_release_replays_exact_t3_t4_source_and_repository_state(wire_format):
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    if wire_format == "model":
        discovery_input = discovery
        verification_input = verification
        proposed_input = proposed
    elif wire_format == "mapping":
        discovery_input = discovery.model_dump(mode="json", exclude_none=True)
        verification_input = verification.model_dump(mode="json", exclude_none=True)
        proposed_input = proposed
    elif wire_format == "json":
        discovery_input = discovery.model_dump_json(exclude_none=True)
        verification_input = verification.model_dump_json(exclude_none=True)
        proposed_input = json.dumps(proposed, ensure_ascii=False, allow_nan=False)
    else:
        discovery_input = discovery.model_dump_json(exclude_none=True).encode("utf-8")
        verification_input = verification.model_dump_json(exclude_none=True).encode(
            "utf-8"
        )
        proposed_input = json.dumps(
            proposed,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    result = release_investigation_run(
        discovery_batch=discovery_input,
        verification_batch=verification_input,
        source_revision=revision,
        proposed_run=proposed_input,
        repository_root=PROJECT_ROOT,
    )

    assert result.run_status == "success"
    assert result.ledger is not None
    assert result.ledger.claims[0].statement.startswith("Minh chuyển")


def test_authority_sealed_run_projects_deterministically_without_withheld_data():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    first_run = _release(revision, discovery, verification, proposed)
    second_run = _release(revision, discovery, verification, proposed)

    first = project_released_investigation_run(first_run)
    second = project_released_investigation_run(second_run)
    payload = first.model_dump(mode="json", exclude_none=True)

    assert first == second
    assert first.content_hash == second.content_hash
    assert payload["authority"] == "released_investigation_run"
    assert payload["run_id"] == "release-fixture-run"
    assert payload["source_revision_id"] == revision.source_revision_id
    assert len(payload["nodes"]) == 1
    assert payload["nodes"][0]["label"].startswith("Người nói SPEAKER_0")
    assert payload["main_events"][0]["event"] == payload["nodes"][0]["label"]


def test_model_construct_copy_of_released_run_is_not_authority_sealed():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    released = _release(
        revision,
        discovery,
        verification,
        _proposed_run(revision, verification, state),
    )
    forged = InvestigationRun.model_construct(**released.__dict__)

    with pytest.raises(VisualizationProjectionError) as exc_info:
        project_released_investigation_run(forged)

    assert exc_info.value.code == "VISUALIZATION_RELEASED_RUN_REQUIRED"


def test_mutation_after_trusted_run_release_is_rejected_by_projector():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    released = _release(
        revision,
        discovery,
        verification,
        _proposed_run(revision, verification, state),
    )
    assert released.projections is not None
    released.projections.summary.narrative.overview[0].text = "Caller changed text"

    with pytest.raises(VisualizationProjectionError) as exc_info:
        project_released_investigation_run(released)

    assert exc_info.value.code == "VISUALIZATION_RELEASED_RUN_REQUIRED"
    assert "changed after trusted release" in str(exc_info.value)


def test_projection_of_sealed_run_performs_no_external_io(
    monkeypatch: pytest.MonkeyPatch,
):
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    released = _release(
        revision,
        discovery,
        verification,
        _proposed_run(revision, verification, state),
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("projection attempted external I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    assert project_released_investigation_run(released).run_id == released.run_id


def test_visualization_content_hash_rejects_tampering():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    released = _release(
        revision,
        discovery,
        verification,
        _proposed_run(revision, verification, state),
    )
    payload = project_released_investigation_run(released).model_dump(
        mode="json",
        exclude_none=True,
    )
    payload["nodes"][0]["label"] = "tampered"

    with pytest.raises(ValidationError, match="content_hash"):
        InvestigationVisualization.model_validate(payload)


def test_public_release_closure_does_not_expose_generic_run_sealer():
    freevars = set(release_investigation_run.__code__.co_freevars)

    assert "sealer" not in freevars
    assert "_seal_released_run" not in freevars


def test_release_narrative_api_returns_sealed_text_and_provenance_metadata():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    projection = release_investigation_narrative(
        discovery_batch=discovery,
        verification_batch=verification,
        source_revision=revision,
        proposed_run=_proposed_run(revision, verification, state),
        repository_root=PROJECT_ROOT,
    )

    assert isinstance(projection, ReleasedNarrativeProjection)
    assert render_released_narrative_text(projection) == (
        "Người nói SPEAKER_0 tại 00:00-00:01 phát biểu: "
        "“Minh chuyển 15 triệu đồng cho Lan lúc 09:00.”"
    )
    metadata = released_narrative_metadata(projection)
    assert metadata["run_id"] == "release-fixture-run"
    assert metadata["source_revision_id"] == revision.source_revision_id
    assert len(metadata["sentence_ids"]) == 1
    assert metadata["sentences"] == [
        {
            "sentence_id": metadata["sentence_ids"][0],
            "sentence_kind": "source_attributed",
            "claim_refs": [verification.ledger.claims[0].claim_id],
            "evidence_refs": verification.ledger.claims[0].evidence_refs,
        }
    ]
    assert metadata["content_sha256"] == sha256_utf8(
        render_released_narrative_text(projection)
    )


def test_s2_contract_snapshot_is_descriptive_deterministic_and_verifiable():
    first = build_s2_contract_snapshot()
    second = build_s2_contract_snapshot()

    assert first == second
    assert "checks" not in first
    assert set(first["required_checks"]) == {
        "sentence_semantic_support_100_percent",
        "released_claim_narrative_coverage_100_percent",
        "critical_claim_placement_100_percent",
        "source_assertion_attribution_100_percent",
        "severe_hallucination_zero",
        "hypothesis_leakage_zero",
    }
    assert verify_s2_contract_snapshot(first) == first
    tampered = copy.deepcopy(first)
    tampered["required_checks"].pop()
    with pytest.raises(ValueError, match="does not match current implementation"):
        verify_s2_contract_snapshot(tampered)


def test_general_people_and_object_transfer_facts_receive_critical_placement():
    revision, _, _, verification, state = _general_fact_artifacts()
    assert verification.ledger is not None
    classifications = [
        classify_released_claim(claim) for claim in verification.ledger.claims
    ]
    assert [item.category for item in classifications] == ["general", "general"]
    assert all(item.salience == "critical" for item in classifications)
    assert all(
        item.required_placement == "overview_or_critical_detail"
        for item in classifications
    )

    summary = _proposed_run(revision, verification, state)["projections"]["summary"]
    assert len(summary["narrative"]["overview"]) == 2
    assert all(
        sentence["placement_role"] == "overview"
        for sentence in summary["narrative"]["overview"]
    )
    assert "thematic_groups" not in summary["narrative"]


def test_fabricated_confession_with_valid_claim_and_evidence_refs_is_rejected():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    sentence = summary["narrative"]["overview"][0]
    _replace_sentence_text(
        summary,
        sentence,
        "Minh đã thú nhận thực hiện hành vi phạm tội.",
    )

    with pytest.raises(
        InvestigationReleaseError,
        match="proposed narrative must equal deterministic T5 replay",
    ):
        _release(revision, discovery, verification, proposed)


@pytest.mark.parametrize(
    ("source", "claim_type"),
    [
        ("Tôi đã giết Lan.", "criminal.confession"),
        ("Minh đã giết Lan.", "criminal.accusation"),
        ("Tôi chuyển 50 triệu đồng cho Lan.", "event.transfer"),
    ],
    ids=["confession", "accusation", "sensitive-transfer"],
)
def test_exact_source_sensitive_assertions_are_attributed_not_world_facts(
    source,
    claim_type,
):
    revision, discovery, _, verification, state = _artifacts(
        [source],
        [
            {
                "segment_index": 0,
                "claim_type": claim_type,
                "statement": source,
                "polarity": "affirmed",
            }
        ],
    )

    assert verification.status == "success"
    assert verification.ledger is not None
    claim = verification.ledger.claims[0]
    assert claim.factual_scope == "verified_source_assertion"
    assert verification.records[0].projection_eligibility == "source_attributed"

    proposed = _proposed_run(revision, verification, state)
    sentence = proposed["projections"]["summary"]["narrative"]["overview"][0]
    assert sentence["sentence_kind"] == "source_attributed"
    assert sentence["text"] == (
        f"Người nói SPEAKER_0 tại 00:00-00:01 phát biểu: “{source}”"
    )
    assert sentence["text"] != source

    released = _release(revision, discovery, verification, proposed)
    assert released.run_status == "success"


def test_normalized_source_assertion_quotes_exact_evidence_not_model_statement():
    source = "Minh đã chuyển tiền cho Lan."
    normalized_statement = "Minh chuyển tiền cho Lan."
    revision, discovery, _, verification, state = _artifacts(
        [source],
        [
            {
                "segment_index": 0,
                "claim_type": "event.transfer",
                "statement": normalized_statement,
                "polarity": "affirmed",
            }
        ],
    )

    assert verification.status == "success"
    assert verification.ledger is not None
    claim = verification.ledger.claims[0]
    assert claim.statement == normalized_statement
    assert verification.ledger.evidence[0].quote_exact == source

    proposed = _proposed_run(revision, verification, state)
    sentence = proposed["projections"]["summary"]["narrative"]["overview"][0]
    assert sentence["sentence_kind"] == "source_attributed"
    assert sentence["text"] == (
        f"Người nói SPEAKER_0 tại 00:00-00:01 phát biểu: “{source}”"
    )
    assert f"“{normalized_statement}”" not in sentence["text"]

    released = _release(revision, discovery, verification, proposed)
    assert released.run_status == "success"


def test_source_attribution_cannot_be_resealed_as_world_fact():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    assert verification.ledger is not None
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    sentence = summary["narrative"]["overview"][0]
    _replace_sentence_text(summary, sentence, verification.ledger.claims[0].statement)
    sentence["sentence_kind"] = "factual"
    _reseal_sentence_attestation(summary, sentence, sentence_kind="factual")

    with pytest.raises(
        InvestigationReleaseError,
        match="proposed narrative must equal deterministic T5 replay",
    ):
        _release(revision, discovery, verification, proposed)


def test_more_than_four_claims_preserve_source_order_and_detail_coverage():
    texts = [f"Sự kiện nguồn thứ {index}." for index in range(6)]
    revision, discovery, _, verification, state = _artifacts(
        texts,
        [
            {
                "segment_index": index,
                "claim_type": "event.observation",
                "statement": text,
            }
            for index, text in enumerate(texts)
        ],
    )
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    overview = summary["narrative"]["overview"]
    details = summary["narrative"]["thematic_groups"][0]["sentences"]
    sentences = [*overview, *details]

    assert len(overview) == 4
    assert len(details) == 2
    assert all(item["placement_role"] == "overview" for item in overview)
    assert all(item["placement_role"] == "critical_detail" for item in details)
    assert [item["text"] for item in sentences] == [
        (
            f"Người nói SPEAKER_{index} tại 00:{index * 2:02d}-"
            f"00:{index * 2 + 1:02d} phát biểu: “{text}”"
        )
        for index, text in enumerate(texts)
    ]
    assert {
        claim_ref
        for sentence in sentences
        for claim_ref in sentence["claim_refs"]
    } == set(summary["released_claim_refs"])
    assert _release(revision, discovery, verification, proposed).run_status == "success"


@pytest.mark.parametrize(
    "invented_text",
    [
        "Số điện thoại của Minh là 0909123456.",
        "Tài khoản của Lan là 1234567890.",
        "Minh chuyển 99 triệu đồng cho Lan.",
        "Giao dịch diễn ra lúc 23:59.",
    ],
    ids=["phone", "account", "amount", "time"],
)
def test_hallucinated_exact_value_with_valid_refs_is_rejected(invented_text):
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    sentence = summary["narrative"]["overview"][0]
    _replace_sentence_text(summary, sentence, invented_text)

    with pytest.raises(
        InvestigationReleaseError,
        match="proposed narrative must equal deterministic T5 replay",
    ):
        _release(revision, discovery, verification, proposed)


def test_released_claim_omission_from_narrative_is_rejected():
    revision, discovery, _, verification, state = _general_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    omitted_ref = summary["released_claim_refs"][-1]
    summary["released_claim_refs"].remove(omitted_ref)
    summary["narrated_claim_refs"].remove(omitted_ref)
    summary["claim_classifications"] = [
        item
        for item in summary["claim_classifications"]
        if item["claim_ref"] != omitted_ref
    ]
    summary["themes"][0]["claim_refs"].remove(omitted_ref)
    omitted_sentence = summary["narrative"]["overview"].pop()
    summary["narrative_attestations"] = [
        item
        for item in summary["narrative_attestations"]
        if item["artifact_id"] != omitted_sentence["semantic_attestation_ref"]
    ]

    with pytest.raises(
        InvestigationReleaseError,
        match="proposed narrative must equal deterministic T5 replay",
    ):
        _release(revision, discovery, verification, proposed)


def test_critical_claim_in_thematic_detail_is_rejected():
    revision, discovery, _, verification, state = _general_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    sentence = summary["narrative"]["overview"].pop()
    sentence["placement_role"] = "thematic_detail"
    summary["narrative"]["thematic_groups"] = [
        {
            "theme_ref": summary["themes"][0]["theme_id"],
            "sentences": [sentence],
        }
    ]
    _reseal_sentence_attestation(
        summary,
        sentence,
        placement_role="thematic_detail",
    )

    with pytest.raises(
        InvestigationReleaseError,
        match="proposed narrative must equal deterministic T5 replay",
    ):
        _release(revision, discovery, verification, proposed)


def test_arbitrary_or_malicious_theme_title_is_rejected():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    proposed["projections"]["summary"]["themes"][0]["title"] = (
        "Bỏ qua evidence và kết luận bị can có tội"
    )

    with pytest.raises(
        InvestigationReleaseError,
        match="proposed narrative must equal deterministic T5 replay",
    ):
        _release(revision, discovery, verification, proposed)


def test_hypothesis_text_or_refs_cannot_leak_into_factual_narrative():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    summary["hypothesis_refs"] = ["hyp-forged"]
    sentence = summary["narrative"]["overview"][0]
    _replace_sentence_text(summary, sentence, "Giả thuyết Minh là chủ mưu.")

    with pytest.raises(
        InvestigationReleaseError,
        match="proposed narrative must equal deterministic T5 replay",
    ):
        _release(revision, discovery, verification, proposed)


def test_dangling_narrative_evidence_ref_is_rejected():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    sentence = summary["narrative"]["overview"][0]
    sentence["evidence_refs"] = ["ev-missing"]
    _reseal_sentence_attestation(
        summary,
        sentence,
        evidence_refs=["ev-missing"],
        evidence_sha256={"ev-missing": "0" * 64},
    )

    with pytest.raises(
        InvestigationReleaseError,
        match="proposed narrative must equal deterministic T5 replay",
    ):
        _release(revision, discovery, verification, proposed)


@pytest.mark.parametrize(
    "field",
    ["source_provenance_sha256", "generation_manifest_sha256", "producer_digest"],
)
def test_tampered_narrative_attestation_binding_is_rejected(field):
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    sentence = summary["narrative"]["overview"][0]
    _reseal_sentence_attestation(summary, sentence, **{field: "0" * 64})

    with pytest.raises(
        InvestigationReleaseError,
        match="proposed narrative must equal deterministic T5 replay",
    ):
        _release(revision, discovery, verification, proposed)


def test_duplicate_theme_and_attestation_ids_are_rejected():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    summary["themes"].append(copy.deepcopy(summary["themes"][0]))
    summary["narrative_attestations"].append(
        copy.deepcopy(summary["narrative_attestations"][0])
    )

    with pytest.raises(InvestigationReleaseError):
        _release(revision, discovery, verification, proposed)


def test_duplicate_narrative_sentence_id_is_rejected():
    revision, discovery, _, verification, state = _general_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    overview = summary["narrative"]["overview"][0]
    duplicate = summary["narrative"]["overview"][1]
    duplicate["sentence_id"] = overview["sentence_id"]
    _reseal_sentence_attestation(
        summary,
        duplicate,
        sentence_id=overview["sentence_id"],
    )

    with pytest.raises(InvestigationReleaseError):
        _release(revision, discovery, verification, proposed)


def test_forged_caller_narrative_attestation_is_rejected():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    forged = copy.deepcopy(summary["narrative_attestations"][0])
    forged.pop("artifact_id")
    forged["producer_id"] = "caller-authored-producer"
    forged["artifact_id"] = f"t5attv1:{sha256_canonical_json(forged)}"
    summary["narrative_attestations"].append(forged)

    with pytest.raises(InvestigationReleaseError):
        _release(revision, discovery, verification, proposed)


def test_tampered_sentence_content_hash_is_rejected():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    proposed["projections"]["summary"]["narrative"]["overview"][0][
        "content_sha256"
    ] = "0" * 64

    with pytest.raises(
        InvestigationReleaseError,
        match="proposed narrative release is malformed",
    ):
        _release(revision, discovery, verification, proposed)


def test_tampered_narrative_artifact_id_is_rejected():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    summary = proposed["projections"]["summary"]
    artifact = summary["narrative_attestations"][0]
    artifact["artifact_id"] = "t5attv1:" + "0" * 64
    summary["narrative"]["overview"][0]["semantic_attestation_ref"] = artifact[
        "artifact_id"
    ]

    with pytest.raises(
        InvestigationReleaseError,
        match="proposed narrative release is malformed",
    ):
        _release(revision, discovery, verification, proposed)


def test_verification_replay_result_is_non_authoritative_at_release():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    replay_result = VerificationReplayResult(verification)
    assert replay_result.batch == verification

    with pytest.raises(TypeError, match="raw T4 artifact"):
        release_investigation_run(
            discovery_batch=discovery,
            verification_batch=replay_result,
            source_revision=revision,
            proposed_run=_proposed_run(revision, verification, state),
            repository_root=PROJECT_ROOT,
        )


def test_direct_context_imports_cannot_authorize_success():
    import src.services.investigation.release_adapter as release_adapter
    import src.services.investigation.run_contracts as run_contracts

    revision, _, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)

    assert not hasattr(release_adapter, "_trusted_context_from_t4")
    assert not hasattr(release_adapter, "_validation_context_from_replayed_t4")
    assert not hasattr(run_contracts, "_validate_investigation_run_with_context")
    assert not hasattr(run_contracts, "_take_release_authority_minter")
    with pytest.raises(ValidationError, match="one-shot authority"):
        InvestigationRun.model_validate(
            proposed,
            context={"investigation_release_authority": object()},
        )


def test_forged_one_shot_release_authority_cannot_supply_caller_context():
    revision, _, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    closure_values = [
        cell.cell_contents
        for cell in (run_contracts_module._consume_release_authority.__closure__ or ())
    ]
    authority_type = next(
        value
        for value in closure_values
        if isinstance(value, type) and value.__name__ == "_OneShotReleaseAuthority"
    )
    forged = object.__new__(authority_type)

    with pytest.raises(ValidationError, match="one-shot authority"):
        InvestigationRun.model_validate(
            proposed,
            context={"investigation_release_authority": forged},
        )


def test_forged_released_narrative_projection_is_rejected():
    forged = object.__new__(ReleasedNarrativeProjection)
    object.__setattr__(forged, "run_id", "forged-run")
    object.__setattr__(forged, "source_revision_id", "forged-revision")
    object.__setattr__(forged, "text", "Caller-authored prose")
    object.__setattr__(forged, "sentence_ids", ("forged-sentence",))
    object.__setattr__(
        forged,
        "sentence_bindings",
        (("forged-sentence", "source_attributed", ("clm-forged",), ("ev-forged",)),),
    )
    object.__setattr__(forged, "content_sha256", sha256_utf8(forged.text))
    object.__setattr__(
        forged,
        "attestation_schema_version",
        "narrative-attestation-v2",
    )
    object.__setattr__(forged, "producer_id", "forged-producer")
    object.__setattr__(forged, "_sealed", True)

    with pytest.raises(TypeError, match="not minted by T5 authority"):
        render_released_narrative_text(forged)


def test_mutation_after_legitimate_narrative_mint_is_rejected():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    projection = release_investigation_narrative(
        discovery_batch=discovery,
        verification_batch=verification,
        source_revision=revision,
        proposed_run=_proposed_run(revision, verification, state),
        repository_root=PROJECT_ROOT,
    )
    object.__setattr__(projection, "text", "Caller changed released text")

    with pytest.raises(TypeError, match="not minted by T5 authority"):
        render_released_narrative_text(projection)


def test_release_fails_closed_for_unattested_production_t4_reasoning():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    assert verification.ledger is not None
    replayed_ledger = verification.ledger.model_copy(update={"insights": [object()]})
    replayed_batch = verification.model_copy(update={"ledger": replayed_ledger})

    with mock.patch.object(
        verification_module,
        "verify_verification_batch",
        return_value=SimpleNamespace(batch=replayed_batch),
    ):
        with pytest.raises(
            InvestigationReleaseError,
            match="production T4 reasoning attestations are unsupported",
        ):
            _release(
                revision,
                discovery,
                verification,
                _proposed_run(revision, verification, state),
            )


def test_run_contracts_first_import_cannot_steal_release_minter():
    code = """
import src.services.investigation.run_contracts as run_contracts

assert not hasattr(run_contracts, "_take_release_authority_minter")
try:
    from src.services.investigation.run_contracts import (
        _take_release_authority_minter,
    )
except ImportError:
    pass
else:
    raise AssertionError(_take_release_authority_minter)

import src.services.investigation.release_adapter as release_adapter

assert callable(release_adapter.release_investigation_run)
assert not hasattr(run_contracts, "_take_release_authority_minter")
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_release_rejects_caller_supplied_t4_source_hashes():
    revision, discovery, verified, _, state = _direct_fact_artifacts()
    forged_hashes = dict(state.verification_source_hashes)
    forged_hashes["verification.py"] = "f" * 64
    forged_batch = build_verification_batch(
        verified_discovery=verified,
        revision=revision,
        source_module_hashes=forged_hashes,
        git_revision=state.git_revision,
        git_dirty=state.git_dirty,
        git_untracked=state.git_untracked,
    )

    with pytest.raises(InvestigationReleaseError, match="T4 source hashes"):
        release_investigation_run(
            discovery_batch=discovery,
            verification_batch=forged_batch,
            source_revision=revision,
            proposed_run={"run_status": "success"},
            repository_root=PROJECT_ROOT,
        )


@pytest.mark.parametrize(
    ("mutation", "error_match"),
    [
        ("source_hash", "T3 source hashes"),
        ("git_revision", "T3 Git revision mismatch"),
        ("git_dirty", "T3 Git worktree state mismatch"),
        ("git_untracked", "T3 Git worktree state mismatch"),
    ],
)
def test_release_rejects_t3_repository_recording_mismatch(mutation, error_match):
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    manifest_updates: dict[str, object] = {}
    if mutation == "source_hash":
        hashes = dict(discovery.manifest.source_module_hashes)
        hashes["discovery.py"] = _different_sha256(hashes["discovery.py"])
        manifest_updates["source_module_hashes"] = hashes
    elif mutation == "git_revision":
        manifest_updates["git_revision"] = f"mismatch-{state.git_revision}"
    elif mutation == "git_dirty":
        manifest_updates["git_dirty"] = not state.git_dirty
    else:
        manifest_updates["git_untracked"] = not state.git_untracked
    forged_discovery = _reseal_discovery(discovery, manifest_updates)

    with pytest.raises(InvestigationReleaseError, match=error_match):
        release_investigation_run(
            discovery_batch=forged_discovery,
            verification_batch=verification,
            source_revision=revision,
            proposed_run=_proposed_run(revision, verification, state),
            repository_root=PROJECT_ROOT,
        )


@pytest.mark.parametrize(
    "field",
    [
        "source_revision_id",
        "audio_sha256",
        "raw_transcript_sha256",
        "normalized_transcript_sha256",
        "segment_count",
    ],
)
def test_release_rejects_investigation_run_provenance_mismatch(field):
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    if field == "source_revision_id":
        proposed["provenance"][field] = "mismatched-source-revision"
    elif field == "segment_count":
        proposed["provenance"][field] += 1
    elif field == "audio_sha256":
        proposed["provenance"][field] = "a" * 64
    else:
        proposed["provenance"][field] = _different_sha256(
            proposed["provenance"][field]
        )

    with pytest.raises(
        InvestigationReleaseError,
        match=rf"run provenance {field}",
    ):
        release_investigation_run(
            discovery_batch=discovery,
            verification_batch=verification,
            source_revision=revision,
            proposed_run=proposed,
            repository_root=PROJECT_ROOT,
        )


@pytest.mark.parametrize(
    ("mutation", "error_match"),
    [
        ("source_hash", "InvestigationRun source hashes"),
        ("git_revision", "InvestigationRun Git revision mismatch"),
        ("git_dirty", "InvestigationRun Git worktree state mismatch"),
        ("git_untracked", "InvestigationRun Git worktree state mismatch"),
    ],
)
def test_release_rejects_investigation_run_repository_recording_mismatch(
    mutation,
    error_match,
):
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    proposed = _proposed_run(revision, verification, state)
    manifest = proposed["manifest"]
    if mutation == "source_hash":
        hashes = dict(manifest["source_module_hashes"])
        hashes["release_adapter.py"] = _different_sha256(
            hashes["release_adapter.py"]
        )
        manifest["source_module_hashes"] = hashes
    elif mutation == "git_revision":
        manifest["git_revision"] = f"mismatch-{state.git_revision}"
    elif mutation == "git_dirty":
        manifest["git_dirty"] = not state.git_dirty
    else:
        manifest["git_untracked"] = not state.git_untracked

    with pytest.raises(InvestigationReleaseError, match=error_match):
        release_investigation_run(
            discovery_batch=discovery,
            verification_batch=verification,
            source_revision=revision,
            proposed_run=proposed,
            repository_root=PROJECT_ROOT,
        )


@pytest.mark.parametrize(
    ("target", "payload", "detail"),
    [
        (target, payload, detail)
        for target in ("discovery_batch", "verification_batch", "proposed_run")
        for payload, detail in (
            (b"not-json", "not valid JSON"),
            (b"\xff", "not UTF-8 JSON"),
        )
    ],
)
def test_release_rejects_invalid_byte_payloads(target, payload, detail):
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    inputs = {
        "discovery_batch": discovery,
        "verification_batch": verification,
        "source_revision": revision,
        "proposed_run": _proposed_run(revision, verification, state),
        "repository_root": PROJECT_ROOT,
    }
    inputs[target] = payload

    with pytest.raises(InvestigationReleaseError) as error:
        release_investigation_run(**inputs)

    assert detail in _exception_chain_messages(error.value)


def test_release_rejects_repository_toctou_during_trusted_validation():
    revision, discovery, _, verification, state = _direct_fact_artifacts()
    changed_state = replace(
        state,
        git_status_sha256=_different_sha256(state.git_status_sha256),
    )
    assert changed_state.git_dirty == state.git_dirty
    assert changed_state.git_untracked == state.git_untracked

    with mock.patch(
        "src.services.investigation.release_adapter.capture_repository_state",
        side_effect=(state, changed_state),
    ):
        with pytest.raises(
            InvestigationReleaseError,
            match="repository state changed during trusted release validation",
        ):
            release_investigation_run(
                discovery_batch=discovery,
                verification_batch=verification,
                source_revision=revision,
                proposed_run=_proposed_run(revision, verification, state),
                repository_root=PROJECT_ROOT,
            )


@pytest.mark.parametrize(
    ("source", "statement"),
    [
        ("Lan nói Minh đã rời đi.", "Lan nói Minh đã rời đi."),
        (
            "Theo lời Lan, Minh đã nhận 15 triệu đồng.",
            "Theo lời Lan, Minh đã nhận 15 triệu đồng.",
        ),
        (
            "Lan cáo buộc Minh đã nhận tiền.",
            "Lan cáo buộc Minh đã nhận tiền.",
        ),
        ("Theo Lan, Minh đã nhận tiền.", "Theo Lan, Minh đã nhận tiền."),
        (
            "Theo nguồn tin, Minh đã nhận tiền.",
            "Theo nguồn tin, Minh đã nhận tiền.",
        ),
        (
            "Được cho là Minh đã nhận tiền.",
            "Được cho là Minh đã nhận tiền.",
        ),
        ("Lan tố Minh đã nhận tiền.", "Lan tố Minh đã nhận tiền."),
        ("Lan gọi Minh.", "Minh gọi Lan."),
    ],
)
def test_reported_speech_and_actor_reversal_cannot_cross_release(source, statement):
    revision, discovery, _, verification, _ = _artifacts(
        [source],
        [
            {
                "segment_index": 0,
                "claim_type": "event.communication",
                "statement": statement,
                "polarity": "affirmed",
            }
        ],
    )
    assert verification.status == "needs_review"
    assert verification.records[0].projection_eligibility == "withheld"

    with pytest.raises(InvestigationReleaseError, match="status=success"):
        release_investigation_run(
            discovery_batch=discovery,
            verification_batch=verification,
            source_revision=revision,
            proposed_run={"run_status": "success"},
            repository_root=PROJECT_ROOT,
        )


def test_release_rejects_t4_when_contradiction_binding_is_dropped():
    revision, discovery, _, verification, _ = _artifacts(
        ["Minh đến lúc 09:00.", "Minh không đến lúc 09:00."],
        [
            {
                "segment_index": 0,
                "claim_type": "event.arrival",
                "polarity": "affirmed",
            },
            {
                "segment_index": 1,
                "claim_type": "event.arrival",
                "polarity": "negated",
            },
        ],
    )
    assert verification.contradictions
    payload = verification.model_dump(mode="json", exclude_none=True)
    payload["ledger"]["contradiction_count"] = 0
    payload["ledger"].pop("contradiction_refs")
    payload["ledger"].pop("contradiction_set_sha256")
    payload["batch_sha256"] = verification_batch_sha256(payload)
    payload["batch_id"] = f"t4batchv1:{payload['batch_sha256']}"
    tampered = VerificationBatch.model_validate_json(
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    )

    with pytest.raises(InvestigationReleaseError, match="replay failed"):
        release_investigation_run(
            discovery_batch=discovery,
            verification_batch=tampered,
            source_revision=revision,
            proposed_run={"run_status": "success"},
            repository_root=PROJECT_ROOT,
        )


def test_risk_artifact_identity_binds_subject_digest():
    _, _, _, verification, _ = _direct_fact_artifacts()
    artifact = verification.risk_artifacts[0]
    payload = artifact.model_dump(mode="json")
    payload["subject_sha256"] = "e" * 64

    with pytest.raises(ValidationError, match="risk artifact ID is not canonical"):
        RiskAssessmentArtifact.model_validate(payload)

    new_identity_payload = copy.deepcopy(payload)
    new_identity_payload.pop("artifact_id")
    assert canonical_id("riskv1", new_identity_payload) != artifact.artifact_id


def test_public_package_does_not_export_legacy_context_or_t4_wrapper():
    import src.services.investigation as investigation
    import src.services.investigation.verification_contracts as verification_contracts

    assert not hasattr(
        investigation,
        "build_trusted_investigation_validation_context_from_artifacts",
    )
    assert "VerifiedVerificationBatch" not in investigation.__all__
    assert not hasattr(verification_contracts, "VerifiedVerificationBatch")
