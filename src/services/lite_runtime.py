from __future__ import annotations

import socket
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Literal

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.logging import logger
from src.database.config.database import SessionLocal
from src.database.models.models import RuntimeJobLease
from src.services.task_service import update_task


Operation = Literal["transcribe", "summarize", "visualize"]
LEASE_KEY = "single_machine_lite"
OWNER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"


def lite_runner_enabled() -> bool:
    return settings.PROCESSING_RUNNER == "single_job_db_lease"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _expires_at(now: datetime | None = None) -> datetime:
    now = now or _utcnow()
    return now + timedelta(seconds=settings.LITE_JOB_LEASE_TTL_SECONDS)


def _lease_to_dict(lease: RuntimeJobLease | None) -> dict[str, Any] | None:
    if not lease:
        return None
    return {
        "lease_key": lease.lease_key,
        "active_task_id": lease.active_task_id,
        "active_operation": lease.active_operation,
        "status": lease.status,
        "owner_id": lease.owner_id,
        "lease_expires_at": lease.lease_expires_at.isoformat() if lease.lease_expires_at else None,
        "heartbeat_at": lease.heartbeat_at.isoformat() if lease.heartbeat_at else None,
    }


def get_active_lease(db: Session) -> dict[str, Any] | None:
    lease = db.query(RuntimeJobLease).filter(RuntimeJobLease.lease_key == LEASE_KEY).first()
    if not lease or lease.status != "active":
        return None
    expires = _aware(lease.lease_expires_at)
    if expires and expires <= _utcnow():
        return None
    return _lease_to_dict(lease)


def acquire_lease(db: Session, *, task_id: str, operation: Operation) -> RuntimeJobLease:
    now = _utcnow()
    query = db.query(RuntimeJobLease).filter(RuntimeJobLease.lease_key == LEASE_KEY)
    if db.bind and db.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    lease = query.first()

    if lease is None:
        lease = RuntimeJobLease(
            lease_key=LEASE_KEY,
            status="active",
            active_task_id=task_id,
            active_operation=operation,
            owner_id=OWNER_ID,
            heartbeat_at=now,
            lease_expires_at=_expires_at(now),
        )
        db.add(lease)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Another job is active")
        return lease

    expires = _aware(lease.lease_expires_at)
    active = lease.status == "active" and expires and expires > now
    if active:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Busy",
                "active_task_id": lease.active_task_id,
                "active_operation": lease.active_operation,
                "lease_expires_at": lease.lease_expires_at.isoformat() if lease.lease_expires_at else None,
            },
        )

    lease.status = "active"
    lease.active_task_id = task_id
    lease.active_operation = operation
    lease.owner_id = OWNER_ID
    lease.heartbeat_at = now
    lease.lease_expires_at = _expires_at(now)
    return lease


def heartbeat_lease(db: Session, *, task_id: str) -> None:
    now = _utcnow()
    query = db.query(RuntimeJobLease).filter(RuntimeJobLease.lease_key == LEASE_KEY)
    if db.bind and db.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    lease = query.first()
    if not lease or lease.active_task_id != task_id or lease.owner_id != OWNER_ID:
        return
    lease.heartbeat_at = now
    lease.lease_expires_at = _expires_at(now)
    db.commit()


def release_lease(db: Session, *, task_id: str) -> None:
    query = db.query(RuntimeJobLease).filter(RuntimeJobLease.lease_key == LEASE_KEY)
    if db.bind and db.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    lease = query.first()
    if not lease or lease.active_task_id != task_id or lease.owner_id != OWNER_ID:
        return
    lease.status = "released"
    lease.active_task_id = None
    lease.active_operation = None
    lease.owner_id = None
    lease.lease_expires_at = None
    lease.heartbeat_at = _utcnow()
    db.commit()


def repair_expired_lite_jobs() -> None:
    if not lite_runner_enabled():
        return
    db = SessionLocal()
    try:
        now = _utcnow()
        leases = db.query(RuntimeJobLease).filter(RuntimeJobLease.status == "active").all()
        for lease in leases:
            expires = _aware(lease.lease_expires_at)
            if expires and expires > now:
                continue
            task_id = lease.active_task_id
            lease.status = "expired"
            lease.active_task_id = None
            lease.active_operation = None
            lease.owner_id = None
            if task_id:
                update_task(
                    task_id,
                    {
                        "status": "failed",
                        "error": "stale_job_after_restart",
                        "result": {"warnings": ["stale_job_after_restart"]},
                    },
                    db=db,
                )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("[LITE_RUNTIME] Failed to repair expired leases")
    finally:
        db.close()


@dataclass
class RunnerJob:
    runner_job_id: str
    task_id: str
    operation: Operation


def start_lite_job(
    *,
    db: Session,
    task_id: str,
    operation: Operation,
    target: Callable[..., Any],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    queued_status: str | None = None,
) -> RunnerJob:
    kwargs = kwargs or {}
    runner_job_id = uuid.uuid4().hex
    acquire_lease(db, task_id=task_id, operation=operation)
    if queued_status:
        update_task(task_id, {"status": queued_status}, db=db)
    db.commit()

    def run() -> None:
        stop_heartbeat = threading.Event()

        def heartbeat_loop() -> None:
            while not stop_heartbeat.wait(settings.LITE_JOB_HEARTBEAT_SECONDS):
                heartbeat_db = SessionLocal()
                try:
                    heartbeat_lease(heartbeat_db, task_id=task_id)
                except Exception:
                    logger.warning("[LITE_RUNTIME] Lease heartbeat failed | task_id=%s", task_id, exc_info=True)
                finally:
                    heartbeat_db.close()

        hb_thread = threading.Thread(target=heartbeat_loop, name=f"lite-heartbeat-{runner_job_id}", daemon=True)
        hb_thread.start()
        job_db = SessionLocal()
        try:
            target(*args, db=job_db, **kwargs)
        except Exception as exc:
            logger.error(
                "[LITE_RUNTIME] Background job failed | task_id=%s | operation=%s | error_class=%s",
                task_id,
                operation,
                exc.__class__.__name__,
                exc_info=True,
            )
            try:
                job_db.rollback()
                update_task(task_id, {"status": "failed", "error": str(exc)}, db=job_db)
                job_db.commit()
            except Exception:
                job_db.rollback()
                logger.exception("[LITE_RUNTIME] Failed to mark task failed | task_id=%s", task_id)
        finally:
            stop_heartbeat.set()
            release_db = SessionLocal()
            try:
                release_lease(release_db, task_id=task_id)
            except Exception:
                logger.warning("[LITE_RUNTIME] Lease release failed | task_id=%s", task_id, exc_info=True)
            finally:
                release_db.close()
                job_db.close()

    thread = threading.Thread(target=run, name=f"lite-job-{operation}-{runner_job_id}", daemon=True)
    thread.start()
    return RunnerJob(runner_job_id=runner_job_id, task_id=task_id, operation=operation)
