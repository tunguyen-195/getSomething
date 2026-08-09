"""Verify serialized pytest access to the dedicated PostgreSQL test database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool


CANONICAL_ROOT = Path(r"E:\research\STT")
DEFAULT_OUTPUT = Path("docs/reviews/artifacts/p0-test-isolation.json")
SOURCE_PATHS = (
    "tests/conftest.py",
    "tests/test_database_safety.py",
    "tests/test_test_database_isolation.py",
    "scripts/verify_test_database_isolation.py",
)


def _normalized_absolute(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _canonical_repo(path: Path) -> Path:
    if _normalized_absolute(path) != _normalized_absolute(CANONICAL_ROOT):
        raise ValueError(f"repo must be exactly {CANONICAL_ROOT}")
    return CANONICAL_ROOT


def _validated_output(repo_root: Path, value: Path) -> Path:
    output = value if value.is_absolute() else repo_root / value
    output = output.resolve(strict=False)
    allowed_root = (repo_root / "docs/reviews/artifacts").resolve(strict=False)
    try:
        within_allowed_root = (
            os.path.commonpath((str(output), str(allowed_root)))
            == str(allowed_root)
        )
    except ValueError:
        within_allowed_root = False
    if not within_allowed_root:
        raise ValueError("output must stay under docs/reviews/artifacts")
    return output


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def _database_urls(repo_root: Path) -> tuple[URL, URL, str]:
    load_dotenv(repo_root / ".env")
    application_value = os.getenv("DATABASE_URL")
    if application_value:
        configured_url = make_url(application_value)
    else:
        configured_url = URL.create(
            "postgresql",
            username=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "postgres"),
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "speech_to_info"),
        )
    protected_name = os.getenv("POSTGRES_DB", "speech_to_info")
    application_url = (
        configured_url.set(database=protected_name)
        if (configured_url.database or "").endswith("_test")
        else configured_url
    )
    explicit_test = os.getenv("TEST_DATABASE_URL")
    if explicit_test:
        test_url = make_url(explicit_test)
    elif (configured_url.database or "").endswith("_test"):
        test_url = configured_url
    else:
        application_name = application_url.database or "speech_to_info"
        test_name = (
            application_name
            if application_name.endswith("_test")
            else f"{application_name}_test"
        )
        test_url = application_url.set(database=test_name)
    driver = test_url.drivername.split("+", 1)[0].casefold()
    if driver != "postgresql" or not (test_url.database or "").endswith("_test"):
        raise ValueError("test database must be a dedicated PostgreSQL _test database")
    if test_url.database == application_url.database:
        raise ValueError("test database must differ from application database")
    maintenance_database = os.getenv("TEST_DATABASE_ADMIN_DB", "postgres")
    if test_url.database == maintenance_database:
        raise ValueError("test database cannot equal maintenance database")
    return application_url, test_url, maintenance_database


def _redacted_database(url: URL) -> dict[str, Any]:
    return {
        "driver": url.drivername,
        "host": (url.host or "localhost").casefold(),
        "port": url.port or 5432,
        "database": url.database,
    }


def _application_fingerprint(url: URL) -> dict[str, Any]:
    engine = create_engine(url, poolclass=NullPool, isolation_level="REPEATABLE READ")
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            select_one = connection.execute(text("SELECT 1")).scalar_one()
            tables: dict[str, dict[str, Any]] = {}
            for table in ("users", "cases", "tasks"):
                rows = connection.execute(
                    text(
                        f'SELECT row_to_json(snapshot)::text FROM '
                        f'(SELECT * FROM "{table}" ORDER BY id) AS snapshot'
                    )
                ).scalars()
                digest = hashlib.sha256()
                count = 0
                for row in rows:
                    encoded = str(row).encode("utf-8")
                    digest.update(len(encoded).to_bytes(8, "big"))
                    digest.update(encoded)
                    count += 1
                tables[table] = {"count": count, "content_sha256": digest.hexdigest()}
            connection.rollback()
            return {"select_one": select_one, "tables": tables}
    finally:
        engine.dispose()


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    rendered = completed.stdout + completed.stderr
    return {
        "command": command,
        "exit_code": completed.returncode,
        "stdout_sha256": _content_sha256(completed.stdout),
        "stderr_sha256": _content_sha256(completed.stderr),
        "pytest_summary": _pytest_summary(rendered),
        "historical_workspace_path_absent": _historical_workspace_path_absent(
            rendered
        ),
        "credential_markers_absent": _credential_markers_absent(
            rendered, _passwords_from_environment(env)
        ),
    }


def _pytest_summary(rendered: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in ("passed", "failed", "skipped", "deselected", "error", "errors"):
        match = re.search(rf"\b(\d+) {name}\b", rendered)
        if match:
            counts[name] = int(match.group(1))
    return counts


def _historical_workspace_path_absent(rendered: str) -> bool:
    historical = "D:" + "\\Workspace\\SpeechToInfomation"
    return historical.casefold() not in rendered.casefold()


def _passwords_from_environment(env: dict[str, str]) -> set[str]:
    passwords: set[str] = set()
    for name in ("DATABASE_URL", "TEST_DATABASE_URL"):
        value = env.get(name)
        if not value:
            continue
        try:
            password = make_url(value).password
        except Exception:
            continue
        if password:
            passwords.add(password)
    return passwords


def _credential_markers_absent(rendered: str, passwords: set[str]) -> bool:
    rendered_casefold = rendered.casefold()
    markers = {
        marker.casefold()
        for password in passwords
        for marker in (
            f":{password}@",
            f"password={password}",
            f'"password": "{password}"',
        )
    }
    return not any(marker in rendered_casefold for marker in markers) and not any(
        password in rendered for password in passwords
    )


def _report_credentials_absent(value: Any, passwords: set[str]) -> bool:
    def visit(item: Any, path: tuple[str, ...]) -> bool:
        if isinstance(item, dict):
            return all(visit(child, (*path, str(key))) for key, child in item.items())
        if isinstance(item, list):
            return all(visit(child, (*path, str(index))) for index, child in enumerate(item))
        if not isinstance(item, str):
            return True
        for password in passwords:
            if password not in item:
                continue
            key = path[-1] if path else ""
            safe_driver = key == "driver" and item.casefold().startswith("postgresql")
            safe_maintenance = key == "maintenance_database" and item == password
            if not safe_driver and not safe_maintenance:
                return False
        return True

    return visit(value, ())


def _run_non_test_guard(repo_root: Path) -> dict[str, Any]:
    secret = "p0-guard-secret-must-not-appear"
    env = os.environ.copy()
    env.update(
        {
            "TEST_DATABASE_URL": (
                f"postgresql://guard_user:{secret}@127.0.0.1:1/speech_to_info"
            ),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    completed = subprocess.run(
        [
            str(repo_root / "venv/Scripts/python.exe"),
            "-c",
            "import runpy; runpy.run_path(r'tests/conftest.py')",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    rendered = completed.stdout + completed.stderr
    return {
        "exit_code": completed.returncode,
        "guard_message_present": "must target a database whose name ends with '_test'"
        in rendered,
        "connection_attempt_absent": "connection refused" not in rendered.casefold(),
        "credential_absent": secret not in rendered,
        "stdout_sha256": _content_sha256(completed.stdout),
        "stderr_sha256": _content_sha256(completed.stderr),
    }


def _database_lock_key(url: URL, scope: str = "pytest-session") -> int:
    driver = url.drivername.split("+", 1)[0].casefold()
    host = (url.host or "localhost").casefold()
    port = url.port or 5432
    database = (url.database or "").casefold()
    material = f"{scope}\0{driver}\0{host}\0{port}\0{database}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=True)


def _run_parallel_probe(
    repo_root: Path,
    test_url: URL,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_root = repo_root / "output/audits"
    evidence_root.mkdir(parents=True, exist_ok=True)
    nonce = f"{os.getpid()}-{datetime.now(timezone.utc).strftime('%H%M%S%f')}"
    evidence_paths = [
        evidence_root / f"p0-test-isolation-{nonce}-{label}.json"
        for label in ("a", "b")
    ]
    command = [
        str(repo_root / "venv/Scripts/python.exe"),
        "-m",
        "pytest",
        "-q",
        "tests/test_test_database_isolation.py",
        "-k",
        "p0_subprocess_lock_probe",
        "-p",
        "no:cacheprovider",
    ]
    processes: list[
        tuple[subprocess.Popen[str], Path, list[str], dict[str, str]]
    ] = []
    base_env = os.environ.copy()
    base_env.update(
        {
            "TEST_DATABASE_URL": test_url.render_as_string(hide_password=False),
            "P0_SUBPROCESS_LOCK_PROBE_SECONDS": "1.0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    for evidence_path in evidence_paths:
        env = base_env.copy()
        env["TEST_DATABASE_LOCK_EVIDENCE_PATH"] = str(
            evidence_path.relative_to(repo_root)
        )
        process = subprocess.Popen(
            command,
            cwd=repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append((process, evidence_path, command, env))
    results: list[dict[str, Any]] = []
    for process, evidence_path, process_command, process_env in processes:
        try:
            stdout, stderr = process.communicate(timeout=240)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        rendered = stdout + stderr
        results.append(
            {
                "command": process_command,
                "exit_code": process.returncode,
                "stdout_sha256": _content_sha256(stdout),
                "stderr_sha256": _content_sha256(stderr),
                "pytest_summary": _pytest_summary(rendered),
                "historical_workspace_path_absent": (
                    _historical_workspace_path_absent(rendered)
                ),
                "credential_markers_absent": _credential_markers_absent(
                    rendered, _passwords_from_environment(process_env)
                ),
                "lock_evidence_path": evidence_path.relative_to(repo_root).as_posix(),
            }
        )
    windows = []
    for path in evidence_paths:
        raw = path.read_text(encoding="utf-8") if path.is_file() else ""
        window = json.loads(raw) if raw else {}
        window["historical_workspace_path_absent"] = _historical_workspace_path_absent(
            raw
        )
        windows.append(window)
    return results, windows


def _run_exception_probe(
    repo_root: Path,
    test_url: URL,
) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence_root = repo_root / "output/audits"
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_root / (
        "p0-test-isolation-exception-"
        f"{os.getpid()}-{datetime.now(timezone.utc).strftime('%H%M%S%f')}.json"
    )
    env = os.environ.copy()
    env.update(
        {
            "TEST_DATABASE_URL": test_url.render_as_string(hide_password=False),
            "TEST_DATABASE_LOCK_EVIDENCE_PATH": str(
                evidence_path.relative_to(repo_root)
            ),
            "P0_SUBPROCESS_LOCK_PROBE_SECONDS": "0.1",
            "P0_SUBPROCESS_LOCK_PROBE_MODE": "raise",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    command = [
        str(repo_root / "venv/Scripts/python.exe"),
        "-m",
        "pytest",
        "-q",
        "tests/test_test_database_isolation.py",
        "-k",
        "p0_subprocess_lock_probe",
        "-p",
        "no:cacheprovider",
    ]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    rendered = completed.stdout + completed.stderr
    result = {
        "command": command,
        "exit_code": completed.returncode,
        "stdout_sha256": _content_sha256(completed.stdout),
        "stderr_sha256": _content_sha256(completed.stderr),
        "pytest_summary": _pytest_summary(rendered),
        "historical_workspace_path_absent": _historical_workspace_path_absent(
            rendered
        ),
        "credential_markers_absent": _credential_markers_absent(
            rendered, _passwords_from_environment(env)
        ),
        "lock_evidence_path": evidence_path.relative_to(repo_root).as_posix(),
    }
    raw = evidence_path.read_text(encoding="utf-8") if evidence_path.is_file() else ""
    window = json.loads(raw) if raw else {}
    window["historical_workspace_path_absent"] = _historical_workspace_path_absent(
        raw
    )
    return result, window


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else None


def _windows_do_not_overlap(windows: list[dict[str, Any]]) -> bool:
    if len(windows) != 2:
        return False
    acquired = [_parse_time(window.get("acquired_at")) for window in windows]
    released = [_parse_time(window.get("released_at")) for window in windows]
    if any(value is None for value in [*acquired, *released]):
        return False
    first_acquired, second_acquired = acquired
    first_released, second_released = released
    assert first_acquired and second_acquired and first_released and second_released
    return first_released <= second_acquired or second_released <= first_acquired


def _lock_window_valid(
    window: dict[str, Any],
    *,
    conftest_sha256: str,
    test_url: URL,
) -> bool:
    expected_database = _redacted_database(test_url)
    expected_key = _database_lock_key(test_url)
    requested = _parse_time(window.get("requested_at"))
    acquired = _parse_time(window.get("acquired_at"))
    released = _parse_time(window.get("released_at"))
    return bool(
        isinstance(window.get("pid"), int)
        and window["pid"] > 0
        and isinstance(window.get("backend_pid"), int)
        and window["backend_pid"] > 0
        and requested is not None
        and acquired is not None
        and released is not None
        and requested <= acquired <= released
        and window.get("scope") == "pytest-session"
        and window.get("lock_key") == expected_key
        and window.get("database") == expected_database
        and window.get("conftest_sha256") == conftest_sha256
        and window.get("historical_workspace_path_absent") is True
    )


def _lock_windows_valid(
    windows: list[dict[str, Any]],
    *,
    conftest_sha256: str,
    test_url: URL,
) -> bool:
    if len(windows) != 2 or not all(
        _lock_window_valid(
            window,
            conftest_sha256=conftest_sha256,
            test_url=test_url,
        )
        for window in windows
    ):
        return False
    process_pids = {int(window["pid"]) for window in windows}
    backend_pids = {int(window["backend_pid"]) for window in windows}
    return (
        len(process_pids) == 2
        and len(backend_pids) == 2
        and _windows_do_not_overlap(windows)
    )


def _remaining_runtime_state(test_url: URL, maintenance_database: str) -> dict[str, int]:
    engine = create_engine(
        test_url.set(database=maintenance_database),
        poolclass=NullPool,
    )
    try:
        with engine.connect() as connection:
            sessions = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": test_url.database},
                ).scalar_one()
            )
            advisory_locks = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM pg_locks l "
                        "JOIN pg_database d ON d.oid = l.database "
                        "WHERE l.locktype = 'advisory' AND d.datname = :database_name"
                    ),
                    {"database_name": test_url.database},
                ).scalar_one()
            )
            return {"test_sessions": sessions, "test_advisory_locks": advisory_locks}
    finally:
        engine.dispose()


def build_report(repo_root: Path) -> dict[str, Any]:
    repo_root = _canonical_repo(repo_root)
    application_url, test_url, maintenance_database = _database_urls(repo_root)
    before = _application_fingerprint(application_url)
    env = os.environ.copy()
    env.update(
        {
            "TEST_DATABASE_URL": test_url.render_as_string(hide_password=False),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    sequential = _run(
        [
            str(repo_root / "venv/Scripts/python.exe"),
            "-m",
            "pytest",
            "-q",
            "tests/test_test_database_isolation.py",
            "tests/test_database_safety.py",
            "-k",
            "not p0_subprocess_lock_probe",
            "-p",
            "no:cacheprovider",
        ],
        cwd=repo_root,
        env=env,
    )
    non_test_guard = _run_non_test_guard(repo_root)
    parallel_results, lock_windows = _run_parallel_probe(repo_root, test_url)
    exception_result, exception_window = _run_exception_probe(repo_root, test_url)
    after = _application_fingerprint(application_url)
    runtime_state = _remaining_runtime_state(test_url, maintenance_database)
    source_hashes = {relative: _sha256(repo_root / relative) for relative in SOURCE_PATHS}
    non_test_rejected = bool(
        non_test_guard["exit_code"] != 0
        and non_test_guard["guard_message_present"]
        and non_test_guard["connection_attempt_absent"]
        and non_test_guard["credential_absent"]
    )
    checks = {
        "non_test_database_rejected": non_test_rejected,
        "concurrent_runs_isolated": all(
            result["exit_code"] == 0 for result in parallel_results
        )
        and _lock_windows_valid(
            lock_windows,
            conftest_sha256=source_hashes["tests/conftest.py"],
            test_url=test_url,
        ),
        "application_database_unchanged": before == after,
        "sequential_targeted_suite_passed": sequential["exit_code"] == 0,
        "session_lock_released": runtime_state
        == {"test_sessions": 0, "test_advisory_locks": 0},
        "exception_path_releases_lock": bool(
            exception_result["exit_code"] != 0
            and _lock_window_valid(
                exception_window,
                conftest_sha256=source_hashes["tests/conftest.py"],
                test_url=test_url,
            )
        ),
        "historical_workspace_path_absent": bool(
            sequential["historical_workspace_path_absent"]
            and all(
                result["historical_workspace_path_absent"]
                for result in parallel_results
            )
            and all(
                window.get("historical_workspace_path_absent") is True
                for window in lock_windows
            )
            and exception_result["historical_workspace_path_absent"]
            and exception_window.get("historical_workspace_path_absent") is True
        ),
        "credentials_absent": bool(
            non_test_guard["credential_absent"]
            and sequential["credential_markers_absent"]
            and all(result["credential_markers_absent"] for result in parallel_results)
            and exception_result["credential_markers_absent"]
        ),
    }
    blockers = sorted(name for name, passed in checks.items() if not passed)
    report = {
        "schema_version": "rtk-evidence-v1",
        "artifact_type": "p0-test-database-isolation",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "canonical_workspace": True,
        "scope": "dedicated_test_database_only_no_application_ddl",
        "verdict": "PASS" if not blockers else "BLOCKED",
        "exit_code": 0 if not blockers else 2,
        "command": [
            str(repo_root / "venv/Scripts/python.exe"),
            "-B",
            "scripts/verify_test_database_isolation.py",
        ],
        "environment": {
            "application_database": _redacted_database(application_url),
            "test_database": _redacted_database(test_url),
            "maintenance_database": maintenance_database,
            "credentials_recorded": False,
        },
        "git_parent_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
        ).strip(),
        "harness_path": "scripts/verify_test_database_isolation.py",
        "harness_sha256": source_hashes["scripts/verify_test_database_isolation.py"],
        "source_sha256": source_hashes,
        "application_fingerprint_before": before,
        "application_fingerprint_after": after,
        "non_test_database_guard": non_test_guard,
        "sequential_targeted_suite": sequential,
        "parallel_probe_results": parallel_results,
        "lock_windows": lock_windows,
        "exception_probe_result": exception_result,
        "exception_lock_window": exception_window,
        "remaining_runtime_state": runtime_state,
        "checks": checks,
        "blockers": blockers,
        "limitations": [
            "Full pytest remains blocked until later P0 packages close their own gates.",
            "This verifier serializes one shared _test database; it does not enable xdist.",
            "Abrupt process termination (hard kill) relies on PostgreSQL connection cleanup and is not simulated here.",
        ],
    }
    sensitive_urls = {
        url.render_as_string(hide_password=False)
        for url in (application_url, test_url)
    }
    passwords = {
        password
        for password in (application_url.password, test_url.password)
        if password
    }
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True)
    if any(value in rendered for value in sensitive_urls) or not _report_credentials_absent(
        report, passwords
    ):
        raise ValueError("credential value leaked into evidence report")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=CANONICAL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        repo_root = _canonical_repo(args.repo)
        output = _validated_output(repo_root, args.output)
        report = build_report(repo_root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
