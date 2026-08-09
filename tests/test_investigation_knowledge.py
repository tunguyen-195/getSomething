import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.services.summarization.models.investigation_knowledge import (
    GroundedContextAnalysisPayload,
    InvestigationKnowledge,
    KnowledgeGroundingError,
    build_grounded_context_analysis,
    build_investigation_knowledge,
    build_s1_schema_artifact,
    remove_ungrounded_high_risk_fields,
)


TRANSCRIPT = "Lan hen Minh luc 09:00 tai ben xe. Minh dong y mang ho so."
SEGMENTS = [
    {
        "start": 0.0,
        "end": 3.5,
        "speaker": "SPEAKER_1",
        "text": "Lan hen Minh luc 09:00 tai ben xe.",
    },
    {
        "start": 3.5,
        "end": 6.0,
        "speaker": "SPEAKER_2",
        "text": "Minh dong y mang ho so.",
    },
]


def _analysis():
    return {
        "summary": "Raw model narrative is not authoritative.",
        "summary_sentences": [
            {
                "draft_id": "summary-1",
                "text": "Lan hen Minh luc 09:00 tai ben xe.",
                "sentence_role": "event",
                "evidence_quotes": ["Lan hen Minh luc 09:00 tai ben xe"],
            },
            {
                "draft_id": "summary-2",
                "text": "Minh dong y mang ho so.",
                "sentence_role": "outcome",
                "evidence_quotes": ["Minh dong y mang ho so"],
            },
        ],
        "key_points": [
            {
                "statement": "Hen luc 09:00 tai ben xe",
                "evidence_quote": "hen Minh luc 09:00 tai ben xe",
            }
        ],
        "entities": {
            "people": [
                {"name": "Lan", "role": "speaker", "evidence_quote": "Lan"},
                {"name": "Minh", "role": "speaker", "evidence_quote": "Minh"},
            ],
            "locations": [{"name": "ben xe", "evidence_quote": "ben xe"}],
            "time": [{"value": "09:00", "evidence_quote": "09:00"}],
            "organizations": [],
        },
        "facts": [
            {
                "category": "document",
                "statement": "Minh dong y mang ho so",
                "evidence_quote": "Minh dong y mang ho so",
                "status": "completed",
            }
        ],
        "relationships": [
            {
                "source": "Lan",
                "target": "Minh",
                "label": "hen gap",
                "evidence_quote": "Lan hen Minh",
            }
        ],
        "events": [
            {
                "time": "09:00",
                "description": "Hen gap tai ben xe",
                "actors": ["Lan", "Minh"],
                "location": "ben xe",
                "evidence_quote": "Lan hen Minh luc 09:00 tai ben xe",
            }
        ],
        "risk_assessment": {
            "overall_risk": "unverified",
            "crime_indicators": [
                {
                    "statement": "Ho so duoc mang den cuoc hen",
                    "crime_type": "other",
                    "confidence": "low",
                    "evidence_quote": "mang ho so",
                }
            ],
        },
    }


def _build_knowledge(**kwargs):
    return build_investigation_knowledge(
        _analysis(),
        TRANSCRIPT,
        SEGMENTS,
        model_id="fixture-model",
        generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        **kwargs,
    )


def test_knowledge_items_are_tied_to_segment_timestamps_and_speakers():
    knowledge = build_investigation_knowledge(
        _analysis(),
        TRANSCRIPT,
        SEGMENTS,
        model_id="fixture-model",
        source_metadata={
            "task_id": "task-1",
            "audio_id": 7,
            "audio_sha256": "a" * 64,
            "audio_integrity_status": "verified",
        },
        high_risk_enabled=False,
        generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )

    InvestigationKnowledge.model_validate(knowledge)
    assert knowledge["entities"]
    assert knowledge["events"]
    assert knowledge["relationships"]
    assert knowledge["summary_sentences"]
    assert knowledge["hypotheses"] == []
    assert knowledge["quality"]["withheld_high_risk_count"] == 1
    assert all(
        item["source_type"] == "transcript_segment"
        for item in knowledge["evidence_spans"]
    )
    assert any(
        item.get("speaker_id") == "SPEAKER_1"
        for item in knowledge["evidence_spans"]
    )
    assert any(
        item.get("start_seconds") == 0.0
        for item in knowledge["evidence_spans"]
    )
    assert knowledge["provenance"]["audio_sha256"] == "a" * 64
    assert knowledge["retention"]["raw_model_response_stored"] is False


def test_summary_quotes_resolve_to_exact_evidence_ids():
    knowledge = _build_knowledge(high_risk_enabled=False)
    evidence_by_id = {
        item["evidence_id"]: item for item in knowledge["evidence_spans"]
    }

    for sentence in knowledge["summary_sentences"]:
        assert sentence["evidence_quotes"] == [
            evidence_by_id[evidence_id]["quote"]
            for evidence_id in sentence["evidence_ids"]
        ]


def test_supported_high_risk_output_is_still_an_unverified_hypothesis():
    analysis = _analysis()
    analysis["hypotheses"] = [
        {
            "category": "coordination",
            "statement": "Cuoc hen co the de ban giao ho so",
            "evidence_quote": "Minh dong y mang ho so",
            "confidence": "low",
            "verification_question": "Muc dich thuc cua ho so la gi?",
        }
    ]

    knowledge = build_investigation_knowledge(
        analysis,
        TRANSCRIPT,
        SEGMENTS,
        model_id="fixture-model",
        high_risk_enabled=True,
    )

    categories = {item["category"] for item in knowledge["hypotheses"]}
    assert {"coordination", "other"} <= categories
    assert all(item["model_generated"] is True for item in knowledge["hypotheses"])
    assert all(
        item["requires_human_verification"] is True
        for item in knowledge["hypotheses"]
    )
    assert all(
        item["verification_status"] == "unverified"
        for item in knowledge["hypotheses"]
    )


def test_unsupported_high_risk_output_is_withheld_even_when_enabled():
    analysis = _analysis()
    analysis["risk_assessment"]["crime_indicators"][0]["evidence_quote"] = (
        "not in transcript"
    )

    knowledge = build_investigation_knowledge(
        analysis,
        TRANSCRIPT,
        SEGMENTS,
        model_id="fixture-model",
        high_risk_enabled=True,
    )

    assert knowledge["hypotheses"] == []
    assert knowledge["quality"]["withheld_high_risk_count"] == 1
    assert knowledge["safety"]["unsupported_high_risk_claims_released"] is False


def test_unsupported_ordinary_fact_fails_the_entire_grounding_operation():
    analysis = _analysis()
    analysis["facts"][0]["evidence_quote"] = "not in transcript"

    with pytest.raises(KnowledgeGroundingError, match="absent from transcript"):
        build_investigation_knowledge(
            analysis,
            TRANSCRIPT,
            SEGMENTS,
            model_id="fixture-model",
        )


def test_legal_hold_disables_automatic_expiry():
    knowledge = _build_knowledge(
        high_risk_enabled=False,
        source_metadata={"legal_hold": True},
    )

    assert knowledge["retention"]["legal_hold"] is True
    assert "expires_at" not in knowledge["retention"]


def test_raw_high_risk_fields_are_removed_from_flat_projection():
    analysis = _analysis()
    analysis["hypotheses"] = [
        {
            "category": "coordination",
            "statement": "Potential coordination",
            "evidence_quote": "mang ho so",
            "confidence": "low",
            "verification_question": "Can this be independently verified?",
        }
    ]

    sanitized = remove_ungrounded_high_risk_fields(analysis)

    assert sanitized["risk_assessment"]["crime_indicators"] == []
    assert sanitized["risk_assessment"]["recommended_actions"] == []
    assert sanitized["risk_assessment"]["overall_risk"] == "unverified"
    assert sanitized["hypotheses"] == []


def test_final_envelope_overwrites_raw_summary_and_revalidates_all_fields():
    result = build_grounded_context_analysis(
        _analysis(),
        TRANSCRIPT,
        SEGMENTS,
        model_id="fixture-model",
        high_risk_enabled=False,
        generated_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )

    GroundedContextAnalysisPayload.model_validate(result)
    assert result["summary"] == (
        "Lan hen Minh luc 09:00 tai ben xe Minh dong y mang ho so"
    )
    assert result["summary"] != _analysis()["summary"]
    assert result["summary_projection_source"] == (
        "summary_sentence_evidence_quotes"
    )
    assert result["compatibility"]["raw_model_summary_released"] is False
    assert result["compatibility"]["release_authority"] == (
        "withheld_pending_claim_attestation"
    )


def test_arbitrary_model_sentence_text_is_discarded_before_final_envelope():
    analysis = _analysis()
    analysis["summary_sentences"][0]["text"] = "Lan la toi pham."

    result = build_grounded_context_analysis(
        analysis,
        TRANSCRIPT,
        SEGMENTS,
        model_id="fixture-model",
        high_risk_enabled=False,
    )

    assert "toi pham" not in json.dumps(result, ensure_ascii=False)
    assert result["summary_sentences"][0]["text"] == (
        "Lan hen Minh luc 09:00 tai ben xe"
    )
    assert result["summary"] == (
        "Lan hen Minh luc 09:00 tai ben xe Minh dong y mang ho so"
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda value: value["facts"][0]["evidence_ids"].append("ev-missing"),
            "dangling evidence reference",
        ),
        (
            lambda value: value["evidence_spans"][0].update(
                {"quote_sha256": "0" * 64}
            ),
            "quote_sha256",
        ),
        (
            lambda value: value["evidence_spans"][0].update(
                {"source_sha256": "0" * 64}
            ),
            "source_sha256 does not match",
        ),
        (
            lambda value: value["quality"].update({"grounded_items": 999}),
            "grounded_items",
        ),
        (
            lambda value: value["timeline"][0].update(
                {"description": "tampered timeline"}
            ),
            "timeline entry",
        ),
        (
            lambda value: value["safety"].update({"unknown_gate": True}),
            "unknown_gate",
        ),
        (
            lambda value: value["evidence_spans"][0].update(
                {"start_seconds": None}
            ),
            "must be paired",
        ),
        (
            lambda value: value["retention"].update(
                {"generated_at": "2026-08-10T00:00:00Z"}
            ),
            "generated_at must match",
        ),
        (
            lambda value: value["entities"][0].update(
                {"entity_id": value["facts"][0]["fact_id"]}
            ),
            "globally unique",
        ),
        (
            lambda value: value["quality"].update(
                {"evidence_coverage": float("nan")}
            ),
            "finite number",
        ),
    ],
)
def test_knowledge_schema_rejects_tamper_and_unknown_nested_fields(mutator, message):
    knowledge = _build_knowledge(high_risk_enabled=False)
    mutator(knowledge)

    with pytest.raises(ValidationError, match=message):
        InvestigationKnowledge.model_validate(knowledge)


def test_knowledge_schema_rejects_duplicate_and_orphan_evidence():
    duplicate = _build_knowledge(high_risk_enabled=False)
    duplicate["evidence_spans"].append(copy.deepcopy(duplicate["evidence_spans"][0]))

    with pytest.raises(ValidationError, match="duplicate evidence span"):
        InvestigationKnowledge.model_validate(duplicate)

    orphan = _build_knowledge(high_risk_enabled=False)
    orphan_span = copy.deepcopy(orphan["evidence_spans"][0])
    orphan_span["evidence_id"] = "ev-orphan"
    orphan["evidence_spans"].append(orphan_span)

    with pytest.raises(ValidationError, match="unreferenced evidence"):
        InvestigationKnowledge.model_validate(orphan)


def test_summary_sentence_references_cannot_be_swapped_or_dangling():
    knowledge = _build_knowledge(high_risk_enabled=False)
    first, second = knowledge["summary_sentences"]
    first["evidence_ids"] = second["evidence_ids"]

    with pytest.raises(ValidationError, match="evidence_quotes"):
        InvestigationKnowledge.model_validate(knowledge)


def test_final_envelope_rejects_post_assembly_nested_mutation():
    result = build_grounded_context_analysis(
        _analysis(),
        TRANSCRIPT,
        SEGMENTS,
        model_id="fixture-model",
        high_risk_enabled=False,
    )
    result["investigation_knowledge"]["safety"]["forged_pass"] = True

    with pytest.raises(ValidationError, match="forged_pass"):
        GroundedContextAnalysisPayload.model_validate(result)


def test_transcript_hash_and_evidence_hashes_are_reproducible():
    knowledge = _build_knowledge(high_risk_enabled=False)

    assert knowledge["provenance"]["transcript_sha256"] == hashlib.sha256(
        TRANSCRIPT.encode("utf-8")
    ).hexdigest()
    for span in knowledge["evidence_spans"]:
        assert span["quote_sha256"] == hashlib.sha256(
            span["quote"].encode("utf-8")
        ).hexdigest()


def test_transcript_text_source_hash_is_bound_to_provenance():
    knowledge = build_investigation_knowledge(
        _analysis(),
        TRANSCRIPT,
        model_id="fixture-model",
        high_risk_enabled=False,
    )
    knowledge["evidence_spans"][0]["source_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="transcript evidence source_sha256"):
        InvestigationKnowledge.model_validate(knowledge)


def test_schema_artifact_is_deterministic_strict_and_honest_about_s2_blocker():
    first = build_s1_schema_artifact()
    second = build_s1_schema_artifact()

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["gates"]["nested_objects_forbid_unknown_fields"] is True
    assert first["gates"]["raw_model_summary_is_release_authority"] is False
    assert first["gates"]["raw_model_sentence_text_released"] is False
    assert first["gates"]["source_hash_manifest_bound"] is True
    assert first["gates"]["per_claim_semantic_attestation_complete"] is False
    assert first["gates"]["summary_release_authority"] == (
        "withheld_pending_claim_attestation"
    )

    object_nodes = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                object_nodes.append(value)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(first["knowledge_schema"])
    visit(first["final_envelope_schema"])

    assert len(object_nodes) >= 20
    assert all(node.get("additionalProperties") is False for node in object_nodes)


def test_committed_schema_artifact_matches_current_models():
    artifact_path = Path("docs/reviews/artifacts/s1-summary-schema.json")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert artifact["schema_version"] == "rtk-evidence-v1"
    assert artifact["verdict"] == "PASS"
    assert artifact["exit_code"] == 0
    assert artifact["source_scope"] == "git_index"
    assert artifact["schema_snapshot"] == build_s1_schema_artifact()
