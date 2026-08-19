import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api.endpoints import audio as audio_v1
from src.api.endpoints import audio_v2
from src.services import task_service
from src.services.summarization import summary_service_v2
from src.services.summarization.contracts import SummaryRequest
from src.worker.tasks import summarize_task as celery_summary


def _valid_result() -> dict:
    return {
        "available": True,
        "summary": "Noi dung tom tat hop le.",
        "context": None,
        "model": "test-model",
        "summary_type": "brief",
        "runtime": {},
    }


def _preview_only_result() -> dict:
    return {
        "available": True,
        "summary": "",
        "summary_state": "grounded_transcript_only",
        "summary_preview": {"text": "Transcript excerpt masquerading as summary."},
    }


def _patch_guards(monkeypatch) -> None:
    monkeypatch.setattr(audio_v1, "assert_task_access", lambda *_args: None)
    monkeypatch.setattr(audio_v1, "check_rate_limit", lambda *_args: None)
    monkeypatch.setattr(audio_v2, "assert_task_access", lambda *_args: None)
    monkeypatch.setattr(audio_v2, "check_rate_limit", lambda *_args: None)


def test_preview_only_result_is_never_a_success_contract() -> None:
    assert audio_v2._summary_contract_failure(_preview_only_result()) == (
        "SUMMARY_EMPTY",
        "Summarization service returned an empty summary.",
    )
    assert audio_v1._summary_output_failure(_preview_only_result()) == (
        "SUMMARY_EMPTY",
        "Summarization service returned an empty summary.",
    )


def test_legacy_completed_status_does_not_promote_summary_state_only() -> None:
    result = {
        "transcription": "Noi dung transcript.",
        "summary_state": "grounded_transcript_only",
        "summary_preview": {"text": "Noi dung preview."},
    }

    assert task_service.canonical_status("completed", result) == "transcribed"


def test_v2_sync_false_persistence_never_returns_success(monkeypatch) -> None:
    _patch_guards(monkeypatch)
    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    monkeypatch.setattr(task_service, "update_task", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda *_args, **_kwargs: _valid_result(),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            audio_v2.summarize_v2(
                "task-1",
                request=audio_v2.SummaryV2Request(
                    model_name="test-model",
                    summary_type="brief",
                    include_context=True,
                    async_mode=False,
                    min_length=0,
                    max_length=20,
                    investigation_scenario="auto",
                ),
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "SUMMARY_PERSISTENCE_FAILED"


def test_v2_sync_failure_persists_worker_equivalent_typed_state(monkeypatch) -> None:
    _patch_guards(monkeypatch)
    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda _task_id: {
            "result": {
                "transcription": "Noi dung",
                "summary": "stale summary",
                "summary_error": {"code": "STALE"},
            },
        },
    )
    persisted: list[dict] = []
    monkeypatch.setattr(
        task_service,
        "update_task",
        lambda _task_id, data: persisted.append(data) or True,
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda *_args, **_kwargs: {
            "available": False,
            "summary": "private provider detail",
            "error": {
                "code": "SUMMARY_CONTEXT_WINDOW_EXCEEDED",
                "message": "private provider detail",
            },
            "runtime": {"llm_call_count": 0, "context_budget": {"fits": False}},
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            audio_v2.summarize_v2(
                "task-1",
                request=audio_v2.SummaryV2Request(
                    summary_type="investigation",
                    async_mode=False,
                    min_length=0,
                    max_length=20,
                    length_mode="auto",
                    investigation_scenario="auto",
                ),
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == {
        "code": "SUMMARY_CONTEXT_WINDOW_EXCEEDED",
        "message": "The complete transcript exceeds the verified model context window.",
        "task_id": "task-1",
    }
    assert persisted == [
        celery_summary._safe_failure_update(
            celery_summary.SafeSummaryTaskError(
                "SUMMARY_CONTEXT_WINDOW_EXCEEDED",
                result={
                    "runtime": {
                        "llm_call_count": 0,
                        "context_budget": {"fits": False},
                    }
                },
            )
        )
    ]
    assert persisted[0]["result"]["summary"] is None
    assert persisted[0]["result"]["summary_error"]["code"] == (
        "SUMMARY_CONTEXT_WINDOW_EXCEEDED"
    )
    assert persisted[0]["result"]["summary_notice"]["retryable"] is False
    assert "private provider detail" not in repr(persisted)


def test_v2_async_persists_before_enqueue(monkeypatch) -> None:
    _patch_guards(monkeypatch)
    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    monkeypatch.setattr(task_service, "update_task", lambda *_args, **_kwargs: False)

    enqueued: list[bool] = []
    monkeypatch.setattr(
        celery_summary.summarize_transcript_task,
        "delay",
        lambda **_kwargs: enqueued.append(True),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            audio_v2.summarize_v2(
                "task-1",
                request=audio_v2.SummaryV2Request(
                    summary_type="brief",
                    async_mode=True,
                    min_length=0,
                    max_length=20,
                    investigation_scenario="auto",
                ),
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )

    assert exc_info.value.detail["code"] == "SUMMARY_PERSISTENCE_FAILED"
    assert enqueued == []


def test_legacy_sync_false_persistence_never_returns_success(monkeypatch) -> None:
    _patch_guards(monkeypatch)
    monkeypatch.setattr(
        audio_v1,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    monkeypatch.setattr(audio_v1, "update_task", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda *_args, **_kwargs: _valid_result(),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            audio_v1.summarize_task(
                "task-1",
                request=SummaryRequest(
                    summary_type="brief",
                    min_length=0,
                    max_length=20,
                ),
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "SUMMARY_PERSISTENCE_FAILED"


def test_celery_final_false_persistence_raises_safe_error(monkeypatch) -> None:
    monkeypatch.setattr(
        celery_summary,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    states: list[str] = []

    def persist(_task_id, data):
        states.append(data["status"])
        return data["status"] != "summarized"

    monkeypatch.setattr(celery_summary, "update_task", persist)
    monkeypatch.setattr(
        celery_summary,
        "_llama_server_handoff",
        lambda *_args: nullcontext(),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: _valid_result(),
    )

    with pytest.raises(celery_summary.SafeSummaryTaskError) as exc_info:
        celery_summary.summarize_transcript_task.run(
            "task-1",
            summary_type="brief",
            min_length=0,
            max_length=20,
        )

    assert exc_info.value.code == "SUMMARY_PERSISTENCE_FAILED"
    assert states == ["summarizing", "summarized", "failed"]


def test_celery_provider_message_is_not_exposed(monkeypatch) -> None:
    secret = "sensitive-transcript-fragment"
    monkeypatch.setattr(
        celery_summary,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    persisted: list[dict] = []
    monkeypatch.setattr(
        celery_summary,
        "update_task",
        lambda _task_id, data: persisted.append(data) or True,
    )
    monkeypatch.setattr(
        celery_summary,
        "_llama_server_handoff",
        lambda *_args: nullcontext(),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: {
            "available": False,
            "summary": "",
            "error": {"code": "LLM_UNAVAILABLE", "message": secret},
        },
    )

    with pytest.raises(celery_summary.SafeSummaryTaskError) as exc_info:
        celery_summary.summarize_transcript_task.run(
            "task-1",
            summary_type="brief",
            min_length=0,
            max_length=20,
        )

    assert exc_info.value.code == "LLM_UNAVAILABLE"
    assert secret not in str(exc_info.value)
    assert secret not in repr(persisted)


def test_failure_patch_replaces_stale_summary_error_with_current_safe_code() -> None:
    secret = "provider-detail-must-not-be-persisted"
    error = celery_summary.SafeSummaryTaskError(
        "INVESTIGATION_WRITER_REJECTED",
        result={
            "error": {"code": "INVESTIGATION_WRITER_REJECTED", "message": secret},
            "runtime": {"writer_status": "rejected", "llm_call_count": 2},
        },
    )

    update = celery_summary._safe_failure_update(error)

    assert update["result"]["summary"] is None
    assert update["result"]["summary_state"] == "unavailable"
    assert update["result"]["summary_error"]["code"] == (
        "INVESTIGATION_WRITER_REJECTED"
    )
    assert update["result"]["summary_runtime"]["writer_status"] == "rejected"
    assert "SUMMARY_ATTEMPT_STALE" not in repr(update)
    assert secret not in repr(update)


def test_celery_preserves_safe_investigation_window_error_code(monkeypatch) -> None:
    monkeypatch.setattr(
        celery_summary,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    persisted: list[dict] = []
    monkeypatch.setattr(
        celery_summary,
        "update_task",
        lambda _task_id, data: persisted.append(data) or True,
    )
    monkeypatch.setattr(
        celery_summary,
        "_llama_server_handoff",
        lambda *_args: nullcontext(),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: {
            "available": False,
            "summary": "",
            "error": {
                "code": "INVESTIGATION_CONTEXT_WINDOW_EXCEEDED",
                "message": "provider details must remain private",
            },
        },
    )

    with pytest.raises(celery_summary.SafeSummaryTaskError) as exc_info:
        celery_summary.summarize_transcript_task.run(
            "task-1",
            summary_type="investigation",
            min_length=120,
            max_length=400,
        )

    assert exc_info.value.code == "INVESTIGATION_CONTEXT_WINDOW_EXCEEDED"
    assert "provider details" not in str(exc_info.value)
    assert persisted[-1]["status"] == "failed"
    assert persisted[-1]["error"] == (
        "The grounded investigation context exceeds the verified model window."
    )


@pytest.mark.parametrize(
    ("code", "next_action"),
    [
        (
            "SUMMARY_CONTEXT_WINDOW_EXCEEDED",
            "use_larger_context_or_shorter_source",
        ),
        ("SUMMARY_PROMPT_SOURCE_INVARIANT_FAILED", "contact_support"),
    ],
)
def test_non_retryable_summary_failures_publish_safe_next_action(
    code: str,
    next_action: str,
) -> None:
    error = celery_summary.SafeSummaryTaskError(
        code,
        result={"runtime": {"llm_call_count": 0}},
    )

    update = celery_summary._safe_failure_update(error)

    assert update["result"]["summary_error"]["code"] == code
    assert update["result"]["summary_notice"]["retryable"] is False
    assert update["result"]["summary_notice"]["next_action"] == next_action


def test_celery_preserves_typed_length_coverage_conflict(monkeypatch) -> None:
    monkeypatch.setattr(
        celery_summary,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    persisted: list[dict] = []
    monkeypatch.setattr(
        celery_summary,
        "update_task",
        lambda _task_id, data: persisted.append(data) or True,
    )
    monkeypatch.setattr(
        celery_summary,
        "_llama_server_handoff",
        lambda *_args: nullcontext(),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: {
            "available": False,
            "summary": "",
            "error": {
                "code": "INVESTIGATION_LENGTH_COVERAGE_CONFLICT",
                "message": "private hard-lock details",
            },
            "runtime": {"llm_call_count": 0},
        },
    )

    with pytest.raises(celery_summary.SafeSummaryTaskError) as exc_info:
        celery_summary.summarize_transcript_task.run(
            "task-1",
            summary_type="investigation",
            min_length=50,
            max_length=200,
        )

    assert exc_info.value.code == "INVESTIGATION_LENGTH_COVERAGE_CONFLICT"
    assert "private hard-lock details" not in repr(persisted)
    assert persisted[-1]["result"]["summary_error"]["code"] == (
        "INVESTIGATION_LENGTH_COVERAGE_CONFLICT"
    )
    assert persisted[-1]["result"]["summary_runtime"]["llm_call_count"] == 0
