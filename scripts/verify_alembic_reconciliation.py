"""Verify Alembic upgrades on a fresh database and a disposable live clone.

The source database is never migrated. A temporary pg_dump is restored into a
randomly named database, upgraded, inspected, and deleted in a finally block.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from check_alembic_reconciliation import build_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, database_url: URL, password: str | None = None) -> str:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url.render_as_string(hide_password=False)
    if password:
        env["PGPASSWORD"] = password
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _database_exists(connection, database_name: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
            {"database_name": database_name},
        ).scalar()
    )


def _create_database(connection, database_name: str) -> None:
    if _database_exists(connection, database_name):
        raise RuntimeError(f"Refusing to overwrite existing database {database_name}")
    connection.execute(text(f'CREATE DATABASE "{database_name}"'))


def _drop_database(connection, database_name: str) -> None:
    if not _database_exists(connection, database_name):
        return
    connection.execute(
        text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :database_name AND pid <> pg_backend_pid()"
        ),
        {"database_name": database_name},
    )
    connection.execute(text(f'DROP DATABASE "{database_name}"'))


def _current_revision(database_url: URL) -> str | None:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    finally:
        engine.dispose()


def _public_table_count(database_url: URL) -> int:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                ).scalar_one()
            )
    finally:
        engine.dispose()


def _prefixed_audio_path_count(database_url: URL) -> int:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM audio_files "
                        "WHERE file_path LIKE 'storage/audio/%' "
                        "OR file_path LIKE 'storage/audio\\\\%'"
                    )
                ).scalar_one()
            )
    finally:
        engine.dispose()


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    source_url_value = os.getenv("DATABASE_URL")
    if not source_url_value:
        raise RuntimeError("DATABASE_URL is required")

    source_url = make_url(source_url_value)
    if source_url.get_backend_name() != "postgresql":
        raise RuntimeError("This verifier requires PostgreSQL")

    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    if not pg_dump or not pg_restore:
        raise RuntimeError("pg_dump and pg_restore must be available on PATH")

    suffix = uuid.uuid4().hex[:10]
    fresh_name = f"sti_alembic_fresh_{suffix}_test"
    clone_name = f"sti_alembic_clone_{suffix}_test"
    fresh_url = source_url.set(database=fresh_name)
    clone_url = source_url.set(database=clone_name)
    maintenance_url = source_url.set(database=os.getenv("TEST_DATABASE_ADMIN_DB", "postgres"))

    maintenance_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    report: dict[str, object] = {
        "source": {
            "host": source_url.host,
            "port": source_url.port,
            "database": source_url.database,
        }
    }
    try:
        with maintenance_engine.connect() as connection:
            _create_database(connection, fresh_name)
            _create_database(connection, clone_name)

        _run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            database_url=fresh_url,
        )
        report["fresh"] = {
            "revision": _current_revision(fresh_url),
            "public_tables": _public_table_count(fresh_url),
        }

        with tempfile.TemporaryDirectory(prefix="sti_alembic_") as temp_dir:
            dump_path = Path(temp_dir) / "source.dump"
            common_args = [
                "-h",
                source_url.host or "localhost",
                "-p",
                str(source_url.port or 5432),
                "-U",
                source_url.username or "postgres",
            ]
            _run(
                [pg_dump, *common_args, "-Fc", "-f", str(dump_path), source_url.database or ""],
                database_url=source_url,
                password=source_url.password,
            )
            _run(
                [
                    pg_restore,
                    *common_args,
                    "--no-owner",
                    "--no-privileges",
                    "-d",
                    clone_name,
                    str(dump_path),
                ],
                database_url=clone_url,
                password=source_url.password,
            )

        clone_before_report, clone_before_exit = build_report(
            clone_url.render_as_string(hide_password=False)
        )
        clone_before_revision = _current_revision(clone_url)
        paths_before = _prefixed_audio_path_count(clone_url)
        if clone_before_exit != 0:
            raise RuntimeError(
                "Disposable clone does not match c4 contract: "
                f"{clone_before_report['mismatches']}"
            )

        _run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            database_url=clone_url,
        )
        report["clone"] = {
            "before_revision": clone_before_revision,
            "before_reconciliation": clone_before_report["status"],
            "after_revision": _current_revision(clone_url),
            "prefixed_audio_paths_before": paths_before,
            "prefixed_audio_paths_after": _prefixed_audio_path_count(clone_url),
        }
    finally:
        with maintenance_engine.connect() as connection:
            _drop_database(connection, fresh_name)
            _drop_database(connection, clone_name)
        maintenance_engine.dispose()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
