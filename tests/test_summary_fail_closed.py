from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api.endpoints import audio as audio_v1
from src.api.endpoints import audio_v2
from src.services import audio_service, task_service
from src.services.summarization import context_service, summary_service_v2
from src.services.summarization.models import llm_manager
from src.services.summarization.contracts import (
    CaseSummaryRequest,
    MultiSummaryRequest,
    SummaryRequest,
)
from src.worker.tasks import summarize_task


SECRET = "S4_SECRET_4f2e9d"


class _FakeQuery:
    def __init__(self, task):
        self.task = task
        self.locked = False

    def filter(self, *_args, **_kwargs):
        return self

    def with_for_update(self):
        self.locked = True
        return self

    def first(self):
        return self.task


class _FakeSession:
    def __init__(self, task, *, fail_commit: bool = False):
        self.task = task
        self.fail_commit = fail_commit
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.query_object = _FakeQuery(task)
        self.snapshot = copy.deepcopy(
            (
                task.status,
                task.result,
                task.error,
                task.updated_at,
                getattr(task, "summary", None),
                getattr(task, "model_name", None),
            )
        )
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.closed = False

    def query(self, _model):
        return self.query_object

    def flush(self):
        self.flush_count += 1

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError(f"commit failed {SECRET}")

    def rollback(self):
        self.rollback_count += 1
        self.task.status = self.snapshot[0]
        self.task.result = copy.deepcopy(self.snapshot[1])
        self.task.error = self.snapshot[2]
        self.task.updated_at = self.snapshot[3]
        if hasattr(self.task, "summary"):
            self.task.summary = self.snapshot[4]
        if hasattr(self.task, "model_name"):
            self.task.model_name = self.snapshot[5]

    def close(self):
        self.closed = True


def _task(*, result: dict | None = None, status: str = "transcribed"):
    stored_result = copy.deepcopy(result or {})
    return SimpleNamespace(
        id="task-1",
        status=status,
        result=stored_result,
        summary=stored_result.get("summary"),
        model_name=stored_result.get("summary_model") or stored_result.get("model_name"),
        error=None,
        updated_at=datetime(2026, 8, 10, 1, 0, 0),
        audio_files=[SimpleNamespace(status="transcribed")],
    )


def _valid_service_result(*, multi: bool = False) -> dict:
    result = {
        "available": True,
        "summary": "Tom tat hop le.",
        "context": {"analysis_status": "success"},
        "model": "test-model",
        "summary_type": "brief",
        "runtime": {"length_contract": {"maximum_met": True}},
    }
    if multi:
        result.update(num_transcripts=1, case_id="1")
    return result


def _valid_investigation_result() -> dict:
    summary = "Noi dung da duoc kiem chung."
    return {
        "available": True,
        "summary": summary,
        "context": None,
        "model": None,
        "summary_type": "investigation",
        "release": {
            "run_id": "run-1",
            "source_revision_id": "investigation-source-1",
            "summary_source_revision_id": "summary-source-1",
            "request_fingerprint": "request-1",
            "sentence_ids": ["sentence-1"],
            "sentences": [
                {
                    "sentence_id": "sentence-1",
                    "sentence_kind": "fact",
                    "claim_refs": ["claim-1"],
                    "evidence_refs": ["evidence-1"],
                }
            ],
            "content_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
            "attestation_schema_version": "narrative-attestation-v2",
            "producer_id": "investigation-narrative-attestor",
        },
        "runtime": {"length_contract": {"maximum_met": True}},
    }


def _install_investigation_authority(monkeypatch, raw_result: dict) -> None:
    authority = object()
    raw_result["_released_narrative_authority"] = authority
    trusted_metadata = {
        key: copy.deepcopy(value)
        for key, value in raw_result["release"].items()
        if key not in {"summary_source_revision_id", "request_fingerprint"}
    }

    def render(value):
        if value is not authority:
            raise TypeError("untrusted authority")
        return raw_result["summary"]

    def metadata(value):
        if value is not authority:
            raise TypeError("untrusted authority")
        return copy.deepcopy(trusted_metadata)

    monkeypatch.setattr(task_service, "render_released_narrative_text", render)
    monkeypatch.setattr(task_service, "released_narrative_metadata", metadata)


def _stored_terminal_result(
    attempt_id: str,
    *,
    transcript: str = "Noi dung",
    summary: str = "Tom tat da luu.",
) -> dict:
    request_fingerprint, source_revision_id = task_service.build_summary_attempt_binding(
        transcript,
        model_name=None,
        summary_type="brief",
        include_context=True,
        min_length=0,
        max_length=20,
    )
    return {
        "transcription": transcript,
        "summary": summary,
        "context_analysis": None,
        "summary_model": "test-model",
        "summary_type": "brief",
        "summary_runtime": {},
        "summary_state": {
            "schema_version": task_service.SUMMARY_STATE_SCHEMA,
            "attempt_id": attempt_id,
            "request_fingerprint": request_fingerprint,
            "source_revision_id": source_revision_id,
            "status": "succeeded",
            "code": "SUMMARY_SUCCEEDED",
            "stage": "execution",
            "retryable": False,
        },
    }


def _transition(
    outcome: str = "applied",
    state: str = "running",
    code: str = "SUMMARY_ATTEMPT_STARTED",
) -> task_service.SummaryTransitionResult:
    return task_service.SummaryTransitionResult(outcome, state, code)


def _begin_persisted_attempt(
    task_id: str,
    attempt_id: str,
    *,
    db=None,
    stage: str = "execution",
):
    transcript = "Nguon"
    if db is not None:
        stored_result = getattr(db.task, "result", {})
        if isinstance(stored_result, dict) and isinstance(
            stored_result.get("transcription"), str
        ):
            transcript = stored_result["transcription"]
    request_fingerprint, source_revision_id = task_service.build_summary_attempt_binding(
        transcript,
        model_name=None,
        summary_type="brief",
        include_context=True,
        min_length=0,
        max_length=20,
    )
    return task_service.begin_summary_attempt(
        task_id,
        attempt_id,
        request_fingerprint=request_fingerprint,
        source_revision_id=source_revision_id,
        stage=stage,
        db=db,
    )


def _patch_endpoint_guards(monkeypatch) -> None:
    monkeypatch.setattr(audio_v1, "assert_task_access", lambda *_args: None)
    monkeypatch.setattr(audio_v1, "assert_case_access", lambda *_args: None)
    monkeypatch.setattr(audio_v1, "check_rate_limit", lambda *_args: None)
    monkeypatch.setattr(audio_v2, "assert_task_access", lambda *_args: None)
    monkeypatch.setattr(audio_v2, "check_rate_limit", lambda *_args: None)


def _patch_v1_transitions(monkeypatch, *, success_outcome=None, failure_outcome=None):
    monkeypatch.setattr(
        audio_v1,
        "begin_summary_attempt",
        lambda *_args, **_kwargs: _transition(),
    )
    monkeypatch.setattr(
        audio_v1,
        "succeed_summary_attempt",
        lambda *_args, **_kwargs: success_outcome
        or _transition("applied", "succeeded", "SUMMARY_SUCCEEDED"),
    )
    monkeypatch.setattr(
        audio_v1,
        "fail_summary_attempt",
        lambda *_args, **_kwargs: failure_outcome
        or _transition("applied", "failed", "SUMMARY_GENERATION_FAILED"),
    )


def _patch_v2_transitions(monkeypatch, *, success_outcome=None, failure_outcome=None):
    monkeypatch.setattr(
        audio_v2,
        "begin_summary_attempt",
        lambda *_args, **_kwargs: _transition(),
    )
    monkeypatch.setattr(
        audio_v2,
        "succeed_summary_attempt",
        lambda *_args, **_kwargs: success_outcome
        or _transition("applied", "succeeded", "SUMMARY_SUCCEEDED"),
    )
    monkeypatch.setattr(
        audio_v2,
        "fail_summary_attempt",
        lambda *_args, **_kwargs: failure_outcome
        or _transition("applied", "failed", "SUMMARY_GENERATION_FAILED"),
    )


def test_summary_attempt_binding_is_deterministic_and_non_sensitive() -> None:
    transcript = f"private transcript {SECRET}"
    user_prompt = f"private prompt {SECRET}"
    options = {
        "model_name": "test-model",
        "summary_type": "brief",
        "include_context": True,
        "min_length": 0,
        "max_length": 20,
        "user_prompt": user_prompt,
    }

    first = task_service.build_summary_attempt_binding(transcript, **options)
    repeated = task_service.build_summary_attempt_binding(transcript, **options)
    changed_source = task_service.build_summary_attempt_binding(
        transcript + " changed", **options
    )
    changed_options = task_service.build_summary_attempt_binding(
        transcript,
        **{**options, "summary_type": "detailed"},
    )

    assert first == repeated
    assert first[0] != changed_source[0]
    assert first[1] != changed_source[1]
    assert first[0] != changed_options[0]
    assert first[1] == changed_options[1]
    assert len(first[0]) == 64
    assert first[1].startswith("summary-source-sha256:")
    assert transcript not in repr(first)
    assert user_prompt not in repr(first)
    assert SECRET not in repr(first)


def test_attempt_state_machine_is_atomic_idempotent_and_preserves_projection() -> None:
    projection = {
        "released_investigation_run": {"run_id": "run-1"},
        "visualization_data": {"nodes": [1]},
        "has_visualization": True,
    }
    stored = {
        "transcription": "Nguon goc",
        "segments": [{"start": 0.0, "text": "Nguon goc"}],
        "summary": "stale",
        "summary_model": "old-model",
        "summary_runtime": {"raw_output": SECRET},
        **projection,
    }
    db_task = _task(result=stored)
    session = _FakeSession(db_task)
    original_audio_status = db_task.audio_files[0].status

    begun = _begin_persisted_attempt("task-1", "attempt-1", db=session)
    assert begun.outcome == "applied"
    assert session.query_object.locked is True
    assert db_task.status == "summarizing"
    assert set(db_task.result["summary_state"]) == {
        "schema_version",
        "attempt_id",
        "request_fingerprint",
        "source_revision_id",
        "status",
        "code",
        "stage",
        "retryable",
    }
    assert db_task.result["summary_state"]["attempt_id"] == "attempt-1"
    expected_binding = task_service.build_summary_attempt_binding(
        "Nguon goc",
        model_name=None,
        summary_type="brief",
        include_context=True,
        min_length=0,
        max_length=20,
    )
    assert db_task.result["summary_state"]["request_fingerprint"] == expected_binding[0]
    assert db_task.result["summary_state"]["source_revision_id"] == expected_binding[1]
    assert "summary" not in db_task.result
    assert "summary_runtime" not in db_task.result
    assert db_task.summary is None
    assert db_task.model_name is None
    assert db_task.result["transcription"] == "Nguon goc"
    assert db_task.result["segments"] == stored["segments"]
    assert {key: db_task.result[key] for key in projection} == projection
    assert db_task.audio_files[0].status == original_audio_status

    begin_updated_at = db_task.updated_at
    binding_conflict = task_service.begin_summary_attempt(
        "task-1",
        "attempt-1",
        request_fingerprint="c" * 64,
        source_revision_id=expected_binding[1],
        db=session,
    )
    assert binding_conflict.outcome == "conflict"
    assert db_task.updated_at == begin_updated_at

    duplicate_begin = _begin_persisted_attempt("task-1", "attempt-1", db=session)
    assert duplicate_begin.outcome == "conflict"
    assert db_task.updated_at == begin_updated_at

    patch = {
        "summary": "Tom tat hop le.",
        "context_analysis": None,
        "summary_model": "test-model",
        "summary_type": "brief",
        "summary_runtime": {},
    }
    success = task_service.succeed_summary_attempt(
        "task-1", "attempt-1", patch, db=session
    )
    assert success.outcome == "applied"
    assert db_task.summary == "Tom tat hop le."
    assert db_task.model_name == "test-model"
    terminal_updated_at = db_task.updated_at
    duplicate_success = task_service.succeed_summary_attempt(
        "task-1", "attempt-1", patch, db=session
    )
    assert duplicate_success.outcome == "duplicate"
    assert db_task.updated_at == terminal_updated_at
    db_task.summary = "tampered direct summary"
    direct_field_conflict = task_service.succeed_summary_attempt(
        "task-1", "attempt-1", patch, db=session
    )
    assert direct_field_conflict.outcome == "conflict"
    assert db_task.updated_at == terminal_updated_at
    db_task.summary = patch["summary"]
    db_task.model_name = "tampered direct model"
    direct_model_conflict = task_service.succeed_summary_attempt(
        "task-1", "attempt-1", patch, db=session
    )
    assert direct_model_conflict.outcome == "conflict"
    assert db_task.updated_at == terminal_updated_at
    db_task.model_name = patch["summary_model"]
    duplicate_terminal_begin = _begin_persisted_attempt(
        "task-1", "attempt-1", db=session
    )
    assert duplicate_terminal_begin.outcome == "duplicate"
    assert db_task.updated_at == terminal_updated_at

    conflict = task_service.fail_summary_attempt(
        "task-1",
        "attempt-1",
        code="SUMMARY_GENERATION_FAILED",
        retryable=True,
        db=session,
    )
    assert conflict.outcome == "conflict"
    assert db_task.status == "summarized"
    assert db_task.updated_at == terminal_updated_at


def test_enqueued_attempt_can_be_claimed_once_for_execution() -> None:
    db_task = _task(result={"transcription": "Nguon"})
    session = _FakeSession(db_task)

    enqueued = _begin_persisted_attempt(
        "task-1",
        "attempt-claim",
        stage="enqueue",
        db=session,
    )
    assert enqueued.outcome == "applied"
    assert db_task.result["summary_state"]["stage"] == "enqueue"

    claimed = _begin_persisted_attempt(
        "task-1",
        "attempt-claim",
        stage="execution",
        db=session,
    )
    assert claimed.outcome == "applied"
    assert db_task.result["summary_state"]["stage"] == "execution"

    duplicate_delivery = _begin_persisted_attempt(
        "task-1",
        "attempt-claim",
        stage="execution",
        db=session,
    )
    assert duplicate_delivery.outcome == "conflict"


def test_terminal_transition_rejects_live_transcript_drift() -> None:
    db_task = _task(result={"transcription": "Nguon"})
    session = _FakeSession(db_task)
    request_fingerprint, source_revision_id = task_service.build_summary_attempt_binding(
        "Nguon",
        model_name=None,
        summary_type="brief",
        include_context=True,
        min_length=0,
        max_length=20,
    )
    assert task_service.begin_summary_attempt(
        "task-1",
        "attempt-drift",
        request_fingerprint=request_fingerprint,
        source_revision_id=source_revision_id,
        db=session,
    ).accepted
    db_task.result["transcription"] = "Nguon da thay doi"

    success = task_service.succeed_summary_attempt(
        "task-1",
        "attempt-drift",
        {
            "summary": "Khong duoc luu.",
            "context_analysis": None,
            "summary_model": None,
            "summary_type": "brief",
            "summary_runtime": {},
        },
        db=session,
    )
    failure = task_service.fail_summary_attempt(
        "task-1",
        "attempt-drift",
        code="SUMMARY_GENERATION_FAILED",
        retryable=True,
        db=session,
    )

    assert success.outcome == "conflict"
    assert failure.outcome == "conflict"
    assert db_task.result["summary_state"]["status"] == "running"
    assert "summary" not in db_task.result


def test_new_source_attempt_supersedes_stale_running_attempt() -> None:
    db_task = _task(result={"transcription": "Nguon A"})
    session = _FakeSession(db_task)
    binding_a = task_service.build_summary_attempt_binding(
        "Nguon A",
        model_name=None,
        summary_type="brief",
        include_context=True,
        min_length=0,
        max_length=20,
    )
    assert task_service.begin_summary_attempt(
        "task-1",
        "attempt-a",
        request_fingerprint=binding_a[0],
        source_revision_id=binding_a[1],
        db=session,
    ).accepted

    db_task.result["transcription"] = "Nguon B"
    binding_b = task_service.build_summary_attempt_binding(
        "Nguon B",
        model_name=None,
        summary_type="brief",
        include_context=True,
        min_length=0,
        max_length=20,
    )
    replacement = task_service.begin_summary_attempt(
        "task-1",
        "attempt-b",
        request_fingerprint=binding_b[0],
        source_revision_id=binding_b[1],
        db=session,
    )
    stale_terminal = task_service.fail_summary_attempt(
        "task-1",
        "attempt-a",
        code="SUMMARY_GENERATION_FAILED",
        retryable=True,
        db=session,
    )

    assert replacement.outcome == "applied"
    assert db_task.result["summary_state"]["attempt_id"] == "attempt-b"
    assert stale_terminal.outcome == "conflict"


def test_failure_transition_is_idempotent_and_stale_attempt_cannot_win() -> None:
    db_task = _task(result={"transcription": "Nguon", "summary": "old"})
    session = _FakeSession(db_task)

    assert _begin_persisted_attempt("task-1", "attempt-old", db=session).accepted
    assert task_service.fail_summary_attempt(
        "task-1",
        "attempt-old",
        code="LLM_UNAVAILABLE",
        retryable=True,
        db=session,
    ).accepted
    failed_at = db_task.updated_at
    duplicate = task_service.fail_summary_attempt(
        "task-1",
        "attempt-old",
        code="LLM_UNAVAILABLE",
        retryable=True,
        db=session,
    )
    assert duplicate.outcome == "duplicate"
    assert db_task.updated_at == failed_at
    assert "summary" not in db_task.result
    assert db_task.summary is None
    assert db_task.model_name is None

    assert _begin_persisted_attempt("task-1", "attempt-new", db=session).accepted
    before_stale = copy.deepcopy(db_task.result)
    stale = task_service.succeed_summary_attempt(
        "task-1",
        "attempt-old",
        {
            "summary": "stale",
            "context_analysis": None,
            "summary_model": None,
            "summary_type": "brief",
            "summary_runtime": {},
        },
        db=session,
    )
    assert stale.outcome == "conflict"
    assert db_task.result == before_stale


def test_release_rejection_becomes_needs_review() -> None:
    db_task = _task(result={"transcription": "Nguon", "summary": "old"})
    session = _FakeSession(db_task)
    assert _begin_persisted_attempt(
        "task-1", "attempt-release", db=session
    ).accepted

    terminal = task_service.fail_summary_attempt(
        "task-1",
        "attempt-release",
        code="INVESTIGATION_NARRATIVE_ATTESTATION_INVALID",
        stage="release",
        retryable=False,
        db=session,
    )
    assert terminal.accepted
    assert db_task.status == "needs_review"
    assert db_task.result["summary_state"]["status"] == "needs_review"
    assert db_task.result["summary_state"]["retryable"] is False
    assert "summary" not in db_task.result


def test_specialized_transition_rejects_arbitrary_state_and_sanitizes_codes() -> None:
    db_task = _task(result={"transcription": "Nguon"})
    session = _FakeSession(db_task)
    with pytest.raises(ValueError, match="Unsupported summary attempt state"):
        task_service.transition_summary_attempt(
            "task-1",
            "attempt-1",
            state="garbage",  # type: ignore[arg-type]
            code="RAW_PROVIDER_CODE",
            stage="raw-stage",
            retryable=True,
            db=session,
        )

    assert _begin_persisted_attempt("task-1", "attempt-1", db=session).accepted
    failed = task_service.fail_summary_attempt(
        "task-1",
        "attempt-1",
        code=f"UNKNOWN_{SECRET}",
        stage=f"stage-{SECRET}",
        retryable=True,
        db=session,
    )
    assert failed.accepted
    state = db_task.result["summary_state"]
    assert state["code"] == "SUMMARY_UNAVAILABLE"
    assert state["stage"] == "execution"
    assert SECRET not in repr(db_task.result)
    assert SECRET not in str(db_task.error)


@pytest.mark.parametrize(
    "data",
    [
        {"status": "summarized"},
        {"status": "needs_review"},
        {"summary": "forged"},
        {"model_name": "forged-model"},
        {"result": {"summary": "forged"}},
        {"result": {"summary_runtime": {"secret": SECRET}}},
        {
            "result": {
                "summary_state": {
                    "message": SECRET,
                    "status": "summarized",
                }
            }
        },
    ],
)
def test_generic_update_cannot_bypass_summary_state_api(data) -> None:
    db_task = _task(result={"transcription": "Nguon"})
    session = _FakeSession(db_task)
    assert task_service.update_task("task-1", data, db=session) is False
    assert "summary_state" not in db_task.result
    assert "summary" not in db_task.result
    assert SECRET not in repr(db_task.result)


def test_generic_update_preserves_non_summary_legacy_fields() -> None:
    db_task = _task(result={"transcription": "Nguon"})
    session = _FakeSession(db_task)

    assert task_service.update_task(
        "task-1",
        {
            "status": "transcribed",
            "result": {
                "transcription": "Nguon moi",
                "context_analysis": {"analysis_status": "success"},
                "model_name": "asr-model",
                "summary": "",
            },
            "duration": 1.5,
        },
        db=session,
    ) is True
    assert db_task.status == "transcribed"
    assert db_task.result["transcription"] == "Nguon moi"
    assert db_task.result["context_analysis"] == {"analysis_status": "success"}
    assert db_task.result["model_name"] == "asr-model"
    assert "summary" not in db_task.result


def test_retranscription_invalidates_stale_summary_and_projection() -> None:
    request_fingerprint, source_revision_id = task_service.build_summary_attempt_binding(
        "source-A",
        model_name=None,
        summary_type="brief",
        include_context=True,
        min_length=0,
        max_length=20,
    )
    db_task = _task(
        status="summarized",
        result={
            "transcription": "source-A",
            "summary": "summary-A",
            "context_analysis": {"stale": True},
            "summary_model": "test-model",
            "summary_type": "brief",
            "summary_runtime": {},
            "summary_state": {
                "schema_version": task_service.SUMMARY_STATE_SCHEMA,
                "attempt_id": "attempt-A",
                "request_fingerprint": request_fingerprint,
                "source_revision_id": source_revision_id,
                "status": "succeeded",
                "code": "SUMMARY_SUCCEEDED",
                "stage": "execution",
                "retryable": False,
            },
            "visualization_data": {"stale": True},
            "has_visualization": True,
        },
    )
    db = _FakeSession(db_task)

    assert task_service.update_task(
        "task-1",
        {"status": "transcribed", "result": {"transcription": "source-B"}},
        db=db,
    )
    assert db_task.status == "transcribed"
    assert db_task.result["transcription"] == "source-B"
    for key in (
        "summary",
        "context_analysis",
        "summary_model",
        "summary_type",
        "summary_runtime",
        "summary_release",
        "summary_state",
        "visualization_data",
        "has_visualization",
    ):
        assert key not in db_task.result
    assert db_task.summary is None
    assert db_task.model_name is None


def test_idempotent_transcription_write_preserves_bound_summary() -> None:
    stored = _stored_terminal_result("attempt-A", transcript="same-source")
    db_task = _task(status="summarized", result=stored)
    db = _FakeSession(db_task)

    assert task_service.update_task(
        "task-1",
        {"result": {"transcription": "same-source"}},
        db=db,
    )
    assert db_task.status == "summarized"
    assert db_task.result["summary"] == "Tom tat da luu."
    assert db_task.result["summary_state"]["attempt_id"] == "attempt-A"


def test_context_endpoint_updates_only_non_transition_fields(monkeypatch) -> None:
    _patch_endpoint_guards(monkeypatch)
    monkeypatch.setattr(
        audio_v1,
        "get_task",
        lambda _task_id: {
            "result": {
                "transcription": "Nguon",
                "summary": "Summary da luu",
                "summary_state": {"status": "succeeded"},
            }
        },
    )
    updates: list[dict] = []
    monkeypatch.setattr(
        audio_v1,
        "update_task",
        lambda _task_id, data: updates.append(copy.deepcopy(data)) or True,
    )

    result = audio_v1.update_task_context(
        "task-1",
        context_analysis={
            "context_analysis": {"analysis_status": "success"},
            "user_context_prompt": "Uu tien moc thoi gian",
        },
        db=object(),
        current_user=SimpleNamespace(id=1),
    )
    assert result == {"detail": "Context updated"}
    assert updates == [
        {
            "result": {
                "context_analysis": {"analysis_status": "success"},
                "user_context_prompt": "Uu tien moc thoi gian",
            }
        }
    ]


def test_transition_persistence_error_rolls_back_and_logs_type_only(
    monkeypatch,
    caplog,
) -> None:
    db_task = _task(result={"transcription": "Nguon", "summary": "old"})
    session = _FakeSession(db_task, fail_commit=True)
    monkeypatch.setattr(task_service, "SessionLocal", lambda: session)

    with caplog.at_level(logging.ERROR):
        outcome = _begin_persisted_attempt("task-1", "attempt-1")

    assert outcome.outcome == "error"
    assert outcome.code == "SUMMARY_PERSISTENCE_FAILED"
    assert session.rollback_count == 1
    assert db_task.status == "transcribed"
    assert db_task.result["summary"] == "old"
    assert SECRET not in caplog.text


@pytest.mark.parametrize(
    "raw_result,expected_code",
    [
        (None, "SUMMARY_RESULT_INVALID"),
        ({"available": True, "summary": "   "}, "SUMMARY_EMPTY"),
        (
            {
                "available": False,
                "summary": "",
                "error": {"code": "LLM_UNAVAILABLE", "message": SECRET},
            },
            "LLM_UNAVAILABLE",
        ),
        (
            {
                "available": False,
                "summary": "",
                "error": {"code": f"UNKNOWN_{SECRET}", "message": SECRET},
            },
            "SUMMARY_UNAVAILABLE",
        ),
    ],
)
def test_result_validator_requires_exact_success_and_never_replays_message(
    raw_result,
    expected_code,
) -> None:
    with pytest.raises(task_service.SummaryResultRejected) as exc_info:
        task_service.validate_summary_service_result(raw_result)
    assert exc_info.value.code == expected_code
    assert SECRET not in str(exc_info.value)


@pytest.mark.parametrize(
    "field,value,multi",
    [
        ("context", "not-a-dict", False),
        ("runtime", [], False),
        ("release", SECRET, False),
        ("error", SECRET, False),
        ("model", 1, False),
        ("requested_model", {}, False),
        ("summary_type", [], False),
        ("case_id", 7, False),
        ("num_transcripts", True, True),
    ],
)
def test_result_validator_rejects_malformed_optional_fields(
    field,
    value,
    multi,
) -> None:
    raw_result = _valid_service_result(multi=multi)
    raw_result[field] = value

    with pytest.raises(task_service.SummaryResultRejected) as exc_info:
        task_service.validate_summary_service_result(raw_result, multi=multi)
    assert exc_info.value.code == "SUMMARY_RESULT_INVALID"
    assert SECRET not in str(exc_info.value)


def test_result_validator_rejects_malformed_error_contract() -> None:
    raw_result = {
        "available": False,
        "summary": "",
        "error": {"code": 7, "message": SECRET},
    }

    with pytest.raises(task_service.SummaryResultRejected) as exc_info:
        task_service.validate_summary_service_result(raw_result)
    assert exc_info.value.code == "SUMMARY_RESULT_INVALID"
    assert SECRET not in str(exc_info.value)


@pytest.mark.parametrize(
    "mutation,expected_code",
    [
        (lambda result: result.pop("release"), "INVESTIGATION_NARRATIVE_ATTESTATION_REQUIRED"),
        (
            lambda result: result["release"].pop("producer_id"),
            "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID",
        ),
        (
            lambda result: result["release"].update(
                summary_source_revision_id="wrong-source"
            ),
            "INVESTIGATION_SOURCE_REVISION_MISMATCH",
        ),
        (
            lambda result: result["release"].update(
                request_fingerprint="wrong-request"
            ),
            "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID",
        ),
        (
            lambda result: result.update(summary="Noi dung khong khop release."),
            "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID",
        ),
        (
            lambda result: result["release"]["sentences"][0].update(
                evidence_refs=[]
            ),
            "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID",
        ),
        (
            lambda result: result.update(summary_type="detailed"),
            "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID",
        ),
    ],
)
def test_investigation_success_requires_bound_release_metadata(
    monkeypatch,
    mutation,
    expected_code,
) -> None:
    raw_result = _valid_investigation_result()
    _install_investigation_authority(monkeypatch, raw_result)
    mutation(raw_result)

    with pytest.raises(task_service.SummaryResultRejected) as exc_info:
        task_service.validate_summary_service_result(
            raw_result,
            expected_summary_type="investigation",
            expected_source_revision_id="summary-source-1",
            expected_request_fingerprint="request-1",
        )
    assert exc_info.value.code == expected_code
    assert exc_info.value.needs_review is True


def test_investigation_success_accepts_exact_release_binding(monkeypatch) -> None:
    raw_result = _valid_investigation_result()
    _install_investigation_authority(monkeypatch, raw_result)
    validated = task_service.validate_summary_service_result(
        raw_result,
        expected_summary_type="investigation",
        expected_source_revision_id="summary-source-1",
        expected_request_fingerprint="request-1",
    )
    patch = task_service.build_summary_result_patch(
        validated,
        summary_type="investigation",
    )
    assert patch["summary_release"]["request_fingerprint"] == "request-1"


def test_investigation_forged_release_without_minted_authority_is_rejected() -> None:
    with pytest.raises(task_service.SummaryResultRejected) as exc_info:
        task_service.validate_summary_service_result(
            _valid_investigation_result(),
            expected_summary_type="investigation",
            expected_source_revision_id="summary-source-1",
            expected_request_fingerprint="request-1",
        )
    assert exc_info.value.code == "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID"
    assert exc_info.value.needs_review is True


def test_v2_sync_persistence_failure_never_returns_success(monkeypatch) -> None:
    _patch_endpoint_guards(monkeypatch)
    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    _patch_v2_transitions(
        monkeypatch,
        success_outcome=_transition(
            "error", "succeeded", "SUMMARY_PERSISTENCE_FAILED"
        ),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda *_args, **_kwargs: _valid_service_result(),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            audio_v2.summarize_v2(
                "task-1",
                model_name="test-model",
                summary_type="brief",
                include_context=True,
                async_mode=False,
                min_length=0,
                max_length=20,
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "SUMMARY_PERSISTENCE_FAILED"


def test_failure_persistence_fault_never_masks_service_failure(monkeypatch) -> None:
    _patch_endpoint_guards(monkeypatch)
    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    _patch_v2_transitions(
        monkeypatch,
        failure_outcome=_transition(
            "error", "failed", "SUMMARY_PERSISTENCE_FAILED"
        ),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda *_args, **_kwargs: {
            "available": False,
            "summary": "",
            "error": {"code": "LLM_UNAVAILABLE", "message": SECRET},
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            audio_v2.summarize_v2(
                "task-1",
                summary_type="brief",
                async_mode=False,
                min_length=0,
                max_length=20,
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "SUMMARY_PERSISTENCE_FAILED"
    assert SECRET not in repr(exc_info.value.detail)


def test_v1_and_resummarize_use_typed_result_and_fail_closed(monkeypatch) -> None:
    _patch_endpoint_guards(monkeypatch)
    _patch_v1_transitions(monkeypatch)
    monkeypatch.setattr(
        audio_v1,
        "get_task",
        lambda _task_id: {
            "transcript": "Noi dung",
            "result": {"transcription": "Noi dung"},
        },
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda *_args, **_kwargs: {"available": True, "summary": "   "},
    )

    request = SummaryRequest(
        model_name="test-model",
        summary_type="brief",
        include_context=True,
        async_mode=False,
        min_length=0,
        max_length=20,
    )
    with pytest.raises(HTTPException) as v1_error:
        asyncio.run(
            audio_v1.summarize_task(
                "task-1",
                request=request,
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )
    with pytest.raises(HTTPException) as resummary_error:
        audio_v1.resummarize_task(
            "task-1",
            summary_type="brief",
            min_length=0,
            max_length=20,
            db=object(),
            current_user=SimpleNamespace(id=1),
        )
    assert v1_error.value.detail["code"] == "SUMMARY_EMPTY"
    assert resummary_error.value.detail["code"] == "SUMMARY_EMPTY"


@pytest.mark.parametrize("lane", ["v1", "resummarize"])
def test_legacy_success_persistence_fault_never_returns_success(monkeypatch, lane) -> None:
    _patch_endpoint_guards(monkeypatch)
    _patch_v1_transitions(
        monkeypatch,
        success_outcome=_transition(
            "error", "succeeded", "SUMMARY_PERSISTENCE_FAILED"
        ),
    )
    snapshot = {
        "transcript": "Noi dung",
        "result": {"transcription": "Noi dung"},
    }
    monkeypatch.setattr(audio_v1, "get_task", lambda _task_id: snapshot)
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda *_args, **_kwargs: _valid_service_result(),
    )

    with pytest.raises(HTTPException) as exc_info:
        if lane == "v1":
            asyncio.run(
                audio_v1.summarize_task(
                    "task-1",
                    request=SummaryRequest(
                        summary_type="brief", min_length=0, max_length=20
                    ),
                    db=object(),
                    current_user=SimpleNamespace(id=1),
                )
            )
        else:
            audio_v1.resummarize_task(
                "task-1",
                summary_type="brief",
                min_length=0,
                max_length=20,
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "SUMMARY_PERSISTENCE_FAILED"


@pytest.mark.parametrize("lane", ["v1", "v2", "resummarize"])
def test_direct_unsafe_handoff_result_is_failed_not_review(monkeypatch, lane) -> None:
    _patch_endpoint_guards(monkeypatch)
    task_snapshot = {
        "transcript": "Noi dung",
        "result": {"transcription": "Noi dung"},
    }
    monkeypatch.setattr(audio_v1, "get_task", lambda _task_id: task_snapshot)
    monkeypatch.setattr(task_service, "get_task", lambda _task_id: task_snapshot)
    failures: list[dict] = []

    def begin(*_args, **_kwargs):
        return _transition()

    def fail(*_args, **kwargs):
        failures.append(kwargs)
        return _transition("applied", "failed", "SUMMARY_UNSAFE_HANDOFF")

    monkeypatch.setattr(audio_v1, "begin_summary_attempt", begin)
    monkeypatch.setattr(audio_v1, "fail_summary_attempt", fail)
    monkeypatch.setattr(audio_v2, "begin_summary_attempt", begin)
    monkeypatch.setattr(audio_v2, "fail_summary_attempt", fail)
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda *_args, **_kwargs: {
            "available": False,
            "summary": "",
            "error": {"code": "SUMMARY_UNSAFE_HANDOFF", "message": SECRET},
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        if lane == "v1":
            asyncio.run(
                audio_v1.summarize_task(
                    "task-1",
                    request=SummaryRequest(
                        summary_type="brief", min_length=0, max_length=20
                    ),
                    db=object(),
                    current_user=SimpleNamespace(id=1),
                )
            )
        elif lane == "v2":
            asyncio.run(
                audio_v2.summarize_v2(
                    "task-1",
                    summary_type="brief",
                    async_mode=False,
                    min_length=0,
                    max_length=20,
                    db=object(),
                    current_user=SimpleNamespace(id=1),
                )
            )
        else:
            audio_v1.resummarize_task(
                "task-1",
                summary_type="brief",
                min_length=0,
                max_length=20,
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
    assert exc_info.value.detail["code"] == "SUMMARY_UNSAFE_HANDOFF"
    assert failures[-1]["stage"] == "handoff"
    assert failures[-1]["retryable"] is True
    assert failures[-1]["needs_review"] is False
    assert SECRET not in repr(exc_info.value.detail)


@pytest.mark.parametrize("endpoint", ["multi", "case"])
@pytest.mark.parametrize(
    "raw_result",
    [
        {"available": True, "summary": "", "num_transcripts": 1},
        {"available": True, "summary": "ok"},
        {"available": False, "summary": "", "error": {"message": SECRET}},
    ],
)
def test_multi_and_case_validate_typed_v2_output(
    monkeypatch,
    endpoint,
    raw_result,
) -> None:
    _patch_endpoint_guards(monkeypatch)
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_multi_transcripts_v2",
        lambda **_kwargs: copy.deepcopy(raw_result),
    )
    if endpoint == "multi":
        request = MultiSummaryRequest(
            transcripts=["Noi dung"],
            summary_type="brief",
            min_length=0,
            max_length=20,
        )
        call = lambda: asyncio.run(
            audio_v1.summarize_multi(
                request=request,
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )
    else:
        monkeypatch.setattr(
            audio_v1,
            "list_tasks",
            lambda **_kwargs: [{"result": {"transcription": "Noi dung"}}],
        )
        request = CaseSummaryRequest(
            case_id="1",
            summary_type="brief",
            min_length=0,
            max_length=20,
        )
        call = lambda: audio_v1.summarize_case(
            request=request,
            db=object(),
            current_user=SimpleNamespace(id=1),
        )

    with pytest.raises(HTTPException) as exc_info:
        call()
    assert exc_info.value.status_code == 502
    assert SECRET not in repr(exc_info.value.detail)


@pytest.mark.parametrize("endpoint", ["multi", "case"])
def test_multi_and_case_zero_transcripts_reject_before_provider(
    monkeypatch,
    endpoint,
) -> None:
    _patch_endpoint_guards(monkeypatch)
    monkeypatch.setattr(audio_v1, "list_tasks", lambda **_kwargs: [])
    provider_calls: list[bool] = []
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_multi_transcripts_v2",
        lambda **_kwargs: provider_calls.append(True),
    )

    if endpoint == "multi":
        call = lambda: asyncio.run(
            audio_v1.summarize_multi(
                request=MultiSummaryRequest(
                    transcripts=[],
                    case_id="1",
                    summary_type="brief",
                    min_length=0,
                    max_length=20,
                ),
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )
    else:
        call = lambda: audio_v1.summarize_case(
            request=CaseSummaryRequest(
                case_id="1",
                summary_type="brief",
                min_length=0,
                max_length=20,
            ),
            db=object(),
            current_user=SimpleNamespace(id=1),
        )

    with pytest.raises(HTTPException) as exc_info:
        call()
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "SUMMARY_RESULT_INVALID"
    assert provider_calls == []


@pytest.mark.parametrize("endpoint", ["multi", "case"])
def test_multi_and_case_propagate_explicit_or_stored_context(monkeypatch, endpoint) -> None:
    _patch_endpoint_guards(monkeypatch)
    captured: list[dict] = []

    def provider(**kwargs):
        captured.append(copy.deepcopy(kwargs))
        result = _valid_service_result(multi=True)
        result["context"] = copy.deepcopy(kwargs.get("context_analysis"))
        return result

    monkeypatch.setattr(summary_service_v2, "summarize_multi_transcripts_v2", provider)
    expected_context = {"case_focus": "election logistics"}
    if endpoint == "multi":
        response = asyncio.run(
            audio_v1.summarize_multi(
                request=MultiSummaryRequest(
                    transcripts=["Noi dung"],
                    context_analysis=expected_context,
                    summary_type="brief",
                    min_length=0,
                    max_length=20,
                ),
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )
    else:
        monkeypatch.setattr(
            audio_v1,
            "list_tasks",
            lambda **_kwargs: [
                {
                    "result": {
                        "transcription": "Noi dung",
                        "context_analysis": expected_context,
                    }
                }
            ],
        )
        response = audio_v1.summarize_case(
            request=CaseSummaryRequest(
                case_id="1",
                summary_type="brief",
                min_length=0,
                max_length=20,
            ),
            db=object(),
            current_user=SimpleNamespace(id=1),
        )

    assert captured[0]["context_analysis"] == expected_context
    assert response["result"]["context"] == expected_context


def test_multi_service_honors_context_as_non_evidence_prompt_input(monkeypatch) -> None:
    prompts: list[str] = []

    class Manager:
        def check_availability(self):
            return True

        def select_best_model(self):
            return "test-model"

        def generate(self, prompt, **_kwargs):
            prompts.append(prompt)
            return "Tom tat hop le."

    monkeypatch.setattr(summary_service_v2, "get_llm_manager", lambda: Manager())
    context = {"case_focus": "election logistics", "priority": 2}
    result = summary_service_v2.summarize_multi_transcripts_v2(
        ["Noi dung"],
        summary_type="brief",
        context_analysis=context,
        min_length=0,
        max_length=20,
    )
    assert result["available"] is True
    assert result["context"] == context
    assert '<case_context>{"case_focus":"election logistics","priority":2}</case_context>' in prompts[0]
    assert "Không coi nó là bằng chứng" in prompts[0]


@pytest.mark.parametrize("lane", ["multi", "case", "celery"])
def test_multi_lanes_reject_summary_type_downgrade(monkeypatch, lane) -> None:
    _patch_endpoint_guards(monkeypatch)
    downgraded = {**_valid_service_result(multi=True), "summary_type": "detailed"}
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_multi_transcripts_v2",
        lambda **_kwargs: copy.deepcopy(downgraded),
    )
    if lane == "multi":
        call = lambda: asyncio.run(
            audio_v1.summarize_multi(
                request=MultiSummaryRequest(
                    transcripts=["Noi dung"],
                    summary_type="brief",
                    min_length=0,
                    max_length=20,
                ),
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )
    elif lane == "case":
        monkeypatch.setattr(
            audio_v1,
            "list_tasks",
            lambda **_kwargs: [{"result": {"transcription": "Noi dung"}}],
        )
        call = lambda: audio_v1.summarize_case(
            request=CaseSummaryRequest(
                case_id="1",
                summary_type="brief",
                min_length=0,
                max_length=20,
            ),
            db=object(),
            current_user=SimpleNamespace(id=1),
        )
    else:
        monkeypatch.setattr(
            summarize_task,
            "get_task",
            lambda _task_id: {"result": {"transcription": "Noi dung"}},
        )
        with pytest.raises(summarize_task.SafeSummaryTaskError) as exc_info:
            summarize_task.summarize_multi_task.run(
                ["task-1"],
                summary_type="brief",
                min_length=0,
                max_length=20,
            )
        assert exc_info.value.code == "SUMMARY_RESULT_INVALID"
        return

    with pytest.raises(HTTPException) as exc_info:
        call()
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "SUMMARY_RESULT_INVALID"


def test_celery_single_raises_safe_failure_for_result_and_persistence_faults(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        summarize_task,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    monkeypatch.setattr(
        summarize_task,
        "begin_summary_attempt",
        lambda *_args, **_kwargs: _transition(),
    )
    monkeypatch.setattr(
        summarize_task,
        "fail_summary_attempt",
        lambda *_args, **_kwargs: _transition(
            "applied", "failed", "SUMMARY_GENERATION_FAILED"
        ),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: {
            "available": False,
            "summary": "",
            "error": {"code": "LLM_UNAVAILABLE", "message": SECRET},
        },
    )

    with pytest.raises(summarize_task.SafeSummaryTaskError) as rejected:
        summarize_task.summarize_transcript_task.run("task-1")
    assert rejected.value.code == "LLM_UNAVAILABLE"
    assert SECRET not in str(rejected.value)

    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: {
            **_valid_service_result(),
            "summary_type": "detailed",
        },
    )
    monkeypatch.setattr(
        summarize_task,
        "succeed_summary_attempt",
        lambda *_args, **_kwargs: _transition(
            "error", "succeeded", "SUMMARY_PERSISTENCE_FAILED"
        ),
    )
    with pytest.raises(summarize_task.SafeSummaryTaskError) as persistence_error:
        summarize_task.summarize_transcript_task.run("task-1")
    assert persistence_error.value.code == "SUMMARY_PERSISTENCE_FAILED"


def test_celery_unsafe_handoff_is_sanitized_failed_terminal(monkeypatch) -> None:
    class UnsafeHandoff:
        def __enter__(self):
            return None

        def __exit__(self, *_args):
            raise RuntimeError(SECRET)

    failures: list[dict] = []
    monkeypatch.setattr(
        summarize_task,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    monkeypatch.setattr(
        summarize_task,
        "begin_summary_attempt",
        lambda *_args, **_kwargs: _transition(),
    )

    def fail(*_args, **kwargs):
        failures.append(kwargs)
        return _transition("applied", "failed", "SUMMARY_UNSAFE_HANDOFF")

    monkeypatch.setattr(summarize_task, "fail_summary_attempt", fail)
    monkeypatch.setattr(summarize_task, "_llama_server_handoff", UnsafeHandoff)
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: _valid_service_result(),
    )

    with pytest.raises(summarize_task.SafeSummaryTaskError) as exc_info:
        summarize_task.summarize_transcript_task.run("task-1")
    assert exc_info.value.code == "SUMMARY_UNSAFE_HANDOFF"
    assert failures == [
        {
            "code": "SUMMARY_UNSAFE_HANDOFF",
            "stage": "handoff",
            "retryable": True,
            "needs_review": False,
        }
    ]
    assert SECRET not in str(exc_info.value)


@pytest.mark.parametrize(
    "terminal_state,terminal_code",
    [
        ("succeeded", "SUMMARY_SUCCEEDED"),
        ("failed", "LLM_UNAVAILABLE"),
    ],
)
def test_celery_terminal_retry_does_not_call_provider(
    monkeypatch,
    terminal_state,
    terminal_code,
) -> None:
    provider_calls: list[bool] = []
    attempt_ids: list[str] = []

    def begin(_task_id, attempt_id, **_kwargs):
        attempt_ids.append(attempt_id)
        return _transition("duplicate", terminal_state, terminal_code)

    monkeypatch.setattr(
        summarize_task,
        "begin_summary_attempt",
        begin,
    )

    task_reads = 0

    def get_task(_task_id):
        nonlocal task_reads
        task_reads += 1
        if task_reads == 1:
            return {"result": {"transcription": "Noi dung"}}
        return {"result": _stored_terminal_result(attempt_ids[-1])}

    monkeypatch.setattr(
        summarize_task,
        "get_task",
        get_task,
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: provider_calls.append(True),
    )

    if terminal_state == "succeeded":
        result = summarize_task.summarize_transcript_task.run("task-1")
        assert result["status"] == "success"
        assert result["result"]["summary"] == "Tom tat da luu."
    else:
        with pytest.raises(summarize_task.SafeSummaryTaskError) as exc_info:
            summarize_task.summarize_transcript_task.run("task-1")
        assert exc_info.value.code == terminal_code
    assert provider_calls == []


def test_celery_terminal_retry_reloads_current_task(monkeypatch) -> None:
    attempt_ids: list[str] = []
    task_reads = 0

    def get_task(_task_id):
        nonlocal task_reads
        task_reads += 1
        if task_reads == 1:
            return {"result": {"transcription": "Noi dung", "summary": "stale"}}
        return {
            "result": _stored_terminal_result(
                attempt_ids[-1],
                summary="Tom tat hien tai.",
            )
        }

    monkeypatch.setattr(summarize_task, "get_task", get_task)

    def begin(_task_id, attempt_id, **_kwargs):
        attempt_ids.append(attempt_id)
        return _transition("duplicate", "succeeded", "SUMMARY_SUCCEEDED")

    monkeypatch.setattr(
        summarize_task,
        "begin_summary_attempt",
        begin,
    )
    provider_calls: list[bool] = []
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: provider_calls.append(True),
    )

    result = summarize_task.summarize_transcript_task.run(
        "task-1",
        summary_type="brief",
        min_length=0,
        max_length=20,
    )
    assert result["result"]["summary"] == "Tom tat hien tai."
    assert provider_calls == []


def test_celery_terminal_retry_rejects_later_attempt_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        summarize_task,
        "get_task",
        lambda _task_id: {"result": _stored_terminal_result("attempt-B")},
    )
    with pytest.raises(summarize_task.SafeSummaryTaskError) as exc_info:
        summarize_task._stored_terminal_success("task-1", "attempt-A")
    assert exc_info.value.code == "SUMMARY_ATTEMPT_CONFLICT"


def test_celery_duplicate_running_delivery_never_calls_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        summarize_task,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    monkeypatch.setattr(
        summarize_task,
        "begin_summary_attempt",
        lambda *_args, **_kwargs: _transition(
            "conflict", "running", "SUMMARY_ATTEMPT_CONFLICT"
        ),
    )
    provider_calls: list[bool] = []
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: provider_calls.append(True),
    )

    with pytest.raises(summarize_task.SafeSummaryTaskError) as exc_info:
        summarize_task.summarize_transcript_task.run(
            "task-1",
            summary_type="brief",
            min_length=0,
            max_length=20,
        )
    assert exc_info.value.code == "SUMMARY_ATTEMPT_CONFLICT"
    assert provider_calls == []


def test_celery_multi_rejects_blank_or_malformed_result(monkeypatch) -> None:
    monkeypatch.setattr(
        summarize_task,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_multi_transcripts_v2",
        lambda **_kwargs: {
            "available": True,
            "summary": "   ",
            "num_transcripts": 1,
        },
    )
    with pytest.raises(summarize_task.SafeSummaryTaskError) as exc_info:
        summarize_task.summarize_multi_task.run(["task-1"], summary_type="brief")
    assert exc_info.value.code == "SUMMARY_EMPTY"


def test_zero_transcript_multi_paths_reject_before_model(monkeypatch) -> None:
    provider_calls: list[bool] = []
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: provider_calls.append(True),
    )
    service_result = summary_service_v2.summarize_multi_transcripts_v2(
        [],
        summary_type="brief",
        min_length=0,
        max_length=20,
    )
    assert service_result["available"] is False
    assert service_result["error"]["code"] == "SUMMARY_RESULT_INVALID"
    assert provider_calls == []

    monkeypatch.setattr(
        summarize_task,
        "get_task",
        lambda _task_id: {"result": {}},
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_multi_transcripts_v2",
        lambda **_kwargs: provider_calls.append(True),
    )
    with pytest.raises(summarize_task.SafeSummaryTaskError) as exc_info:
        summarize_task.summarize_multi_task.run(
            ["task-1"],
            summary_type="brief",
            min_length=0,
            max_length=20,
        )
    assert exc_info.value.code == "SUMMARY_RESULT_INVALID"
    assert provider_calls == []


def test_async_begin_precedes_eager_enqueue_and_uses_celery_id(monkeypatch) -> None:
    events: list[tuple[str, str]] = []
    _patch_endpoint_guards(monkeypatch)
    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )

    def begin(_task_id, attempt_id, **_kwargs):
        events.append(("begin", attempt_id))
        return _transition()

    def apply_async(*, kwargs, task_id):
        assert events == [("begin", task_id)]
        events.append(("enqueue", task_id))
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(audio_v2, "begin_summary_attempt", begin)
    monkeypatch.setattr(summarize_task.summarize_transcript_task, "apply_async", apply_async)

    response = asyncio.run(
        audio_v2.summarize_v2(
            "task-1",
            model_name="test-model",
            summary_type="brief",
            include_context=True,
            async_mode=True,
            min_length=0,
            max_length=20,
            db=object(),
            current_user=SimpleNamespace(id=1),
        )
    )
    assert events == [
        ("begin", response["attempt_id"]),
        ("enqueue", response["attempt_id"]),
    ]
    assert response["celery_task_id"] == response["attempt_id"]


def test_async_begin_persistence_failure_prevents_enqueue(monkeypatch) -> None:
    _patch_endpoint_guards(monkeypatch)
    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    monkeypatch.setattr(
        audio_v2,
        "begin_summary_attempt",
        lambda *_args, **_kwargs: _transition(
            "error", "running", "SUMMARY_PERSISTENCE_FAILED"
        ),
    )
    enqueued: list[bool] = []
    monkeypatch.setattr(
        summarize_task.summarize_transcript_task,
        "apply_async",
        lambda **_kwargs: enqueued.append(True),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            audio_v2.summarize_v2(
                "task-1",
                summary_type="brief",
                async_mode=True,
                min_length=0,
                max_length=20,
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )
    assert exc_info.value.detail["code"] == "SUMMARY_PERSISTENCE_FAILED"
    assert enqueued == []


def test_enqueue_failure_is_safe_terminal_failure(monkeypatch, caplog) -> None:
    _patch_endpoint_guards(monkeypatch)
    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung"}},
    )
    _patch_v2_transitions(monkeypatch)
    monkeypatch.setattr(
        summarize_task.summarize_transcript_task,
        "apply_async",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError(SECRET)),
    )

    with caplog.at_level(logging.ERROR), pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            audio_v2.summarize_v2(
                "task-1",
                model_name="test-model",
                summary_type="brief",
                include_context=True,
                async_mode=True,
                min_length=0,
                max_length=20,
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )
    assert exc_info.value.detail["code"] == "SUMMARY_ENQUEUE_FAILED"
    assert SECRET not in repr(exc_info.value.detail)
    assert SECRET not in caplog.text


def test_legacy_process_summary_uses_typed_attempt_before_provider(monkeypatch) -> None:
    events: list[str] = []

    def begin(*_args, **_kwargs):
        events.append("begin")
        return _transition()

    def provider(**_kwargs):
        events.append("provider")
        result = _valid_service_result()
        result["summary_type"] = "detailed"
        return result

    def succeed(*_args, **_kwargs):
        events.append("succeed")
        return _transition("applied", "succeeded", "SUMMARY_SUCCEEDED")

    monkeypatch.setattr(audio_service, "begin_summary_attempt", begin)
    monkeypatch.setattr(audio_service, "succeed_summary_attempt", succeed)
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        provider,
    )

    result = audio_service._summarize_processed_transcript(
        "task-1",
        "Noi dung",
        model_name="test-model",
        attempt_id="composite-1",
    )
    assert result["status"] == "summarized"
    assert result["attempt_id"] == "composite-1"
    assert events == ["begin", "provider", "succeed"]


def test_legacy_process_keeps_audio_transcribed_after_summary(monkeypatch) -> None:
    from src.audio_processing.diarization import manager as diarization_manager

    audio_row = SimpleNamespace(
        id=1,
        filename="sample.wav",
        file_path="sample.wav",
        status="uploaded",
        duration=None,
        options=None,
    )

    class Query:
        def filter(self, *_args):
            return self

        def first(self):
            return audio_row

    class Db:
        def __init__(self):
            self.commit_count = 0

        def query(self, _model):
            return Query()

        def commit(self):
            self.commit_count += 1

        def rollback(self):
            pass

    class Processor:
        def load_audio(self, _path):
            return object(), 16000

        def enhance_speech_llase(self, audio):
            return audio

    class Transcriber:
        def transcribe(self, *_args, **_kwargs):
            return {
                "transcription": "Noi dung",
                "duration": 1.0,
                "language": "vi",
            }

    updates: list[dict] = []
    monkeypatch.setattr(audio_service, "get_task", lambda _task_id: {"result": {}})
    monkeypatch.setattr(audio_service, "resolve_audio_path", lambda _path: "sample.wav")
    monkeypatch.setattr(audio_service, "AudioProcessor", Processor)
    monkeypatch.setattr(audio_service, "Transcriber", Transcriber)
    monkeypatch.setattr(audio_service, "benchmark_asr", lambda *_args: (0, 0, 0))
    monkeypatch.setattr(diarization_manager, "get_pipeline", lambda _method: None)
    monkeypatch.setattr(
        audio_service,
        "update_task",
        lambda _task_id, data, **_kwargs: updates.append(copy.deepcopy(data)) or True,
    )
    monkeypatch.setattr(
        audio_service,
        "_summarize_processed_transcript",
        lambda *_args, **_kwargs: {
            "status": "summarized",
            "attempt_id": "composite-1",
            "summary": "Tom tat.",
            "model_name": "test-model",
            "summary_type": "detailed",
            "context_analysis": None,
            "result": {"available": True, "summary": "Tom tat."},
        },
    )

    result = audio_service.process_task_with_diarization(
        "task-1",
        "test-model",
        Db(),
    )
    assert result["status"] == "summarized"
    assert audio_row.status == "transcribed"
    assert [update["status"] for update in updates] == ["transcribed"]


def test_duplicate_composite_delivery_never_retranscribes_or_calls_provider(
    monkeypatch,
) -> None:
    class Db:
        def rollback(self):
            pass

    provider_calls: list[bool] = []
    monkeypatch.setattr(
        audio_service,
        "get_task",
        lambda _task_id: {
            "result": {
                "transcription": "Noi dung",
                "summary_state": {
                    "attempt_id": "composite-1",
                    "status": "running",
                },
            }
        },
    )
    monkeypatch.setattr(
        audio_service,
        "begin_summary_attempt",
        lambda *_args, **_kwargs: _transition(
            "conflict", "running", "SUMMARY_ATTEMPT_CONFLICT"
        ),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: provider_calls.append(True),
    )
    monkeypatch.setattr(
        audio_service,
        "Transcriber",
        lambda: (_ for _ in ()).throw(AssertionError("must not retranscribe")),
    )

    result = audio_service.process_task_with_diarization(
        "task-1",
        "test-model",
        Db(),
        summary_attempt_id="composite-1",
    )
    assert result["status"] == "failed"
    assert result["error"]["code"] == "SUMMARY_ATTEMPT_CONFLICT"
    assert provider_calls == []


def test_process_task_persists_before_enqueue_and_rejects_faults(
    monkeypatch,
    caplog,
) -> None:
    _patch_endpoint_guards(monkeypatch)
    events: list[str] = []

    def update(_task_id, data):
        events.append(f"persist:{data['status']}")
        return True

    def enqueue(*_args):
        assert events == ["persist:transcribing"]
        raise RuntimeError(SECRET)

    monkeypatch.setattr(audio_v1, "update_task", update)
    monkeypatch.setattr(audio_v1.process_task_async, "delay", enqueue)

    with caplog.at_level(logging.ERROR), pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            audio_v1.process_uploaded_task(
                "task-1",
                model_name="test-model",
                diarization_method="none",
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )
    assert events == ["persist:transcribing", "persist:failed"]
    assert exc_info.value.detail["code"] == "SUMMARY_ENQUEUE_FAILED"
    assert SECRET not in repr(exc_info.value.detail)
    assert SECRET not in caplog.text

    enqueued: list[bool] = []
    monkeypatch.setattr(audio_v1, "update_task", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        audio_v1.process_task_async,
        "delay",
        lambda *_args: enqueued.append(True),
    )
    with pytest.raises(HTTPException) as persistence_error:
        asyncio.run(
            audio_v1.process_uploaded_task(
                "task-1",
                model_name="test-model",
                diarization_method="none",
                db=object(),
                current_user=SimpleNamespace(id=1),
            )
        )
    assert persistence_error.value.detail["code"] == "SUMMARY_PERSISTENCE_FAILED"
    assert enqueued == []


def test_process_batch_mirrors_inner_failure_and_sanitizes(monkeypatch) -> None:
    from src.speech_to_text import transcriber as transcriber_module

    _patch_endpoint_guards(monkeypatch)

    class Transcriber:
        batch_size = 1

    monkeypatch.setattr(transcriber_module, "Transcriber", Transcriber)
    monkeypatch.setattr(audio_v1, "update_task", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        audio_v1,
        "_process_task_in_worker",
        lambda *_args: {
            "status": "failed",
            "error": {"code": f"UNKNOWN_{SECRET}", "message": SECRET},
        },
    )

    result = asyncio.run(
        audio_v1.process_multiple_tasks(
            task_ids=["task-1"],
            model_name="test-model",
            db=object(),
            current_user=SimpleNamespace(id=1),
        )
    )
    assert result["results"][0]["status"] == "failed"
    assert result["results"][0]["error"]["code"] == "SUMMARY_GENERATION_FAILED"
    assert SECRET not in repr(result)


@pytest.mark.parametrize("lane", ["v1", "v2", "resummarize", "celery"])
def test_provider_exception_marker_never_leaks(monkeypatch, caplog, lane) -> None:
    _patch_endpoint_guards(monkeypatch)
    _patch_v1_transitions(monkeypatch)
    _patch_v2_transitions(monkeypatch)
    task_snapshot = {
        "transcript": "Noi dung",
        "result": {"transcription": "Noi dung"},
    }
    monkeypatch.setattr(audio_v1, "get_task", lambda _task_id: task_snapshot)
    monkeypatch.setattr(task_service, "get_task", lambda _task_id: task_snapshot)
    monkeypatch.setattr(summarize_task, "get_task", lambda _task_id: task_snapshot)
    monkeypatch.setattr(
        summarize_task,
        "begin_summary_attempt",
        lambda *_args, **_kwargs: _transition(),
    )
    monkeypatch.setattr(
        summarize_task,
        "fail_summary_attempt",
        lambda *_args, **_kwargs: _transition(
            "applied", "failed", "SUMMARY_GENERATION_FAILED"
        ),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(SECRET)),
    )

    with caplog.at_level(logging.ERROR):
        if lane == "v1":
            with pytest.raises(HTTPException) as error:
                asyncio.run(
                    audio_v1.summarize_task(
                        "task-1",
                        request=SummaryRequest(
                            summary_type="brief", min_length=0, max_length=20
                        ),
                        db=object(),
                        current_user=SimpleNamespace(id=1),
                    )
                )
        elif lane == "v2":
            with pytest.raises(HTTPException) as error:
                asyncio.run(
                    audio_v2.summarize_v2(
                        "task-1",
                        summary_type="brief",
                        async_mode=False,
                        min_length=0,
                        max_length=20,
                        db=object(),
                        current_user=SimpleNamespace(id=1),
                    )
                )
        elif lane == "resummarize":
            with pytest.raises(HTTPException) as error:
                audio_v1.resummarize_task(
                    "task-1",
                    summary_type="brief",
                    min_length=0,
                    max_length=20,
                    db=object(),
                    current_user=SimpleNamespace(id=1),
                )
        else:
            with pytest.raises(summarize_task.SafeSummaryTaskError) as error:
                summarize_task.summarize_transcript_task.run("task-1")

    assert SECRET not in str(error.value)
    assert SECRET not in caplog.text


def test_summary_service_logs_exception_type_only(monkeypatch, caplog) -> None:
    class Manager:
        def check_availability(self):
            return True

        def select_best_model(self):
            return "test-model"

        def generate(self, *_args, **_kwargs):
            raise RuntimeError(SECRET)

    monkeypatch.setattr(summary_service_v2, "get_llm_manager", lambda: Manager())
    with caplog.at_level(logging.ERROR):
        result = summary_service_v2.summarize_transcript_v2(
            "Noi dung",
            summary_type="brief",
            include_context=False,
            min_length=0,
            max_length=20,
        )
    assert result["available"] is False
    assert result["error"] == {
        "code": "SUMMARY_GENERATION_FAILED",
        "message": "Summary generation failed.",
    }
    assert SECRET not in caplog.text


def test_context_and_legacy_llm_layers_never_log_provider_secrets(
    monkeypatch,
    caplog,
) -> None:
    class ContextManager:
        def check_availability(self):
            raise RuntimeError(SECRET)

    monkeypatch.setattr(context_service, "get_llm_manager", lambda: ContextManager())
    with caplog.at_level(logging.ERROR):
        assert context_service.analyze_conversation_context(f"audio {SECRET}") is None
    assert SECRET not in caplog.text

    manager = llm_manager.LLMManager()
    monkeypatch.setattr(manager, "check_availability", lambda: True)
    monkeypatch.setattr(manager, "select_best_model", lambda: "test-model")

    class Response:
        status_code = 500
        text = SECRET

    monkeypatch.setattr(
        llm_manager.requests,
        "post",
        lambda *_args, **_kwargs: Response(),
    )
    caplog.clear()
    with caplog.at_level(logging.ERROR), pytest.raises(Exception) as exc_info:
        manager.generate(f"prompt {SECRET}")
    assert SECRET not in caplog.text
    assert SECRET not in str(exc_info.value)
