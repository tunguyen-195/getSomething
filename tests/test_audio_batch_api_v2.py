from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.core.auth import get_current_user
from src.core.config import settings
from src.database.config.database import SessionLocal
from src.database.models.models import (
    AudioBatch,
    AudioBatchItem,
    AudioBatchSummaryJob,
    AudioFile,
    Case,
    CasePriority,
    CaseStatus,
    Task,
    User,
)
from src.main import app
from src.services.audio_storage import StagedAudio


def _case_for_dev_user() -> tuple[int, int]:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == settings.DEV_USER_ID).one()
        case_status = db.query(CaseStatus).order_by(CaseStatus.id.asc()).first()
        priority = db.query(CasePriority).order_by(CasePriority.id.asc()).first()
        assert case_status is not None and priority is not None
        case = Case(
            case_code=uuid4().hex,
            title="Audio batch API",
            status_id=case_status.id,
            priority_id=priority.id,
            created_by=user.id,
        )
        db.add(case)
        db.commit()
        return user.id, case.id
    finally:
        db.close()


def _fake_audio_stager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    storage_root = tmp_path / "audio-storage"
    monkeypatch.setattr(settings, "AUDIO_STORAGE_ROOT", str(storage_root))

    def fake_stage(upload) -> StagedAudio:
        name = upload.filename or "audio.wav"
        payload = upload.file.read()
        suffix = Path(name).suffix.lower().lstrip(".") or "wav"
        temp_dir = storage_root / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"{uuid4().hex}.{suffix}"
        temp_path.write_bytes(payload)
        return StagedAudio(
            original_filename=name,
            temp_path=temp_path,
            size=len(payload),
            extension=suffix,
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    monkeypatch.setattr("src.services.audio_batch_service.stage_upload", fake_stage)
    return storage_root


def _batch_files(*names: str):
    return [
        ("files[]", (name, f"payload:{name}".encode(), "audio/wav")) for name in names
    ]


def test_batch_upload_is_ordered_atomic_and_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_audio_stager(monkeypatch, tmp_path)
    _user_id, case_id = _case_for_dev_user()
    client = TestClient(app)
    data = {"case_id": str(case_id), "idempotency_key": "api-replay"}

    first = client.post(
        "/api/v1/audio/v2/batches",
        data=data,
        files=_batch_files("one.wav", "two.wav"),
    )
    assert first.status_code == 202, first.text
    payload = first.json()
    assert [item["position"] for item in payload["items"]] == [0, 1]
    assert [item["original_filename"] for item in payload["items"]] == [
        "one.wav",
        "two.wav",
    ]

    replay = client.post(
        "/api/v1/audio/v2/batches",
        data=data,
        files=_batch_files("one.wav", "two.wav"),
    )
    assert replay.status_code == 202, replay.text
    assert replay.json() == payload

    db = SessionLocal()
    try:
        assert db.query(AudioBatch).count() == 1
        assert db.query(AudioBatchItem).count() == 2
        assert db.query(Task).count() == 2
        assert db.query(AudioFile).count() == 2
    finally:
        db.close()


def test_batch_upload_mixed_invalid_file_rolls_back_rows_and_temp_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    storage_root = _fake_audio_stager(monkeypatch, tmp_path)
    _user_id, case_id = _case_for_dev_user()
    original_stage = __import__(
        "src.services.audio_batch_service", fromlist=["stage_upload"]
    ).stage_upload
    calls = 0

    def fail_second(upload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HTTPException(status_code=400, detail="unsafe provider detail")
        return original_stage(upload)

    monkeypatch.setattr("src.services.audio_batch_service.stage_upload", fail_second)
    response = TestClient(app).post(
        "/api/v1/audio/v2/batches",
        data={"case_id": str(case_id), "idempotency_key": "mixed-invalid"},
        files=_batch_files("valid.wav", "invalid.wav"),
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "BATCH_AUDIO_FILE_INVALID"
    assert "unsafe provider detail" not in response.text

    db = SessionLocal()
    try:
        assert db.query(AudioBatch).count() == 0
        assert db.query(AudioBatchItem).count() == 0
        assert db.query(Task).count() == 0
        assert db.query(AudioFile).count() == 0
    finally:
        db.close()
    assert not list((storage_root / "tmp").glob("*"))


def test_batch_status_is_owner_scoped_and_malformed_ids_are_safe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_audio_stager(monkeypatch, tmp_path)
    _user_id, case_id = _case_for_dev_user()
    client = TestClient(app)
    created = client.post(
        "/api/v1/audio/v2/batches",
        data={"case_id": str(case_id), "idempotency_key": "owner-scope"},
        files=_batch_files("owner.wav"),
    )
    batch_id = created.json()["id"]

    db = SessionLocal()
    try:
        foreign = User(
            username=f"foreign-{uuid4().hex}",
            email=f"foreign-{uuid4().hex}@example.test",
            password_hash="not-used",
            is_active=True,
        )
        db.add(foreign)
        db.commit()
        db.refresh(foreign)
        foreign_id = foreign.id
    finally:
        db.close()

    def foreign_user():
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == foreign_id).one()
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = foreign_user
    try:
        denied = client.get(f"/api/v1/audio/v2/batches/{batch_id}")
        assert denied.status_code == 404
        assert batch_id not in denied.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    malformed = client.get("/api/v1/audio/v2/batches/not-a-uuid")
    assert malformed.status_code == 422
    assert "not-a-uuid" not in malformed.text


def test_batch_transcribe_duplicate_and_cancel_are_durable_and_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_audio_stager(monkeypatch, tmp_path)
    _user_id, case_id = _case_for_dev_user()
    client = TestClient(app)
    created = client.post(
        "/api/v1/audio/v2/batches",
        data={"case_id": str(case_id), "idempotency_key": "queue-cancel"},
        files=_batch_files("one.wav", "two.wav"),
    )
    batch_id = created.json()["id"]
    published: list[dict[str, object]] = []

    def fake_apply_async(*, kwargs, task_id):
        published.append({"kwargs": kwargs, "task_id": task_id})

    monkeypatch.setattr(
        "src.worker.tasks.batch_task.transcribe_audio_batch_task.apply_async",
        fake_apply_async,
    )
    queued = client.post(
        f"/api/v1/audio/v2/batches/{batch_id}/transcribe",
        json={
            "task_ids": [created.json()["items"][1]["task_id"]],
            "enable_diarization": False,
            "diarization_method": "none",
            "language": "vi",
            "fast_mode": True,
        },
    )
    assert queued.status_code == 202, queued.text
    assert queued.json() == {"batch_id": batch_id, "status": "queued"}
    assert published[0]["kwargs"] == {"batch_id": batch_id}
    selected_task_id = created.json()["items"][1]["task_id"]
    queued_status = client.get(f"/api/v1/audio/v2/batches/{batch_id}").json()
    assert [item["status"] for item in queued_status["items"]] == [
        "uploaded",
        "queued",
    ]
    db = SessionLocal()
    try:
        persisted = db.query(AudioBatch).filter(AudioBatch.id == batch_id).one()
        assert persisted.transcription_task_ids == [selected_task_id]
        selected = next(
            item for item in persisted.items if item.task_id == selected_task_id
        )
        unselected = next(
            item for item in persisted.items if item.task_id != selected_task_id
        )
        assert selected.celery_task_id == published[0]["task_id"]
        assert unselected.celery_task_id is None
    finally:
        db.close()

    duplicate = client.post(
        f"/api/v1/audio/v2/batches/{batch_id}/transcribe",
        json={"task_ids": [created.json()["items"][0]["task_id"]]},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "BATCH_TRANSCRIPTION_ALREADY_RUNNING"

    cancelled = client.post(f"/api/v1/audio/v2/batches/{batch_id}/cancel")
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelled"
    repeated = client.post(f"/api/v1/audio/v2/batches/{batch_id}/cancel")
    assert repeated.status_code == 202
    assert repeated.json() == cancelled.json()
    status_response = client.get(f"/api/v1/audio/v2/batches/{batch_id}").json()
    assert status_response["cancelled_count"] == 2
    assert {item["status"] for item in status_response["items"]} == {"cancelled"}


def test_batch_transcribe_invalid_subset_rejects_without_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_audio_stager(monkeypatch, tmp_path)
    _user_id, case_id = _case_for_dev_user()
    client = TestClient(app)
    created = client.post(
        "/api/v1/audio/v2/batches",
        data={"case_id": str(case_id), "idempotency_key": "invalid-subset"},
        files=_batch_files("one.wav", "two.wav"),
    ).json()
    batch_id = created["id"]
    valid_task_id = created["items"][0]["task_id"]
    response = client.post(
        f"/api/v1/audio/v2/batches/{batch_id}/transcribe",
        json={"task_ids": [valid_task_id, str(uuid4())]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "BATCH_TRANSCRIPTION_SELECTION_INVALID"

    status_response = client.get(f"/api/v1/audio/v2/batches/{batch_id}").json()
    assert status_response["status"] == "created"
    assert [item["status"] for item in status_response["items"]] == [
        "uploaded",
        "uploaded",
    ]
    db = SessionLocal()
    try:
        persisted = db.query(AudioBatch).filter(AudioBatch.id == batch_id).one()
        assert persisted.transcription_task_ids == []
        assert all(item.celery_task_id is None for item in persisted.items)
    finally:
        db.close()


def test_batch_summary_captures_exact_order_and_never_projects_raw_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_audio_stager(monkeypatch, tmp_path)
    _user_id, case_id = _case_for_dev_user()
    client = TestClient(app)
    created = client.post(
        "/api/v1/audio/v2/batches",
        data={"case_id": str(case_id), "idempotency_key": "summary-order"},
        files=_batch_files("first.wav", "second.wav"),
    ).json()
    batch_id = created["id"]
    task_ids = [item["task_id"] for item in created["items"]]

    db = SessionLocal()
    try:
        batch_items = (
            db.query(AudioBatchItem)
            .filter(AudioBatchItem.batch_id == batch_id)
            .order_by(AudioBatchItem.position.asc())
            .all()
        )
        for index, item in enumerate(batch_items):
            item.status = "transcribed"
            task = db.query(Task).filter(Task.id == item.task_id).one()
            task.status = "transcribed"
            task.result = {
                **(task.result or {}),
                "transcription": f"transcript {index}",
            }
        batch = db.query(AudioBatch).filter(AudioBatch.id == batch_id).one()
        batch.status = "succeeded"
        batch.completed_count = 2
        db.commit()
    finally:
        db.close()

    published: list[dict[str, object]] = []

    def fake_summary_apply_async(*, kwargs, task_id):
        published.append({"kwargs": kwargs, "task_id": task_id})

    monkeypatch.setattr(
        "src.worker.tasks.summarize_task.summarize_audio_batch_job_task.apply_async",
        fake_summary_apply_async,
    )
    secret_prompt = "focus SECRET_SUMMARY_PREFERENCE on chronology"
    submitted = client.post(
        f"/api/v1/audio/v2/batches/{batch_id}/summary",
        json={
            "task_ids": list(reversed(task_ids)),
            "summary_type": "detailed",
            "min_length": 100,
            "max_length": 400,
            "length_mode": "auto",
            "user_prompt": secret_prompt,
        },
    )
    assert submitted.status_code == 202, submitted.text
    response = submitted.json()
    assert response["status"] == "queued"
    assert response["user_prompt_applied"] is False
    assert [item["task_id"] for item in response["source_manifest"]] == list(
        reversed(task_ids)
    )
    assert secret_prompt not in submitted.text
    assert published[0]["kwargs"]["user_prompt"] == secret_prompt

    summary_job_id = response["summary_job_id"]
    polled = client.get(f"/api/v1/audio/v2/batches/{batch_id}/summary/{summary_job_id}")
    assert polled.status_code == 200
    assert polled.json() == response
    assert secret_prompt not in polled.text
    assert "transcript_sha256" not in polled.text
    assert "audio_id" not in polled.text

    cancelled = client.post(f"/api/v1/audio/v2/batches/{batch_id}/cancel")
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "succeeded"
    cancelled_job = client.get(
        f"/api/v1/audio/v2/batches/{batch_id}/summary/{summary_job_id}"
    )
    assert cancelled_job.status_code == 200
    assert cancelled_job.json()["status"] == "cancelled"
    assert cancelled_job.json()["summary"] is None

    db = SessionLocal()
    try:
        job = (
            db.query(AudioBatchSummaryJob)
            .filter(AudioBatchSummaryJob.id == summary_job_id)
            .one()
        )
        assert secret_prompt not in str(job.source_manifest)
        assert secret_prompt not in str(job.summary_options)
        assert len(job.source_manifest_sha256) == 64
    finally:
        db.close()
