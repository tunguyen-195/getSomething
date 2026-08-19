from __future__ import annotations

import pytest

from src.services.summarization.context_service import (
    build_transcript_grounded_fallback,
)


SOURCE = {
    "task_id": "deterministic-analysis-task",
    "case_id": "case-1",
    "file_name": "evidence.wav",
    "audio_id": 17,
    "audio_sha256": "a" * 64,
}


def _rich_context() -> dict:
    segments = [
        {
            "start": 0.0,
            "end": 6.0,
            "speaker": "SPEAKER_00",
            "text": (
                "Ông Nguyễn Văn An, giám đốc Công ty Sao Việt, nói sẽ chuyển "
                "15 triệu đồng cho bà Trần Thị Lan lúc 09:30 ngày 12/08/2026 "
                "tại 25 Lê Lợi bằng xe 30A-12345."
            ),
        },
        {
            "start": 6.0,
            "end": 9.0,
            "speaker": None,
            "text": (
                "Lan cung cấp số điện thoại 0901234567 và tài khoản 0123456789."
            ),
        },
        {
            "start": 9.0,
            "end": 12.0,
            "speaker": "SPEAKER_00",
            "text": "An phủ nhận đã giao 3 hồ sơ cho Lan.",
        },
    ]
    transcript = " ".join(item["text"] for item in segments)
    context = build_transcript_grounded_fallback(transcript, segments, SOURCE)
    assert context is not None
    return context


def test_v3_extracts_explicit_semantics_with_internal_source_binding() -> None:
    context = _rich_context()
    knowledge = context["investigation_knowledge"]

    assert knowledge["provenance"]["model_id"] == (
        "deterministic-transcript-fallback-v3"
    )
    assert len(knowledge["summary_sentences"]) == 3
    assert knowledge["provenance"]["transcript_segment_count"] == 3
    assert {item["segment_index"] for item in knowledge["evidence_spans"]} == {
        0,
        1,
        2,
    }
    evidence_by_segment = {
        item["segment_index"]: item for item in knowledge["evidence_spans"]
    }
    assert evidence_by_segment[0]["speaker_id"] == "SPEAKER_00"
    assert "speaker_id" not in evidence_by_segment[1]
    assert evidence_by_segment[1]["start_seconds"] == 6.0
    assert evidence_by_segment[1]["end_seconds"] == 9.0

    entities = {
        (item["entity_type"], item["value"]): item for item in knowledge["entities"]
    }
    assert entities[("person", "Nguyễn Văn An")]["role"] == "giám đốc"
    assert ("person", "Trần Thị Lan") in entities
    assert ("organization", "Công ty Sao Việt") in entities
    assert ("location", "25 Lê Lợi") in entities
    assert ("time", "09:30") in entities
    assert ("time", "12/08/2026") in entities
    assert ("phone", "0901234567") in entities
    assert ("bank_account", "0123456789") in entities
    assert all(item["verification_status"] == "unverified" for item in entities.values())

    typed_facts = {
        (item["category"], item["statement"]): item
        for item in knowledge["facts"]
        if item["category"] != "key_point"
    }
    assert typed_facts[("exact_value.money", "15 triệu đồng")]["status"] == (
        "planned"
    )
    assert typed_facts[("exact_value.quantity", "3 hồ sơ")]["status"] == (
        "negated"
    )
    assert (
        "exact_value.vehicle_identifier",
        "30A-12345",
    ) in typed_facts
    assert typed_facts[("mention.role", "giám đốc")]["status"] == "reported"

    assert [item["status"] for item in knowledge["events"]] == [
        "planned",
        "reported",
        "negated",
    ]
    assert knowledge["events"][0]["time_text"] == "09:30; 12/08/2026"
    assert knowledge["events"][0]["location"] == "25 Lê Lợi"
    assert all(item.get("time_text") != "00:00" for item in knowledge["events"])
    assert knowledge["timeline"][0]["time"] == "09:30; 12/08/2026"

    relationships = {
        (item["source"], item["label"], item["target"]): item
        for item in knowledge["relationships"]
    }
    assert relationships[
        ("Nguyễn Văn An", "giám đốc", "Công ty Sao Việt")
    ]["status"] == "reported"
    assert relationships[
        ("Nguyễn Văn An", "chuyển", "Trần Thị Lan")
    ]["status"] == "planned"
    assert relationships[("An", "giao", "Lan")]["status"] == "negated"

    assert knowledge["hypotheses"] == []
    assert context["hypotheses"] == []
    assert context["compatibility"]["release_authority"] == (
        "withheld_pending_claim_attestation"
    )
    question_text = {item["question"] for item in context["open_questions"]}
    assert any("0901234567" in item for item in question_text)
    assert any("0123456789" in item for item in question_text)
    assert any("speaker" in item for item in question_text)


def test_v2_scans_every_segment_without_promoting_descriptions_to_events() -> None:
    segments = [
        {
            "start": float(index),
            "end": float(index + 1),
            "speaker": None,
            "text": f"Đoạn mô tả nguồn số {index} không nêu hành động cụ thể.",
        }
        for index in range(12)
    ]
    transcript = " ".join(item["text"] for item in segments)

    context = build_transcript_grounded_fallback(transcript, segments, SOURCE)
    assert context is not None
    knowledge = context["investigation_knowledge"]

    assert len(knowledge["summary_sentences"]) == 12
    assert len([item for item in knowledge["facts"] if item["category"] == "key_point"]) == 12
    assert knowledge["events"] == []
    assert knowledge["timeline"] == []
    assert knowledge["hypotheses"] == []


def test_v2_does_not_reuse_unsafe_person_or_location_substring_cues() -> None:
    segments = [
        {
            "start": 0.0,
            "end": 2.0,
            "speaker": None,
            "text": (
                "Kinh doanh nghiệp vụ và công tác nội bộ không nêu tên cá nhân, "
                "tổ chức hay địa điểm cụ thể."
            ),
        }
    ]
    context = build_transcript_grounded_fallback(segments[0]["text"], segments, SOURCE)
    assert context is not None
    knowledge = context["investigation_knowledge"]

    assert [
        item for item in knowledge["entities"] if item["entity_type"] == "person"
    ] == []
    assert [
        item for item in knowledge["entities"] if item["entity_type"] == "location"
    ] == []
    assert [
        item for item in knowledge["entities"] if item["entity_type"] == "organization"
    ] == []
    assert knowledge["events"] == []


def test_v2_rejects_sentence_starters_as_people_without_identity_cues() -> None:
    segments = [
        {
            "start": 0.0,
            "end": 3.0,
            "speaker": "SPEAKER_00",
            "text": (
                "Thế để chị chuyển khoản. Ngay sau cuộc gọi khách sạn sẽ gửi email. "
                "Số tài khoản sẽ được gửi kèm."
            ),
        }
    ]
    context = build_transcript_grounded_fallback(
        segments[0]["text"],
        segments,
        SOURCE,
    )
    assert context is not None

    people = {
        item["value"]
        for item in context["investigation_knowledge"]["entities"]
        if item["entity_type"] == "person"
    }
    assert people.isdisjoint({"Thế", "Ngay", "Số"})


def test_v2_honorific_does_not_override_single_token_person_stop_words() -> None:
    text = "Chị Số tài khoản sẽ được gửi kèm."
    context = build_transcript_grounded_fallback(
        text,
        [{"speaker": "SPEAKER_00", "text": text}],
        SOURCE,
    )
    assert context is not None

    people = {
        item["value"]
        for item in context["investigation_knowledge"]["entities"]
        if item["entity_type"] == "person"
    }
    assert "Số" not in people


def test_v2_keeps_stop_word_name_when_source_explicitly_self_identifies() -> None:
    text = "Tôi tên là Thế."
    context = build_transcript_grounded_fallback(
        text,
        [{"speaker": "SPEAKER_00", "text": text}],
        SOURCE,
    )
    assert context is not None

    assert any(
        item["entity_type"] == "person" and item["value"] == "Thế"
        for item in context["investigation_knowledge"]["entities"]
    )


def test_v2_preserves_original_segment_index_after_blank_segment() -> None:
    segments = [
        {"start": 0.0, "end": 1.0, "speaker": None, "text": "Mở đầu."},
        {"start": 1.0, "end": 2.0, "speaker": None, "text": ""},
        {
            "start": 2.0,
            "end": 3.0,
            "speaker": "SPEAKER_02",
            "text": "Lan cung cấp số điện thoại 0901234567.",
        },
    ]
    transcript = "Mở đầu. Lan cung cấp số điện thoại 0901234567."

    context = build_transcript_grounded_fallback(transcript, segments, SOURCE)
    assert context is not None
    knowledge = context["investigation_knowledge"]
    phone = next(
        item for item in knowledge["entities"] if item["entity_type"] == "phone"
    )
    evidence_by_id = {
        item["evidence_id"]: item for item in knowledge["evidence_spans"]
    }

    assert knowledge["provenance"]["transcript_segment_count"] == 3
    assert evidence_by_id[phone["evidence_ids"][0]]["segment_index"] == 2


def test_v2_splits_adjacent_asr_windows_at_modality_transition() -> None:
    segments = [
        {
            "start": 227.34,
            "end": 234.34,
            "speaker": "SPEAKER_00",
            "text": (
                "Bữa sáng của một xuất nó là 690.000 nhưng mà đã bao gồm "
                "ở trong giá phòng rồi ạ"
            ),
        },
        {
            "start": 234.34,
            "end": 240.18,
            "speaker": "SPEAKER_00",
            "text": (
                "Vì vậy mình sẽ được sử dụng bữa sáng ở khách sạn với hình "
                "thức là buffet tự chọn món"
            ),
        },
        {
            "start": 240.18,
            "end": 243.28,
            "speaker": "SPEAKER_00",
            "text": "Và mình không phải mất thêm tiền sử dụng mưa sáng đâu ạ",
        },
    ]
    transcript = " ".join(item["text"] for item in segments)

    context = build_transcript_grounded_fallback(transcript, segments, SOURCE)
    assert context is not None
    sentences = context["investigation_knowledge"]["summary_sentences"]

    assert [item["draft_id"] for item in sentences] == [
        "deterministic-source-0",
        "deterministic-source-1",
    ]
    assert sentences[0]["text"] == segments[0]["text"]
    assert sentences[1]["text"] == f'{segments[1]["text"]} {segments[2]["text"]}'


@pytest.mark.parametrize(
    "question",
    [
        "Không biết chị quan tâm đến phòng nào ạ?",
        "Nhưng mà em muốn biết thêm thông tin là mình đi với mục đích gì ạ",
        "Vậy không biết chị muốn thanh toán theo hình thức nào ạ?",
    ],
)
def test_v2_does_not_merge_a_new_question_into_preceding_assertion(
    question: str,
) -> None:
    assertion = "Khách sạn vẫn còn phòng với giá 3 triệu đồng"
    segments = [
        {
            "start": 0.0,
            "end": 2.0,
            "speaker": "SPEAKER_00",
            "text": assertion,
        },
        {
            "start": 2.0,
            "end": 4.0,
            "speaker": "SPEAKER_00",
            "text": question,
        },
    ]

    context = build_transcript_grounded_fallback(
        f"{assertion} {question}",
        segments,
        SOURCE,
    )
    assert context is not None

    assert [
        item["text"]
        for item in context["investigation_knowledge"]["summary_sentences"]
    ] == [assertion, question]


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (
            "Lan sẽ gửi hồ sơ cho Minh",
            "Lan đã gửi biên bản cho Hùng",
        ),
        (
            "Lan không gửi hồ sơ cho Minh",
            "Lan gửi biên bản cho Hùng",
        ),
        (
            "Nếu Lan gửi hồ sơ cho Minh",
            "Hùng nhận biên bản từ Mai",
        ),
        (
            "Lan gửi hồ sơ cho Minh",
            "Hùng gửi biên bản cho Mai",
        ),
        (
            "Lan gửi hồ sơ cho Minh",
            "Lan gửi hồ sơ cho Hùng",
        ),
    ],
)
def test_v2_keeps_distinct_modality_and_role_frames_atomic(
    left: str,
    right: str,
) -> None:
    segments = [
        {
            "start": 0.0,
            "end": 1.0,
            "speaker": "SPEAKER_00",
            "text": left,
        },
        {
            "start": 1.0,
            "end": 2.0,
            "speaker": "SPEAKER_00",
            "text": right,
        },
    ]
    transcript = f"{left} {right}"

    context = build_transcript_grounded_fallback(transcript, segments, SOURCE)
    assert context is not None

    assert [
        item["text"]
        for item in context["investigation_knowledge"]["summary_sentences"]
    ] == [left, right]


def test_v2_still_merges_incomplete_asr_role_fragment() -> None:
    segments = [
        {
            "start": 0.0,
            "end": 1.0,
            "speaker": "SPEAKER_00",
            "text": "Lan sẽ gửi hồ sơ",
        },
        {
            "start": 1.0,
            "end": 2.0,
            "speaker": "SPEAKER_00",
            "text": "cho Minh vào sáng mai",
        },
    ]
    transcript = "Lan sẽ gửi hồ sơ cho Minh vào sáng mai"

    context = build_transcript_grounded_fallback(transcript, segments, SOURCE)
    assert context is not None

    assert [
        item["text"]
        for item in context["investigation_knowledge"]["summary_sentences"]
    ] == [transcript]

    sentence = context["investigation_knowledge"]["summary_sentences"][0]
    evidence_by_id = {
        item["evidence_id"]: item
        for item in context["investigation_knowledge"]["evidence_spans"]
    }
    assert {
        evidence_by_id[evidence_id]["segment_index"]
        for evidence_id in sentence["evidence_ids"]
    } == {0, 1}
    assert {
        evidence_by_id[evidence_id]["speaker_id"]
        for evidence_id in sentence["evidence_ids"]
    } == {"SPEAKER_00"}


def test_v2_does_not_attach_a_nearby_role_without_explicit_relation() -> None:
    text = "Nguyễn Văn An nói sẽ dự họp. Giám đốc phát biểu sau đó."
    context = build_transcript_grounded_fallback(
        text,
        [{"speaker": "SPEAKER_00", "text": text}],
        SOURCE,
    )
    assert context is not None

    person = next(
        item
        for item in context["investigation_knowledge"]["entities"]
        if item["entity_type"] == "person" and item["value"] == "Nguyễn Văn An"
    )
    assert person.get("role") is None
