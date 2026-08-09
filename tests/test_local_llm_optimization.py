from __future__ import annotations

from src.services.summarization import summary_service_v2


def test_investigation_summary_renders_only_attested_projection_without_llm(
    monkeypatch,
):
    forbidden_calls = []
    released = object()
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: forbidden_calls.append("manager"),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "analyze_conversation_context",
        lambda *_args, **_kwargs: forbidden_calls.append("context"),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "render_released_narrative_text",
        lambda value: "Hùng đưa gói hàng cho Lan." if value is released else "",
    )
    monkeypatch.setattr(
        summary_service_v2,
        "released_narrative_metadata",
        lambda value: {
            "run_id": "run-1",
            "source_revision_id": "source-rev-1",
            "sentence_ids": ["sentence-1"],
            "content_sha256": "a" * 64,
        }
        if value is released
        else {},
    )

    result = summary_service_v2.summarize_transcript_v2(
        "Hùng đưa gói hàng cho Lan.",
        model_name="qwen3.5:9b",
        summary_type="investigation",
        include_context=True,
        source_metadata={"source_revision_id": "source-rev-1"},
        released_narrative=released,
    )

    assert result["available"] is True
    assert result["runtime"]["llm_call_count"] == 0
    assert result["runtime"]["summary_generation"] == (
        "attested_deterministic_projection"
    )
    assert result["summary"] == "Hùng đưa gói hàng cho Lan."
    assert forbidden_calls == []


def test_investigation_summary_requires_attestation_before_any_model_call(
    monkeypatch,
):
    forbidden_calls = []
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: forbidden_calls.append("manager"),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "analyze_conversation_context",
        lambda *_args, **_kwargs: forbidden_calls.append("context"),
    )

    result = summary_service_v2.summarize_transcript_v2(
        "Nội dung chưa có narrative release.",
        model_name="qwen3.5:9b",
        summary_type="investigation",
        include_context=True,
    )

    assert result["available"] is False
    assert result["summary"] == ""
    assert result["error"]["code"] == (
        "INVESTIGATION_NARRATIVE_ATTESTATION_REQUIRED"
    )
    assert forbidden_calls == []


def test_investigation_summary_rejects_shape_valid_mapping_spoof(monkeypatch):
    forbidden_calls = []
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: forbidden_calls.append("manager"),
    )

    result = summary_service_v2.summarize_transcript_v2(
        "Nội dung không có evidence đã resolve.",
        model_name="qwen3.5:9b",
        summary_type="investigation",
        include_context=True,
        released_narrative={
            "text": "Minh đã thú nhận và chuyển 50 triệu đồng.",
            "source_revision_id": "forged",
        },
    )

    assert result["available"] is False
    assert result["summary"] == ""
    assert result["error"]["code"] == "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID"
    assert forbidden_calls == []


def test_investigation_summary_rejects_source_revision_mismatch(monkeypatch):
    released = object()
    monkeypatch.setattr(
        summary_service_v2,
        "render_released_narrative_text",
        lambda value: "Dữ kiện đã xác minh." if value is released else "",
    )
    monkeypatch.setattr(
        summary_service_v2,
        "released_narrative_metadata",
        lambda _value: {
            "run_id": "run-1",
            "source_revision_id": "source-rev-other",
            "sentence_ids": ["sentence-1"],
            "content_sha256": "a" * 64,
        },
    )

    result = summary_service_v2.summarize_transcript_v2(
        "Dữ kiện đã xác minh.",
        summary_type="investigation",
        source_metadata={"source_revision_id": "source-rev-expected"},
        released_narrative=released,
    )

    assert result["available"] is False
    assert result["summary"] == ""
    assert result["error"]["code"] == "INVESTIGATION_SOURCE_REVISION_MISMATCH"


def test_legacy_forensic_provider_is_never_called(monkeypatch):
    forbidden_calls = []
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: forbidden_calls.append("manager"),
    )

    result = summary_service_v2.summarize_transcript_v2(
        "Nội dung cần điều tra.",
        summary_type="forensic",
        include_context=False,
    )

    assert result["available"] is False
    assert result["summary"] == ""
    assert result["error"]["code"] == "FORENSIC_LEGACY_PROVIDER_DISABLED"
    assert forbidden_calls == []


def test_forensic_model_alias_fails_closed_without_generic_generation(monkeypatch):
    forbidden_calls = []
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: forbidden_calls.append("manager"),
    )

    result = summary_service_v2.summarize_transcript_v2(
        "Nội dung cần điều tra.",
        model_name="forensic",
        summary_type="detailed",
        include_context=False,
    )

    assert result["available"] is False
    assert result["summary"] == ""
    assert result["summary_type"] == "forensic"
    assert result["error"]["code"] == "FORENSIC_LEGACY_PROVIDER_DISABLED"
    assert forbidden_calls == []
