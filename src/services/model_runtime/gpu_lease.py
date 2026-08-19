"""Cross-process GPU lease for single-GPU offline deployments."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from src.core.config import settings


_PROCESS_LEASE_LOCK = threading.RLock()
_PROCESS_LEASE_STATE = threading.local()


class GpuLeaseTimeout(TimeoutError):
    """Raised when a GPU phase cannot acquire the host-wide lease in time."""


class GpuLeaseQuarantined(RuntimeError):
    """Raised when a prior GPU owner could not prove a safe handoff."""

    def __init__(self, snapshot: "GpuQuarantineSnapshot") -> None:
        self.snapshot = snapshot
        super().__init__(
            "GPU lease is quarantined: "
            f"reason={snapshot.reason} owner={snapshot.owner} "
            f"stage={snapshot.stage}. {snapshot.recovery}"
        )


class GpuQuarantineRecoveryError(RuntimeError):
    """Raised when quarantine verification cannot complete safely."""


@dataclass(frozen=True)
class GpuLeaseSnapshot:
    lease_id: str
    stage: str
    owner: str
    pid: int
    acquired_at: str
    waited_seconds: float


@dataclass(frozen=True)
class GpuQuarantineSnapshot:
    quarantine_id: str
    stage: str
    owner: str
    pid: int
    created_at: str
    updated_at: str
    reason: str
    verification_required: str
    allowed_stages: tuple[str, ...]
    recovery: str
    last_verification_error: str | None = None


def _resolve_lock_path(path: str | Path | None = None) -> Path:
    configured = Path(path or settings.GPU_LEASE_PATH)
    if configured.is_absolute():
        return configured
    repository_root = Path(__file__).resolve().parents[3]
    return (repository_root / configured).resolve()


def _quarantine_path(lock_path: Path) -> Path:
    return lock_path.with_suffix(f"{lock_path.suffix}.quarantine.json")


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex}"
    )
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_quarantine(lock_path: Path) -> GpuQuarantineSnapshot | None:
    path = _quarantine_path(lock_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return GpuQuarantineSnapshot(
            quarantine_id=str(payload["quarantine_id"]),
            stage=str(payload["stage"]),
            owner=str(payload["owner"]),
            pid=int(payload["pid"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            reason=str(payload["reason"]),
            verification_required=str(payload["verification_required"]),
            allowed_stages=tuple(str(item) for item in payload["allowed_stages"]),
            recovery=str(payload["recovery"]),
            last_verification_error=(
                str(payload["last_verification_error"])
                if payload.get("last_verification_error")
                else None
            ),
        )
    except FileNotFoundError:
        return None
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        try:
            created_at = datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat()
        except OSError:
            created_at = datetime.now(timezone.utc).isoformat()
        return GpuQuarantineSnapshot(
            quarantine_id="unreadable",
            stage="unknown",
            owner="unknown",
            pid=-1,
            created_at=created_at,
            updated_at=created_at,
            reason=f"quarantine metadata is unreadable: {type(exc).__name__}: {exc}",
            verification_required="llama_server_sleeping",
            allowed_stages=(),
            recovery=(
                "Confirm llama-server /props reports is_sleeping=true, then run "
                "verify_and_clear_gpu_quarantine with a live verifier."
            ),
            last_verification_error=str(exc),
        )


def get_gpu_quarantine(
    *,
    path: str | Path | None = None,
) -> GpuQuarantineSnapshot | None:
    """Return the durable host-wide quarantine marker, if one exists."""

    return _read_quarantine(_resolve_lock_path(path))


def _try_lock(file_handle) -> bool:
    file_handle.seek(0)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    import fcntl

    try:
        fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(file_handle) -> None:
    file_handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


class GpuLease:
    """Advisory file lock shared by API and Celery worker processes."""

    def __init__(
        self,
        stage: str,
        owner: str,
        *,
        timeout_seconds: float | None = None,
        poll_seconds: float = 0.25,
        path: str | Path | None = None,
        enabled: bool | None = None,
        _allow_quarantine: bool = False,
    ) -> None:
        self.stage = stage
        self.owner = owner
        self.timeout_seconds = (
            float(settings.GPU_LEASE_TIMEOUT_SECONDS)
            if timeout_seconds is None
            else max(0.0, float(timeout_seconds))
        )
        self.poll_seconds = max(0.01, float(poll_seconds))
        self.path = _resolve_lock_path(path)
        self.enabled = settings.GPU_LEASE_ENABLED if enabled is None else enabled
        self._allow_quarantine = _allow_quarantine
        self.snapshot: GpuLeaseSnapshot | None = None
        self._handle = None
        self._file_lock_acquired = False
        self._process_lock_acquired = False
        self._nested = False

    @property
    def owner_path(self) -> Path:
        return self.path.with_suffix(f"{self.path.suffix}.owner.json")

    @property
    def quarantine_path(self) -> Path:
        return _quarantine_path(self.path)

    def _raise_if_quarantined(self) -> None:
        quarantine = _read_quarantine(self.path)
        if quarantine is None or self._allow_quarantine:
            return
        if (
            quarantine.owner == self.owner
            and self.stage in quarantine.allowed_stages
        ):
            return
        raise GpuLeaseQuarantined(quarantine)

    def __enter__(self) -> GpuLeaseSnapshot | None:
        if not self.enabled:
            return None

        _PROCESS_LEASE_LOCK.acquire()
        self._process_lock_acquired = True
        depth = int(getattr(_PROCESS_LEASE_STATE, "depth", 0))
        if depth:
            try:
                self._raise_if_quarantined()
                self._nested = True
                _PROCESS_LEASE_STATE.depth = depth + 1
                self.snapshot = getattr(_PROCESS_LEASE_STATE, "snapshot", None)
                return self.snapshot
            except Exception:
                _PROCESS_LEASE_LOCK.release()
                self._process_lock_acquired = False
                raise

        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._raise_if_quarantined()
            self._handle = self.path.open("a+b")
            if self.path.stat().st_size == 0:
                self._handle.write(b"\0")
                self._handle.flush()

            started = time.monotonic()
            while not _try_lock(self._handle):
                waited = time.monotonic() - started
                if waited >= self.timeout_seconds:
                    self._handle.close()
                    self._handle = None
                    raise GpuLeaseTimeout(
                        f"GPU lease timed out after {waited:.2f}s "
                        f"for stage={self.stage} owner={self.owner}"
                    )
                time.sleep(min(self.poll_seconds, self.timeout_seconds - waited))

            self._file_lock_acquired = True
            self._raise_if_quarantined()
            waited = time.monotonic() - started
            self.snapshot = GpuLeaseSnapshot(
                lease_id=str(uuid.uuid4()),
                stage=self.stage,
                owner=self.owner,
                pid=os.getpid(),
                acquired_at=datetime.now(timezone.utc).isoformat(),
                waited_seconds=round(waited, 6),
            )
            _PROCESS_LEASE_STATE.depth = 1
            _PROCESS_LEASE_STATE.snapshot = self.snapshot
            _atomic_write_json(self.owner_path, asdict(self.snapshot))
            return self.snapshot
        except Exception:
            try:
                if self._handle is not None:
                    if self._file_lock_acquired:
                        _unlock(self._handle)
                        self._file_lock_acquired = False
                    self._handle.close()
                    self._handle = None
            finally:
                if self._process_lock_acquired:
                    _PROCESS_LEASE_LOCK.release()
                    self._process_lock_acquired = False
            raise

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if not self.enabled:
            return
        if self._nested:
            _PROCESS_LEASE_STATE.depth = max(
                0,
                int(getattr(_PROCESS_LEASE_STATE, "depth", 1)) - 1,
            )
            if self._process_lock_acquired:
                _PROCESS_LEASE_LOCK.release()
                self._process_lock_acquired = False
            return
        if self._handle is None:
            if self._process_lock_acquired:
                _PROCESS_LEASE_LOCK.release()
                self._process_lock_acquired = False
            return
        try:
            if self.owner_path.exists():
                current = json.loads(self.owner_path.read_text(encoding="utf-8"))
                if self.snapshot and current.get("lease_id") == self.snapshot.lease_id:
                    self.owner_path.unlink(missing_ok=True)
        finally:
            try:
                _unlock(self._handle)
                self._file_lock_acquired = False
                self._handle.close()
                self._handle = None
                _PROCESS_LEASE_STATE.depth = 0
                _PROCESS_LEASE_STATE.snapshot = None
            finally:
                if self._process_lock_acquired:
                    _PROCESS_LEASE_LOCK.release()
                    self._process_lock_acquired = False


def arm_gpu_quarantine(
    stage: str,
    owner: str,
    reason: str,
    *,
    allowed_stages: tuple[str, ...],
    path: str | Path | None = None,
    timeout_seconds: float | None = None,
) -> GpuQuarantineSnapshot:
    """Persist a fail-closed marker before an external runtime handoff."""

    lock_path = _resolve_lock_path(path)
    with GpuLease(
        "quarantine_arm",
        owner,
        timeout_seconds=timeout_seconds,
        path=lock_path,
        enabled=True,
        _allow_quarantine=True,
    ):
        existing = _read_quarantine(lock_path)
        if existing is not None:
            if existing.owner != owner:
                raise GpuLeaseQuarantined(existing)
            return existing

        timestamp = datetime.now(timezone.utc).isoformat()
        snapshot = GpuQuarantineSnapshot(
            quarantine_id=str(uuid.uuid4()),
            stage=stage,
            owner=owner,
            pid=os.getpid(),
            created_at=timestamp,
            updated_at=timestamp,
            reason=reason,
            verification_required="llama_server_sleeping",
            allowed_stages=tuple(dict.fromkeys(allowed_stages)),
            recovery=(
                "Confirm llama-server /props reports is_sleeping=true, then run "
                "verify_and_clear_gpu_quarantine with a live verifier."
            ),
        )
        _atomic_write_json(_quarantine_path(lock_path), asdict(snapshot))
        return snapshot


def _record_quarantine_failure(
    lock_path: Path,
    snapshot: GpuQuarantineSnapshot,
    error: str,
) -> None:
    updated = replace(
        snapshot,
        updated_at=datetime.now(timezone.utc).isoformat(),
        reason="llama-server sleep verification failed; GPU handoff is unsafe",
        last_verification_error=error[:1000],
    )
    _atomic_write_json(_quarantine_path(lock_path), asdict(updated))


def verify_and_clear_gpu_quarantine(
    verifier: Callable[[], bool],
    *,
    verified_by: str,
    expected_quarantine_id: str | None = None,
    path: str | Path | None = None,
    timeout_seconds: float | None = None,
) -> bool:
    """Clear quarantine only while holding the lease and proving server sleep."""

    lock_path = _resolve_lock_path(path)
    with GpuLease(
        "quarantine_recovery",
        verified_by,
        timeout_seconds=timeout_seconds,
        path=lock_path,
        enabled=True,
        _allow_quarantine=True,
    ):
        snapshot = _read_quarantine(lock_path)
        if snapshot is None:
            return True
        if (
            expected_quarantine_id is not None
            and snapshot.quarantine_id != expected_quarantine_id
        ):
            raise GpuQuarantineRecoveryError(
                "GPU quarantine changed before recovery verification"
            )

        try:
            sleeping = bool(verifier())
        except Exception as exc:
            _record_quarantine_failure(
                lock_path,
                snapshot,
                f"{type(exc).__name__}: {exc}",
            )
            raise GpuQuarantineRecoveryError(
                "llama-server sleep verification raised an exception; "
                "quarantine remains active"
            ) from exc

        if not sleeping:
            _record_quarantine_failure(
                lock_path,
                snapshot,
                "verifier returned false",
            )
            return False

        _quarantine_path(lock_path).unlink(missing_ok=True)
        return True


@contextmanager
def gpu_lease(
    stage: str,
    owner: str,
    *,
    timeout_seconds: float | None = None,
) -> Iterator[GpuLeaseSnapshot | None]:
    """Acquire the configured host-wide GPU lease for one pipeline stage."""

    with GpuLease(stage, owner, timeout_seconds=timeout_seconds) as snapshot:
        yield snapshot
