"""Safe recovery helpers for Summary tasks left in a stale running state."""

from __future__ import annotations

import ast
import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from src.database.models.models import Task as DBTask
from src.services.task_service import update_task
from src.worker.runtime_contract import SUMMARY_TASK_NAME


STALE_SUMMARY_ERROR_CODE = "SUMMARY_ATTEMPT_STALE"
STALE_SUMMARY_ERROR_MESSAGE = (
    "The summary attempt exceeded the recovery threshold and no active worker owns it."
)


@dataclass(frozen=True)
class WorkerActivity:
    worker_names: tuple[str, ...]
    summary_task_ids: frozenset[str]
    errors: tuple[str, ...] = ()

    @property
    def worker_replies(self) -> int:
        return len(self.worker_names)


@dataclass
class ReconciliationReport:
    cutoff_utc: str
    apply: bool
    candidates: list[str] = field(default_factory=list)
    reconciled: list[str] = field(default_factory=list)
    skipped_active: list[str] = field(default_factory=list)
    skipped_has_summary: list[str] = field(default_factory=list)
    skipped_changed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconciliation_apply_refusal_reason(
    activity: WorkerActivity,
    *,
    allow_no_workers: bool,
) -> str | None:
    if activity.worker_replies == 0 and not allow_no_workers:
        return (
            "no Celery worker replied; pass --allow-no-workers only after "
            "verifying workers are stopped"
        )
    return None


def _literal_collection(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def _request_payload(entry: object) -> Mapping[str, Any] | None:
    if not isinstance(entry, Mapping):
        return None
    request = entry.get("request")
    if isinstance(request, Mapping):
        return request
    return entry


def extract_active_summary_task_ids(replies: Iterable[object]) -> frozenset[str]:
    task_ids: set[str] = set()
    for reply in replies:
        if not isinstance(reply, Mapping):
            continue
        for entries in reply.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                request = _request_payload(entry)
                if request is None or request.get("name") != SUMMARY_TASK_NAME:
                    continue
                kwargs = _literal_collection(request.get("kwargs"))
                args = _literal_collection(request.get("args"))
                task_id: object = None
                if isinstance(kwargs, Mapping):
                    task_id = kwargs.get("task_id")
                if task_id is None and isinstance(args, (list, tuple)) and args:
                    task_id = args[0]
                if isinstance(task_id, str) and task_id.strip():
                    task_ids.add(task_id)
    return frozenset(task_ids)


def inspect_worker_activity(celery_app: Any, timeout_seconds: float) -> WorkerActivity:
    inspector = celery_app.control.inspect(timeout=timeout_seconds)
    replies: list[Mapping[str, Any]] = []
    worker_names: set[str] = set()
    errors: list[str] = []
    for state_name in ("active", "reserved", "scheduled"):
        try:
            response = getattr(inspector, state_name)()
        except Exception as exc:
            errors.append(f"{state_name}:{type(exc).__name__}")
            continue
        if not isinstance(response, Mapping):
            continue
        replies.append(response)
        worker_names.update(str(name) for name in response)
    return WorkerActivity(
        worker_names=tuple(sorted(worker_names)),
        summary_task_ids=extract_active_summary_task_ids(replies),
        errors=tuple(errors),
    )


def stale_cutoff(now_utc: datetime, older_than_seconds: int) -> datetime:
    if older_than_seconds < 60:
        raise ValueError("older_than_seconds must be at least 60")
    return now_utc - timedelta(seconds=older_than_seconds)


def _is_stale(task: DBTask, cutoff_utc: datetime) -> bool:
    observed = task.updated_at or task.created_at
    return (
        task.status == "summarizing"
        and isinstance(observed, datetime)
        and observed < cutoff_utc
    )


def _has_completed_summary(task: DBTask) -> bool:
    result = task.result if isinstance(task.result, dict) else {}
    summary = result.get("summary")
    return isinstance(summary, str) and bool(summary.strip())


def _failure_patch(task: DBTask, reconciled_at: datetime) -> dict[str, Any]:
    result = copy.deepcopy(task.result) if isinstance(task.result, dict) else {}
    runtime = result.get("summary_runtime")
    if not isinstance(runtime, dict):
        runtime = {}
    runtime = {
        **runtime,
        "reconciliation": {
            "code": STALE_SUMMARY_ERROR_CODE,
            "reconciled_at": reconciled_at.isoformat() + "Z",
        },
    }
    return {
        "status": "failed",
        "error": STALE_SUMMARY_ERROR_MESSAGE,
        "result": {
            "summary": None,
            "summary_state": "unavailable",
            "summary_error": {
                "code": STALE_SUMMARY_ERROR_CODE,
                "message": STALE_SUMMARY_ERROR_MESSAGE,
            },
            "summary_notice": {
                "code": STALE_SUMMARY_ERROR_CODE,
                "severity": "error",
                "message": STALE_SUMMARY_ERROR_MESSAGE,
                "retryable": True,
                "next_action": "verify_worker_contract_then_retry",
            },
            "summary_preview": None,
            "summary_runtime": runtime,
        },
    }


def reconcile_stale_summary_tasks(
    db: Session,
    *,
    cutoff_utc: datetime,
    active_task_ids: frozenset[str] = frozenset(),
    task_ids: frozenset[str] | None = None,
    apply: bool = False,
    now_utc: datetime | None = None,
) -> ReconciliationReport:
    """Plan or atomically fail stale Summary attempts that have no active owner."""

    now_utc = now_utc or datetime.utcnow()
    report = ReconciliationReport(cutoff_utc=cutoff_utc.isoformat() + "Z", apply=apply)
    age_filter = or_(
        DBTask.updated_at < cutoff_utc,
        and_(DBTask.updated_at.is_(None), DBTask.created_at < cutoff_utc),
    )
    query = db.query(DBTask).filter(DBTask.status == "summarizing", age_filter)
    if task_ids is not None:
        if not task_ids:
            return report
        query = query.filter(DBTask.id.in_(sorted(task_ids)))
    candidate_rows = query.order_by(DBTask.id).all()
    candidate_ids = [task.id for task in candidate_rows]
    report.candidates.extend(candidate_ids)

    for task in candidate_rows:
        task_id = task.id
        if task_id in active_task_ids:
            report.skipped_active.append(task_id)
            continue
        if _has_completed_summary(task):
            report.skipped_has_summary.append(task_id)
            continue
        if not apply:
            continue

        locked = (
            db.query(DBTask)
            .filter(DBTask.id == task_id)
            .with_for_update()
            .first()
        )
        if locked is None or not _is_stale(locked, cutoff_utc):
            report.skipped_changed.append(task_id)
            continue
        if task_id in active_task_ids:
            report.skipped_active.append(task_id)
            continue
        if _has_completed_summary(locked):
            report.skipped_has_summary.append(task_id)
            continue
        if not update_task(
            task_id,
            _failure_patch(locked, now_utc),
            db=db,
        ):
            raise RuntimeError(f"failed to reconcile Summary task {task_id}")
        report.reconciled.append(task_id)

    if apply:
        db.commit()
    return report


__all__ = [
    "ReconciliationReport",
    "STALE_SUMMARY_ERROR_CODE",
    "STALE_SUMMARY_ERROR_MESSAGE",
    "WorkerActivity",
    "extract_active_summary_task_ids",
    "inspect_worker_activity",
    "reconciliation_apply_refusal_reason",
    "reconcile_stale_summary_tasks",
    "stale_cutoff",
]
