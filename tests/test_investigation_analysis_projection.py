from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace

import pytest
from pydantic import ValidationError

from src.services.investigation.analysis_projection import (
    AnalysisProjectionRegistry,
    AnalysisProjectionV1_1,
    AnalysisQualityArtifact,
    ExactValueRecord,
    GroundedEventRecord,
    ReleasedAnalysisArtifact,
    SourceSetProvenance,
    SpeakerAssignmentRecord,
    analysis_projection_json_schema,
    analysis_projection_schema_sha256,
    build_released_analysis_artifact,
    validate_analysis_projection_refs,
)
from src.services.investigation.contracts import (
    ConceptMention,
    EvidenceSpan,
    GroundedClaim,
    sha256_utf8,
)


def _evidence(*, speaker_id: str = "speaker-00") -> EvidenceSpan:
    quote = "Tai khoan 001234 nhan 50 trieu dong."
    return EvidenceSpan(
        evidence_id="ev-1",
        segment_id="seg-1",
        quote_exact=quote,
        raw_char_start=0,
        raw_char_end=len(quote),
        start_seconds=12.0,
        end_seconds=15.5,
        speaker_id=speaker_id,
        quote_sha256=sha256_utf8(quote),
        source_sha256="b" * 64,
    )


def _claim(*, polarity: str = "affirmed") -> GroundedClaim:
    return GroundedClaim(
        claim_id="claim-1",
        claim_type="financial_transfer_statement",
        statement="Speaker 00 stated that account 001234 received 50 million VND.",
        polarity=polarity,
        disposition="supported",
        epistemic_status="fact",
        factual_scope="verified_source_assertion",
        risk_tier="ordinary",
        risk_screening_artifact_ref="risk-1",
        requires_human_verification=False,
        evidence_refs=["ev-1"],
        concept_refs=["concept-person"],
    )


def _projection() -> AnalysisProjectionV1_1:
    return AnalysisProjectionV1_1(
        source_set_ref="source-set-1",
        quality_ref="quality-1",
        source_assertion_refs=["claim-1"],
        concept_refs=["concept-person"],
        exact_value_refs=["value-1"],
        speaker_assignment_refs=["speaker-assignment-1"],
        event_refs=["event-1"],
        briefing_claim_refs=["claim-1"],
    )


def _registry(
    *,
    claim: GroundedClaim | None = None,
    evidence: EvidenceSpan | None = None,
    exact_value: ExactValueRecord | None = None,
    speaker_assignment: SpeakerAssignmentRecord | None = None,
    event: GroundedEventRecord | None = None,
) -> AnalysisProjectionRegistry:
    claim = claim or _claim()
    evidence = evidence or _evidence()
    source_set = SourceSetProvenance.bind(
        source_set_id="source-set-1",
        case_id="case-1",
        source_revision_refs=["source-revision-1"],
        authorization_scope_sha256="a" * 64,
    )
    quality = AnalysisQualityArtifact.bind(
        quality_id="quality-1",
        source_set_ref="source-set-1",
        coverage_manifest_ref="coverage-1",
        source_coverage_complete=True,
        source_quality_refs=["source-quality-1"],
        asr_state="verified",
        diarization_state="verified",
        deterministic_fallback_used=False,
        release_ready=True,
    )
    speaker_assignment = speaker_assignment or SpeakerAssignmentRecord.bind(
        speaker_assignment_id="speaker-assignment-1",
        source_revision_id="source-revision-1",
        file_id="file-1",
        diarization_revision_id="diarization-1",
        local_speaker_id="speaker-00",
        assignment_state="anonymous_cluster",
        evidence_refs=["ev-1"],
    )
    exact_value = exact_value or ExactValueRecord.bind(
        exact_value_id="value-1",
        value_type="money",
        semantic_role="money",
        surface_exact="50 trieu dong",
        normalized_value="50000000",
        owner_state="explicit",
        owner_ref="concept-person",
        unit_state="explicit",
        unit="VND",
        claim_refs=["claim-1"],
        evidence_refs=["ev-1"],
        speaker_assignment_ref="speaker-assignment-1",
        sensitivity="sensitive",
        verification_artifact_ref="verification-1",
    )
    event = event or GroundedEventRecord.bind(
        event_id="event-1",
        event_type="reported_financial_transfer",
        event_state="reported",
        claim_refs=["claim-1"],
        participant_bindings=[
            {
                "role": "reported_owner",
                "participant_ref": "concept-person",
                "participant_kind": "concept",
            }
        ],
        exact_value_refs=["value-1"],
        evidence_refs=["ev-1"],
    )
    concept = ConceptMention(
        concept_id="concept-person",
        concept_type="person",
        surface="nguoi nhan",
        role="reported_owner",
        evidence_refs=["ev-1"],
    )
    return AnalysisProjectionRegistry(
        source_sets={source_set.source_set_id: source_set},
        quality={quality.quality_id: quality},
        claims={claim.claim_id: claim},
        source_assertions={claim.claim_id: claim},
        world_findings={},
        concepts={concept.concept_id: concept},
        exact_values={exact_value.exact_value_id: exact_value},
        speaker_assignments={
            speaker_assignment.speaker_assignment_id: speaker_assignment
        },
        events={event.event_id: event},
        relationships={},
        flows={},
        contradictions={},
        evidence={evidence.evidence_id: evidence},
        insights={},
        hypotheses={},
        hypothesis_sets={},
        verification_actions={},
    )


def _assert_closed_objects(node: object) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
        for value in node.values():
            _assert_closed_objects(value)
    elif isinstance(node, list):
        for value in node:
            _assert_closed_objects(value)


def test_projection_is_strict_reference_only_and_authority_hash_bound() -> None:
    projection = _projection()
    validate_analysis_projection_refs(projection, _registry())

    artifact = build_released_analysis_artifact(
        run_id="run-1",
        release_subject_sha256="c" * 64,
        projection=projection,
    )
    assert artifact.authority == "released_investigation_run"
    assert artifact.projection.model_dump(exclude_none=True) == (
        projection.model_dump(exclude_none=True)
    )

    payload = artifact.model_dump(mode="json", exclude_none=True)
    payload["projection"]["source_assertion_refs"] = ["claim-forged"]
    payload["projection"]["briefing_claim_refs"] = ["claim-forged"]
    with pytest.raises(ValidationError, match="content_hash"):
        ReleasedAnalysisArtifact.model_validate(payload)


def test_projection_schema_is_closed_and_stable_across_processes() -> None:
    schema = analysis_projection_json_schema()
    _assert_closed_objects(schema)
    local_hash = analysis_projection_schema_sha256()

    code = (
        "from src.services.investigation.analysis_projection import "
        "analysis_projection_schema_sha256; print(analysis_projection_schema_sha256())"
    )
    first = subprocess.check_output([sys.executable, "-c", code], text=True).strip()
    second = subprocess.check_output([sys.executable, "-c", code], text=True).strip()
    assert first == second == local_hash


def test_reference_indexes_require_canonical_order() -> None:
    with pytest.raises(ValidationError, match="canonical sorted order"):
        AnalysisProjectionV1_1(
            source_set_ref="source-set-1",
            quality_ref="quality-1",
            source_assertion_refs=["claim-b", "claim-a"],
        )


def test_unknown_nested_fields_and_hypothesis_briefing_leakage_are_rejected() -> None:
    payload = _projection().model_dump(mode="json", exclude_none=True)
    payload["briefing_hypothesis_refs"] = ["hypothesis-1"]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalysisProjectionV1_1.model_validate(payload)

    payload = _projection().model_dump(mode="json", exclude_none=True)
    payload["briefing_claim_refs"] = ["hypothesis-1"]
    with pytest.raises(ValidationError, match="briefing claims"):
        AnalysisProjectionV1_1.model_validate(payload)


def test_projection_requires_exact_registry_coverage_and_no_dangling_refs() -> None:
    projection = _projection().model_copy(update={"exact_value_refs": None})
    with pytest.raises(ValueError, match="exact value refs must cover"):
        validate_analysis_projection_refs(projection, _registry())

    event = GroundedEventRecord.bind(
        event_id="event-1",
        event_type="reported_financial_transfer",
        event_state="reported",
        claim_refs=["claim-missing"],
        participant_bindings=[
            {
                "role": "reported_owner",
                "participant_ref": "concept-person",
                "participant_kind": "concept",
            }
        ],
        exact_value_refs=["value-1"],
        evidence_refs=["ev-1"],
    )
    with pytest.raises(ValueError, match="dangling event claim refs"):
        validate_analysis_projection_refs(_projection(), _registry(event=event))


@pytest.mark.parametrize(
    ("field", "value"),
    [("owner_ref", "concept-forged"), ("unit", "USD")],
)
def test_exact_value_owner_and_unit_mutation_breaks_attestation(
    field: str,
    value: str,
) -> None:
    exact_value = next(iter(_registry().exact_values.values()))
    payload = exact_value.model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError, match="content_sha256"):
        ExactValueRecord.model_validate(payload)


def test_wrong_speaker_mutation_and_high_impact_ambiguity_fail_closed() -> None:
    assignment = next(iter(_registry().speaker_assignments.values()))
    payload = assignment.model_dump(mode="json")
    payload["local_speaker_id"] = "speaker-99"
    with pytest.raises(ValidationError, match="content_sha256"):
        SpeakerAssignmentRecord.model_validate(payload)

    forged_assignment = SpeakerAssignmentRecord.bind(
        speaker_assignment_id="speaker-assignment-1",
        source_revision_id="source-revision-1",
        file_id="file-1",
        diarization_revision_id="diarization-1",
        local_speaker_id="speaker-99",
        assignment_state="anonymous_cluster",
        evidence_refs=["ev-1"],
    )
    with pytest.raises(ValueError, match="conflicts with evidence speaker"):
        validate_analysis_projection_refs(
            _projection(),
            _registry(speaker_assignment=forged_assignment),
        )

    ambiguous = SpeakerAssignmentRecord.bind(
        speaker_assignment_id="speaker-assignment-1",
        source_revision_id="source-revision-1",
        file_id="file-1",
        diarization_revision_id="diarization-1",
        local_speaker_id="speaker-00",
        assignment_state="ambiguous",
        evidence_refs=["ev-1"],
    )
    high_impact = ExactValueRecord.bind(
        exact_value_id="value-1",
        value_type="account",
        semantic_role="identifier",
        surface_exact="001234",
        normalized_value="001234",
        owner_state="explicit",
        owner_ref="concept-person",
        unit_state="not_applicable",
        claim_refs=["claim-1"],
        evidence_refs=["ev-1"],
        speaker_assignment_ref="speaker-assignment-1",
        sensitivity="high_impact",
        verification_artifact_ref="verification-1",
    )
    with pytest.raises(ValueError, match="uncertain speaker assignment"):
        validate_analysis_projection_refs(
            _projection(),
            _registry(
                speaker_assignment=ambiguous,
                exact_value=high_impact,
            ),
        )


def test_reported_statement_cannot_be_promoted_to_world_finding() -> None:
    reported = _claim(polarity="reported")
    projection = AnalysisProjectionV1_1(
        source_set_ref="source-set-1",
        quality_ref="quality-1",
        world_finding_refs=["claim-1"],
        concept_refs=["concept-person"],
        exact_value_refs=["value-1"],
        speaker_assignment_refs=["speaker-assignment-1"],
        event_refs=["event-1"],
        briefing_claim_refs=["claim-1"],
    )
    registry = _registry(claim=reported)
    registry = replace(
        registry,
        source_assertions={},
        world_findings={reported.claim_id: reported},
    )
    with pytest.raises(ValueError, match="corroborated fact authority"):
        validate_analysis_projection_refs(projection, registry)


def test_audio_occurrence_cannot_substitute_for_described_event_time() -> None:
    event = GroundedEventRecord.bind(
        event_id="event-1",
        event_type="reported_financial_transfer",
        event_state="reported",
        claim_refs=["claim-1"],
        participant_bindings=[
            {
                "role": "reported_owner",
                "participant_ref": "concept-person",
                "participant_kind": "concept",
            }
        ],
        exact_value_refs=["value-1"],
        described_time_value_refs=["value-1"],
        evidence_refs=["ev-1"],
    )
    with pytest.raises(ValueError, match="temporal exact value"):
        validate_analysis_projection_refs(_projection(), _registry(event=event))

    payload = event.model_dump(mode="json", exclude_none=True)
    payload["audio_start_seconds"] = 12.0
    payload["content_sha256"] = sha256_utf8(json.dumps(payload, sort_keys=True))
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GroundedEventRecord.model_validate(payload)


def test_stale_source_set_and_non_release_quality_are_rejected() -> None:
    assignment = SpeakerAssignmentRecord.bind(
        speaker_assignment_id="speaker-assignment-1",
        source_revision_id="source-revision-other",
        file_id="file-1",
        local_speaker_id="speaker-00",
        assignment_state="anonymous_cluster",
        evidence_refs=["ev-1"],
    )
    with pytest.raises(ValueError, match="outside the authorized source set"):
        validate_analysis_projection_refs(
            _projection(),
            _registry(speaker_assignment=assignment),
        )

    registry = _registry()
    blocked_quality = AnalysisQualityArtifact.bind(
        quality_id="quality-1",
        source_set_ref="source-set-1",
        coverage_manifest_ref="coverage-1",
        source_coverage_complete=False,
        source_quality_refs=["source-quality-1"],
        asr_state="degraded",
        diarization_state="degraded",
        deterministic_fallback_used=True,
        release_ready=False,
        blocking_codes=["INCOMPLETE_SOURCE_COVERAGE"],
    )
    with pytest.raises(ValueError, match="not release-ready"):
        validate_analysis_projection_refs(
            _projection(),
            replace(registry, quality={"quality-1": blocked_quality}),
        )
