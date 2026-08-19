from __future__ import annotations

import asyncio
import copy
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.services.investigation.contracts import (
    ConceptMention,
    EvidenceSpan,
    GroundedClaim,
    GroundedRelationship,
    NarrativeAttestationArtifact,
    NarrativeSentence,
    NarrativeSynthesis,
    SafetyEnvelope,
    SourceProvenance,
    sha256_canonical_json,
)
from src.services.investigation.run_contracts import (
    AnalysisProjection,
    CanonicalClaimLedger,
    DiscoveryCandidate,
    InvestigationProjections,
    InvestigationRun,
    InvestigationRunManifest,
    SummaryProjection,
    VerificationDecision,
)
from src.services.summarization.projections import project_visualization
from src.services.task_service import (
    _deep_merge,
    extract_active_visualization_payload,
    extract_visualization_payload,
)
from src.services.visualization import (
    InvestigationVisualization,
    VisualizationEvidence,
    VisualizationProjectionError,
    VisualizationTimelineItem,
    project_released_investigation_run,
)
from src.services.visualization_service import generate_visualization


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _released_shaped_run(*, reverse: bool = False) -> InvestigationRun:
    quote_a = "Nguoi noi xac nhan cuoc hen luc 20 gio."
    quote_b = "Dia diem duoc nhac den la Ben xe B."
    evidence = [
        EvidenceSpan(
            evidence_id="ev-a",
            segment_id="seg-a",
            quote_exact=quote_a,
            raw_char_start=0,
            raw_char_end=len(quote_a),
            start_seconds=10.0,
            end_seconds=12.5,
            speaker_id="speaker-1",
            quote_sha256=_hash(quote_a),
            source_sha256=_hash(quote_a),
        ),
        EvidenceSpan(
            evidence_id="ev-b",
            segment_id="seg-b",
            quote_exact=quote_b,
            raw_char_start=40,
            raw_char_end=40 + len(quote_b),
            start_seconds=20.0,
            end_seconds=22.0,
            speaker_id="speaker-2",
            quote_sha256=_hash(quote_b),
            source_sha256=_hash(quote_b),
        ),
    ]
    claim = GroundedClaim(
        claim_id="claim-released",
        claim_type="event.meeting",
        statement="Nguoi noi xac nhan cuoc hen tai Ben xe B luc 20 gio.",
        polarity="affirmed",
        disposition="supported",
        factual_scope="verified_source_assertion",
        risk_tier="ordinary",
        risk_screening_artifact_ref="risk-claim-released",
        evidence_refs=["ev-b", "ev-a"] if reverse else ["ev-a", "ev-b"],
        concept_refs=["concept-place", "concept-person"]
        if reverse
        else ["concept-person", "concept-place"],
        candidate_refs=["candidate-released"],
    )
    withheld = GroundedClaim(
        claim_id="claim-withheld",
        claim_type="accusation.unverified",
        statement="Noi dung nay phai bi giu lai.",
        polarity="reported",
        disposition="supported",
        factual_scope="verified_source_assertion",
        risk_tier="ordinary",
        risk_screening_artifact_ref="risk-claim-withheld",
        evidence_refs=["ev-withheld"],
        candidate_refs=["candidate-withheld"],
    )
    withheld_quote = "Bang chung chua duoc xac minh."
    withheld_evidence = EvidenceSpan(
        evidence_id="ev-withheld",
        segment_id="seg-withheld",
        quote_exact=withheld_quote,
        quote_sha256=_hash(withheld_quote),
        source_sha256=_hash(withheld_quote),
    )
    concepts = [
        ConceptMention(
            concept_id="concept-person",
            concept_type="person",
            surface="Nguoi noi",
            role="nguoi xac nhan",
            evidence_refs=["ev-a"],
        ),
        ConceptMention(
            concept_id="concept-place",
            concept_type="location",
            surface="Ben xe B",
            evidence_refs=["ev-b"],
        ),
    ]
    relationship = GroundedRelationship(
        relationship_id="relationship-meeting",
        relationship_type="meeting_at",
        source_ref="concept-person",
        target_ref="concept-place",
        evidence_refs=["ev-b", "ev-a"] if reverse else ["ev-a", "ev-b"],
        epistemic_status="fact",
        disposition="supported",
        evidence_resolution="resolved",
        source_revision_id="source-revision-1",
        resolution_authority="t2-evidence-selector-v1",
        resolution_artifact_ref="selector-relationship-meeting",
        risk_tier="ordinary",
        risk_screening_artifact_ref="risk-relationship-meeting",
        projection_eligibility="source_attributed",
        eligibility_artifact_ref="eligibility-relationship-meeting",
        premise_claim_refs=["claim-released"],
    )
    candidate = DiscoveryCandidate(
        candidate_id="candidate-released",
        claim_type=claim.claim_type,
        statement=claim.statement,
        polarity=claim.polarity,
        evidence_refs=list(claim.evidence_refs),
        concept_refs=list(claim.concept_refs or []),
    )
    withheld_candidate = DiscoveryCandidate(
        candidate_id="candidate-withheld",
        claim_type=withheld.claim_type,
        statement=withheld.statement,
        polarity=withheld.polarity,
        evidence_refs=["ev-withheld"],
    )
    decision = VerificationDecision(
        verification_id="verification-released",
        candidate_ref="candidate-released",
        disposition="supported",
        evidence_resolution="resolved",
        source_revision_id="source-revision-1",
        resolution_authority="t2-evidence-selector-v1",
        resolution_artifact_ref="selector-verification-released",
        verified_evidence_refs=["ev-b", "ev-a"] if reverse else ["ev-a", "ev-b"],
        canonical_claim_ref="claim-released",
        projection_eligibility="source_attributed",
        eligibility_artifact_ref="eligibility-verification-released",
    )
    withheld_decision = VerificationDecision(
        verification_id="verification-withheld",
        candidate_ref="candidate-withheld",
        disposition="supported",
        evidence_resolution="unresolved",
        source_revision_id="source-revision-1",
        canonical_claim_ref="claim-withheld",
        projection_eligibility="withheld",
        failure_codes=["insufficient_evidence"],
    )
    ledger = CanonicalClaimLedger.model_construct(
        candidates=[withheld_candidate, candidate]
        if reverse
        else [candidate, withheld_candidate],
        verification_decisions=[withheld_decision, decision]
        if reverse
        else [decision, withheld_decision],
        claims=[withheld, claim] if reverse else [claim, withheld],
        evidence=[withheld_evidence, *reversed(evidence)]
        if reverse
        else [*evidence, withheld_evidence],
        concepts=list(reversed(concepts)) if reverse else concepts,
        relationships=[relationship],
        insights=None,
        hypotheses=None,
        verification_actions=None,
        attributed_assertion_candidate_refs=None,
        contradiction_refs=None,
        contradiction_set_sha256=None,
        contradiction_count=0,
    )
    display_text = "Nguoi noi speaker-1 tai 00:10-00:12 phat bieu: " f'"{quote_a}"'
    attestation_id = f"t5attv1:{'c' * 64}"
    sentence = NarrativeSentence(
        sentence_id="sentence-released",
        text=display_text,
        sentence_kind="source_attributed",
        placement_role="overview",
        claim_refs=["claim-released"],
        evidence_refs=["ev-a", "ev-b"],
        content_sha256=_hash(display_text),
        semantic_attestation_ref=attestation_id,
    )
    attestation = NarrativeAttestationArtifact.model_construct(
        artifact_id=attestation_id,
        sentence_id=sentence.sentence_id,
        source_revision_id="source-revision-1",
        content_sha256=sentence.content_sha256,
        claim_refs=list(sentence.claim_refs),
        evidence_refs=list(sentence.evidence_refs),
        decision="supported",
        replay_verified=True,
    )
    summary = SummaryProjection.model_construct(
        released_claim_refs=["claim-released"],
        narrated_claim_refs=["claim-released"],
        claim_classifications=[],
        insight_refs=None,
        hypothesis_refs=None,
        verification_action_refs=None,
        themes=[],
        narrative=NarrativeSynthesis(overview=[sentence]),
        narrative_attestations=[attestation],
    )
    analysis = AnalysisProjection(
        released_claim_refs=["claim-released"],
        source_attributed_claim_refs=["claim-released"],
        relationship_refs=["relationship-meeting"],
    )
    return InvestigationRun.model_construct(
        run_id="run-released-1",
        run_status="success",
        ledger=ledger,
        projections=InvestigationProjections(summary=summary, analysis=analysis),
        gate_failures=None,
        provenance=SourceProvenance(
            source_revision_id="source-revision-1",
            raw_transcript_sha256="a" * 64,
            normalized_transcript_sha256="b" * 64,
            segment_count=3,
        ),
        safety=SafetyEnvelope(
            transcript_is_untrusted_data=True,
            evidence_required_for_released_claims=True,
            high_risk_requires_human_verification=True,
            unsupported_high_risk_claims_released=False,
        ),
        manifest=InvestigationRunManifest.model_construct(),
    )


def _stored_release_identity(
    *,
    run_id: str = "run-released-1",
    source_revision_id: str = "source-revision-1",
) -> dict[str, object]:
    return {
        "schema_version": "investigation-run-v1.0",
        "run_id": run_id,
        "run_status": "success",
        "provenance": {"source_revision_id": source_revision_id},
    }


def _released_visualization_payload() -> dict[str, object]:
    released_run = _stored_release_identity()
    payload: dict[str, object] = {
        "schema_version": "investigation-visualization-v1",
        "authority": "released_investigation_run",
        "run_id": "run-released-1",
        "source_revision_id": "source-revision-1",
        "release_subject_sha256": sha256_canonical_json(released_run),
        "nodes": [],
        "edges": [],
        "timeline": [],
        "main_events": [],
        "extracted_entities": [],
    }
    return InvestigationVisualization.model_validate(
        {**payload, "content_hash": sha256_canonical_json(payload)}
    ).model_dump(mode="json", exclude_none=True)


def _semantic_stored_release_and_visualization() -> tuple[
    dict[str, object], dict[str, object]
]:
    released_run = _released_shaped_run().model_dump(mode="json", exclude_none=True)
    source_revision_id = "source-revision-1"
    evidence = []
    for item in released_run["ledger"]["evidence"]:
        if item["evidence_id"] not in {"ev-a", "ev-b"}:
            continue
        evidence.append(
            {
                key: item[key]
                for key in (
                    "evidence_id",
                    "segment_id",
                    "quote_exact",
                    "quote_sha256",
                    "source_sha256",
                    "start_seconds",
                    "end_seconds",
                    "speaker_id",
                )
                if key in item
            }
            | {"source_revision_id": source_revision_id}
        )
    display_text = released_run["projections"]["summary"]["narrative"]["overview"][
        0
    ]["text"]
    payload: dict[str, object] = {
        "schema_version": "investigation-visualization-v1",
        "authority": "released_investigation_run",
        "run_id": "run-released-1",
        "source_revision_id": source_revision_id,
        "release_subject_sha256": sha256_canonical_json(released_run),
        "nodes": [
            {
                "id": "claim-released",
                "kind": "claim",
                "label": display_text,
                "type": "event.meeting",
                "epistemic_type": "source_attributed",
                "source_revision_id": source_revision_id,
                "claim_refs": ["claim-released"],
                "evidence": evidence,
            }
        ],
        "edges": [],
        "timeline": [],
        "main_events": [],
        "extracted_entities": [],
    }
    artifact = InvestigationVisualization.model_validate(
        {**payload, "content_hash": sha256_canonical_json(payload)}
    ).model_dump(mode="json", exclude_none=True)
    return released_run, artifact


def test_model_construct_typed_run_cannot_forge_release_authority() -> None:
    forged = _released_shaped_run()

    for callable_ in (
        project_released_investigation_run,
        project_visualization,
        generate_visualization,
    ):
        with pytest.raises(VisualizationProjectionError) as exc_info:
            callable_(forged)
        assert exc_info.value.code == "VISUALIZATION_RELEASED_RUN_REQUIRED"


@pytest.mark.parametrize("status", ["needs_review", "failed", "no_extractable_claims"])
def test_non_released_run_states_fail_closed(status: str) -> None:
    run = _released_shaped_run().model_copy(update={"run_status": status})

    with pytest.raises(VisualizationProjectionError) as exc_info:
        project_released_investigation_run(run)

    assert exc_info.value.code == "VISUALIZATION_RELEASED_RUN_REQUIRED"


def test_raw_mapping_and_legacy_s1_projection_fail_closed() -> None:
    raw = {"run_status": "success", "investigation_knowledge": {"entities": []}}

    for callable_ in (
        project_released_investigation_run,
        project_visualization,
        generate_visualization,
    ):
        with pytest.raises(VisualizationProjectionError) as exc_info:
            callable_(raw)
        assert exc_info.value.code == "VISUALIZATION_RELEASED_RUN_REQUIRED"


def test_visualization_contract_rejects_content_tampering() -> None:
    payload = _released_visualization_payload()
    payload["nodes"] = [
        {
            "id": "claim-1",
            "kind": "claim",
            "label": "tampered",
            "type": "event",
            "epistemic_type": "fact",
            "source_revision_id": "source-revision-1",
            "claim_refs": ["claim-1"],
            "evidence": [
                {
                    "evidence_id": "ev-1",
                    "segment_id": "seg-1",
                    "quote_exact": "tampered",
                    "quote_sha256": _hash("tampered"),
                    "source_sha256": _hash("source"),
                    "source_revision_id": "source-revision-1",
                }
            ],
        }
    ]

    with pytest.raises(ValidationError, match="content_hash"):
        InvestigationVisualization.model_validate(payload)


def test_visualization_contract_rejects_reversed_time_bounds() -> None:
    evidence_payload = {
        "evidence_id": "ev-reversed",
        "segment_id": "seg-reversed",
        "quote_exact": "Noi dung nguon.",
        "quote_sha256": _hash("Noi dung nguon."),
        "source_sha256": _hash("source"),
        "source_revision_id": "source-revision-1",
        "start_seconds": 9.0,
        "end_seconds": 4.0,
    }
    with pytest.raises(ValidationError, match="cannot precede"):
        VisualizationEvidence.model_validate(evidence_payload)

    valid_evidence = {
        **evidence_payload,
        "start_seconds": 4.0,
        "end_seconds": 9.0,
    }
    with pytest.raises(ValidationError, match="cannot precede"):
        VisualizationTimelineItem.model_validate(
            {
                "id": "timeline-reversed",
                "time": "00:09-00:04",
                "event": "Noi dung nguon.",
                "claim_ref": "claim-1",
                "epistemic_type": "fact",
                "source_revision_id": "source-revision-1",
                "start_seconds": 9.0,
                "end_seconds": 4.0,
                "evidence": [valid_evidence],
            }
        )


def test_visualization_contract_rejects_nested_provenance_forgery() -> None:
    released_run, artifact = _semantic_stored_release_and_visualization()
    del released_run
    artifact["nodes"][0]["source_revision_id"] = "source-other"
    payload = copy.deepcopy(artifact)
    payload.pop("content_hash")
    artifact["content_hash"] = sha256_canonical_json(payload)

    with pytest.raises(ValidationError, match="top-level source revision"):
        InvestigationVisualization.model_validate(artifact)


def test_visualization_contract_rejects_quote_hash_and_graph_identity_errors() -> None:
    released_run, artifact = _semantic_stored_release_and_visualization()
    del released_run
    evidence = artifact["nodes"][0]["evidence"][0]
    evidence["quote_exact"] = "Noi dung bi thay doi."
    payload = copy.deepcopy(artifact)
    payload.pop("content_hash")
    artifact["content_hash"] = sha256_canonical_json(payload)
    with pytest.raises(ValidationError, match="quote_sha256"):
        InvestigationVisualization.model_validate(artifact)

    _, artifact = _semantic_stored_release_and_visualization()
    artifact["nodes"].append(copy.deepcopy(artifact["nodes"][0]))
    payload = copy.deepcopy(artifact)
    payload.pop("content_hash")
    artifact["content_hash"] = sha256_canonical_json(payload)
    with pytest.raises(ValidationError, match="node IDs must be unique"):
        InvestigationVisualization.model_validate(artifact)

    _, artifact = _semantic_stored_release_and_visualization()
    artifact["edges"] = [
        {
            "id": "edge-dangling",
            "source": "claim-released",
            "target": "node-missing",
            "label": "dangling",
            "type": "relation",
            "epistemic_type": "source_attributed",
            "source_revision_id": "source-revision-1",
            "claim_refs": ["claim-released"],
            "evidence": artifact["nodes"][0]["evidence"],
        }
    ]
    payload = copy.deepcopy(artifact)
    payload.pop("content_hash")
    artifact["content_hash"] = sha256_canonical_json(payload)
    with pytest.raises(ValidationError, match="edge endpoints"):
        InvestigationVisualization.model_validate(artifact)

    _, artifact = _semantic_stored_release_and_visualization()
    concept_node = {
        "id": "concept-z",
        "kind": "concept",
        "label": "Concept Z",
        "type": "person",
        "epistemic_type": "source_attributed",
        "source_revision_id": "source-revision-1",
        "claim_refs": ["claim-released"],
        "evidence": artifact["nodes"][0]["evidence"],
    }
    artifact["nodes"] = [concept_node, artifact["nodes"][0]]
    payload = copy.deepcopy(artifact)
    payload.pop("content_hash")
    artifact["content_hash"] = sha256_canonical_json(payload)
    with pytest.raises(ValidationError, match="canonical sorted order"):
        InvestigationVisualization.model_validate(artifact)


def test_visualization_extraction_requires_matching_active_run_identity() -> None:
    artifact = _released_visualization_payload()
    active_identity = _stored_release_identity()
    subject_sha256 = sha256_canonical_json(active_identity)

    assert extract_visualization_payload(artifact) is None
    assert (
        extract_visualization_payload(
            artifact,
            expected_run_id="run-released-1",
            expected_source_revision_id="source-revision-1",
            expected_release_subject_sha256=subject_sha256,
        )
        == artifact
    )
    assert (
        extract_visualization_payload(
            artifact,
            expected_run_id="run-stale",
            expected_source_revision_id="source-revision-1",
            expected_release_subject_sha256=subject_sha256,
        )
        is None
    )
    assert (
        extract_visualization_payload(
            artifact,
            expected_run_id="run-released-1",
            expected_source_revision_id="source-stale",
            expected_release_subject_sha256=subject_sha256,
        )
        is None
    )
    assert (
        extract_visualization_payload(
            artifact,
            expected_run_id="run-released-1",
            expected_source_revision_id="source-revision-1",
            expected_release_subject_sha256="0" * 64,
        )
        is None
    )


def test_active_visualization_hides_standalone_and_stale_artifacts() -> None:
    artifact = _released_visualization_payload()
    assert (
        extract_active_visualization_payload({"visualization_data": artifact})
        is None
    )

    matching = {
        "released_investigation_run": _stored_release_identity(),
        "visualization_data": artifact,
    }
    assert extract_active_visualization_payload(matching) is None

    released_run, semantic_artifact = _semantic_stored_release_and_visualization()
    assert (
        extract_active_visualization_payload(
            {
                "released_investigation_run": released_run,
                "visualization_data": semantic_artifact,
            }
        )
        == semantic_artifact
    )

    stale = copy.deepcopy(matching)
    stale["released_investigation_run"] = _stored_release_identity(
        run_id="run-new"
    )
    assert extract_active_visualization_payload(stale) is None


def test_rehashed_visualization_must_match_released_run_semantics() -> None:
    released_run, artifact = _semantic_stored_release_and_visualization()
    artifact["nodes"][0]["label"] = "Noi dung bi gia mao."
    payload = copy.deepcopy(artifact)
    payload.pop("content_hash")
    artifact["content_hash"] = sha256_canonical_json(payload)

    assert (
        extract_active_visualization_payload(
            {
                "released_investigation_run": released_run,
                "visualization_data": artifact,
            }
        )
        is None
    )

    released_run, artifact = _semantic_stored_release_and_visualization()
    artifact["nodes"][0]["id"] = "hypothesis-forged"
    artifact["nodes"][0]["claim_refs"] = ["hypothesis-forged"]
    payload = copy.deepcopy(artifact)
    payload.pop("content_hash")
    artifact["content_hash"] = sha256_canonical_json(payload)
    assert (
        extract_active_visualization_payload(
            {
                "released_investigation_run": released_run,
                "visualization_data": artifact,
            }
        )
        is None
    )


def test_changing_active_release_identity_clears_stale_visualization() -> None:
    artifact = _released_visualization_payload()
    base = {
        "released_investigation_run": _stored_release_identity(),
        "visualization_data": artifact,
        "has_visualization": True,
    }

    merged = _deep_merge(
        base,
        {
            "released_investigation_run": _stored_release_identity(
                run_id="run-released-2"
            )
        },
    )

    assert merged["visualization_data"] is None
    assert merged["has_visualization"] is False


class _FakeQuery:
    def __init__(self, *, all_rows: list[object] | None = None) -> None:
        self._all_rows = all_rows or []

    def options(self, *_args: object) -> "_FakeQuery":
        return self

    def filter(self, *_args: object) -> "_FakeQuery":
        return self

    def order_by(self, *_args: object) -> "_FakeQuery":
        return self

    def all(self) -> list[object]:
        return self._all_rows

    def first(self) -> None:
        return None


class _FakeDb:
    def __init__(self, *, all_rows: list[object] | None = None) -> None:
        self._all_rows = all_rows

    def query(self, *_args: object) -> _FakeQuery:
        return _FakeQuery(all_rows=self._all_rows)


def test_get_routes_hide_stale_or_standalone_visualization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.api.endpoints import audio as audio_v1
    from src.api.endpoints import audio_v2
    from src.services import task_service

    artifact = _released_visualization_payload()
    stale_result = {
        "transcription": "Noi dung nguon.",
        "summary": "Tom tat.",
        "released_investigation_run": _stored_release_identity(run_id="run-new"),
        "visualization_data": artifact,
        "has_visualization": True,
    }
    now = datetime.now(timezone.utc)
    audio_row = SimpleNamespace(
        id=1,
        task_id="task-route",
        task=SimpleNamespace(status="visualized", result=stale_result),
        status="transcribed",
        duration=None,
        filename="sample.wav",
        case_id=1,
        created_at=now,
        uploaded_at=now,
    )
    monkeypatch.setattr(audio_v1, "accessible_case_ids", lambda *_args: None)
    listed = audio_v1.read_audio(
        case_id=None,
        db=_FakeDb(all_rows=[audio_row]),
        current_user=object(),
    )
    assert listed[0]["visualization_data"] is None
    assert listed[0]["has_visualization"] is False
    assert listed[0]["status"] == "summarized"

    standalone_result = {
        "transcription": "Noi dung nguon.",
        "summary": "Tom tat.",
        "visualization_data": artifact,
        "has_visualization": True,
    }
    monkeypatch.setattr(
        audio_v1,
        "get_task",
        lambda _task_id: {
            "id": "task-route",
            "status": "visualized",
            "result": standalone_result,
        },
    )
    monkeypatch.setattr(audio_v1, "assert_task_access", lambda *_args: None)
    detail = asyncio.run(
        audio_v1.get_task_by_id(
            "task-route",
            db=_FakeDb(),
            current_user=object(),
        )
    )
    assert detail["visualization_data"] is None
    assert detail["result"]["visualization_data"] is None
    assert detail["has_visualization"] is False
    assert detail["status"] == "summarized"

    stale_revision_result = copy.deepcopy(stale_result)
    stale_revision_result["released_investigation_run"] = _stored_release_identity(
        source_revision_id="source-new"
    )
    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda _task_id, db=None: {
            "id": "task-route",
            "status": "visualized",
            "result": stale_revision_result,
        },
    )
    authorized = SimpleNamespace(
        status="visualized",
        error=None,
        filename="sample.wav",
        created_at=now,
        updated_at=now,
    )
    monkeypatch.setattr(
        audio_v2,
        "assert_task_access",
        lambda *_args: authorized,
    )
    status = asyncio.run(
        audio_v2.get_status_v2(
            "task-route",
            include_result=True,
            db=_FakeDb(),
            current_user=object(),
        )
    )
    assert status["visualization_data"] is None
    assert status["result"]["visualization_data"] is None
    assert status["has_visualization"] is False
    assert status["status"] == "summarized"


def test_hidden_visualization_downgrades_empty_visualized_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.api.endpoints import audio as audio_v1
    from src.api.endpoints import audio_v2
    from src.services import task_service

    artifact = _released_visualization_payload()
    result = {
        "visualization_data": artifact,
        "has_visualization": True,
    }
    now = datetime.now(timezone.utc)
    audio_row = SimpleNamespace(
        id=1,
        task_id="task-empty-visualized",
        task=SimpleNamespace(status="visualized", result=result),
        status="visualized",
        duration=None,
        filename="sample.wav",
        case_id=1,
        created_at=now,
        uploaded_at=now,
    )
    monkeypatch.setattr(audio_v1, "accessible_case_ids", lambda *_args: None)
    listed = audio_v1.read_audio(
        case_id=None,
        db=_FakeDb(all_rows=[audio_row]),
        current_user=object(),
    )
    assert listed[0]["status"] == "uploaded"

    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda _task_id, db=None: {
            "id": "task-empty-visualized",
            "status": "visualized",
            "result": result,
        },
    )
    monkeypatch.setattr(
        audio_v2,
        "assert_task_access",
        lambda *_args: SimpleNamespace(
            status="visualized",
            error=None,
            filename="sample.wav",
            created_at=now,
            updated_at=now,
        ),
    )
    status = asyncio.run(
        audio_v2.get_status_v2(
            "task-empty-visualized",
            include_result=True,
            db=_FakeDb(),
            current_user=object(),
        )
    )
    assert status["status"] == "uploaded"
