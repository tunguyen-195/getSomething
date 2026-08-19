import importlib
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, text

from src.database.config.database import SessionLocal, engine
from src.database.models.models import AudioFile, Case, Language, Task, User
from src.main import app


client = TestClient(app)
MIGRATION = importlib.import_module(
    "src.database.migrations.versions."
    "e6f7a8b9c2_normalize_case_audio_created_at"
)


def _assert_utc_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
    return parsed


def _create_case(title: str) -> int:
    response = client.post("/api/v1/cases/", json={"title": title})
    assert response.status_code == 201, response.text
    _assert_utc_iso(response.json()["created_at"])
    return response.json()["id"]


def _seed_audio(case_id: int, *, transcription: str = "") -> tuple[str, int]:
    with SessionLocal() as db:
        user_id = db.query(User.id).order_by(User.id.asc()).first()[0]
        language_id = db.query(Language.id).order_by(Language.id.asc()).first()[0]
        task = Task(
            id=str(uuid.uuid4()),
            filename=f"{uuid.uuid4().hex}.wav",
            status="transcribed" if transcription else "uploaded",
            result={
                "transcription": transcription,
                "audio_sha256": "a" * 64,
                "audio_integrity_status": "verified_at_upload",
            },
            case_id=case_id,
            user_id=user_id,
        )
        db.add(task)
        db.flush()
        audio = AudioFile(
            filename=task.filename,
            file_path=f"cases/{case_id}/{task.filename}",
            file_size=16,
            status=task.status,
            task_id=task.id,
            case_id=case_id,
            language_id=language_id,
            uploaded_by=user_id,
        )
        db.add(audio)
        db.commit()
        return task.id, audio.id


def test_creation_timestamp_model_contract_and_query_indexes():
    for model in (Case, AudioFile):
        column = model.__table__.c.created_at
        assert column.type.timezone is True
        assert column.nullable is False
        assert column.server_default is not None

    case_indexes = {
        index.name: [column.name for column in index.columns]
        for index in Case.__table__.indexes
    }
    audio_indexes = {
        index.name: [column.name for column in index.columns]
        for index in AudioFile.__table__.indexes
    }
    assert case_indexes["idx_case_archived_created_at"] == [
        "is_archived",
        "created_at",
        "id",
    ]
    assert audio_indexes["idx_audio_case_archived_created_at"] == [
        "case_id",
        "is_archived",
        "created_at",
        "id",
    ]


def test_case_and_audio_apis_return_utc_creation_metadata_without_n_plus_one():
    case_id = _create_case("Timestamp API contract")
    for _ in range(3):
        _seed_audio(case_id)

    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        compact_response = client.get(
            "/api/v1/cases/",
            params={"compact": True, "limit": 10, "search": "Timestamp API"},
        )
        files_response = client.get(f"/api/v1/cases/{case_id}/files")
        audio_response = client.get("/api/v1/audio/", params={"case_id": case_id})
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert compact_response.status_code == 200, compact_response.text
    compact_case = compact_response.json()[0]
    assert compact_case["id"] == case_id
    _assert_utc_iso(compact_case["created_at"])

    assert files_response.status_code == 200, files_response.text
    files = files_response.json()
    assert len(files) == 3
    for audio_file in files:
        created_at = _assert_utc_iso(audio_file["created_at"])
        uploaded_at = _assert_utc_iso(audio_file["uploaded_at"])
        assert uploaded_at == created_at

    assert audio_response.status_code == 200, audio_response.text
    assert len(audio_response.json()) == 3
    for audio_file in audio_response.json():
        assert _assert_utc_iso(audio_file["created_at"]) == _assert_utc_iso(
            audio_file["uploaded_at"]
        )

    direct_task_queries = [
        statement
        for statement in statements
        if "from tasks" in re.sub(r"\s+", " ", statement.lower())
    ]
    assert direct_task_queries == []


def test_summary_source_metadata_excludes_timestamp_fields(monkeypatch):
    case_id = _create_case("No timestamp prompt leakage")
    task_id, _ = _seed_audio(case_id, transcription="Nội dung kiểm thử")
    captured: dict = {}

    def fake_summary(*_args, **kwargs):
        captured.update(kwargs.get("source_metadata") or {})
        return {
            "available": True,
            "summary": "Tóm tắt kiểm thử",
            "visualization_data": None,
            "has_visualization": False,
        }

    module = importlib.import_module(
        "src.services.summarization.summary_service_v2"
    )
    monkeypatch.setattr(module, "summarize_transcript_v2", fake_summary)
    response = client.post(
        f"/api/v1/audio/v2/summarize/{task_id}",
        json={
            "model_name": "configured_api",
            "summary_type": "detailed",
            "include_context": True,
            "async_mode": False,
        },
    )
    assert response.status_code == 200, response.text
    assert {"created_at", "uploaded_at", "updated_at"}.isdisjoint(captured)


def test_batch_upload_returns_creation_metadata_with_one_metadata_query(monkeypatch):
    case_id = _create_case("Batch upload timestamp contract")
    seeded = [_seed_audio(case_id), _seed_audio(case_id)]
    pending_results = iter(
        {
            "task_id": task_id,
            "audio_id": audio_id,
            "audio_file_id": audio_id,
            "filename": f"batch-{index}.wav",
            "status": "uploaded",
        }
        for index, (task_id, audio_id) in enumerate(seeded, start=1)
    )

    audio_endpoint = importlib.import_module("src.api.endpoints.audio")
    monkeypatch.setattr(
        audio_endpoint,
        "save_audio_and_create_task",
        lambda *_args, **_kwargs: next(pending_results),
    )

    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        response = client.post(
            "/api/v1/audio/batch",
            data={"case_id": str(case_id)},
            files=[
                ("files", ("batch-1.wav", b"one", "audio/wav")),
                ("files", ("batch-2.wav", b"two", "audio/wav")),
            ],
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert len(payload["results"]) == 2
    for item in payload["results"]:
        assert _assert_utc_iso(item["created_at"]) == _assert_utc_iso(
            item["uploaded_at"]
        )

    metadata_queries = [
        statement
        for statement in statements
        if "from audio_files" in re.sub(r"\s+", " ", statement.lower())
        and "audio_files.id in" in re.sub(r"\s+", " ", statement.lower())
    ]
    assert len(metadata_queries) == 1


def test_migration_rehearsal_converts_only_case_and_audio_created_at():
    with engine.begin() as connection:
        for table_name in ("cases", "audio_files"):
            connection.execute(
                text(
                    f"ALTER TABLE {table_name} ALTER COLUMN created_at "
                    "TYPE TIMESTAMP WITHOUT TIME ZONE USING created_at "
                    "AT TIME ZONE 'Asia/Bangkok'"
                )
            )
            connection.execute(
                text(
                    f"ALTER TABLE {table_name} ALTER COLUMN created_at "
                    "DROP NOT NULL"
                )
            )
        connection.execute(text("DROP INDEX IF EXISTS idx_case_archived_created_at"))
        connection.execute(
            text("DROP INDEX IF EXISTS idx_audio_case_archived_created_at")
        )

        identifiers = connection.execute(
            text(
                """
                SELECT
                    (SELECT id FROM casestatuses ORDER BY id LIMIT 1) AS status_id,
                    (SELECT id FROM casepriorities ORDER BY id LIMIT 1) AS priority_id,
                    (SELECT id FROM users ORDER BY id LIMIT 1) AS user_id,
                    (SELECT id FROM languages ORDER BY id LIMIT 1) AS language_id
                """
            )
        ).mappings().one()
        legacy_time = datetime(2026, 8, 9, 10, 0)
        case_id = connection.execute(
            text(
                """
                INSERT INTO cases (
                    case_code, title, status_id, priority_id, created_by,
                    is_archived, case_metadata, created_at
                ) VALUES (
                    :case_code, 'Legacy creation time', :status_id, :priority_id,
                    :user_id, false, '{}'::json, :created_at
                ) RETURNING id
                """
            ),
            {
                "case_code": str(uuid.uuid4()),
                "status_id": identifiers["status_id"],
                "priority_id": identifiers["priority_id"],
                "user_id": identifiers["user_id"],
                "created_at": legacy_time,
            },
        ).scalar_one()
        audio_id = connection.execute(
            text(
                """
                INSERT INTO audio_files (
                    filename, file_path, file_size, status, case_id, language_id,
                    uploaded_by, is_archived, storage_type, storage_config,
                    extra_metadata, created_at
                ) VALUES (
                    'legacy.wav', :file_path, 16, 'uploaded', :case_id,
                    :language_id, :user_id, false, 'local', '{}'::json,
                    '{}'::json, :created_at
                ) RETURNING id
                """
            ),
            {
                "file_path": f"cases/{case_id}/legacy.wav",
                "case_id": case_id,
                "language_id": identifiers["language_id"],
                "user_id": identifiers["user_id"],
                "created_at": legacy_time,
            },
        ).scalar_one()
        context = MigrationContext.configure(connection)
        MIGRATION._upgrade(connection, Operations(context))

        expected = datetime(2026, 8, 9, 3, 0, tzinfo=timezone.utc)
        case_created = connection.execute(
            text("SELECT created_at FROM cases WHERE id = :id"),
            {"id": case_id},
        ).scalar_one()
        audio_created = connection.execute(
            text("SELECT created_at FROM audio_files WHERE id = :id"),
            {"id": audio_id},
        ).scalar_one()
        assert case_created.astimezone(timezone.utc) == expected
        assert audio_created.astimezone(timezone.utc) == expected

        inspector = inspect(connection)
        for table_name in ("cases", "audio_files"):
            created_at = {
                column["name"]: column
                for column in inspector.get_columns(table_name)
            }["created_at"]
            assert created_at["type"].timezone is True
            assert created_at["nullable"] is False
            assert created_at["default"] is not None

        task_created_at = {
            column["name"]: column
            for column in inspector.get_columns("tasks")
        }["created_at"]
        assert task_created_at["type"].timezone is False
        assert "idx_case_archived_created_at" in {
            index["name"] for index in inspector.get_indexes("cases")
        }
        assert "idx_audio_case_archived_created_at" in {
            index["name"] for index in inspector.get_indexes("audio_files")
        }


def test_migration_refuses_to_invent_missing_creation_time():
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE audio_files ALTER COLUMN created_at "
                "DROP NOT NULL"
            )
        )
        identifiers = connection.execute(
            text(
                """
                SELECT
                    (SELECT id FROM casestatuses ORDER BY id LIMIT 1) AS status_id,
                    (SELECT id FROM casepriorities ORDER BY id LIMIT 1) AS priority_id,
                    (SELECT id FROM users ORDER BY id LIMIT 1) AS user_id,
                    (SELECT id FROM languages ORDER BY id LIMIT 1) AS language_id
                """
            )
        ).mappings().one()
        case_id = connection.execute(
            text(
                """
                INSERT INTO cases (
                    case_code, title, status_id, priority_id, created_by,
                    is_archived, case_metadata
                ) VALUES (
                    :case_code, 'Missing audio creation time', :status_id,
                    :priority_id, :user_id, false, '{}'::json
                ) RETURNING id
                """
            ),
            {
                "case_code": str(uuid.uuid4()),
                "status_id": identifiers["status_id"],
                "priority_id": identifiers["priority_id"],
                "user_id": identifiers["user_id"],
            },
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO audio_files (
                    filename, file_path, file_size, status, case_id, language_id,
                    uploaded_by, is_archived, storage_type, storage_config,
                    extra_metadata, created_at
                ) VALUES (
                    'missing-created.wav', :file_path, 16, 'uploaded', :case_id,
                    :language_id, :user_id, false, 'local', '{}'::json,
                    '{}'::json, NULL
                )
                """
            ),
            {
                "file_path": f"cases/{case_id}/missing-created.wav",
                "case_id": case_id,
                "language_id": identifiers["language_id"],
                "user_id": identifiers["user_id"],
            },
        )
        context = MigrationContext.configure(connection)
        with pytest.raises(RuntimeError, match="Refusing to invent creation metadata"):
            MIGRATION._upgrade(connection, Operations(context))
