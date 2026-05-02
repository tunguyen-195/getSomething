import uuid
from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.core.auth import hash_value
from src.core.config import settings, validate_security_settings
from src.database.config.database import SessionLocal
from src.database.init_db import init_db
from src.database.models.models import (
    ActivityLog,
    ActivityType,
    AudioFile,
    Case,
    CaseParticipant,
    CasePriority,
    CaseStatus,
    ParticipantRole,
    SecurityAuditLog,
    Summary,
    Task,
    User,
    UserRole,
    Language,
)
from src.main import app
from src.services.task_service import extract_visualization_payload, update_task


@pytest.fixture()
def auth_enabled(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "COOKIE_SECURE", False)
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret-key-with-enough-length-1234567890")
    init_db()


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _create_user(
    username: str | None = None,
    password: str = "Password123!",
    *,
    is_active: bool = True,
    null_hash: bool = False,
    role_name: str = "user",
) -> tuple[int, str, str]:
    init_db()
    username = username or _unique("user")
    db = SessionLocal()
    try:
        role = db.query(UserRole).filter(UserRole.role_name == role_name).first()
        user = db.query(User).filter(User.username == username).first()
        if not user:
            user = User(
                username=username,
                email=f"{username}@example.test",
                full_name=username,
                role_id=role.id,
            )
            db.add(user)
            db.flush()
        user.is_active = is_active
        user.role_id = role.id
        user.email = f"{username}@example.test"
        if null_hash:
            user.password_hash = None
        else:
            user.set_password(password)
        db.commit()
        return user.id, username, password
    finally:
        db.close()


def _create_case_for_user(user_id: int) -> int:
    db = SessionLocal()
    try:
        status = db.query(CaseStatus).filter(CaseStatus.status_name == "active").first()
        priority = db.query(CasePriority).filter(CasePriority.priority_name == "high").first()
        owner_role = db.query(ParticipantRole).filter(ParticipantRole.role_name == "owner").first()
        case = Case(
            title=_unique("case"),
            case_code=str(uuid.uuid4()),
            status_id=status.id,
            priority_id=priority.id,
            created_by=user_id,
        )
        db.add(case)
        db.flush()
        db.add(CaseParticipant(case_id=case.id, user_id=user_id, role_id=owner_role.id, is_active=True))
        db.commit()
        return case.id
    finally:
        db.close()


def _create_task_for_user(user_id: int, case_id: int) -> str:
    task_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(
            Task(
                id=task_id,
                filename="restricted.wav",
                status="pending",
                case_id=case_id,
                user_id=user_id,
                result={"transcription": "restricted"},
            )
        )
        db.commit()
        return task_id
    finally:
        db.close()


def _create_orphan_task_for_user(user_id: int) -> str:
    task_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(
            Task(
                id=task_id,
                filename="orphan.wav",
                status="pending",
                case_id=None,
                user_id=user_id,
                result={"summary": "private orphan summary"},
            )
        )
        db.commit()
        return task_id
    finally:
        db.close()


def _create_audio_for_task(user_id: int, case_id: int, task_id: str, status: str = "uploaded") -> int:
    db = SessionLocal()
    try:
        language = db.query(Language).filter(Language.language_code == "vi").first() or db.query(Language).first()
        audio = AudioFile(
            filename=f"{uuid.uuid4().hex}.wav",
            file_path=f"cases/{case_id}/{uuid.uuid4().hex}.wav",
            file_size=10,
            duration=1.0,
            status=status,
            task_id=task_id,
            case_id=case_id,
            language_id=language.id,
            uploaded_by=user_id,
        )
        db.add(audio)
        db.commit()
        return audio.id
    finally:
        db.close()


def _create_summary(case_id: int | None, content: str) -> int:
    db = SessionLocal()
    try:
        summary = Summary(
            type="case" if case_id is not None else "global",
            case_id=case_id,
            files=[],
            content=content,
        )
        db.add(summary)
        db.commit()
        return summary.id
    finally:
        db.close()


def _login_client(username: str, password: str) -> TestClient:
    client = TestClient(app)
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 200, response.text
    return client


def _csrf_header(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(settings.CSRF_COOKIE_NAME)
    return {"x-csrf-token": token}


def _sample_path(path: str) -> str:
    return path.replace("{case_id}", "1").replace("{task_id}", "1").replace("{audio_id}", "1").replace("{file_id}", "1").replace("{summary_id}", "1").replace("{filename}", "sample.wav")


def test_route_inventory_is_private_by_default_when_auth_enabled(auth_enabled):
    client = TestClient(app)
    public = {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/auth/csrf"),
        ("POST", "/api/v1/auth/login"),
    }

    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        for method in sorted(route.methods or []):
            if method in {"HEAD", "OPTIONS"} or (method, route.path) in public:
                continue
            response = client.request(method, _sample_path(route.path))
            assert response.status_code == 401, f"{method} {route.path} returned {response.status_code}"


def test_static_audio_mount_removed():
    assert all(getattr(route, "path", None) != "/storage/audio" for route in app.routes)


def test_login_failures_are_generic_and_audited(auth_enabled):
    _, null_hash_username, _ = _create_user(null_hash=True)
    inactive_id, inactive_username, _ = _create_user(is_active=False)
    client = TestClient(app)
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]

    attempted = ["missing-user", null_hash_username, inactive_username]
    details = set()
    for username in attempted:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "wrong"},
            headers={"x-csrf-token": csrf},
        )
        assert response.status_code == 401
        details.add(response.json()["detail"])

    assert details == {"Invalid credentials"}

    db = SessionLocal()
    try:
        for username in attempted:
            assert (
                db.query(SecurityAuditLog)
                .filter(
                    SecurityAuditLog.event_type == "login",
                    SecurityAuditLog.status == "failure",
                    SecurityAuditLog.attempted_identifier_hash == hash_value(username.lower()),
                )
                .count()
                >= 1
            )
        inactive_log = (
            db.query(SecurityAuditLog)
            .filter(
                SecurityAuditLog.event_type == "login",
                SecurityAuditLog.status == "failure",
                SecurityAuditLog.user_id == inactive_id,
            )
            .first()
        )
        assert inactive_log is not None
        assert "password" not in (inactive_log.detail or {})
    finally:
        db.close()


def test_login_rate_limit_returns_429(auth_enabled, monkeypatch):
    calls: dict[str, int] = {}

    def fake_limiter(key: str, limit: int, window_seconds: int) -> None:
        calls[key] = calls.get(key, 0) + 1
        if calls[key] > 1:
            raise HTTPException(status_code=429, detail="Too many requests")

    monkeypatch.setattr("src.api.endpoints.auth.check_rate_limit", fake_limiter)
    client = TestClient(app)
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    payload = {"username": "rate-limit-user", "password": "wrong"}

    first_headers = {"x-csrf-token": csrf, "x-forwarded-for": "203.0.113.10"}
    second_headers = {"x-csrf-token": csrf, "x-forwarded-for": "203.0.113.11"}
    assert client.post("/api/v1/auth/login", json=payload, headers=first_headers).status_code == 401
    assert client.post("/api/v1/auth/login", json=payload, headers=second_headers).status_code == 429


def test_logout_revokes_server_side_session(auth_enabled):
    _, username, password = _create_user()
    client = _login_client(username, password)
    old_token = client.cookies.get(settings.AUTH_COOKIE_NAME)
    csrf = client.cookies.get(settings.CSRF_COOKIE_NAME)

    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf}).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401

    replay = TestClient(app)
    replay.cookies.set(settings.AUTH_COOKIE_NAME, old_token)
    replay.cookies.set(settings.CSRF_COOKIE_NAME, csrf)
    assert replay.get("/api/v1/auth/me").status_code == 401


def test_csrf_refresh_after_authenticated_reload_stays_usable(auth_enabled):
    _, username, password = _create_user()
    client = _login_client(username, password)

    refreshed = client.get("/api/v1/auth/csrf")
    assert refreshed.status_code == 200
    csrf = refreshed.json()["csrf_token"]
    assert client.cookies.get(settings.CSRF_COOKIE_NAME) == csrf

    response = client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    assert response.status_code == 200, response.text


def test_resource_level_auth_blocks_cross_case_task(auth_enabled):
    user_a_id, user_a, password_a = _create_user()
    user_b_id, _, _ = _create_user()
    case_b = _create_case_for_user(user_b_id)
    task_b = _create_task_for_user(user_b_id, case_b)

    client = _login_client(user_a, password_a)
    assert client.get(f"/api/v1/cases/{case_b}").status_code == 403
    assert client.get(f"/api/v1/tasks/{task_b}").status_code == 403


def test_case_archive_is_hidden_and_logged(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    client = _login_client(username, password)

    response = client.delete(f"/api/v1/cases/{case_id}", headers=_csrf_header(client))
    assert response.status_code == 200
    list_response = client.get("/api/v1/cases")
    assert list_response.status_code == 200
    assert case_id not in {case["id"] for case in list_response.json()}

    db = SessionLocal()
    try:
        archive_type = db.query(ActivityType).filter(ActivityType.type_name == "archive").first()
        assert (
            db.query(ActivityLog)
            .filter(
                ActivityLog.case_id == case_id,
                ActivityLog.user_id == user_id,
                ActivityLog.activity_type_id == archive_type.id,
            )
            .count()
            >= 1
        )
    finally:
        db.close()


def test_archived_case_is_read_only_for_owner(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    client = _login_client(username, password)

    assert client.delete(f"/api/v1/cases/{case_id}", headers=_csrf_header(client)).status_code == 200

    create_task_response = client.post(
        "/api/v1/tasks",
        json={"filename": "new.wav", "case_id": case_id},
        headers=_csrf_header(client),
    )
    assert create_task_response.status_code == 403

    process_response = client.post(
        f"/api/v1/audio/process-task/{task_id}",
        json={"model_name": "test-model"},
        headers=_csrf_header(client),
    )
    assert process_response.status_code == 403

    read_response = client.get(f"/api/v1/tasks/{task_id}")
    assert read_response.status_code == 200


def test_summaries_are_scoped_to_accessible_cases_and_global_is_admin_only(auth_enabled):
    user_a_id, username_a, password_a = _create_user()
    user_b_id, _, _ = _create_user()
    _, admin_username, admin_password = _create_user(role_name="admin")
    case_a = _create_case_for_user(user_a_id)
    case_b = _create_case_for_user(user_b_id)
    summary_a = _create_summary(case_a, "user a summary")
    summary_b = _create_summary(case_b, "user b summary")
    global_summary = _create_summary(None, "global summary")

    client_a = _login_client(username_a, password_a)
    response = client_a.get("/api/v1/summaries")
    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()}
    assert summary_a in returned_ids
    assert summary_b not in returned_ids
    assert global_summary not in returned_ids

    assert client_a.get(f"/api/v1/summaries/{summary_b}").status_code == 403
    assert client_a.get(f"/api/v1/summaries/{global_summary}").status_code == 403
    assert client_a.post(
        "/api/v1/summaries",
        json={
            "type": "global",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "case_id": None,
            "files": [],
            "content": "should not be created",
        },
        headers=_csrf_header(client_a),
    ).status_code == 403

    admin_client = _login_client(admin_username, admin_password)
    admin_response = admin_client.get("/api/v1/summaries")
    assert admin_response.status_code == 200
    admin_ids = {item["id"] for item in admin_response.json()}
    assert {summary_a, summary_b, global_summary}.issubset(admin_ids)


def test_expensive_summary_endpoints_are_rate_limited(auth_enabled, monkeypatch):
    _, username, password = _create_user()
    client = _login_client(username, password)

    def deny_limiter(key: str, limit: int, window_seconds: int) -> None:
        raise HTTPException(status_code=429, detail="Too many requests")

    monkeypatch.setattr("src.api.endpoints.summary.check_rate_limit", deny_limiter)
    monkeypatch.setattr("src.api.endpoints.audio.check_rate_limit", deny_limiter)

    assert client.post(
        "/api/v1/summaries/analyze",
        json={"summary": "hello"},
        headers=_csrf_header(client),
    ).status_code == 429
    assert client.post(
        "/api/v1/summaries/visualize",
        json={"summary": "hello"},
        headers=_csrf_header(client),
    ).status_code == 429
    assert client.post(
        "/api/v1/audio/summarize-multi",
        json={"transcripts": {"transcripts": ["hello"]}},
        headers=_csrf_header(client),
    ).status_code == 429


def test_required_torch_requirements_file_is_tracked():
    path = Path("requirements-torch-cu121.txt")
    assert path.is_file()
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path)],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_audio_list_preserves_case_authorization_errors(auth_enabled):
    _, username_a, password_a = _create_user()
    user_b_id, _, _ = _create_user()
    case_b = _create_case_for_user(user_b_id)
    client = _login_client(username_a, password_a)

    forbidden = client.get(f"/api/v1/audio?case_id={case_b}")
    assert forbidden.status_code == 403

    missing = client.get("/api/v1/audio?case_id=99999999")
    assert missing.status_code == 404


def test_audio_list_derives_summarized_status_from_task(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    audio_id = _create_audio_for_task(user_id, case_id, task_id, status="transcribed")
    assert update_task(task_id, {"status": "summarized", "summary": "done"})
    db = SessionLocal()
    try:
        audio = db.query(AudioFile).filter(AudioFile.id == audio_id).first()
        audio.status = "transcribed"
        db.commit()
    finally:
        db.close()

    client = _login_client(username, password)
    response = client.get(f"/api/v1/audio?case_id={case_id}")
    assert response.status_code == 200, response.text
    item = next(row for row in response.json() if row["task_id"] == task_id)
    assert item["status"] == "summarized"
    assert item["audio_status"] == "transcribed"


def test_visualization_payload_is_unwrapped_across_writers(auth_enabled, monkeypatch):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    _create_audio_for_task(user_id, case_id, task_id, status="transcribed")
    payload = {"nodes": [{"id": "n1"}], "edges": [], "timeline": [], "entity_types": ["person"], "main_events": []}
    wrapper = {"task_id": task_id, "status": "visualization_ready", "visualization_type": "all", "data": payload}

    assert extract_visualization_payload(wrapper) == payload
    assert update_task(task_id, {"visualization": wrapper})

    db = SessionLocal()
    try:
        assert db.query(Task).filter(Task.id == task_id).first().result["visualization_data"] == payload
    finally:
        db.close()

    from src.services.visualization_service import generate_visualization

    result = generate_visualization(task_id)
    assert result["visualization_data"]["schema_version"] == "analysis_intelligence.v2"
    assert result["visualization_data"]["legacy_view"] == {
        "nodes": result["visualization_data"]["nodes"],
        "edges": result["visualization_data"]["edges"],
        "timeline": result["visualization_data"]["timeline"],
        "main_events": result["visualization_data"]["main_events"],
        "entity_types": result["visualization_data"]["entity_types"],
    }

    monkeypatch.setattr("src.api.endpoints.audio.generate_visualization", lambda *_args, **_kwargs: wrapper)
    monkeypatch.setattr("src.services.visualization_service.generate_visualization", lambda *_args, **_kwargs: wrapper)

    client = _login_client(username, password)
    headers = _csrf_header(client)
    legacy = client.post(
        f"/api/v1/audio/visualize/{task_id}",
        json={"visualization_type": "all"},
        headers=headers,
    )
    assert legacy.status_code == 200, legacy.text

    v2 = client.post(
        f"/api/v1/audio/v2/visualize/{task_id}",
        json={"visualization_type": "all"},
        headers=headers,
    )
    assert v2.status_code == 200, v2.text

    from src.worker.tasks import visualize_task

    worker_result = visualize_task.run(task_id, "all")
    assert worker_result["status"] == "success"

    db = SessionLocal()
    try:
        stored = db.query(Task).filter(Task.id == task_id).first().result["visualization_data"]
        assert stored == payload
    finally:
        db.close()


def test_summary_analyze_blocks_cross_user_orphan_task(auth_enabled):
    user_a_id, _, _ = _create_user()
    _, username_b, password_b = _create_user()
    orphan_task_id = _create_orphan_task_for_user(user_a_id)
    client_b = _login_client(username_b, password_b)

    response = client_b.post(
        "/api/v1/summaries/analyze",
        json={"summary": "private summary", "task_id": orphan_task_id},
        headers=_csrf_header(client_b),
    )
    assert response.status_code == 403


def test_task_result_updates_merge_without_dropping_existing_fields():
    user_id, _, _ = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)

    assert update_task(task_id, {"transcript": "hello", "segments": [{"start": 0, "end": 1}]})
    assert update_task(task_id, {"summary": "short summary"})
    assert update_task(task_id, {"visualization_data": {"nodes": []}, "has_visualization": True})

    db = SessionLocal()
    try:
        result = db.query(Task).filter(Task.id == task_id).first().result
        assert result["transcription"] == "hello"
        assert result["summary"] == "short summary"
        assert result["segments"] == [{"start": 0, "end": 1}]
        assert result["visualization_data"] == {"nodes": []}
        assert result["has_visualization"] is True
    finally:
        db.close()


def test_production_rejects_default_secret(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "COOKIE_SECURE", True)
    monkeypatch.setattr(settings, "SECRET_KEY", "your-super-secret-key-here")

    with pytest.raises(RuntimeError, match="Weak SECRET_KEY"):
        validate_security_settings()
