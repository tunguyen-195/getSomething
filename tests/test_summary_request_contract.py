from __future__ import annotations

import asyncio
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api.endpoints import audio, audio_v2
from src.services import audio_service
from src.services import task_service
from src.services.summarization import summary_service_v2
from src.services.summarization.contracts import (
    InvalidSummaryLengthBounds,
    InvestigationSummaryMaxTooSmall,
    SummaryMaximumExceeded,
    UnsupportedSummaryType,
    evaluate_summary_length,
)
from src.worker.tasks import summarize_task


class FakeManager:
    def __init__(self, summary: str) -> None:
        self.summary = summary
        self.generation_count = 0

    def check_availability(self) -> bool:
        return True

    def select_best_model(self, *_args) -> str:
        return "test-model"

    def get_generation_count(self) -> int:
        return self.generation_count

    def generate(self, _prompt: str, **_kwargs) -> str:
        self.generation_count += 1
        return self.summary

    def get_last_generation_metadata(self):
        return {"provider": "fake"}

    def unload_last_model(self) -> bool:
        return True


def _disable_gpu_and_cleanup(monkeypatch, manager: FakeManager) -> None:
    monkeypatch.setattr(
        summary_service_v2,
        "gpu_lease",
        lambda *_args: nullcontext(),
        raising=False,
    )
    monkeypatch.setattr(summary_service_v2, "get_llm_manager", lambda: manager)
    if hasattr(summary_service_v2, "settings"):
        monkeypatch.setattr(summary_service_v2.settings, "UNLOAD_MODELS_AFTER_TASK", False)


def test_direct_summary_rejects_unknown_type_before_gpu_or_model(monkeypatch) -> None:
    touched: list[str] = []
    monkeypatch.setattr(
        summary_service_v2,
        "gpu_lease",
        lambda *_args: touched.append("gpu") or nullcontext(),
        raising=False,
    )
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: touched.append("model"),
    )

    with pytest.raises(UnsupportedSummaryType) as exc_info:
        summary_service_v2.summarize_transcript_v2(
            "Noi dung",
            summary_type="bogus",  # type: ignore[arg-type]
        )

    assert exc_info.value.code == "UNSUPPORTED_SUMMARY_TYPE"
    assert touched == []


def test_direct_summary_rejects_invalid_bounds_before_gpu_or_model(monkeypatch) -> None:
    touched: list[str] = []
    monkeypatch.setattr(
        summary_service_v2,
        "gpu_lease",
        lambda *_args: touched.append("gpu") or nullcontext(),
        raising=False,
    )
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: touched.append("model"),
    )

    with pytest.raises(InvalidSummaryLengthBounds) as exc_info:
        summary_service_v2.summarize_transcript_v2(
            "Noi dung",
            min_length=10,
            max_length=5,
        )

    assert exc_info.value.code == "INVALID_LENGTH_BOUNDS"
    assert touched == []


def test_tiny_investigation_maximum_is_rejected_before_model_work(monkeypatch) -> None:
    touched: list[str] = []
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: touched.append("model"),
    )

    with pytest.raises(InvestigationSummaryMaxTooSmall) as exc_info:
        summary_service_v2.summarize_transcript_v2(
            "Noi dung",
            summary_type="investigation",
            min_length=0,
            max_length=5,
            length_mode="manual",
        )

    assert exc_info.value.code == "INVESTIGATION_MAX_LENGTH_TOO_SMALL"
    assert touched == []


def test_below_minimum_generated_summary_remains_available(monkeypatch) -> None:
    manager = FakeManager("Tom tat du.")
    _disable_gpu_and_cleanup(monkeypatch, manager)

    result = summary_service_v2.summarize_transcript_v2(
        "Noi dung ngan nhung day du.",
        model_name="test-model",
        summary_type="brief",
        include_context=False,
        min_length=20,
        max_length=30,
        length_mode="manual",
    )

    assert result["available"] is True
    assert result["runtime"]["length_contract"]["minimum_met"] is False
    assert result["runtime"]["length_contract"]["maximum_met"] is True
    assert result["runtime"]["length_contract"]["satisfied"] is True


def test_below_minimum_attested_summary_remains_available_without_model(monkeypatch) -> None:
    released = object()
    touched: list[str] = []
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: touched.append("model"),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "render_released_narrative_text",
        lambda value: "Thong tin da duoc doi chieu." if value is released else "",
    )
    monkeypatch.setattr(
        summary_service_v2,
        "released_narrative_metadata",
        lambda _value: {
            "run_id": "run-1",
            "source_revision_id": "source-1",
            "sentence_ids": ["sentence-1"],
            "content_sha256": "a" * 64,
        },
    )

    result = summary_service_v2.summarize_transcript_v2(
        "Noi dung",
        summary_type="investigation",
        min_length=50,
        max_length=100,
        released_narrative=released,
    )

    assert result["available"] is True
    assert result["runtime"]["length_contract"]["minimum_met"] is False
    assert result["runtime"]["llm_call_count"] == 0
    assert touched == []


def test_final_generated_output_above_maximum_fails_closed(monkeypatch) -> None:
    manager = FakeManager("mot hai ba bon nam sau")
    _disable_gpu_and_cleanup(monkeypatch, manager)

    result = summary_service_v2.summarize_transcript_v2(
        "Noi dung",
        model_name="test-model",
        summary_type="brief",
        include_context=False,
        min_length=0,
        max_length=5,
        length_mode="manual",
    )

    assert result["available"] is False
    assert result["summary"] == ""
    assert result["error"]["code"] == "SUMMARY_MAX_LENGTH_EXCEEDED"
    assert result["runtime"]["length_contract"]["maximum_met"] is False


def test_multi_service_rejects_unknown_type_before_gpu_or_model(monkeypatch) -> None:
    touched: list[str] = []
    monkeypatch.setattr(
        summary_service_v2,
        "gpu_lease",
        lambda *_args: touched.append("gpu") or nullcontext(),
        raising=False,
    )
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: touched.append("model"),
    )

    with pytest.raises(UnsupportedSummaryType):
        summary_service_v2.summarize_multi_transcripts_v2(
            ["Noi dung"],
            summary_type="bogus",  # type: ignore[arg-type]
        )

    assert touched == []


def test_workers_reject_unknown_type_before_task_read_or_update(monkeypatch) -> None:
    touched: list[str] = []
    monkeypatch.setattr(summarize_task, "get_task", lambda *_args: touched.append("read"))
    monkeypatch.setattr(summarize_task, "update_task", lambda *_args: touched.append("update"))
    monkeypatch.setattr(
        summarize_task,
        "_llama_server_handoff",
        lambda *_args: touched.append("gpu") or nullcontext(),
        raising=False,
    )

    with pytest.raises(UnsupportedSummaryType):
        summarize_task.summarize_transcript_task.run(
            "task-1",
            summary_type="bogus",  # type: ignore[arg-type]
        )
    with pytest.raises(UnsupportedSummaryType):
        summarize_task.summarize_multi_task.run(
            ["task-1"],
            summary_type="bogus",  # type: ignore[arg-type]
        )

    assert touched == []


def test_worker_propagates_identical_bounds_to_service(monkeypatch) -> None:
    captured: dict[str, object] = {}
    updates: list[dict[str, object]] = []
    monkeypatch.setattr(
        summarize_task,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    monkeypatch.setattr(
        summarize_task,
        "update_task",
        lambda _task_id, patch: updates.append(patch) or True,
    )
    monkeypatch.setattr(
        summarize_task,
        "_llama_server_handoff",
        lambda *_args: nullcontext(),
        raising=False,
    )

    def summarize(**kwargs):
        captured.update(kwargs)
        return {
            "available": True,
            "summary": "Tom tat du.",
            "context": None,
            "model": "test-model",
            "runtime": {
                "length_contract": evaluate_summary_length(
                    "Tom tat du.",
                    min_length=7,
                    max_length=11,
                )
            },
        }

    monkeypatch.setattr(summary_service_v2, "summarize_transcript_v2", summarize)

    result = summarize_task.summarize_transcript_task.run(
        "task-1",
        summary_type="brief",
        min_length=7,
        max_length=11,
    )

    assert result["status"] == "success"
    assert captured["summary_type"] == "brief"
    assert captured["min_length"] == 7
    assert captured["max_length"] == 11
    assert updates[-1]["status"] == "summarized"


def test_legacy_single_rejects_unknown_type_before_context_or_model(monkeypatch) -> None:
    touched: list[str] = []
    monkeypatch.setattr(
        audio_service,
        "OllamaProcessor",
        lambda *_args, **_kwargs: touched.append("context"),
    )

    with pytest.raises(UnsupportedSummaryType):
        audio_service.summarize_transcript(
            "Noi dung",
            summary_type="bogus",  # type: ignore[arg-type]
        )

    assert touched == []


def test_legacy_investigation_summary_routes_to_grounded_writer(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def summarize(**kwargs):
        captured.update(kwargs)
        return {
            "available": True,
            "summary": "Bản tin điều tra liền mạch.",
        }

    monkeypatch.setattr(summary_service_v2, "summarize_transcript_v2", summarize)
    monkeypatch.setattr(
        audio_service,
        "OllamaProcessor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy generic summary path must not run")
        ),
    )

    summary = audio_service.summarize_transcript(
        "Nội dung nguồn.",
        context={"analysis_status": "success"},
        summary_type="investigation",
        min_length=0,
        max_length=200,
    )

    assert summary == "Bản tin điều tra liền mạch."
    assert captured["summary_type"] == "investigation"
    assert captured["allow_evidence_preview"] is True
    assert captured["grounded_context"] == {"analysis_status": "success"}


def test_legacy_finalizer_enforces_max_after_postprocessing(monkeypatch) -> None:
    monkeypatch.setattr(
        audio_service,
        "force_vietnamese_output",
        lambda _text: "mot hai ba bon nam sau",
    )

    with pytest.raises(SummaryMaximumExceeded) as exc_info:
        audio_service._finalize_legacy_summary(
            "mot hai",
            min_length=0,
            max_length=5,
        )

    assert exc_info.value.contract["maximum_met"] is False


def test_legacy_multi_defaults_to_adaptive_without_enforcing_requested_cap(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def summarize(**kwargs):
        captured.update(kwargs)
        return {
            "available": True,
            "summary": "mot hai ba bon nam sau",
        }

    monkeypatch.setattr(
        summary_service_v2,
        "summarize_multi_transcripts_v2",
        summarize,
    )

    result = audio_service.summarize_multi_transcripts(
        ["Noi dung"],
        context={},
        model_name="test-model",
        summary_type="brief",
        min_length=0,
        max_length=5,
    )

    assert result == "mot hai ba bon nam sau"
    assert captured["length_mode"] == "auto"


def test_legacy_multi_failure_exposes_only_typed_code(monkeypatch) -> None:
    secret = "provider-body-must-not-escape"
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_multi_transcripts_v2",
        lambda **_kwargs: {
            "available": False,
            "error": {
                "code": "SUMMARY_GENERATION_FAILED",
                "message": secret,
            },
        },
    )

    with pytest.raises(RuntimeError) as exc_info:
        audio_service.summarize_multi_transcripts(
            ["Noi dung"],
            summary_type="brief",
            min_length=0,
            max_length=1,
        )

    assert str(exc_info.value) == "SUMMARY_GENERATION_FAILED"
    assert secret not in str(exc_info.value)


def test_v2_sync_summary_response_never_exposes_visualization_projection(
    monkeypatch,
) -> None:
    updates: list[dict[str, object]] = []
    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda _task_id: {
            "result": {
                "transcription": "Noi dung hop le.",
                "segments": [],
            }
        },
    )
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
        lambda *_args, **_kwargs: {
            "available": True,
            "summary": "Tom tat hop le.",
            "context": {"analysis_status": "success"},
            "model": "test-model",
            "summary_type": "detailed",
            "runtime": {"length_contract": {"satisfied": True}},
            "visualization_data": {"nodes": ["stale"]},
            "has_visualization": True,
            "released_investigation_run": {"run_id": "stale-run"},
        },
    )

    response = asyncio.run(
        audio_v2.summarize_v2(
            "task-1",
            request=audio_v2.SummaryV2Request(
                model_name="test-model",
                summary_type="detailed",
                include_context=True,
                async_mode=False,
                min_length=0,
                max_length=20,
            ),
            db=object(),
            current_user=SimpleNamespace(id=1),
        )
    )

    assert response["status"] == "summarized"
    assert response["result"]["summary"] == "Tom tat hop le."
    assert "visualization_data" not in response["result"]
    assert "has_visualization" not in response["result"]
    assert "released_investigation_run" not in response["result"]
    assert len(updates) == 1
    persisted = updates[0]
    assert persisted["status"] == "summarized"
    assert persisted["summary"] == "Tom tat hop le."
    assert persisted["model_name"] == "test-model"
    assert persisted["error"] is None
    assert set(persisted["result"]) == {
        "summary",
        "context_analysis",
        "summary_model",
        "summary_type",
        "summary_state",
        "summary_authority",
        "summary_notice",
        "summary_error",
        "summary_preview",
        "summary_runtime",
    }
    assert persisted["result"]["summary"] == "Tom tat hop le."
    assert persisted["result"]["context_analysis"] == {
        "analysis_status": "success"
    }


def test_compatibility_summary_endpoint_propagates_auto_length_mode(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        audio,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung hop le."}},
    )
    monkeypatch.setattr(audio, "update_task", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(audio, "assert_task_access", lambda *_args: None)
    monkeypatch.setattr(audio, "check_rate_limit", lambda *_args: None)

    def summarize(**kwargs):
        captured.update(kwargs)
        return {
            "available": True,
            "summary": "Tom tat hop le.",
            "context": None,
            "model": "test-model",
            "summary_state": "generated",
            "runtime": {"length_contract": {"mode": "auto"}},
        }

    monkeypatch.setattr(summary_service_v2, "summarize_transcript_v2", summarize)

    response = asyncio.run(
        audio.summarize_task(
            "task-1",
            request=audio.SummaryRequest(
                model_name="test-model",
                summary_type="investigation",
                include_context=True,
                async_mode=False,
                min_length=0,
                max_length=20,
                length_mode="auto",
            ),
            db=object(),
            current_user=SimpleNamespace(id=1),
        )
    )

    assert response["status"] == "summarized"
    assert captured["length_mode"] == "auto"


def test_frontend_summary_type_options_use_the_shared_typescript_allowlist() -> None:
    client_source = Path("frontend/src/api/client.ts").read_text(encoding="utf-8")
    dialog_source = Path("frontend/src/components/SummarizeDialog.tsx").read_text(
        encoding="utf-8"
    )

    assert "['brief', 'detailed', 'investigation', 'forensic'] as const" in client_source
    assert "summary_type: SummaryType" in client_source
    assert "DEFAULT_SUMMARY_TYPE: SummaryType = 'detailed'" in client_source
    assert (
        "useState<SummaryType>(DEFAULT_INTERACTIVE_SUMMARY_TYPE)"
        in dialog_source
    )
    assert "summary_type: string" not in dialog_source
