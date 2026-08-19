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
    aligned_summary_clause,
    remove_ungrounded_high_risk_fields,
    validate_grounded_summary_text,
)


def test_clause_alignment_prefers_matching_action_over_repeated_actor_labels() -> None:
    candidate = (
        "Người tham gia thứ hai cho biết Quyên phải đặt cọc để khách sạn giữ "
        "phòng cho Quyên; Quyên chuyển khoản."
    )

    assert aligned_summary_clause(
        candidate,
        "Quyên chuyển khoản cho người tham gia thứ hai.",
    ) == "Quyên chuyển khoản"


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


def _minimal_analysis(
    summary_rows: list[tuple[str, str]],
    *,
    people: list[dict] | None = None,
) -> dict:
    return {
        "summary": " ".join(text for text, _quote in summary_rows),
        "summary_sentences": [
            {
                "draft_id": f"summary-{index}",
                "text": text,
                "sentence_role": "event",
                "evidence_quotes": [quote],
            }
            for index, (text, quote) in enumerate(summary_rows)
        ],
        "key_points": [],
        "entities": {
            "people": people or [],
            "locations": [],
            "time": [],
            "organizations": [],
        },
        "facts": [],
        "relationships": [],
        "events": [],
        "risk_assessment": {
            "overall_risk": "unverified",
            "crime_indicators": [],
        },
    }


def _trusted_diarization_metadata(speaker_count: int) -> dict:
    return {
        "audio_integrity_status": "verified",
        "has_diarization": True,
        "degraded": False,
        "diarization_status": "success",
        "diarization_method_used": "pyannote",
        "num_speakers": speaker_count,
        "speaker_provenance": {
            "status": "success",
            "speaker_count": speaker_count,
            "artifact_verified": True,
            "model_revision": "a" * 40,
            "assignment_method": "segment_max_overlap",
            "method_used": "pyannote",
            "load_error": None,
        },
    }


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
    ambiguous_mentions = [
        item for item in knowledge["evidence_spans"] if item["quote"] == "Minh"
    ]
    assert len(ambiguous_mentions) == 1
    assert ambiguous_mentions[0]["source_type"] == "transcript_text"
    assert ambiguous_mentions[0].get("speaker_id") is None
    assert all(
        item["source_type"] == "transcript_segment"
        for item in knowledge["evidence_spans"]
        if item["quote"] != "Minh"
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


def test_verified_self_identification_binds_only_the_speaking_cluster():
    transcript = "Tôi tên là Nguyễn Văn An. Tôi sẽ gửi hồ sơ."
    segments = [
        {
            "start": 0.0,
            "end": 2.0,
            "speaker": "SPEAKER_00",
            "text": "Tôi tên là Nguyễn Văn An.",
        },
        {
            "start": 2.0,
            "end": 4.0,
            "speaker": "SPEAKER_00",
            "text": "Tôi sẽ gửi hồ sơ.",
        },
    ]
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [
                ("Tôi tên là Nguyễn Văn An.", "Tôi tên là Nguyễn Văn An."),
                ("Tôi sẽ gửi hồ sơ.", "Tôi sẽ gửi hồ sơ."),
            ],
            people=[
                {
                    "name": "Nguyễn Văn An",
                    "evidence_quote": "Tôi tên là Nguyễn Văn An.",
                }
            ],
        ),
        transcript,
        segments,
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(1),
        high_risk_enabled=False,
    )

    participant = next(
        item
        for item in knowledge["participant_registry"]["participants"]
        if item.get("display_name") == "Nguyễn Văn An"
    )
    assert participant["participant_kind"] == "speaker"
    assert participant["identity_basis"] == "self_identified"
    assert participant["speaker_binding_state"] == "verified_cluster"
    assert participant["source_speaker_ids"] == ["SPEAKER_00"]
    assert participant["public_actor_label"] == "Nguyễn Văn An"


def test_same_speaker_short_and_full_name_remain_distinct_without_attestation():
    short_identity = "Ờ... Chị tên là Quyên em ạ!"
    full_name_claim = (
        "Chị là Nguyễn Thị Quyên, số điện thoại của chị là 0978 711 253"
    )
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [
                (short_identity, short_identity),
                (full_name_claim, full_name_claim),
            ],
            people=[
                {"name": "Quyên", "evidence_quote": short_identity},
                {"name": "Nguyễn Thị Quyên", "evidence_quote": full_name_claim},
            ],
        ),
        f"{short_identity} {full_name_claim}",
        [
            {"speaker": "SPEAKER_01", "text": short_identity},
            {"speaker": "SPEAKER_01", "text": full_name_claim},
        ],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(1),
        high_risk_enabled=False,
    )

    named = {
        item["display_name"]: item
        for item in knowledge["participant_registry"]["participants"]
        if item.get("display_name")
    }
    assert set(named) == {"Quyên", "Nguyễn Thị Quyên"}

    short = named["Quyên"]
    assert short["identity_basis"] == "self_identified"
    assert short["source_speaker_ids"] == ["SPEAKER_01"]
    assert short["speaker_binding_state"] == "verified_cluster"
    assert short["public_actor_label"] == "Quyên"
    assert short["attribution_required"] is False

    full = named["Nguyễn Thị Quyên"]
    assert full["identity_basis"] == "source_attributed"
    assert full["source_speaker_ids"] == []
    assert full["speaker_binding_state"] == "not_applicable"
    assert full["attribution_required"] is True
    assert full["public_actor_label"] == (
        "người được nhắc đến là Nguyễn Thị Quyên"
    )
    assert "Nguyễn Thị Quyên" not in full["allowed_reference_forms"]


@pytest.mark.parametrize(
    ("statement", "display_name"),
    [
        ("Chị tên là Nguyễn Văn An.", "Nguyễn Văn An"),
        ("Anh họ tên là Trần Văn Bình.", "Trần Văn Bình"),
    ],
)
def test_honorific_self_identification_requires_an_explicit_name_cue(
    statement: str,
    display_name: str,
) -> None:
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(statement, statement)],
            people=[{"name": display_name, "evidence_quote": statement}],
        ),
        statement,
        [{"speaker": "SPEAKER_00", "text": statement}],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(1),
        high_risk_enabled=False,
    )

    participant = next(
        item
        for item in knowledge["participant_registry"]["participants"]
        if item.get("display_name") == display_name
    )
    assert participant["identity_basis"] == "self_identified"
    assert participant["source_speaker_ids"] == ["SPEAKER_00"]


def test_self_identified_participant_rejects_tampered_non_identity_evidence() -> None:
    first = "Tôi tên là Nguyễn Văn An."
    second = "Tôi sẽ gửi hồ sơ."
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(first, first), (second, second)],
            people=[{"name": "Nguyễn Văn An", "evidence_quote": first}],
        ),
        f"{first} {second}",
        [
            {"speaker": "SPEAKER_00", "text": first},
            {"speaker": "SPEAKER_00", "text": second},
        ],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(1),
        high_risk_enabled=False,
    )
    action_evidence_id = knowledge["summary_sentences"][1]["evidence_ids"][0]
    participant = next(
        item
        for item in knowledge["participant_registry"]["participants"]
        if item.get("display_name") == "Nguyễn Văn An"
    )
    participant["evidence_ids"] = [action_evidence_id]

    with pytest.raises(
        ValueError,
        match="self-identified participant lacks direct identification evidence",
    ):
        InvestigationKnowledge.model_validate(knowledge)


def test_self_identified_participant_rejects_cross_speaker_binding_tamper() -> None:
    first = "Tôi tên là Nguyễn Văn An."
    second = "Tôi sẽ gửi hồ sơ."
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(first, first), (second, second)],
            people=[{"name": "Nguyễn Văn An", "evidence_quote": first}],
        ),
        f"{first} {second}",
        [
            {"speaker": "SPEAKER_00", "text": first},
            {"speaker": "SPEAKER_01", "text": second},
        ],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(2),
        high_risk_enabled=False,
    )
    participants = knowledge["participant_registry"]["participants"]
    named = next(item for item in participants if item.get("display_name"))
    anonymous = next(
        item for item in participants if item["identity_basis"] == "anonymous"
    )
    evidence_by_speaker = {
        item["speaker_id"]: item["evidence_id"]
        for item in knowledge["evidence_spans"]
        if item.get("speaker_id")
    }
    named["source_speaker_ids"] = ["SPEAKER_01"]
    named["evidence_ids"] = [
        evidence_by_speaker["SPEAKER_00"],
        evidence_by_speaker["SPEAKER_01"],
    ]
    anonymous["source_speaker_ids"] = ["SPEAKER_00"]
    anonymous["evidence_ids"] = [evidence_by_speaker["SPEAKER_00"]]

    with pytest.raises(
        ValueError,
        match="self-identification evidence speaker does not match participant binding",
    ):
        InvestigationKnowledge.model_validate(knowledge)


@pytest.mark.parametrize(
    "statement",
    [
        "Chị là Nguyễn Văn An.",
        "Anh là Nguyễn Văn An, đúng không?",
        "Có phải tôi là Nguyễn Văn An",
        "Phải chăng tôi tên là Nguyễn Văn An",
        "Tôi là Nguyễn Văn An hả",
        "Tôi tên là Nguyễn Văn An sao",
        "Tôi là Nguyễn Văn An, không đúng.",
        "Tôi là Nguyễn Văn An đâu.",
        "Lan nói: tôi là Nguyễn Văn An.",
        "Lan nói với Minh rằng tôi là Nguyễn Văn An.",
        "Theo lời Lan, tôi tên là Nguyễn Văn An.",
        "Lan nhắn: tôi là Nguyễn Văn An.",
        "Theo tin nhắn của Lan: tôi là Nguyễn Văn An.",
        "Lan viết rằng tôi là Nguyễn Văn An.",
    ],
)
def test_question_denial_and_reported_speech_do_not_bind_self_identity(
    statement: str,
) -> None:
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(statement, statement)],
            people=[
                {
                    "name": "Nguyễn Văn An",
                    "evidence_quote": statement,
                }
            ],
        ),
        statement,
        [{"speaker": "SPEAKER_00", "text": statement}],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(1),
        high_risk_enabled=False,
    )

    named = next(
        item
        for item in knowledge["participant_registry"]["participants"]
        if item.get("display_name") == "Nguyễn Văn An"
    )
    assert named["identity_basis"] != "self_identified"
    assert named["source_speaker_ids"] == []
    assert named["attribution_required"] is True


def test_attribution_required_participant_rejects_bare_name_release() -> None:
    statement = "Chị là Nguyễn Văn An."
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(statement, statement)],
            people=[{"name": "Nguyễn Văn An", "evidence_quote": statement}],
        ),
        statement,
        [{"speaker": "SPEAKER_00", "text": statement}],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(1),
        high_risk_enabled=False,
    )
    participant = next(
        item
        for item in knowledge["participant_registry"]["participants"]
        if item.get("display_name") == "Nguyễn Văn An"
    )
    participant["public_actor_label"] = participant["display_name"]
    participant["allowed_reference_forms"] = [participant["display_name"]]

    with pytest.raises(
        ValidationError,
        match="attribution-required participant cannot release a bare identity",
    ):
        InvestigationKnowledge.model_validate(knowledge)


def test_provider_generic_person_surface_is_not_released() -> None:
    statement = "Số tài khoản sẽ được gửi kèm."
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(statement, statement)],
            people=[{"name": "Số", "evidence_quote": statement}],
        ),
        statement,
        [{"speaker": "SPEAKER_00", "text": statement}],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(1),
        high_risk_enabled=False,
    )

    assert not any(
        item["entity_type"] == "person" and item["value"] == "Số"
        for item in knowledge["entities"]
    )
    assert not any(
        item.get("display_name") == "Số"
        for item in knowledge["participant_registry"]["participants"]
    )


def test_provider_person_entity_requires_a_supported_name_surface() -> None:
    statement = "Số tài khoản sẽ được gửi kèm."

    with pytest.raises(
        KnowledgeGroundingError,
        match="entity person value is not supported by its evidence quote",
    ):
        build_investigation_knowledge(
            _minimal_analysis(
                [(statement, statement)],
                people=[{"name": "Nguyễn Văn An", "evidence_quote": statement}],
            ),
            statement,
            [{"speaker": "SPEAKER_00", "text": statement}],
            model_id="fixture-model",
            source_metadata=_trusted_diarization_metadata(1),
            high_risk_enabled=False,
        )


@pytest.mark.parametrize(
    ("group_name", "entity_type", "item", "statement"),
    [
        (
            "locations",
            "location",
            {"name": "Kho A", "evidence_quote": "Kho B"},
            "Cuộc gặp diễn ra tại Kho B.",
        ),
        (
            "organizations",
            "organization",
            {"name": "Công ty A", "evidence_quote": "Công ty B"},
            "Hồ sơ do Công ty B gửi.",
        ),
        (
            "time",
            "time",
            {"value": "10:00", "evidence_quote": "9:00"},
            "Cuộc gặp bắt đầu lúc 9:00.",
        ),
    ],
)
def test_provider_non_person_entity_requires_a_supported_value_surface(
    group_name: str,
    entity_type: str,
    item: dict,
    statement: str,
) -> None:
    analysis = _minimal_analysis([(statement, statement)])
    analysis["entities"][group_name] = [item]

    with pytest.raises(
        KnowledgeGroundingError,
        match=rf"entity {entity_type} value is not supported by its evidence quote",
    ):
        build_investigation_knowledge(
            analysis,
            statement,
            [{"speaker": "SPEAKER_00", "text": statement}],
            model_id="fixture-model",
            source_metadata=_trusted_diarization_metadata(1),
            high_risk_enabled=False,
        )


def test_provider_numeric_entities_allow_safe_canonical_surface_matching() -> None:
    transcript = (
        "Gọi số 0912.345.678, chuyển vào tài khoản 0012 345 678 lúc 9:00."
    )
    analysis = _minimal_analysis([(transcript, transcript)])
    analysis["entities"]["time"] = [
        {"value": "09:00", "evidence_quote": "9:00"}
    ]
    analysis["entities"]["contact_info"] = {
        "phones": [
            {"value": "0912345678", "evidence_quote": "0912.345.678"}
        ],
        "bank_accounts": [
            {
                "account_number": "0012345678",
                "evidence_quote": "0012 345 678",
            }
        ],
    }

    knowledge = build_investigation_knowledge(
        analysis,
        transcript,
        [{"speaker": "SPEAKER_00", "text": transcript}],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(1),
        high_risk_enabled=False,
    )

    entity_values = {
        (item["entity_type"], item["value"]) for item in knowledge["entities"]
    }
    assert ("time", "09:00") in entity_values
    assert ("phone", "0912345678") in entity_values
    assert ("bank_account", "0012345678") in entity_values


def test_provider_numeric_entity_rejects_a_different_supported_length_value() -> None:
    statement = "Số điện thoại được đọc là 0912.345.678."
    analysis = _minimal_analysis([(statement, statement)])
    analysis["entities"]["contact_info"] = {
        "phones": [
            {"value": "0987654321", "evidence_quote": "0912.345.678"}
        ]
    }

    with pytest.raises(
        KnowledgeGroundingError,
        match="entity phone value is not supported by its evidence quote",
    ):
        build_investigation_knowledge(
            analysis,
            statement,
            [{"speaker": "SPEAKER_00", "text": statement}],
            model_id="fixture-model",
            source_metadata=_trusted_diarization_metadata(1),
            high_risk_enabled=False,
        )


def test_unverified_diarization_artifact_withholds_count_and_self_binding() -> None:
    statement = "Tôi tên là Nguyễn Văn An."
    metadata = _trusted_diarization_metadata(1)
    metadata["speaker_provenance"]["artifact_verified"] = False
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(statement, statement)],
            people=[{"name": "Nguyễn Văn An", "evidence_quote": statement}],
        ),
        statement,
        [{"speaker": "SPEAKER_00", "text": statement}],
        model_id="fixture-model",
        source_metadata=metadata,
        high_risk_enabled=False,
    )

    registry = knowledge["participant_registry"]
    named = next(item for item in registry["participants"] if item.get("display_name"))
    assert registry["speaker_count_release_status"] == "withheld"
    assert "verified_speaker_count" not in registry
    assert named["identity_basis"] == "source_attributed"
    assert named["source_speaker_ids"] == []
    assert named["public_actor_label"] == (
        "người được nhắc đến là Nguyễn Văn An"
    )
    assert "Nguyễn Văn An" not in named["allowed_reference_forms"]
    assert any(
        item["public_actor_label"] == "một người tham gia"
        for item in registry["participants"]
    )


def test_role_requires_an_explicit_relation_span_not_quote_cooccurrence() -> None:
    statement = "Nguyễn Văn An gọi cho Lan. Nhân viên xác nhận hồ sơ."
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(statement, statement)],
            people=[
                {
                    "name": "Nguyễn Văn An",
                    "role": "nhân viên",
                    "evidence_quote": statement,
                }
            ],
        ),
        statement,
        [{"text": statement}],
        model_id="fixture-model",
        high_risk_enabled=False,
    )

    participant = next(
        item
        for item in knowledge["participant_registry"]["participants"]
        if item.get("display_name") == "Nguyễn Văn An"
    )
    assert participant["grounded_roles"] == []


def test_explicit_conversation_role_is_resolved_without_speaker_binding() -> None:
    statement = "Nguyễn Văn An là người gọi."
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(statement, statement)],
            people=[
                {
                    "name": "Nguyễn Văn An",
                    "role": "người gọi",
                    "evidence_quote": statement,
                }
            ],
        ),
        statement,
        [{"text": statement}],
        model_id="fixture-model",
        high_risk_enabled=False,
    )

    participant = next(
        item
        for item in knowledge["participant_registry"]["participants"]
        if item.get("display_name") == "Nguyễn Văn An"
    )
    assert participant["identity_basis"] == "conversation_role"
    assert participant["source_speaker_ids"] == []
    assert participant["grounded_roles"][0]["role_type"] == "conversation_role"
    assert participant["public_actor_label"] == (
        "người được nhắc đến là Nguyễn Văn An"
    )
    assert "Nguyễn Văn An là người gọi" in participant["allowed_reference_forms"]
    assert "Nguyễn Văn An" not in participant["allowed_reference_forms"]


def test_identity_conflict_on_one_cluster_withholds_named_binding() -> None:
    first = "Tôi tên là Nguyễn Văn An."
    second = "Tôi tên là Trần Văn Bình."
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(first, first), (second, second)],
            people=[
                {"name": "Nguyễn Văn An", "evidence_quote": first},
                {"name": "Trần Văn Bình", "evidence_quote": second},
            ],
        ),
        f"{first} {second}",
        [
            {"speaker": "SPEAKER_00", "text": first},
            {"speaker": "SPEAKER_00", "text": second},
        ],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(1),
        high_risk_enabled=False,
    )

    named = [
        item
        for item in knowledge["participant_registry"]["participants"]
        if item.get("display_name")
    ]
    assert len(named) == 2
    assert all(item["source_speaker_ids"] == [] for item in named)
    assert all(item["withheld_identity_reason"] == "identity_conflict" for item in named)
    assert all(item["attribution_required"] is True for item in named)


def test_same_self_identified_name_on_multiple_clusters_is_not_collapsed() -> None:
    first = "Tôi tên là Nguyễn Văn An."
    second = "Mình là Nguyễn Văn An."
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(first, first), (second, second)],
            people=[
                {"name": "Nguyễn Văn An", "evidence_quote": first},
                {"name": "Nguyễn Văn An", "evidence_quote": second},
            ],
        ),
        f"{first} {second}",
        [
            {"speaker": "SPEAKER_00", "text": first},
            {"speaker": "SPEAKER_01", "text": second},
        ],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(2),
        high_risk_enabled=False,
    )

    named = next(
        item
        for item in knowledge["participant_registry"]["participants"]
        if item.get("display_name") == "Nguyễn Văn An"
    )
    assert named["source_speaker_ids"] == []
    assert named["withheld_identity_reason"] == "identity_conflict"


def test_mentioned_name_does_not_become_the_current_speaker():
    transcript = "Tôi đã gặp Nguyễn Văn An."
    segments = [
        {
            "start": 0.0,
            "end": 2.0,
            "speaker": "SPEAKER_00",
            "text": transcript,
        }
    ]
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(transcript, transcript)],
            people=[
                {
                    "name": "Nguyễn Văn An",
                    "evidence_quote": "Nguyễn Văn An",
                }
            ],
        ),
        transcript,
        segments,
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(1),
        high_risk_enabled=False,
    )

    participants = knowledge["participant_registry"]["participants"]
    mentioned = next(item for item in participants if item.get("display_name"))
    speaker = next(item for item in participants if item["participant_kind"] == "speaker")
    assert mentioned["participant_kind"] == "mentioned_person"
    assert mentioned["source_speaker_ids"] == []
    assert speaker["identity_basis"] == "anonymous"
    assert speaker["source_speaker_ids"] == ["SPEAKER_00"]


def test_self_identified_evidence_does_not_overlap_another_anonymous_speaker() -> None:
    first = "Tôi tên là Nguyễn Văn An."
    second = "Tôi đã gặp Nguyễn Văn An."
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [(first, first), (second, second)],
            people=[
                {"name": "Nguyễn Văn An", "evidence_quote": first},
                {"name": "Nguyễn Văn An", "evidence_quote": second},
            ],
        ),
        f"{first} {second}",
        [
            {"speaker": "SPEAKER_00", "text": first},
            {"speaker": "SPEAKER_01", "text": second},
        ],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(2),
        high_risk_enabled=False,
    )

    participants = knowledge["participant_registry"]["participants"]
    named = next(item for item in participants if item.get("display_name"))
    anonymous = next(
        item
        for item in participants
        if item["identity_basis"] == "anonymous"
        and item["source_speaker_ids"] == ["SPEAKER_01"]
    )
    evidence_by_id = {
        item["evidence_id"]: item for item in knowledge["evidence_spans"]
    }

    assert {
        evidence_by_id[evidence_id].get("speaker_id")
        for evidence_id in named["evidence_ids"]
    } == {"SPEAKER_00"}
    assert set(named["evidence_ids"]).isdisjoint(anonymous["evidence_ids"])


def test_degraded_diarization_withholds_count_ordinals_and_cluster_bindings():
    analysis = _minimal_analysis(
        [
            ("Lan sẽ gửi hồ sơ.", "Lan sẽ gửi hồ sơ."),
            ("Minh sẽ nhận hồ sơ.", "Minh sẽ nhận hồ sơ."),
        ]
    )
    segments = [
        {"speaker": "SPEAKER_00", "text": "Lan sẽ gửi hồ sơ."},
        {"speaker": "SPEAKER_01", "text": "Minh sẽ nhận hồ sơ."},
    ]
    knowledge = build_investigation_knowledge(
        analysis,
        "Lan sẽ gửi hồ sơ. Minh sẽ nhận hồ sơ.",
        segments,
        model_id="fixture-model",
        source_metadata={
            "diarization_status": "degraded",
            "num_speakers": 2,
            "speaker_provenance": {"status": "degraded"},
        },
        high_risk_enabled=False,
    )

    registry = knowledge["participant_registry"]
    assert registry["speaker_count_release_status"] == "withheld"
    assert registry.get("verified_speaker_count") is None
    assert all(
        not item["source_speaker_ids"] for item in registry["participants"]
    )
    assert all(
        not item["public_actor_label"].startswith("người nói")
        for item in registry["participants"]
    )


def test_speaker_id_alias_preserves_verified_participant_bindings():
    segments = [
        {"speaker_id": "SPEAKER_00", "text": "Lan sẽ gửi hồ sơ."},
        {"speaker_id": "SPEAKER_01", "text": "Minh sẽ nhận hồ sơ."},
    ]
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [
                ("Lan sẽ gửi hồ sơ.", "Lan sẽ gửi hồ sơ."),
                ("Minh sẽ nhận hồ sơ.", "Minh sẽ nhận hồ sơ."),
            ]
        ),
        "Lan sẽ gửi hồ sơ. Minh sẽ nhận hồ sơ.",
        segments,
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(2),
        high_risk_enabled=False,
    )

    registry = knowledge["participant_registry"]
    assert registry["verified_speaker_count"] == 2
    assert {
        speaker_id
        for item in registry["participants"]
        for speaker_id in item["source_speaker_ids"]
    } == {"SPEAKER_00", "SPEAKER_01"}


def test_trusted_diarization_does_not_register_unreferenced_unassigned_segment():
    transcript = "Lan xác nhận đặt hai phòng. Ờ... Minh xác nhận thanh toán."
    segments = [
        {"speaker": "SPEAKER_00", "text": "Lan xác nhận đặt hai phòng."},
        {"speaker": None, "text": "Ờ..."},
        {"speaker": "SPEAKER_01", "text": "Minh xác nhận thanh toán."},
    ]
    knowledge = build_investigation_knowledge(
        _minimal_analysis(
            [
                ("Lan xác nhận đặt hai phòng.", "Lan xác nhận đặt hai phòng."),
                ("Minh xác nhận thanh toán.", "Minh xác nhận thanh toán."),
            ]
        ),
        transcript,
        segments,
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(2),
        high_risk_enabled=False,
    )

    assert knowledge["participant_registry"]["verified_speaker_count"] == 2
    assert all(item["quote"] != "Ờ..." for item in knowledge["evidence_spans"])


def test_duplicate_quote_is_not_silently_assigned_to_first_speaker():
    transcript = "Đồng ý. Đồng ý."
    knowledge = build_investigation_knowledge(
        _minimal_analysis([("Đồng ý.", "Đồng ý.")]),
        transcript,
        [
            {"speaker": "SPEAKER_00", "text": "Đồng ý."},
            {"speaker": "SPEAKER_01", "text": "Đồng ý."},
        ],
        model_id="fixture-model",
        source_metadata=_trusted_diarization_metadata(2),
        high_risk_enabled=False,
    )

    sentence_evidence_id = knowledge["summary_sentences"][0]["evidence_ids"][0]
    evidence = next(
        item
        for item in knowledge["evidence_spans"]
        if item["evidence_id"] == sentence_evidence_id
    )
    assert evidence["source_type"] == "transcript_text"
    assert evidence.get("speaker_id") is None


def test_cross_segment_evidence_uses_the_smallest_contiguous_window() -> None:
    quote = "Lan chuyển hồ sơ cho Minh."
    transcript = "Nội dung mở đầu. Lan chuyển hồ sơ cho Minh. Nội dung kết thúc."
    knowledge = build_investigation_knowledge(
        _minimal_analysis([(quote, quote)]),
        transcript,
        [
            {"speaker": "SPEAKER_00", "text": "Nội dung mở đầu."},
            {"speaker": "SPEAKER_01", "text": "Lan chuyển hồ sơ"},
            {"speaker": "SPEAKER_01", "text": "cho Minh."},
            {"speaker": "SPEAKER_02", "text": "Nội dung kết thúc."},
        ],
        model_id="fixture-model",
        high_risk_enabled=False,
    )

    evidence_by_id = {
        item["evidence_id"]: item for item in knowledge["evidence_spans"]
    }
    indexes = {
        evidence_by_id[evidence_id]["segment_index"]
        for evidence_id in knowledge["summary_sentences"][0]["evidence_ids"]
    }
    assert indexes == {1, 2}


def test_action_and_decision_actor_survive_the_typed_knowledge_projection() -> None:
    first = "Lan sẽ gửi hồ sơ."
    second = "Minh đồng ý nhận hồ sơ."
    analysis = _minimal_analysis([(first, first), (second, second)])
    analysis["actions"] = [
        {
            "action": "sẽ gửi hồ sơ",
            "actor": "Lan",
            "status": "planned",
            "evidence_quote": first,
        }
    ]
    analysis["decisions"] = [
        {
            "decision": "đồng ý nhận hồ sơ",
            "actor": "Minh",
            "evidence_quote": second,
        }
    ]
    knowledge = build_investigation_knowledge(
        analysis,
        f"{first} {second}",
        [{"text": first}, {"text": second}],
        model_id="fixture-model",
        high_risk_enabled=False,
    )

    facts = {item["category"]: item for item in knowledge["facts"]}
    assert facts["action"]["actor"] == "Lan"
    assert facts["decision"]["actor"] == "Minh"


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
        "Lan hen Minh luc 09:00 tai ben xe. Minh dong y mang ho so."
    )
    assert result["summary"] != _analysis()["summary"]
    assert result["summary_projection_source"] == (
        "grounded_summary_sentence_text"
    )
    assert result["compatibility"]["raw_model_summary_released"] is False
    assert result["compatibility"]["release_authority"] == (
        "withheld_pending_claim_attestation"
    )


def test_arbitrary_model_sentence_text_is_rejected_before_final_envelope():
    analysis = _analysis()
    analysis["summary_sentences"][0]["text"] = "Lan la toi pham."

    with pytest.raises(KnowledgeGroundingError, match="unsupported synthesis tokens"):
        build_grounded_context_analysis(
            analysis,
            TRANSCRIPT,
            SEGMENTS,
            model_id="fixture-model",
            high_risk_enabled=False,
        )


@pytest.mark.parametrize(
    ("source", "candidate", "message"),
    [
        (
            "Lan hẹn Minh lúc 09:00 tại bến xe.",
            "Minh hẹn Lan lúc 09:00 tại bến xe.",
            "actor binding",
        ),
        (
            "Lan bán xe cho Minh.",
            "Minh bán xe cho Lan.",
            "actor binding|recipient binding",
        ),
        (
            "Lan nói Minh lấy hồ sơ.",
            "Minh nói Lan lấy hồ sơ.",
            "actor binding",
        ),
        (
            "Lan nghi Minh trộm hồ sơ.",
            "Minh nghi Lan trộm hồ sơ.",
            "actor binding",
        ),
        (
            "Lan dự tính gọi Minh.",
            "Lan gọi Minh.",
            "planned action modality",
        ),
        (
            "Lan bảo Minh lấy hồ sơ.",
            "Minh lấy hồ sơ.",
            "source attribution",
        ),
        (
            "Lan mặc áo đỏ và đội mũ đen.",
            "Lan mặc áo đỏ.",
            "changes or drops source actions",
        ),
    ],
)
def test_grounded_context_rejects_semantic_corruption_before_writer(
    source,
    candidate,
    message,
) -> None:
    analysis = {
        "summary": "raw",
        "summary_sentences": [
            {
                "draft_id": "semantic-boundary",
                "text": candidate,
                "sentence_role": "event",
                "evidence_quotes": [source],
            }
        ],
        "key_points": [],
        "entities": {
            "people": [],
            "locations": [],
            "time": [],
            "organizations": [],
        },
        "facts": [],
        "relationships": [],
        "events": [],
        "risk_assessment": {"overall_risk": "unverified"},
    }
    segments = [{"start": 0.0, "end": 1.0, "text": source}]

    with pytest.raises(KnowledgeGroundingError, match=message):
        build_grounded_context_analysis(
            analysis,
            source,
            segments,
            model_id="semantic-boundary-fixture",
            high_risk_enabled=False,
        )


@pytest.mark.parametrize(
    ("source", "candidate", "message"),
    [
        (
            "Lan không gọi Minh và Hùng gặp Mai.",
            "Lan gọi Minh và Hùng không gặp Mai.",
            "source negation",
        ),
        (
            "Lan sẽ gọi Minh và Hùng gặp Mai.",
            "Lan gọi Minh và Hùng sẽ gặp Mai.",
            "planned action modality",
        ),
        (
            "Lan đã gọi Minh và Hùng gặp Mai.",
            "Lan gọi Minh và Hùng đã gặp Mai.",
            "completed action modality",
        ),
    ],
)
def test_summary_validator_rejects_modality_reattachment_between_predicates(
    source: str,
    candidate: str,
    message: str,
) -> None:
    with pytest.raises(KnowledgeGroundingError, match=message):
        validate_grounded_summary_text(
            candidate,
            [source],
            owner="predicate-scope-fixture",
            allow_safe_paraphrase=True,
        )


@pytest.mark.parametrize(
    ("source", "candidate"),
    [
        (
            "Khách có thể sử dụng wifi miễn phí.",
            "Khách được sử dụng wifi miễn phí.",
        ),
        (
            "Đơn vị sắp xếp hồ sơ theo thứ tự.",
            "Đơn vị xếp hồ sơ theo thứ tự.",
        ),
        ("Mức phí vừa đủ.", "Mức phí đủ."),
        ("Không gian phòng họp rộng rãi.", "Phòng họp rộng rãi."),
    ],
)
def test_summary_validator_accepts_lexical_marker_paraphrases(
    source: str,
    candidate: str,
) -> None:
    assert validate_grounded_summary_text(
        candidate,
        [source],
        owner="lexical-marker-fixture",
        allow_safe_paraphrase=True,
    ) == candidate


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
    assert first["gates"]["grounded_model_sentence_text_released"] is True
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
    assert artifact["environment"]["packages"]["pydantic"]
    assert artifact["environment"]["git_index"]["sha256"]
    assert artifact["environment"]["git_index"]["alternate"] is True
    assert (
        artifact["environment"]["git_index"][
            "working_tree_matches_selected_index"
        ]
        is True
    )
    assert artifact["schema_snapshot"] == build_s1_schema_artifact()
