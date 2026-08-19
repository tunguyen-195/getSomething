from __future__ import annotations

from datetime import datetime, timedelta

from src.database.config.database import SessionLocal
from src.database.models.models import Task as DBTask
from src.worker.summary_reconciliation import (
    STALE_SUMMARY_ERROR_CODE,
    WorkerActivity,
    extract_active_summary_task_ids,
    inspect_worker_activity,
    reconciliation_apply_refusal_reason,
    reconcile_stale_summary_tasks,
    stale_cutoff,
)


def _insert_task(
    task_id: str,
    *,
    updated_at: datetime,
    summary: str | None = None,
) -> None:
    with SessionLocal() as db:
        db.add(
            DBTask(
                id=task_id,
                filename=f"{task_id}.wav",
                status="summarizing",
                result={
                    "transcription": "Nội dung transcript phải được giữ nguyên.",
                    "summary": summary,
                    "summary_state": "grounded_transcript_only",
                    "summary_preview": {
                        "text": "Bản xem trước không được giữ như Summary."
                    },
                },
                error=None,
                created_at=updated_at - timedelta(minutes=1),
                updated_at=updated_at,
                user_id=1,
            )
        )
        db.commit()


def test_extract_active_summary_task_ids_handles_celery_payload_shapes() -> None:
    replies = [
        {
            "worker-a": [
                {
                    "name": "tasks.summarize_transcript",
                    "args": [],
                    "kwargs": {"task_id": "task-from-kwargs"},
                },
                {
                    "name": "tasks.transcribe_audio",
                    "args": ["ignored"],
                    "kwargs": {},
                },
            ]
        },
        {
            "worker-b": [
                {
                    "request": {
                        "name": "tasks.summarize_transcript",
                        "args": "('task-from-string-args',)",
                        "kwargs": "{}",
                    }
                }
            ]
        },
    ]

    assert extract_active_summary_task_ids(replies) == frozenset(
        {"task-from-kwargs", "task-from-string-args"}
    )


def test_stale_cutoff_rejects_aggressive_threshold() -> None:
    try:
        stale_cutoff(datetime.utcnow(), 59)
    except ValueError as exc:
        assert "at least 60" in str(exc)
    else:
        raise AssertionError("unsafe stale threshold was accepted")


def test_apply_refuses_unverified_no_worker_state() -> None:
    no_workers = WorkerActivity(worker_names=(), summary_task_ids=frozenset())

    assert reconciliation_apply_refusal_reason(
        no_workers,
        allow_no_workers=False,
    )
    assert (
        reconciliation_apply_refusal_reason(
            no_workers,
            allow_no_workers=True,
        )
        is None
    )


def test_worker_activity_collects_active_reserved_and_scheduled_tasks() -> None:
    class Inspector:
        def active(self):
            return {
                "worker-a": [
                    {
                        "name": "tasks.summarize_transcript",
                        "kwargs": {"task_id": "active-summary"},
                        "args": [],
                    }
                ]
            }

        def reserved(self):
            return {
                "worker-a": [
                    {
                        "name": "tasks.summarize_transcript",
                        "kwargs": {},
                        "args": ["reserved-summary"],
                    }
                ]
            }

        def scheduled(self):
            return {
                "worker-a": [
                    {
                        "request": {
                            "name": "tasks.summarize_transcript",
                            "kwargs": "{'task_id': 'scheduled-summary'}",
                            "args": "[]",
                        }
                    }
                ]
            }

    class Control:
        def inspect(self, timeout):
            assert timeout == 2.0
            return Inspector()

    class App:
        control = Control()

    activity = inspect_worker_activity(App(), 2.0)

    assert activity.worker_names == ("worker-a",)
    assert activity.summary_task_ids == frozenset(
        {"active-summary", "reserved-summary", "scheduled-summary"}
    )
    assert activity.errors == ()


def test_reconciliation_dry_run_does_not_mutate_task() -> None:
    now = datetime.utcnow()
    _insert_task("stale-dry-run", updated_at=now - timedelta(hours=1))

    with SessionLocal() as db:
        report = reconcile_stale_summary_tasks(
            db,
            cutoff_utc=now - timedelta(minutes=15),
            apply=False,
            now_utc=now,
        )
        task = db.query(DBTask).filter(DBTask.id == "stale-dry-run").one()

    assert report.candidates == ["stale-dry-run"]
    assert report.reconciled == []
    assert task.status == "summarizing"


def test_reconciliation_fails_preview_only_task_and_preserves_transcript() -> None:
    now = datetime.utcnow()
    _insert_task("stale-preview", updated_at=now - timedelta(hours=1))

    with SessionLocal() as db:
        report = reconcile_stale_summary_tasks(
            db,
            cutoff_utc=now - timedelta(minutes=15),
            apply=True,
            now_utc=now,
        )

    with SessionLocal() as db:
        task = db.query(DBTask).filter(DBTask.id == "stale-preview").one()
        result = task.result

    assert report.reconciled == ["stale-preview"]
    assert task.status == "failed"
    assert result["transcription"] == "Nội dung transcript phải được giữ nguyên."
    assert result["summary"] is None
    assert result["summary_preview"] is None
    assert result["summary_state"] == "unavailable"
    assert result["summary_error"]["code"] == STALE_SUMMARY_ERROR_CODE
    assert result["summary_notice"]["retryable"] is True


def test_reconciliation_skips_active_and_completed_summary_tasks() -> None:
    now = datetime.utcnow()
    old = now - timedelta(hours=1)
    _insert_task("stale-active", updated_at=old)
    _insert_task(
        "stale-with-summary",
        updated_at=old,
        summary="Bản tin điều tra đã có nội dung.",
    )

    with SessionLocal() as db:
        report = reconcile_stale_summary_tasks(
            db,
            cutoff_utc=now - timedelta(minutes=15),
            active_task_ids=frozenset({"stale-active"}),
            apply=True,
            now_utc=now,
        )

    assert report.skipped_active == ["stale-active"]
    assert report.skipped_has_summary == ["stale-with-summary"]
    assert report.reconciled == []
