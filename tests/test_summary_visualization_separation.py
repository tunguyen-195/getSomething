import asyncio
import copy
import json
from contextlib import nullcontext
from types import SimpleNamespace

from src.services.summarization import summary_service_v2
from src.services.summarization.contracts import SummaryRequest
from src.services.task_service import _deep_merge


_PROJECTION_FIELDS = {
    "visualization_data",
    "has_visualization",
    "released_investigation_run",
}


def _released_projection_state(run_id: str = "run-1") -> dict:
    return {
        "released_investigation_run": {
            "schema_version": "investigation-run-v1.0",
            "run_status": "success",
            "run_id": run_id,
            "source_revision_id": "source-1",
            "release_subject_sha256": "b" * 64,
        },
        "visualization_data": {
            "schema_version": "investigation-visualization-v1",
            "authority": "released_investigation_run",
            "content_hash": "a" * 64,
            "run_id": run_id,
            "source_revision_id": "source-1",
        },
        "has_visualization": True,
    }


def _apply_result_patch(stored_result: dict, payload: dict) -> None:
    result_patch = payload.get("result")
    if isinstance(result_patch, dict):
        merged = _deep_merge(stored_result, result_patch)
        stored_result.clear()
        stored_result.update(merged)


def _assert_projection_free_result_patch(payload: dict) -> None:
    result_patch = payload.get("result")
    assert isinstance(result_patch, dict)
    assert _PROJECTION_FIELDS.isdisjoint(result_patch)


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


def test_v1_summarize_endpoint_persists_only_summary_context_patch(
    monkeypatch,
) -> None:
    from src.api.endpoints import audio as audio_v1

    task_result = {
        "transcription": "Noi dung nguon co bang chung.",
        "context_analysis": {"stale": True},
        **_released_projection_state("run-task-snapshot"),
    }
    stored_result = copy.deepcopy(task_result)
    stored_result.update(_released_projection_state("run-concurrent"))
    task = {
        "transcript": task_result["transcription"],
        "context_analysis": task_result["context_analysis"],
        "result": task_result,
    }
    projection_before = copy.deepcopy(
        {key: stored_result[key] for key in _PROJECTION_FIELDS}
    )
    updates: list[dict] = []

    monkeypatch.setattr(audio_v1, "get_task", lambda _task_id: task)
    monkeypatch.setattr(audio_v1, "assert_task_access", lambda *_args: None)
    monkeypatch.setattr(audio_v1, "check_rate_limit", lambda *_args: None)

    def apply_update(_task_id: str, payload: dict) -> bool:
        updates.append(copy.deepcopy(payload))
        _apply_result_patch(stored_result, payload)
        return True

    monkeypatch.setattr(audio_v1, "update_task", apply_update)
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: {
            "available": True,
            "summary": "Tom tat moi.",
            "context": {"analysis_status": "success"},
            "model": "test-model",
            "runtime": {"length_contract": {"maximum_met": True}},
            "visualization_data": {"forged": True},
            "has_visualization": True,
            "released_investigation_run": {"run_id": "forged"},
        },
    )

    response = asyncio.run(
        audio_v1.summarize_task(
            "task-v1-summary",
            request=SummaryRequest(
                model_name="test-model",
                summary_type="detailed",
                include_context=True,
                async_mode=False,
                min_length=1,
                max_length=20,
            ),
            db=object(),
            current_user=SimpleNamespace(id=1),
        )
    )

    persisted = updates[-1]
    _assert_projection_free_result_patch(persisted)
    assert set(persisted["result"]) == {
        "summary",
        "context_analysis",
        "summary_model",
        "summary_type",
        "summary_runtime",
    }
    assert response["result"] == persisted["result"]
    assert _PROJECTION_FIELDS.isdisjoint(response)
    assert _PROJECTION_FIELDS.isdisjoint(response["result"])
    assert {key: stored_result[key] for key in _PROJECTION_FIELDS} == projection_before


def test_v1_resummarize_endpoint_does_not_replay_projection_fields(
    monkeypatch,
) -> None:
    from src.api.endpoints import audio as audio_v1

    task_result = {
        "transcription": "Noi dung nguon co bang chung.",
        "context_analysis": {"analysis_status": "success"},
        **_released_projection_state("run-task-snapshot"),
    }
    stored_result = copy.deepcopy(task_result)
    stored_result.update(_released_projection_state("run-concurrent"))
    task = {"result": task_result}
    projection_before = copy.deepcopy(
        {key: stored_result[key] for key in _PROJECTION_FIELDS}
    )
    updates: list[dict] = []
    summary_calls: list[dict] = []

    monkeypatch.setattr(audio_v1, "get_task", lambda _task_id: task)
    monkeypatch.setattr(audio_v1, "assert_task_access", lambda *_args: None)
    monkeypatch.setattr(audio_v1, "check_rate_limit", lambda *_args: None)
    monkeypatch.setattr(
        audio_v1.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="test-model latest\n"),
    )

    def summarize(*_args, **kwargs) -> str:
        summary_calls.append(kwargs)
        return "Tom tat lai."

    monkeypatch.setattr(audio_v1, "summarize_transcript", summarize)

    def apply_update(_task_id: str, payload: dict) -> bool:
        updates.append(copy.deepcopy(payload))
        _apply_result_patch(stored_result, payload)
        return True

    monkeypatch.setattr(audio_v1, "update_task", apply_update)

    response = audio_v1.resummarize_task(
        "task-v1-resummary",
        summary_type="brief",
        min_length=1,
        max_length=20,
        db=object(),
        current_user=SimpleNamespace(id=1),
    )

    persisted = updates[-1]
    _assert_projection_free_result_patch(persisted)
    assert set(persisted["result"]) == {
        "summary",
        "context_analysis",
        "summary_model",
        "summary_type",
        "summary_runtime",
    }
    assert summary_calls[-1]["summary_type"] == "brief"
    assert response["result"] == persisted["result"]
    assert _PROJECTION_FIELDS.isdisjoint(response)
    assert _PROJECTION_FIELDS.isdisjoint(response["result"])
    assert {key: stored_result[key] for key in _PROJECTION_FIELDS} == projection_before


def test_summary_analyze_persists_only_context_patch(
    monkeypatch,
) -> None:
    from src.api.endpoints import summary as summary_endpoint

    task_result = {
        "transcription": "Noi dung nguon co bang chung.",
        "context_analysis": {"analysis_status": "failed"},
        "segments": [],
        **_released_projection_state("run-task-snapshot"),
    }
    stored_result = copy.deepcopy(task_result)
    stored_result.update(_released_projection_state("run-concurrent"))
    task = {"result": task_result}
    projection_before = copy.deepcopy(
        {key: stored_result[key] for key in _PROJECTION_FIELDS}
    )
    updates: list[dict] = []
    generated_context = {
        "analysis_status": "success",
        "summary": "Phan tich moi.",
    }

    monkeypatch.setattr(summary_endpoint, "get_task", lambda _task_id: task)
    monkeypatch.setattr(summary_endpoint, "assert_task_access", lambda *_args: None)
    monkeypatch.setattr(summary_endpoint, "check_rate_limit", lambda *_args: None)

    class FakeProcessor:
        def analyze_context(self, _summary: str) -> dict:
            return generated_context

    monkeypatch.setattr(summary_endpoint, "OllamaProcessor", FakeProcessor)

    def apply_update(_task_id: str, payload: dict) -> bool:
        updates.append(copy.deepcopy(payload))
        _apply_result_patch(stored_result, payload)
        return True

    monkeypatch.setattr(summary_endpoint, "update_task", apply_update)

    response = summary_endpoint.analyze_summary(
        summary="Legacy summary must not become evidence.",
        task_id="task-summary-analysis",
        db=object(),
        current_user=SimpleNamespace(id=1),
    )

    persisted = updates[-1]
    assert persisted == {"result": {"context_analysis": generated_context}}
    _assert_projection_free_result_patch(persisted)
    assert response["result"] == persisted["result"]
    assert _PROJECTION_FIELDS.isdisjoint(response)
    assert _PROJECTION_FIELDS.isdisjoint(response["result"])
    assert {key: stored_result[key] for key in _PROJECTION_FIELDS} == projection_before
