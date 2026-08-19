from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from src.api.endpoints import audio, audio_v2
from src.services import task_service
from src.services.summarization import summary_service_v2
from src.services.summarization.context_service import (
    build_transcript_grounded_fallback,
)
from src.services.summarization.investigation_preview import (
    TranscriptEvidencePreviewError,
    build_transcript_evidence_preview,
    coerce_public_preview_payload,
    sanitize_legacy_preview_text,
    validate_current_grounded_context,
)
from src.worker.tasks import summarize_task


TRANSCRIPT = (
    "Minh nói sẽ chuyển 15 triệu đồng cho Lan. "
    "Lan yêu cầu gửi vào tài khoản 0123456789."
)
SEGMENTS = [
    {
        "start": 0.0,
        "end": 3.0,
        "speaker": "SPEAKER_00",
        "text": "Minh nói sẽ chuyển 15 triệu đồng cho Lan.",
    },
    {
        "start": 3.0,
        "end": 6.0,
        "speaker": "SPEAKER_01",
        "text": "Lan yêu cầu gửi vào tài khoản 0123456789.",
    },
]
SOURCE = {
    "task_id": "task-investigation",
    "case_id": "case-1",
    "file_name": "evidence.wav",
    "audio_id": 9,
    "audio_sha256": "a" * 64,
}


def _legacy_preview_payload() -> dict:
    return {
        "schema_version": "transcript-evidence-preview-v1",
        "authority": "transcript_evidence_only",
        "source": {"task_id": SOURCE["task_id"]},
        "evidence": [{"start_seconds": 0, "speaker_id": "SPEAKER_00"}],
        "lines": [{"evidence_ref": "ev-1"}],
        "content_sha256": "a" * 64,
        "text": (
            "Bản xem trước evidence transcript - chưa phải tóm tắt điều tra đã phát hành.\n"
            '[offset âm thanh: 00:00-00:16; người nói: SPEAKER_00; đoạn: 0] '
            'Nguồn ghi nhận: "Nội dung cần giữ lại."'
        ),
    }


def _grounded_context(transcript: str = TRANSCRIPT, segments=None) -> dict:
    context = build_transcript_grounded_fallback(
        transcript,
        SEGMENTS if segments is None else segments,
        SOURCE,
    )
    assert context is not None
    return context


def _disable_summary_gpu(monkeypatch) -> None:
    monkeypatch.setattr(
        summary_service_v2,
        "gpu_lease",
        lambda *_args: nullcontext(),
        raising=False,
    )
    monkeypatch.setattr(
        summary_service_v2.settings,
        "UNLOAD_MODELS_AFTER_TASK",
        False,
    )


class _FakeWriterManager:
    def __init__(self) -> None:
        self.generation_count = 0

    def check_availability(self):
        return True

    def generate(self, prompt, *_args, **_kwargs):
        self.generation_count += 1
        assert "<transcript>" in prompt
        assert "</transcript>" in prompt
        assert "<host_sentence_plan>" not in prompt
        return (
            "Qua nội dung nghe được, Minh nói sẽ chuyển 15 triệu đồng cho Lan; "
            "Lan yêu cầu gửi vào tài khoản 0123456789."
        )

    def get_generation_count(self):
        return self.generation_count

    def get_last_generation_metadata(self):
        return {"model": "test-officer-writer"}


def _patch_writer(monkeypatch) -> None:
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: _FakeWriterManager(),
    )


def _accepted_summary_result() -> dict:
    summary = (
        "Qua nội dung nghe được, Minh nói sẽ chuyển 15 triệu đồng cho Lan; "
        "Lan yêu cầu gửi vào tài khoản 0123456789."
    )
    return {
        "available": True,
        "summary": summary,
        "context": _grounded_context(),
        "model": "test-officer-writer",
        "summary_type": "investigation",
        "summary_state": "source_grounded_narrative",
        "summary_authority": {
            "kind": "grounded_synthesis_pending_human_review",
            "release_status": "pending_human_review",
            "world_facts_released": False,
        },
        "summary_notice": {
            "code": "INVESTIGATION_SOURCE_NARRATIVE_READY",
            "message": "Bản tin đã sẵn sàng để kiểm tra.",
        },
        "summary_preview": {
            "schema_version": "preliminary-bulletin-v2",
            "artifact_type": "preliminary_bulletin",
            "world_facts_released": False,
            "projection_mode": "grounded_synthesis",
            "completeness": "complete",
            "text": summary,
        },
        "runtime": {"writer_status": "accepted"},
    }


def test_source_grounded_writer_returns_reader_facing_report_body(
    monkeypatch,
) -> None:
    _disable_summary_gpu(monkeypatch)
    _patch_writer(monkeypatch)
    result = summary_service_v2.summarize_transcript_v2(
        TRANSCRIPT,
        summary_type="investigation",
        include_context=False,
        min_length=0,
        max_length=160,
        transcript_segments=SEGMENTS,
        source_metadata=SOURCE,
        grounded_context=_grounded_context(),
        allow_evidence_preview=True,
    )

    assert result["available"] is True
    assert result["summary"].startswith("Qua nội dung nghe được")
    assert result["summary_state"] == "generated"
    assert result["context"] is None
    assert result["runtime"]["summary_generation"] == "single_prompt_llm"
    assert result["runtime"]["llm_call_count"] == 1

    internal_preview = build_transcript_evidence_preview(
        context_analysis=_grounded_context(),
        transcript=TRANSCRIPT,
        segments=SEGMENTS,
        source_metadata=SOURCE,
        max_words=160,
    )
    assert internal_preview.evidence[0].start_seconds == 0.0
    assert internal_preview.evidence[0].end_seconds == 3.0
    assert internal_preview.evidence[0].speaker_id == "SPEAKER_00"
    assert internal_preview.lines[0].evidence_refs
    assert internal_preview.lines[0].evidence_refs[0] in {
        item.evidence_id for item in internal_preview.evidence
    }


def test_investigation_bypasses_writer_completeness_pipeline(monkeypatch) -> None:
    _disable_summary_gpu(monkeypatch)
    summary = (
        "Qua nội dung nghe được, Minh nói sẽ chuyển 15 triệu đồng cho Lan."
    )
    context = _grounded_context()
    context["summary"] = summary

    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: _FakeWriterManager(),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "synthesize_bulletin_context",
        lambda *_args, **_kwargs: SimpleNamespace(
            context_analysis=context,
            coverage=SimpleNamespace(
                coverage_status="partial",
                model_dump=lambda **_kwargs: {
                    "coverage_status": "partial",
                    "demoted_source_items": 1,
                },
            ),
            attempt_count=1,
            repair_applied=False,
            deterministic_repair_applied=False,
            sentence_delta_repair_applied=False,
            token_budgets=(),
        ),
    )

    result = summary_service_v2.summarize_transcript_v2(
        TRANSCRIPT,
        summary_type="investigation",
        include_context=False,
        min_length=0,
        max_length=160,
        transcript_segments=SEGMENTS,
        source_metadata=SOURCE,
        grounded_context=_grounded_context(),
        allow_evidence_preview=True,
    )

    assert result["available"] is True
    assert result["available"] is True
    assert "summary_preview" not in result
    assert "coverage" not in result["runtime"]


def test_investigation_scenario_does_not_add_a_writer_gate(monkeypatch) -> None:
    _disable_summary_gpu(monkeypatch)
    _patch_writer(monkeypatch)
    result = summary_service_v2.summarize_transcript_v2(
        TRANSCRIPT,
        summary_type="investigation",
        include_context=True,
        min_length=0,
        max_length=160,
        transcript_segments=SEGMENTS,
        source_metadata=SOURCE,
        grounded_context=_grounded_context(),
        investigation_scenario="financial_asset",
        allow_evidence_preview=True,
    )

    assert result["runtime"]["summary_generation"] == "single_prompt_llm"
    assert result["summary_state"] == "generated"
    assert result["summary"].startswith("Qua nội dung nghe được")
    assert result["runtime"]["scenario_profile"] == "llm_inferred_from_transcript"


def test_public_preview_redacts_stale_internal_payload_and_legacy_metadata() -> None:
    public = coerce_public_preview_payload(_legacy_preview_payload())

    assert public == {
        "schema_version": "preliminary-bulletin-v2",
        "artifact_type": "preliminary_bulletin",
        "world_facts_released": False,
        "projection_mode": "legacy_sanitized",
        "completeness": "unknown",
        "text": "Nội dung cần giữ lại.",
    }
    assert "offset âm thanh" not in public["text"].lower()
    assert "speaker" not in str(public).lower()
    assert "evidence" not in public


def test_legacy_preview_sanitizer_handles_multiple_excerpts_on_one_line() -> None:
    text = (
        '### **[offset-am-thanh: 00:00-00:16; người nói: A]** '
        'Nguồn ghi nhận: "Đoạn một" '
        '[audio offset: 00:16-00:30; speaker: B] Source: “Đoạn hai”'
    )

    assert sanitize_legacy_preview_text(text) == "Đoạn một\nĐoạn hai"


def test_summary_preview_patch_replaces_stale_internal_keys() -> None:
    public_preview = {
        "schema_version": "preliminary-bulletin-v2",
        "artifact_type": "preliminary_bulletin",
        "world_facts_released": False,
        "projection_mode": "grounded_bulletin",
        "completeness": "complete",
        "text": "Nội dung sạch.",
    }

    merged = task_service._deep_merge(
        {"summary_preview": _legacy_preview_payload()},
        {"summary_preview": public_preview},
        bind_visualization=False,
    )

    assert merged["summary_preview"] == public_preview
    assert "evidence" not in merged["summary_preview"]
    assert "source" not in merged["summary_preview"]


def test_preview_rejects_paraphrase_even_when_evidence_id_is_reused() -> None:
    context = _grounded_context()
    knowledge = context["investigation_knowledge"]
    knowledge["summary_sentences"][0]["text"] = "Minh đã chuyển tiền cho Lan."
    context["summary_sentences"][0]["text"] = "Minh đã chuyển tiền cho Lan."
    context["summary"] = "Minh đã chuyển tiền cho Lan."

    with pytest.raises(
        TranscriptEvidencePreviewError,
        match="Grounded context failed",
    ):
        build_transcript_evidence_preview(
            context_analysis=context,
            transcript=TRANSCRIPT,
            segments=SEGMENTS,
            source_metadata=SOURCE,
            max_words=160,
        )


def test_stale_context_does_not_block_summary_of_current_transcript(monkeypatch) -> None:
    _disable_summary_gpu(monkeypatch)
    stale_context = _grounded_context()
    manager = _FakeWriterManager()
    monkeypatch.setattr(summary_service_v2, "get_llm_manager", lambda: manager)
    changed_transcript = TRANSCRIPT.replace("15 triệu", "50 triệu")
    changed_segments = [dict(item) for item in SEGMENTS]
    changed_segments[0]["text"] = changed_segments[0]["text"].replace(
        "15 triệu",
        "50 triệu",
    )

    result = summary_service_v2.summarize_transcript_v2(
        changed_transcript,
        summary_type="investigation",
        include_context=False,
        min_length=0,
        max_length=160,
        transcript_segments=changed_segments,
        source_metadata=SOURCE,
        grounded_context=stale_context,
        allow_evidence_preview=True,
    )

    assert result["available"] is True
    assert result["summary_state"] == "generated"
    assert result["context"] is None


def test_worker_persists_grounded_preview_without_marking_task_failed(
    monkeypatch,
) -> None:
    _disable_summary_gpu(monkeypatch)
    updates: list[dict] = []
    task_payload = {
        "id": SOURCE["task_id"],
        "case_id": SOURCE["case_id"],
        "filename": SOURCE["file_name"],
        "result": {
            "transcription": TRANSCRIPT,
            "segments": SEGMENTS,
            "context_analysis": _grounded_context(),
            "audio_id": SOURCE["audio_id"],
            "audio_sha256": SOURCE["audio_sha256"],
        },
    }
    monkeypatch.setattr(summarize_task, "get_task", lambda _task_id: task_payload)
    monkeypatch.setattr(
        summarize_task,
        "update_task",
        lambda _task_id, patch: updates.append(patch) or True,
    )
    monkeypatch.setattr(
        summarize_task,
        "_llama_server_handoff",
        lambda *_args: nullcontext(),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: _accepted_summary_result(),
    )

    response = summarize_task.summarize_transcript_task.run(
        SOURCE["task_id"],
        summary_type="investigation",
        include_context=False,
        min_length=0,
        max_length=160,
    )

    assert response["status"] == "success"
    assert updates[-1]["status"] == "summarized"
    assert updates[-1]["error"] is None
    assert updates[-1]["result"]["summary"].startswith("Qua nội dung nghe được")
    assert updates[-1]["result"]["summary_state"] == "source_grounded_narrative"
    assert updates[-1]["result"]["summary_preview"]["world_facts_released"] is False
    assert not any(update.get("status") == "failed" for update in updates)


def test_sync_endpoint_uses_same_grounded_preview_state(monkeypatch) -> None:
    _disable_summary_gpu(monkeypatch)
    updates: list[dict] = []
    task_payload = {
        "id": SOURCE["task_id"],
        "case_id": SOURCE["case_id"],
        "filename": SOURCE["file_name"],
        "result": {
            "transcription": TRANSCRIPT,
            "segments": SEGMENTS,
            "context_analysis": _grounded_context(),
            "audio_id": SOURCE["audio_id"],
            "audio_sha256": SOURCE["audio_sha256"],
        },
    }
    monkeypatch.setattr(task_service, "get_task", lambda _task_id: task_payload)
    monkeypatch.setattr(
        task_service,
        "update_task",
        lambda _task_id, patch: updates.append(patch) or True,
    )
    monkeypatch.setattr(audio_v2, "assert_task_access", lambda *_args: None)
    monkeypatch.setattr(audio_v2, "check_rate_limit", lambda *_args: None)
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda *_args, **_kwargs: _accepted_summary_result(),
    )

    response = asyncio.run(
        audio_v2.summarize_v2(
            SOURCE["task_id"],
            request=audio_v2.SummaryV2Request(
                model_name=None,
                summary_type="investigation",
                include_context=False,
                async_mode=False,
                min_length=0,
                max_length=160,
            ),
            db=object(),
            current_user=SimpleNamespace(id=1),
        )
    )

    assert response["status"] == "summarized"
    assert response["result"]["summary_state"] == "source_grounded_narrative"
    assert response["result"]["summary"].startswith("Qua nội dung nghe được")
    assert updates[-1]["status"] == "summarized"
    assert updates[-1]["result"]["summary_state"] == "source_grounded_narrative"


def test_preview_reports_partial_coverage_instead_of_claiming_full_source() -> None:
    long_segments = [
        {
            "start": float(index),
            "end": float(index + 1),
            "speaker": f"SPEAKER_{index % 2:02d}",
            "text": f"Đoạn evidence số {index} có nội dung cần rà soát.",
        }
        for index in range(12)
    ]
    transcript = " ".join(item["text"] for item in long_segments)
    context = build_transcript_grounded_fallback(transcript, long_segments, SOURCE)
    assert context is not None

    preview = build_transcript_evidence_preview(
        context_analysis=context,
        transcript=transcript,
        segments=long_segments,
        source_metadata=SOURCE,
        max_words=90,
    )

    assert preview.coverage.status == "partial"
    assert preview.coverage.total_source_units == 12
    assert preview.coverage.omitted_source_units > 0
    assert preview.coverage.selected_source_units < 12


def test_audio_list_exposes_preview_without_releasing_summary(monkeypatch) -> None:
    _disable_summary_gpu(monkeypatch)
    preview_result = _accepted_summary_result()
    stored_result = {
        "transcription": TRANSCRIPT,
        "segments": SEGMENTS,
        "summary": (
            '[offset âm thanh: 00:00-00:16; người nói: SPEAKER_00] '
            'Nguồn ghi nhận: "Nội dung summary cũ."'
        ),
        "summary_state": preview_result["summary_state"],
        "summary_authority": preview_result["summary_authority"],
        "summary_notice": preview_result["summary_notice"],
        "summary_preview": _legacy_preview_payload(),
        "summary_runtime": preview_result["runtime"],
    }
    task = SimpleNamespace(status="summarized", result=stored_result)
    audio_file = SimpleNamespace(
        id=SOURCE["audio_id"],
        task_id=SOURCE["task_id"],
        task=task,
        filename=SOURCE["file_name"],
        case_id=1,
        status="summarized",
        duration=6.0,
        created_at=None,
        uploaded_at=None,
    )

    class FakeAudioQuery:
        def options(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def all(self):
            return [audio_file]

    monkeypatch.setattr(audio, "assert_case_access", lambda *_args: None)
    response = audio.read_audio(
        case_id=1,
        db=SimpleNamespace(query=lambda _model: FakeAudioQuery()),
        current_user=SimpleNamespace(id=1),
    )

    assert len(response) == 1
    item = response[0]
    assert item["status"] == "summarized"
    assert item["summary"] == "Nội dung summary cũ."
    assert item["summary_state"] == "source_grounded_narrative"
    assert item["summary_notice"]["code"] == "INVESTIGATION_SOURCE_NARRATIVE_READY"
    assert item["summary_preview"]["artifact_type"] == "preliminary_bulletin"
    assert item["summary_preview"]["world_facts_released"] is False
    assert set(item["summary_preview"]) == {
        "schema_version",
        "artifact_type",
        "world_facts_released",
        "projection_mode",
        "completeness",
        "text",
    }
    assert item["summary_preview"]["text"] == "Nội dung cần giữ lại."


def test_task_detail_redacts_stale_preview_in_top_level_and_nested_result(
    monkeypatch,
) -> None:
    task_payload = {
        "id": SOURCE["task_id"],
        "filename": SOURCE["file_name"],
        "status": "summarized",
        "case_id": SOURCE["case_id"],
        "result": {
            "transcription": TRANSCRIPT,
            "summary_state": "grounded_transcript_only",
            "summary": (
                '[offset âm thanh: 00:00-00:16; người nói: A] '
                'Nguồn ghi nhận: "Nội dung summary cũ."'
            ),
            "summary_preview": _legacy_preview_payload(),
        },
    }
    monkeypatch.setattr(audio, "get_task", lambda _task_id: task_payload)
    monkeypatch.setattr(audio, "assert_task_access", lambda *_args: None)

    response = asyncio.run(
        audio.get_task_by_id(
            SOURCE["task_id"],
            db=object(),
            current_user=SimpleNamespace(id=1),
        )
    )

    assert response["summary"] == "Nội dung summary cũ."
    assert response["summary_preview"]["text"] == "Nội dung cần giữ lại."
    assert set(response["summary_preview"]) == {
        "schema_version",
        "artifact_type",
        "world_facts_released",
        "projection_mode",
        "completeness",
        "text",
    }
    assert response["result"]["summary"] == "Nội dung summary cũ."
    assert response["result"]["summary_preview"] == response["summary_preview"]


def test_v2_status_redacts_stale_preview_in_top_level_and_nested_result(
    monkeypatch,
) -> None:
    result = {
        "transcription": TRANSCRIPT,
        "summary_state": "grounded_transcript_only",
        "summary": (
            '[audio_offset: 00:00-00:16; speaker: A] '
            'Source: "Legacy summary content."'
        ),
        "summary_preview": _legacy_preview_payload(),
    }
    authorized_task = SimpleNamespace(
        id=SOURCE["task_id"],
        result=result,
        status="summarized",
        error=None,
        filename=SOURCE["file_name"],
        created_at=None,
        updated_at=None,
    )

    class FakeAudioQuery:
        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def first(self):
            return None

    fake_db = SimpleNamespace(query=lambda _model: FakeAudioQuery())
    monkeypatch.setattr(audio_v2, "assert_task_access", lambda *_args: authorized_task)
    monkeypatch.setattr(task_service, "get_task", lambda _task_id, db=None: {
        "id": SOURCE["task_id"],
        "status": "summarized",
        "filename": SOURCE["file_name"],
        "result": result,
    })

    response = asyncio.run(
        audio_v2.get_status_v2(
            SOURCE["task_id"],
            include_result=True,
            db=fake_db,
            current_user=SimpleNamespace(id=1),
        )
    )

    assert response["summary"] == "Legacy summary content."
    assert response["summary_preview"]["text"] == "Nội dung cần giữ lại."
    assert response["result"]["summary"] == "Legacy summary content."
    assert response["result"]["summary_preview"] == response["summary_preview"]


@pytest.mark.parametrize(
    "stale_model_id",
    ["deterministic-transcript-fallback-v1", "deterministic-transcript-fallback-v2"],
)
def test_stale_deterministic_context_is_ignored(monkeypatch, stale_model_id) -> None:
    _disable_summary_gpu(monkeypatch)
    _patch_writer(monkeypatch)
    stale_context = _grounded_context()
    stale_context["investigation_knowledge"]["provenance"]["model_id"] = (
        stale_model_id
    )
    calls = 0
    original_builder = summary_service_v2.build_transcript_grounded_fallback

    def tracked_builder(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(
        summary_service_v2,
        "build_transcript_grounded_fallback",
        tracked_builder,
    )

    result = summary_service_v2.summarize_transcript_v2(
        TRANSCRIPT,
        summary_type="investigation",
        include_context=False,
        min_length=0,
        max_length=160,
        transcript_segments=SEGMENTS,
        source_metadata=SOURCE,
        grounded_context=stale_context,
        allow_evidence_preview=True,
    )

    assert calls == 0
    assert result["available"] is True
    assert result["context"] is None
    assert result["runtime"]["summary_generation"] == "single_prompt_llm"


def test_non_stale_cached_context_is_not_used(monkeypatch) -> None:
    _disable_summary_gpu(monkeypatch)
    _patch_writer(monkeypatch)
    cached_context = _grounded_context()
    cached_context["investigation_knowledge"]["provenance"]["model_id"] = (
        "trusted-provider-model"
    )

    def unexpected_rebuild(*_args, **_kwargs):
        raise AssertionError("non-stale cached context must not be rebuilt")

    monkeypatch.setattr(
        summary_service_v2,
        "build_transcript_grounded_fallback",
        unexpected_rebuild,
    )
    monkeypatch.setattr(
        summary_service_v2,
        "analyze_conversation_context",
        unexpected_rebuild,
    )

    result = summary_service_v2.summarize_transcript_v2(
        TRANSCRIPT,
        summary_type="investigation",
        include_context=False,
        min_length=0,
        max_length=160,
        transcript_segments=SEGMENTS,
        source_metadata=SOURCE,
        grounded_context=cached_context,
        allow_evidence_preview=True,
    )

    assert result["available"] is True
    assert result["context"] is None
    assert result["runtime"]["summary_generation"] == "single_prompt_llm"


def test_summary_does_not_require_segment_selection(
    monkeypatch,
) -> None:
    _disable_summary_gpu(monkeypatch)
    _patch_writer(monkeypatch)
    stale_segments = [
        {**SEGMENTS[0], "speaker": None},
        {**SEGMENTS[1], "speaker": None},
    ]

    result = summary_service_v2.summarize_transcript_v2(
        TRANSCRIPT,
        summary_type="investigation",
        include_context=False,
        min_length=0,
        max_length=160,
        transcript_segments=stale_segments,
        source_metadata={
            **SOURCE,
            "current_transcript_segments": SEGMENTS,
        },
        allow_evidence_preview=True,
    )

    assert result["available"] is True
    assert result["context"] is None
    assert result["runtime"]["summary_generation"] == "single_prompt_llm"


def test_sparse_trusted_cached_context_is_ignored(
    monkeypatch,
) -> None:
    _disable_summary_gpu(monkeypatch)
    _patch_writer(monkeypatch)
    cached_context = _grounded_context()
    cached_context["investigation_knowledge"]["provenance"]["model_id"] = (
        "trusted-provider-model"
    )
    first_sentence = cached_context["summary_sentences"][0]
    cached_context["summary_sentences"] = [first_sentence]
    cached_context["investigation_knowledge"]["summary_sentences"] = [first_sentence]
    cached_context["summary"] = first_sentence["text"]

    result = summary_service_v2.summarize_transcript_v2(
        TRANSCRIPT,
        summary_type="investigation",
        include_context=False,
        min_length=0,
        max_length=160,
        transcript_segments=SEGMENTS,
        source_metadata=SOURCE,
        grounded_context=cached_context,
        allow_evidence_preview=True,
    )

    assert result["available"] is True
    assert result["context"] is None
    assert result["runtime"]["summary_generation"] == "single_prompt_llm"


def test_invalid_cached_context_is_ignored(monkeypatch) -> None:
    _disable_summary_gpu(monkeypatch)
    _patch_writer(monkeypatch)
    invalid_context = _grounded_context()
    invalid_context.pop("investigation_knowledge")
    calls = 0
    original_builder = summary_service_v2.build_transcript_grounded_fallback

    def tracked_builder(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(
        summary_service_v2,
        "build_transcript_grounded_fallback",
        tracked_builder,
    )
    result = summary_service_v2.summarize_transcript_v2(
        TRANSCRIPT,
        summary_type="investigation",
        include_context=False,
        min_length=0,
        max_length=160,
        transcript_segments=SEGMENTS,
        source_metadata=SOURCE,
        grounded_context=invalid_context,
        allow_evidence_preview=True,
    )

    assert calls == 0
    assert result["available"] is True
    assert result["context"] is None
    assert result["runtime"]["summary_generation"] == "single_prompt_llm"


@pytest.mark.parametrize(
    ("segments", "source_metadata", "error_code"),
    [
        (
            [
                {**SEGMENTS[0], "speaker": "SPEAKER_09"},
                SEGMENTS[1],
            ],
            SOURCE,
            "INVESTIGATION_PREVIEW_STALE_SEGMENTS",
        ),
        (
            [
                {**SEGMENTS[0], "start": 0.25},
                SEGMENTS[1],
            ],
            SOURCE,
            "INVESTIGATION_PREVIEW_STALE_SEGMENTS",
        ),
        (
            SEGMENTS,
            {**SOURCE, "diarization_status": "degraded"},
            "INVESTIGATION_PREVIEW_STALE_DIARIZATION",
        ),
    ],
)
def test_cached_context_is_stale_when_only_participant_provenance_changes(
    segments,
    source_metadata,
    error_code,
) -> None:
    context = _grounded_context()

    with pytest.raises(TranscriptEvidencePreviewError) as exc_info:
        validate_current_grounded_context(
            context_analysis=context,
            transcript=TRANSCRIPT,
            segments=segments,
            source_metadata=source_metadata,
        )

    assert exc_info.value.code == error_code
