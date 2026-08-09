from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

import conftest as db_conftest
import scripts.verify_test_database_isolation as isolation_verifier


def _base_environment() -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql://app:secret@localhost:5432/speech_to_info",
        "POSTGRES_DB": "speech_to_info",
        "TEST_DATABASE_ADMIN_DB": "postgres",
    }


def test_implicit_application_url_derives_dedicated_test_database() -> None:
    url = db_conftest._build_test_database_url(_base_environment())

    assert url.database == "speech_to_info_test"
    assert url.drivername == "postgresql"


def test_database_url_already_targeting_test_database_is_accepted() -> None:
    env = _base_environment() | {
        "DATABASE_URL": "postgresql://app:secret@localhost:5432/speech_to_info_test"
    }

    url = db_conftest._build_test_database_url(env)

    assert url.database == "speech_to_info_test"


def test_verifier_separates_direct_test_url_from_protected_application_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://app:secret@localhost:5432/speech_to_info_test",
    )
    monkeypatch.setenv("POSTGRES_DB", "speech_to_info")
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

    application_url, test_url, _maintenance = isolation_verifier._database_urls(
        db_conftest.REPO_ROOT
    )

    assert application_url.database == "speech_to_info"
    assert test_url.database == "speech_to_info_test"


@pytest.mark.parametrize(
    "test_database_url",
    [
        "postgresql://app:secret@localhost:5432/speech_to_info",
        "sqlite:///speech_to_info_test.db",
        "postgresql://app:secret@localhost:5432/postgres",
        "postgresql://app:secret@localhost:5432/speech-to-info-test",
    ],
)
def test_explicit_unsafe_test_database_url_fails_before_engine_creation(
    monkeypatch: pytest.MonkeyPatch,
    test_database_url: str,
) -> None:
    env = _base_environment() | {"TEST_DATABASE_URL": test_database_url}
    engine_called = False

    def forbidden_engine(*args, **kwargs):
        del args, kwargs
        nonlocal engine_called
        engine_called = True
        raise AssertionError("create_engine must not run")

    monkeypatch.setattr(db_conftest, "create_engine", forbidden_engine)
    with pytest.raises(db_conftest.DatabaseIsolationError):
        db_conftest._build_test_database_url(env)

    assert engine_called is False


@pytest.mark.parametrize(
    "argv,environ",
    [
        (["pytest", "-n", "2"], {}),
        (["pytest", "-n2"], {}),
        (["pytest", "-n=auto"], {}),
        (["pytest", "--numprocesses", "2"], {}),
        (["pytest", "--numprocesses=2"], {}),
        (["pytest"], {"PYTEST_XDIST_WORKER": "gw0"}),
        (["pytest"], {"PYTEST_XDIST_WORKER_COUNT": "2"}),
    ],
)
def test_parallel_pytest_is_rejected_before_database_work(
    argv: list[str], environ: dict[str, str]
) -> None:
    with pytest.raises(db_conftest.DatabaseIsolationError, match="Parallel pytest"):
        db_conftest._reject_parallel_pytest(argv, environ)


def test_lock_key_is_deterministic_and_database_specific() -> None:
    first = make_url("postgresql://one:a@localhost:5432/alpha_test")
    same_database = make_url("postgresql://two:b@LOCALHOST:5432/alpha_test")
    other_database = make_url("postgresql://one:a@localhost:5432/beta_test")
    other_host = make_url("postgresql://one:a@127.0.0.2:5432/alpha_test")
    other_port = make_url("postgresql://one:a@localhost:5433/alpha_test")

    assert db_conftest._database_lock_key(first) == db_conftest._database_lock_key(
        same_database
    )
    assert db_conftest._database_lock_key(first) != db_conftest._database_lock_key(
        other_database
    )
    assert db_conftest._database_lock_key(first) != db_conftest._database_lock_key(
        other_host
    )
    assert db_conftest._database_lock_key(first) != db_conftest._database_lock_key(
        other_port
    )


def test_lock_timeout_closes_connection_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        def scalar(self) -> bool:
            return False

    class Connection:
        closed = False

        def execute(self, statement, parameters=None):
            del statement, parameters
            return Result()

        def close(self) -> None:
            self.closed = True

    class Engine:
        def __init__(self) -> None:
            self.connection = Connection()
            self.disposed = False

        def connect(self) -> Connection:
            return self.connection

        def dispose(self) -> None:
            self.disposed = True

    fake_engine = Engine()
    monotonic_values = iter((0.0, 2.0))
    monkeypatch.setattr(db_conftest, "create_engine", lambda *args, **kwargs: fake_engine)
    monkeypatch.setattr(db_conftest.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(db_conftest.time, "sleep", lambda _seconds: None)

    with pytest.raises(db_conftest.DatabaseLockTimeout):
        db_conftest._acquire_database_lock(
            make_url("postgresql://app:secret@localhost:5432/speech_to_info_test"),
            lock_key=123,
            timeout_seconds=1.0,
            scope="test-timeout",
        )

    assert fake_engine.connection.closed is True
    assert fake_engine.disposed is True


def test_release_closes_resources_even_when_unlock_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        closed = False

        def execute(self, statement, parameters=None):
            del statement, parameters
            raise RuntimeError("simulated unlock failure")

        def close(self) -> None:
            self.closed = True

    class Engine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    connection = Connection()
    lock_engine = Engine()
    handle = db_conftest.DatabaseLockHandle(
        engine=lock_engine,
        connection=connection,
        database_url=make_url(
            "postgresql://app:secret@localhost:5432/speech_to_info_test"
        ),
        lock_key=123,
        backend_pid=456,
        scope="test-release",
        requested_at="2026-08-09T10:00:00+00:00",
        acquired_at="2026-08-09T10:00:01+00:00",
    )
    monkeypatch.setattr(db_conftest, "_write_lock_evidence", lambda _handle: None)

    with pytest.raises(RuntimeError, match="simulated unlock failure"):
        db_conftest._release_database_lock(handle)

    assert handle.released is True
    assert connection.closed is True
    assert lock_engine.disposed is True


def test_release_closes_resources_even_when_evidence_write_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        def scalar(self) -> bool:
            return True

    class Connection:
        closed = False

        def execute(self, statement, parameters=None):
            del statement, parameters
            return Result()

        def close(self) -> None:
            self.closed = True

    class Engine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    connection = Connection()
    lock_engine = Engine()
    handle = db_conftest.DatabaseLockHandle(
        engine=lock_engine,
        connection=connection,
        database_url=make_url(
            "postgresql://app:secret@localhost:5432/speech_to_info_test"
        ),
        lock_key=123,
        backend_pid=456,
        scope="test-release",
        requested_at="2026-08-09T10:00:00+00:00",
        acquired_at="2026-08-09T10:00:01+00:00",
    )
    monkeypatch.setattr(
        db_conftest,
        "_write_lock_evidence",
        lambda _handle: (_ for _ in ()).throw(RuntimeError("evidence write failed")),
    )

    with pytest.raises(RuntimeError, match="evidence write failed"):
        db_conftest._release_database_lock(handle)

    assert handle.released is True
    assert connection.closed is True
    assert lock_engine.disposed is True


def test_release_disposes_engine_even_when_connection_close_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Result:
        def scalar(self) -> bool:
            return True

    class Connection:
        closed = False

        def execute(self, statement, parameters=None):
            del statement, parameters
            return Result()

        def close(self) -> None:
            self.closed = True
            raise RuntimeError("connection close failed")

    class Engine:
        disposed = False

        def dispose(self) -> None:
            self.disposed = True

    connection = Connection()
    lock_engine = Engine()
    handle = db_conftest.DatabaseLockHandle(
        engine=lock_engine,
        connection=connection,
        database_url=make_url(
            "postgresql://app:secret@localhost:5432/speech_to_info_test"
        ),
        lock_key=123,
        backend_pid=456,
        scope="test-release",
        requested_at="2026-08-09T10:00:00+00:00",
        acquired_at="2026-08-09T10:00:01+00:00",
    )
    monkeypatch.setattr(db_conftest, "_write_lock_evidence", lambda _handle: None)

    with pytest.raises(RuntimeError, match="connection close failed"):
        db_conftest._release_database_lock(handle)

    assert handle.released is True
    assert connection.closed is True
    assert lock_engine.disposed is True


def test_bound_engine_mismatch_fails_before_lock_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        db_conftest,
        "engine",
        SimpleNamespace(url="postgresql://app:secret@localhost:5432/not_the_target_test"),
    )
    lock_probed = False

    def forbidden_lock_probe(handle) -> bool:
        del handle
        nonlocal lock_probed
        lock_probed = True
        return True

    monkeypatch.setattr(db_conftest, "_lock_is_held", forbidden_lock_probe)
    with pytest.raises(db_conftest.DatabaseIsolationError, match="Bound SQLAlchemy engine"):
        db_conftest._assert_safe_ddl_target(
            db_conftest.TEST_DATABASE_URL,
            db_conftest._SESSION_LOCK_HANDLE,
        )

    assert lock_probed is False


def test_current_session_lock_is_live_and_bound_to_test_database() -> None:
    handle = db_conftest._SESSION_LOCK_HANDLE

    assert handle.released is False
    assert handle.database_url.database == db_conftest.TEST_DATABASE_URL.database
    assert db_conftest._lock_is_held(handle) is True


def test_xdist_environment_fails_before_url_or_credentials_are_processed() -> None:
    secret = "p0-secret-must-not-appear"
    env = os.environ.copy()
    env.update(
        {
            "PYTEST_XDIST_WORKER": "gw0",
            "TEST_DATABASE_URL": f"not-a-url://user:{secret}@invalid/production",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy; runpy.run_path(r'tests/conftest.py')",
        ],
        cwd=db_conftest.REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    rendered = result.stdout + result.stderr

    assert result.returncode != 0
    assert "Parallel pytest is disabled" in rendered
    assert secret not in rendered


def test_lock_evidence_path_cannot_escape_workspace_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TEST_DATABASE_LOCK_EVIDENCE_PATH", str(tmp_path / "outside.json"))

    with pytest.raises(db_conftest.DatabaseIsolationError, match="output/audits"):
        db_conftest._validated_lock_evidence_path()


def test_p0_subprocess_lock_probe() -> None:
    raw_seconds = os.getenv("P0_SUBPROCESS_LOCK_PROBE_SECONDS")
    if raw_seconds is None:
        pytest.skip("only executed by the P0 subprocess verifier")
    seconds = float(raw_seconds)
    assert 0 < seconds <= 10
    if os.getenv("P0_SUBPROCESS_LOCK_PROBE_MODE") == "raise":
        raise RuntimeError("intentional P0 lock-release probe failure")
    time.sleep(seconds)


def test_raw_credential_token_is_rejected_by_verifier() -> None:
    assert isolation_verifier._credential_markers_absent(
        "prefix p0-raw-token suffix", {"p0-raw-token"}
    ) is False
