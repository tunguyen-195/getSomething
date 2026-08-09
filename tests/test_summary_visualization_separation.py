import copy
import json
from contextlib import nullcontext

from src.services.summarization import summary_service_v2
from src.services.task_service import _deep_merge


class _FakeLlmManager:
    def __init__(self) -> None:
        self.generation_count = 0

    def check_availability(self) -> bool:
        return True

    def select_best_model(self, *_args) -> str:
        return "test-model"

    def get_generation_count(self) -> int:
        return self.generation_count

    def generate(self, *_args, **_kwargs) -> str:
        self.generation_count += 1
        return "Tom tat co bang chung ro rang."

    def get_last_generation_metadata(self) -> dict:
        return {"model": "test-model"}


def test_summary_service_never_generates_visualization(monkeypatch) -> None:
    manager = _FakeLlmManager()
    monkeypatch.setattr(summary_service_v2, "get_llm_manager", lambda: manager)
    if hasattr(summary_service_v2, "gpu_lease"):
        monkeypatch.setattr(
            summary_service_v2,
            "gpu_lease",
            lambda *_args: nullcontext(),
        )
    if hasattr(summary_service_v2, "settings"):
        monkeypatch.setattr(
            summary_service_v2.settings,
            "UNLOAD_MODELS_AFTER_TASK",
            False,
        )

    result = summary_service_v2.summarize_transcript_v2(
        transcript="Noi dung nguon co bang chung.",
        summary_type="detailed",
        include_context=False,
        min_length=1,
        max_length=20,
    )

    assert result["available"] is True
    assert manager.generation_count == 1
    assert "visualization_data" not in result
    assert "has_visualization" not in result


def test_summary_worker_preserves_visualization_and_clears_stale_context(
    monkeypatch,
) -> None:
    from src.worker.tasks import summarize_task

    released_visualization = {
        "schema_version": "investigation-visualization-v1",
        "authority": "released_investigation_run",
        "content_hash": "a" * 64,
        "run_id": "run-1",
        "source_revision_id": "source-1",
    }
    task = {
        "result": {
            "transcription": "Noi dung nguon co bang chung.",
            "context_analysis": {"stale": True},
            "visualization_data": released_visualization,
            "has_visualization": True,
        }
    }
    stored_result = copy.deepcopy(task["result"])
    visualization_before = json.dumps(
        stored_result["visualization_data"],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    updates: list[dict] = []
    if hasattr(summarize_task, "settings"):
        monkeypatch.setattr(
            summarize_task.settings,
            "LOCAL_LLM_PROVIDER",
            "ollama",
        )
    monkeypatch.setattr(summarize_task, "get_task", lambda _task_id: task)

    def apply_update(_task_id: str, payload: dict) -> bool:
        updates.append(copy.deepcopy(payload))
        result_patch = payload.get("result")
        if isinstance(result_patch, dict):
            merged = _deep_merge(stored_result, result_patch)
            stored_result.clear()
            stored_result.update(merged)
        return True

    monkeypatch.setattr(summarize_task, "update_task", apply_update)
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: {
            "available": True,
            "summary": "Tom tat moi.",
            "context": None,
            "model": "test-model",
            "runtime": {"visualization_projection": "not_requested"},
        },
    )

    result = summarize_task.summarize_transcript_task.run(
        "task-summary-only",
        include_context=False,
    )

    assert result["status"] == "success"
    persisted = next(
        update for update in updates if update.get("status") == "summarized"
    )
    assert set(persisted["result"]) == {
        "summary",
        "context_analysis",
        "summary_model",
        "summary_type",
        "summary_runtime",
    }
    assert persisted["result"]["context_analysis"] is None
    assert "visualization_data" not in persisted["result"]
    assert "has_visualization" not in persisted["result"]
    visualization_after = json.dumps(
        stored_result["visualization_data"],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert visualization_after == visualization_before
    assert stored_result["has_visualization"] is True
    assert stored_result["context_analysis"] is None
