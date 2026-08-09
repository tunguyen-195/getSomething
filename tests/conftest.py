from __future__ import annotations

import atexit
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, URL, make_url
from sqlalchemy.orm import close_all_sessions
from sqlalchemy.pool import NullPool


load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_]+_test")
SAFE_DATABASE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_]+")


class DatabaseIsolationError(RuntimeError):
    """Raised before unsafe or concurrent test database work can begin."""


class DatabaseLockTimeout(DatabaseIsolationError):
    """Raised when another pytest session owns the test database lock."""


@dataclass
class DatabaseLockHandle:
    engine: Engine
    connection: Connection
    database_url: URL
    lock_key: int
    backend_pid: int
    scope: str
    requested_at: str
    acquired_at: str
    evidence_path: Path | None = None
    released_at: str | None = None
    released: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_parallel_pytest(
    argv: Sequence[str], environ: Mapping[str, str]
) -> None:
    if environ.get("PYTEST_XDIST_WORKER") or environ.get("PYTEST_XDIST_WORKER_COUNT"):
        raise DatabaseIsolationError(
            "Parallel pytest is disabled until per-worker database isolation exists"
        )
    for index, argument in enumerate(argv):
        if argument == "-n" or argument.startswith("-n="):
            raise DatabaseIsolationError(
                "Parallel pytest is disabled; remove -n/--numprocesses"
            )
        if argument.startswith("-n") and argument != "-n":
            raise DatabaseIsolationError(
                "Parallel pytest is disabled; remove -n/--numprocesses"
            )
        if argument == "--numprocesses" or argument.startswith("--numprocesses="):
            raise DatabaseIsolationError(
                "Parallel pytest is disabled; remove -n/--numprocesses"
            )
        if index > 0 and argv[index - 1] in {"-n", "--numprocesses"}:
            raise DatabaseIsolationError(
                "Parallel pytest is disabled; remove -n/--numprocesses"
            )


def _maintenance_database_name(environ: Mapping[str, str]) -> str:
    database_name = environ.get("TEST_DATABASE_ADMIN_DB", "postgres")
    if not SAFE_DATABASE_NAME_PATTERN.fullmatch(database_name):
        raise DatabaseIsolationError(
            "TEST_DATABASE_ADMIN_DB must contain only letters, digits, and underscores"
        )
    return database_name


def _application_database_name(environ: Mapping[str, str]) -> str:
    configured = environ.get("DATABASE_URL")
    if configured:
        try:
            configured_name = make_url(configured).database or ""
        except Exception as exc:
            raise DatabaseIsolationError("DATABASE_URL is not a valid database URL") from exc
        if configured_name and not configured_name.endswith("_test"):
            return configured_name
    protected_name = environ.get("POSTGRES_DB", "speech_to_info")
    return "" if protected_name.endswith("_test") else protected_name


def _validate_test_database_url(
    url: URL,
    *,
    application_database: str,
    maintenance_database: str,
) -> URL:
    driver = url.drivername.split("+", 1)[0].casefold()
    database_name = url.database or ""
    if driver != "postgresql":
        raise DatabaseIsolationError("Test database must use PostgreSQL")
    if not TEST_DATABASE_NAME_PATTERN.fullmatch(database_name):
        raise DatabaseIsolationError(
            "TEST_DATABASE_URL must target a database whose name ends with '_test'"
        )
    if database_name.casefold() == maintenance_database.casefold():
        raise DatabaseIsolationError("Test database cannot be the maintenance database")
    if application_database and database_name.casefold() == application_database.casefold():
        raise DatabaseIsolationError("Test database cannot be the application database")
    return url


def _build_test_database_url(
    environ: Mapping[str, str] | None = None,
) -> URL:
    env = os.environ if environ is None else environ
    explicit_url = env.get("TEST_DATABASE_URL")
    application_database = _application_database_name(env)
    maintenance_database = _maintenance_database_name(env)
    if explicit_url:
        try:
            test_url = make_url(explicit_url)
        except Exception as exc:
            raise DatabaseIsolationError("TEST_DATABASE_URL is not valid") from exc
    else:
        configured_url = env.get("DATABASE_URL")
        if configured_url:
            try:
                test_url = make_url(configured_url)
            except Exception as exc:
                raise DatabaseIsolationError("DATABASE_URL is not valid") from exc
        else:
            test_url = URL.create(
                "postgresql",
                username=env.get("POSTGRES_USER", "postgres"),
                password=env.get("POSTGRES_PASSWORD", "postgres"),
                host=env.get("POSTGRES_HOST", "localhost"),
                port=int(env.get("POSTGRES_PORT", "5432")),
                database=application_database,
            )
        database_name = test_url.database or "speech_to_info"
        if not database_name.endswith("_test"):
            test_url = test_url.set(database=f"{database_name}_test")
    return _validate_test_database_url(
        test_url,
        application_database=application_database,
        maintenance_database=maintenance_database,
    )


def _redacted_database_identity(url: URL) -> dict[str, object]:
    return {
        "driver": url.drivername,
        "host": (url.host or "localhost").casefold(),
        "port": url.port or 5432,
        "database": url.database,
    }


def _database_identity(url: URL) -> tuple[str, str, int, str]:
    return (
        url.drivername.split("+", 1)[0].casefold(),
        (url.host or "localhost").casefold(),
        url.port or 5432,
        (url.database or "").casefold(),
    )


def _database_lock_key(url: URL, scope: str = "pytest-session") -> int:
    driver, host, port, database = _database_identity(url)
    material = f"{scope}\0{driver}\0{host}\0{port}\0{database}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=True)


def _positive_float_from_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        value = default if raw is None else float(raw)
    except ValueError as exc:
        raise DatabaseIsolationError(f"{name} must be numeric") from exc
    if value <= 0 or value > 600:
        raise DatabaseIsolationError(f"{name} must be in the range (0, 600]")
    return value


def _validated_lock_evidence_path() -> Path | None:
    raw = os.getenv("TEST_DATABASE_LOCK_EVIDENCE_PATH")
    if not raw:
        return None
    path = Path(raw)
    path = path if path.is_absolute() else REPO_ROOT / path
    path = path.resolve(strict=False)
    allowed_root = (REPO_ROOT / "output/audits").resolve(strict=False)
    try:
        within_allowed_root = os.path.commonpath((str(path), str(allowed_root))) == str(
            allowed_root
        )
    except ValueError:
        within_allowed_root = False
    if not within_allowed_root:
        raise DatabaseIsolationError(
            "TEST_DATABASE_LOCK_EVIDENCE_PATH must stay under output/audits"
        )
    return path


def _write_lock_evidence(handle: DatabaseLockHandle) -> None:
    if handle.evidence_path is None:
        return
    payload = {
        "schema_version": "p0-test-lock-window-v1",
        "pid": os.getpid(),
        "backend_pid": handle.backend_pid,
        "scope": handle.scope,
        "lock_key": handle.lock_key,
        "database": _redacted_database_identity(handle.database_url),
        "requested_at": handle.requested_at,
        "acquired_at": handle.acquired_at,
        "released_at": handle.released_at,
        "conftest_sha256": _sha256(Path(__file__)),
    }
    handle.evidence_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = handle.evidence_path.with_suffix(handle.evidence_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(handle.evidence_path)


def _acquire_database_lock(
    database_url: URL,
    *,
    lock_key: int,
    timeout_seconds: float,
    scope: str,
    evidence_path: Path | None = None,
) -> DatabaseLockHandle:
    requested_at = _utc_now()
    lock_engine = create_engine(
        database_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    connection: Connection | None = None
    try:
        connection = lock_engine.connect()
        deadline = time.monotonic() + timeout_seconds
        while True:
            acquired = bool(
                connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": lock_key},
                ).scalar()
            )
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise DatabaseLockTimeout(
                    "Timed out waiting for serialized test database access: "
                    f"{_redacted_database_identity(database_url)}"
                )
            time.sleep(0.1)
        backend_pid = int(connection.execute(text("SELECT pg_backend_pid()")) .scalar_one())
        handle = DatabaseLockHandle(
            engine=lock_engine,
            connection=connection,
            database_url=database_url,
            lock_key=lock_key,
            backend_pid=backend_pid,
            scope=scope,
            requested_at=requested_at,
            acquired_at=_utc_now(),
            evidence_path=evidence_path,
        )
        _write_lock_evidence(handle)
        return handle
    except Exception:
        if connection is not None:
            connection.close()
        lock_engine.dispose()
        raise


def _release_database_lock(handle: DatabaseLockHandle) -> bool:
    if handle.released:
        return True
    unlocked = False
    try:
        if not handle.connection.closed:
            unlocked = bool(
                handle.connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": handle.lock_key},
                ).scalar()
            )
    finally:
        handle.released_at = _utc_now()
        handle.released = True
        try:
            _write_lock_evidence(handle)
        finally:
            try:
                handle.connection.close()
            finally:
                handle.engine.dispose()
    return unlocked


def _lock_is_held(handle: DatabaseLockHandle) -> bool:
    if handle.released or handle.connection.closed:
        return False
    unsigned_key = handle.lock_key & ((1 << 64) - 1)
    class_id = unsigned_key >> 32
    object_id = unsigned_key & 0xFFFFFFFF
    row = handle.connection.execute(
        text(
            """
            SELECT pg_backend_pid() AS backend_pid,
                   EXISTS (
                       SELECT 1
                       FROM pg_locks
                       WHERE locktype = 'advisory'
                         AND pid = pg_backend_pid()
                         AND granted
                         AND classid::bigint = :class_id
                         AND objid::bigint = :object_id
                         AND objsubid = 1
                   ) AS held
            """
        ),
        {"class_id": class_id, "object_id": object_id},
    ).mappings().one()
    return int(row["backend_pid"]) == handle.backend_pid and bool(row["held"])


def _ensure_test_database(test_url: URL) -> None:
    maintenance_database = _maintenance_database_name(os.environ)
    maintenance_url = test_url.set(database=maintenance_database)
    lock = _acquire_database_lock(
        maintenance_url,
        lock_key=_database_lock_key(test_url, "database-create"),
        timeout_seconds=_positive_float_from_env(
            "TEST_DATABASE_LOCK_TIMEOUT_SECONDS", 120.0
        ),
        scope="database-create",
    )
    try:
        database_name = test_url.database or ""
        exists = lock.connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
            {"database_name": database_name},
        ).scalar()
        if not exists:
            lock.connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        if not _release_database_lock(lock):
            raise DatabaseIsolationError("Failed to release test database creation lock")


def _acquire_test_session_lock(test_url: URL) -> DatabaseLockHandle:
    return _acquire_database_lock(
        test_url,
        lock_key=_database_lock_key(test_url),
        timeout_seconds=_positive_float_from_env(
            "TEST_DATABASE_LOCK_TIMEOUT_SECONDS", 120.0
        ),
        scope="pytest-session",
        evidence_path=_validated_lock_evidence_path(),
    )


_reject_parallel_pytest(sys.argv, os.environ)
APPLICATION_DATABASE_NAME = _application_database_name(os.environ)
MAINTENANCE_DATABASE_NAME = _maintenance_database_name(os.environ)
TEST_DATABASE_URL = _build_test_database_url()
_ensure_test_database(TEST_DATABASE_URL)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL.render_as_string(hide_password=False)

os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "true"
os.environ["AUTH_ENABLED"] = "false"
os.environ["DEV_AUTH_BYPASS"] = "true"
os.environ["DEV_USER_ID"] = "1"
os.environ["INIT_DB_ON_STARTUP"] = "false"
os.environ["INITIAL_ADMIN_PASSWORD"] = "test-admin-password"
os.environ["SECRET_KEY"] = "test-secret-key-with-enough-length-1234567890"
os.environ["RATE_LIMIT_ENABLED"] = "false"

sys.path.insert(0, str(REPO_ROOT))

_SESSION_LOCK_HANDLE = _acquire_test_session_lock(TEST_DATABASE_URL)


def _release_session_lock_at_exit() -> None:
    if not _SESSION_LOCK_HANDLE.released:
        _release_database_lock(_SESSION_LOCK_HANDLE)


atexit.register(_release_session_lock_at_exit)


from src.database.config.database import Base, SessionLocal, engine, get_db  # noqa: E402
from src.database.init_db import init_db  # noqa: E402
from src.database.models import models as _models  # noqa: E402,F401
from src.main import app  # noqa: E402


def _override_get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


def _assert_safe_ddl_target(
    expected_url: URL, lock_handle: DatabaseLockHandle
) -> None:
    _validate_test_database_url(
        expected_url,
        application_database=APPLICATION_DATABASE_NAME,
        maintenance_database=MAINTENANCE_DATABASE_NAME,
    )
    bound_url = make_url(str(engine.url))
    if _database_identity(bound_url) != _database_identity(expected_url):
        raise DatabaseIsolationError("Bound SQLAlchemy engine is not the locked test database")
    if _database_identity(lock_handle.database_url) != _database_identity(expected_url):
        raise DatabaseIsolationError("Advisory lock belongs to a different database")
    if not _lock_is_held(lock_handle):
        raise DatabaseIsolationError("Test database advisory lock is not held")


def _ddl_timeout_milliseconds() -> int:
    return int(_positive_float_from_env("TEST_DATABASE_DDL_TIMEOUT_SECONDS", 30.0) * 1000)


def _reset_test_schema(lock_handle: DatabaseLockHandle) -> None:
    close_all_sessions()
    _assert_safe_ddl_target(TEST_DATABASE_URL, lock_handle)
    timeout_ms = _ddl_timeout_milliseconds()
    with engine.begin() as connection:
        current_database = connection.execute(text("SELECT current_database()")) .scalar_one()
        if current_database != TEST_DATABASE_URL.database:
            raise DatabaseIsolationError("DDL connection is not bound to the test database")
        connection.execute(text(f"SET LOCAL lock_timeout = '{timeout_ms}ms'"))
        connection.execute(text(f"SET LOCAL statement_timeout = '{timeout_ms}ms'"))
        Base.metadata.drop_all(bind=connection)
        Base.metadata.create_all(bind=connection)
    init_db(create_schema=False)


def _drop_test_schema(lock_handle: DatabaseLockHandle) -> None:
    close_all_sessions()
    _assert_safe_ddl_target(TEST_DATABASE_URL, lock_handle)
    timeout_ms = _ddl_timeout_milliseconds()
    with engine.begin() as connection:
        current_database = connection.execute(text("SELECT current_database()")) .scalar_one()
        if current_database != TEST_DATABASE_URL.database:
            raise DatabaseIsolationError("DDL connection is not bound to the test database")
        connection.execute(text(f"SET LOCAL lock_timeout = '{timeout_ms}ms'"))
        connection.execute(text(f"SET LOCAL statement_timeout = '{timeout_ms}ms'"))
        Base.metadata.drop_all(bind=connection)


@pytest.fixture(scope="session", autouse=True)
def serialized_test_database_session() -> DatabaseLockHandle:
    _assert_safe_ddl_target(TEST_DATABASE_URL, _SESSION_LOCK_HANDLE)
    yield _SESSION_LOCK_HANDLE


@pytest.fixture(autouse=True)
def isolated_test_database(
    serialized_test_database_session: DatabaseLockHandle,
):
    """Reset only the locked PostgreSQL test database for every test."""

    _reset_test_schema(serialized_test_database_session)
    try:
        yield
    finally:
        _drop_test_schema(serialized_test_database_session)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    engine.dispose()
    if not _SESSION_LOCK_HANDLE.released:
        try:
            released = _release_database_lock(_SESSION_LOCK_HANDLE)
        except Exception:
            session.exitstatus = pytest.ExitCode.INTERNAL_ERROR
            raise
        if not released:
            session.exitstatus = pytest.ExitCode.INTERNAL_ERROR
            raise DatabaseIsolationError("Failed to release pytest session advisory lock")
