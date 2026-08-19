from __future__ import annotations

from contextlib import nullcontext

from src.services.summarization import summary_service_v2


class FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def check_availability(self) -> bool:
        return True

    def select_best_model(self, *_args) -> str:
        return "test-model"

    def get_generation_count(self) -> int:
        return len(self.calls)

    def get_last_generation_metadata(self) -> dict:
        return {"model": "test-model", "provider": "fake"}

    def generate(self, prompt: str, **kwargs) -> str:
        self.calls.append((prompt, kwargs))
        return f"Ghi chú tóm tắt từ lần gọi {len(self.calls)}."


def _patch_small_context(monkeypatch, manager: FakeManager) -> None:
    monkeypatch.setattr(summary_service_v2, "get_llm_manager", lambda: manager)
    monkeypatch.setattr(
        summary_service_v2,
        "context_window_tokens_for_provider",
        lambda _provider: 1024,
    )
    monkeypatch.setattr(summary_service_v2, "gpu_lease", lambda *_args: nullcontext())
    monkeypatch.setattr(
        summary_service_v2.settings,
        "UNLOAD_MODELS_AFTER_TASK",
        False,
    )


def test_generic_long_summary_uses_source_complete_llm_hierarchy(monkeypatch) -> None:
    manager = FakeManager()
    _patch_small_context(monkeypatch, manager)
    transcript = " ".join(
        ["BEGIN_GENERIC"]
        + [f"noi-dung-{index}" for index in range(1800)]
        + ["END_GENERIC"]
    )

    result = summary_service_v2.summarize_transcript_v2(
        transcript,
        summary_type="detailed",
        length_mode="auto",
    )

    assert result["available"] is True
    assert result["runtime"]["summary_generation"] == "hierarchical_llm"
    assert result["runtime"]["llm_call_count"] == len(manager.calls)
    assert result["runtime"]["context_budget"]["fits_context_window"] is False
    hierarchy = result["runtime"]["hierarchical"]
    assert hierarchy["source_chunk_count"] > 1
    assert hierarchy["source_coverage_complete"] is True
    map_prompts = [prompt for prompt, _options in manager.calls if "transcript_chunk" in prompt]
    assert any("BEGIN_GENERIC" in prompt for prompt in map_prompts)
    assert any("END_GENERIC" in prompt for prompt in map_prompts)


def test_multi_long_summary_uses_source_complete_llm_hierarchy(monkeypatch) -> None:
    manager = FakeManager()
    _patch_small_context(monkeypatch, manager)
    transcripts = [
        " ".join(["FILE_ONE_BEGIN"] + [f"mot-{index}" for index in range(900)]),
        " ".join([f"hai-{index}" for index in range(900)] + ["FILE_TWO_END"]),
    ]

    result = summary_service_v2.summarize_multi_transcripts_v2(
        transcripts,
        summary_type="detailed",
        length_mode="auto",
    )

    assert result["available"] is True
    assert result["runtime"]["summary_generation"] == "hierarchical_llm"
    assert result["runtime"]["llm_call_count"] == len(manager.calls)
    hierarchy = result["runtime"]["hierarchical"]
    assert hierarchy["source_chunk_count"] > 1
    assert hierarchy["source_coverage_complete"] is True
    map_prompts = [prompt for prompt, _options in manager.calls if "transcript_chunk" in prompt]
    assert any("FILE_ONE_BEGIN" in prompt for prompt in map_prompts)
    assert any("FILE_TWO_END" in prompt for prompt in map_prompts)
