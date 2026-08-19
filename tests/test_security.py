import uuid
from contextlib import nullcontext
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


def test_csrf_endpoint_recovers_cookie_session_mismatch(auth_enabled):
    _, username, password = _create_user()
    client = _login_client(username, password)

    client.cookies.set(
        settings.CSRF_COOKIE_NAME,
        "rotated-after-browser-reload",
        domain="testserver.local",
        path="/",
    )
    refresh = client.get("/api/v1/auth/csrf")

    assert refresh.status_code == 200
    recovered = refresh.json()["csrf_token"]
    assert recovered != "rotated-after-browser-reload"
    assert client.cookies.get(settings.CSRF_COOKIE_NAME) == recovered
    assert (
        client.post(
            "/api/v1/auth/logout",
            headers={"x-csrf-token": recovered},
        ).status_code
        == 200
    )


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
        json={"transcripts": ["hello"]},
        headers=_csrf_header(client),
    ).status_code == 429


def test_summary_request_contract_returns_422_before_task_or_enqueue(
    auth_enabled,
    monkeypatch,
):
    _, username, password = _create_user()
    client = _login_client(username, password)
    touched: list[str] = []
    monkeypatch.setattr(
        "src.services.task_service.get_task",
        lambda *_args: touched.append("v2-task-read"),
    )
    monkeypatch.setattr(
        "src.api.endpoints.audio.get_task",
        lambda *_args: touched.append("v1-task-read"),
    )

    headers = _csrf_header(client)
    responses = [
        client.post(
            "/api/v1/audio/v2/summarize/missing-task",
            json={"summary_type": "bogus"},
            headers=headers,
        ),
        client.post(
            "/api/v1/audio/summarize-task/missing-task",
            json={"summary_type": "bogus"},
            headers=headers,
        ),
        client.post(
            "/api/v1/audio/summarize-multi",
            json={"transcripts": ["hello"], "summary_type": "bogus"},
            headers=headers,
        ),
        client.post(
            "/api/v1/audio/summarize-case",
            json={"case_id": "999999", "summary_type": "bogus"},
            headers=headers,
        ),
        client.post(
            "/api/v1/audio/v2/summarize/missing-task",
            json={"summary_type": "brief", "min_length": 10, "max_length": 5},
            headers=headers,
        ),
        client.post(
            "/api/v1/audio/summarize-task/missing-task",
            json={"summary_type": "brief", "min_length": 10, "max_length": 5},
            headers=headers,
        ),
    ]

    assert [response.status_code for response in responses] == [422] * len(responses)
    assert touched == []


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


def test_legacy_visualization_paths_fail_closed_without_released_run(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    _create_audio_for_task(user_id, case_id, task_id, status="transcribed")
    payload = {
        "nodes": [{"id": "n1"}],
        "edges": [],
        "timeline": [],
        "entity_types": ["person"],
        "main_events": [],
    }
    wrapper = {
        "task_id": task_id,
        "status": "visualization_ready",
        "visualization_type": "all",
        "data": payload,
    }

    assert extract_visualization_payload(wrapper) is None
    assert update_task(task_id, {"visualization": wrapper})

    db = SessionLocal()
    try:
        task_before_routes = db.query(Task).filter(Task.id == task_id).first()
        assert task_before_routes.result["visualization_data"] is None
        assert task_before_routes.result["has_visualization"] is False
        status_before_routes = task_before_routes.status
        result_before_routes = dict(task_before_routes.result)
    finally:
        db.close()

    from src.services.visualization_service import (
        VisualizationProjectionError,
        generate_visualization,
    )

    with pytest.raises(VisualizationProjectionError, match="InvestigationRun"):
        generate_visualization(task_id)
    with pytest.raises(VisualizationProjectionError) as raw_error:
        generate_visualization(payload)
    assert raw_error.value.code == "VISUALIZATION_RELEASED_RUN_REQUIRED"

    client = _login_client(username, password)
    headers = _csrf_header(client)
    task_detail = client.get(f"/api/v1/audio/tasks/{task_id}")
    assert task_detail.status_code == 200, task_detail.text
    assert task_detail.json()["visualization_data"] is None
    assert task_detail.json()["has_visualization"] is False

    v2_status = client.get(f"/api/v1/audio/v2/tasks/{task_id}/status")
    assert v2_status.status_code == 200, v2_status.text
    assert v2_status.json()["visualization_data"] is None
    assert v2_status.json()["has_visualization"] is False

    case_files = client.get(f"/api/v1/cases/{case_id}/files")
    assert case_files.status_code == 200, case_files.text
    file_row = next(row for row in case_files.json() if row["task_id"] == task_id)
    assert file_row["result"]["visualization_data"] is None
    assert file_row["result"]["has_visualization"] is False

    legacy = client.post(
        f"/api/v1/audio/visualize/{task_id}",
        json={"visualization_type": "all"},
        headers=headers,
    )
    assert legacy.status_code == 409, legacy.text
    assert legacy.json()["detail"]["code"] == "VISUALIZATION_RELEASED_RUN_REQUIRED"

    v2 = client.post(
        f"/api/v1/audio/v2/visualize/{task_id}",
        json={"visualization_type": "all"},
        headers=headers,
    )
    assert v2.status_code == 409, v2.text
    assert v2.json()["detail"]["code"] == "VISUALIZATION_RELEASED_RUN_REQUIRED"

    from src.worker.tasks import visualize_task

    worker_result = visualize_task.run(task_id, "all")
    assert worker_result["status"] == "error"
    assert "InvestigationRun" in worker_result["error"]

    db = SessionLocal()
    try:
        stored_task = db.query(Task).filter(Task.id == task_id).first()
        assert stored_task.status == status_before_routes
        assert stored_task.result == result_before_routes
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


def _analysis_payload(transcript: str, segments: list[dict] | None = None) -> dict:
    from src.api.endpoints.summary import (
        _exact_transcript_sha256,
        _segments_sha256,
    )
    from src.services.summarization.models.context_analysis import (
        ANALYSIS_SCHEMA_VERSION,
        CONTEXT_PROMPT_VERSION,
    )

    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "analysis_status": "success",
        "analysis_generation": "single_prompt_llm",
        "prompt_version": CONTEXT_PROMPT_VERSION,
        "analysis_text": "Noi dung phan tich co the hien thi.",
        "key_points": [
            {
                "text": "Diem chinh.",
                "evidence_quote": "server-only evidence",
                "custom_extension": "server-only extension",
            }
        ],
        "metrics": {
            "transcript_sha256": _exact_transcript_sha256(transcript),
            "segments_sha256": _segments_sha256(segments or []),
        },
    }


def _replace_task_result(task_id: str, result: dict) -> None:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        task.result = result
        db.commit()
    finally:
        db.close()


def _stored_task_result(task_id: str) -> dict:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        return dict(task.result or {})
    finally:
        db.close()


def test_task_context_patch_rejects_client_analysis_and_preserves_db(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    original = _stored_task_result(task_id)
    client = _login_client(username, password)

    forged = client.patch(
        f"/api/v1/audio/tasks/{task_id}/context",
        json={"context_analysis": {"analysis_status": "success"}},
        headers=_csrf_header(client),
    )

    assert forged.status_code == 422, forged.text
    assert _stored_task_result(task_id) == original

    allowed = client.patch(
        f"/api/v1/audio/tasks/{task_id}/context",
        json={"user_context_prompt": "Tap trung vao moc thoi gian."},
        headers=_csrf_header(client),
    )
    assert allowed.status_code == 200, allowed.text
    stored = _stored_task_result(task_id)
    assert stored["user_context_prompt"] == "Tap trung vao moc thoi gian."
    assert "context_analysis" not in stored


def test_summary_analyze_rejects_forged_and_arbitrary_fields_before_processing(
    monkeypatch,
    auth_enabled,
):
    from src.api.endpoints import summary as summary_endpoint

    _, username, password = _create_user()
    client = _login_client(username, password)
    touched: list[str] = []
    monkeypatch.setattr(
        summary_endpoint,
        "get_task",
        lambda *_args: touched.append("task-read"),
    )
    headers = _csrf_header(client)

    forged = client.post(
        "/api/v1/summaries/analyze",
        json={
            "summary": "ignored",
            "task_id": str(uuid.uuid4()),
            "context_analysis": {"analysis_status": "success"},
        },
        headers=headers,
    )
    arbitrary = client.post(
        "/api/v1/summaries/analyze",
        json={
            "summary": "ignored",
            "task_id": str(uuid.uuid4()),
            "unexpected": "server-only fields cannot be supplied by clients",
        },
        headers=headers,
    )

    assert forged.status_code == 422, forged.text
    assert arbitrary.status_code == 422, arbitrary.text
    assert touched == []


def test_summary_and_visualization_routes_reject_extra_fields_before_processing(
    monkeypatch,
    auth_enabled,
):
    from src.api.endpoints import audio as audio_v1
    _, username, password = _create_user()
    client = _login_client(username, password)
    touched: list[str] = []
    monkeypatch.setattr(
        audio_v1,
        "get_task",
        lambda *_args: touched.append("v1-task-read"),
    )
    monkeypatch.setattr(
        "src.services.task_service.get_task",
        lambda *_args, **_kwargs: touched.append("v2-task-read"),
    )
    headers = _csrf_header(client)
    task_id = str(uuid.uuid4())

    responses = [
        client.post(
            f"/api/v1/audio/tasks/{task_id}/resummarize",
            json={"summary_type": "brief", "context_analysis": {"forged": True}},
            headers=headers,
        ),
        client.post(
            f"/api/v1/audio/v2/summarize/{task_id}",
            json={"summary_type": "brief", "summary_runtime": {"forged": True}},
            headers=headers,
        ),
        client.post(
            f"/api/v1/audio/visualize/{task_id}",
            json={"visualization_type": "all", "released_run": {"forged": True}},
            headers=headers,
        ),
        client.post(
            f"/api/v1/audio/v2/visualize/{task_id}",
            json={"visualization_type": "all", "nodes": [{"forged": True}]},
            headers=headers,
        ),
    ]

    assert [response.status_code for response in responses] == [422] * len(responses)
    assert touched == []


def test_analysis_cache_requires_server_attestation(monkeypatch, auth_enabled):
    from src.api.endpoints import summary as summary_endpoint

    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    transcript = "Lan hen Minh luc chin gio tai ben xe."
    segments = [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00", "text": transcript}
    ]
    legacy = _analysis_payload(transcript, segments)
    _replace_task_result(
        task_id,
        {"transcription": transcript, "segments": segments, "context_analysis": legacy},
    )
    generated = _analysis_payload(transcript, segments)
    generated["analysis_text"] = "Ket qua moi duoc sinh lai."
    calls = []
    monkeypatch.setattr(summary_endpoint, "gpu_lease", lambda *_args: nullcontext())
    monkeypatch.setattr(summary_endpoint.settings, "UNLOAD_MODELS_AFTER_TASK", False)
    monkeypatch.setattr(
        summary_endpoint,
        "analyze_conversation_context",
        lambda *_args, **_kwargs: calls.append(True) or generated,
    )
    client = _login_client(username, password)

    response = client.post(
        "/api/v1/summaries/analyze",
        json={"summary": "ignored", "task_id": task_id},
        headers=_csrf_header(client),
    )

    assert response.status_code == 200, response.text
    assert response.json()["cache_hit"] is False
    assert len(calls) == 1
    stored = _stored_task_result(task_id)
    assert stored["context_analysis"] == generated
    assert stored["context_analysis_attestation"]["task_id"] == task_id
    assert "context_analysis_attestation" not in response.json()["result"]
    assert "evidence_quote" not in str(response.json())
    assert "custom_extension" not in str(response.json())


def test_tampered_analysis_cache_misses_but_valid_attestation_hits(
    monkeypatch, auth_enabled
):
    from src.api.endpoints import summary as summary_endpoint

    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    transcript = "Lan hen Minh luc chin gio tai ben xe."
    segments = [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00", "text": transcript}
    ]
    cached = _analysis_payload(transcript, segments)
    attestation = summary_endpoint._build_context_analysis_attestation(
        cached,
        task_id=task_id,
        transcript=transcript,
        segments=segments,
    )
    _replace_task_result(
        task_id,
        {
            "transcription": transcript,
            "segments": segments,
            "context_analysis": cached,
            "context_analysis_attestation": attestation,
        },
    )
    client = _login_client(username, password)

    def unexpected_llm(*_args, **_kwargs):
        raise AssertionError("valid attested cache must not call the LLM")

    monkeypatch.setattr(summary_endpoint, "analyze_conversation_context", unexpected_llm)
    hit = client.post(
        "/api/v1/summaries/analyze",
        json={"summary": "ignored", "task_id": task_id},
        headers=_csrf_header(client),
    )
    assert hit.status_code == 200, hit.text
    assert hit.json()["cache_hit"] is True
    assert "evidence_quote" not in str(hit.json())

    tampered = dict(cached)
    tampered["analysis_text"] = "Noi dung bi sua sau khi ky."
    _replace_task_result(
        task_id,
        {
            "transcription": transcript,
            "segments": segments,
            "context_analysis": tampered,
            "context_analysis_attestation": attestation,
        },
    )
    regenerated = _analysis_payload(transcript, segments)
    regenerated["analysis_text"] = "Ket qua sinh lai sau tamper."
    calls = []
    monkeypatch.setattr(summary_endpoint, "gpu_lease", lambda *_args: nullcontext())
    monkeypatch.setattr(summary_endpoint.settings, "UNLOAD_MODELS_AFTER_TASK", False)
    monkeypatch.setattr(
        summary_endpoint,
        "analyze_conversation_context",
        lambda *_args, **_kwargs: calls.append(True) or regenerated,
    )
    miss = client.post(
        "/api/v1/summaries/analyze",
        json={"summary": "ignored", "task_id": task_id},
        headers=_csrf_header(client),
    )
    assert miss.status_code == 200, miss.text
    assert miss.json()["cache_hit"] is False
    assert len(calls) == 1


def test_summary_analyze_rejects_ambiguous_persisted_inputs_before_llm(
    monkeypatch,
    auth_enabled,
):
    from src.api.endpoints import summary as summary_endpoint

    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    _replace_task_result(
        task_id,
        {
            "transcription": "Noi dung nguon.",
            "segments": {"0": {"text": "khong phai danh sach"}},
        },
    )
    calls: list[str] = []
    monkeypatch.setattr(
        summary_endpoint,
        "analyze_conversation_context",
        lambda *_args, **_kwargs: calls.append("llm") or {},
    )
    client = _login_client(username, password)

    response = client.post(
        "/api/v1/summaries/analyze",
        json={"summary": "ignored", "task_id": task_id},
        headers=_csrf_header(client),
    )

    assert response.status_code == 500, response.text
    assert response.json()["detail"] == "Task analysis inputs are invalid"
    assert calls == []


def test_generic_task_aliases_downgrade_stale_visualized_status(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    _replace_task_result(
        task_id,
        {
            "transcription": "Noi dung nguon.",
            "summary": "Tom tat.",
            "visualization_data": {"nodes": [{"id": "stale"}]},
            "has_visualization": True,
        },
    )
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        task.status = "visualized"
        db.commit()
    finally:
        db.close()
    client = _login_client(username, password)

    for path in (
        "/api/v1/tasks",
        f"/api/v1/tasks/{task_id}",
        f"/api/v1/tasks/results/{task_id}",
        f"/api/v1/tasks/tasks/results/{task_id}",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        payload = response.json()
        if isinstance(payload, list):
            task_payload = next(row for row in payload if row["id"] == task_id)
            assert task_payload["status"] == "summarized"
            assert task_payload["result"]["visualization_data"] is None
        else:
            assert payload["status"] == "summarized"
            assert payload["result"]["status"] == "summarized"
            assert payload["result"]["result"]["visualization_data"] is None


def test_task_read_endpoints_never_return_analysis_attestation(auth_enabled):
    from src.api.endpoints import summary as summary_endpoint

    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    audio_id = _create_audio_for_task(user_id, case_id, task_id)
    transcript = "Noi dung task duoc bao ve."
    analysis = _analysis_payload(transcript)
    _replace_task_result(
        task_id,
        {
            "transcription": transcript,
            "summary_runtime": {"model_id": "internal", "raw_exception": "secret"},
            "released_investigation_run": {"run_id": "internal-run"},
            "audio_sha256": "a" * 64,
            "arbitrary_extension": {"secret": True},
            "context_analysis": analysis,
            "context_analysis_attestation": summary_endpoint._build_context_analysis_attestation(
                analysis,
                task_id=task_id,
                transcript=transcript,
                segments=[],
            ),
        },
    )
    client = _login_client(username, password)

    for path in (
        f"/api/v1/tasks/{task_id}",
        f"/api/v1/tasks/results/{task_id}",
        f"/api/v1/audio/tasks/{task_id}",
        f"/api/v1/audio/v2/tasks/{task_id}/status",
        f"/api/v1/audio/files/{audio_id}/transcript",
        f"/api/v1/cases/{case_id}/files",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        serialized = str(response.json())
        assert "context_analysis_attestation" not in serialized
        assert "signature" not in serialized
        assert "evidence_quote" not in serialized
        assert "custom_extension" not in serialized
        assert "summary_runtime" not in serialized
        assert "released_investigation_run" not in serialized
        assert "audio_sha256" not in serialized
        assert "arbitrary_extension" not in serialized
        assert "raw_exception" not in serialized

    for path in (
        "/api/v1/tasks",
        "/api/v1/audio/tasks",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        serialized = str(response.json())
        assert "context_analysis_attestation" not in serialized
        assert "summary_runtime" not in serialized
        assert "released_investigation_run" not in serialized
        assert "audio_sha256" not in serialized
        assert "arbitrary_extension" not in serialized


def test_lightweight_v2_status_projects_summary_signals(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    _create_audio_for_task(user_id, case_id, task_id)
    _replace_task_result(
        task_id,
        {
            "summary_state": "needs_review",
            "summary_notice": {
                "code": "SUMMARY_REVIEW_REQUIRED",
                "retryable": False,
                "message": "internal operator guidance",
                "custom_extension": "secret",
            },
            "summary_error": {
                "code": "SUMMARY_GENERATION_FAILED",
                "needs_review": True,
                "raw_exception": "secret traceback",
            },
        },
    )
    client = _login_client(username, password)

    response = client.get(
        f"/api/v1/audio/v2/tasks/{task_id}/status",
        params={"include_result": False},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary_notice"] == {
        "code": "SUMMARY_REVIEW_REQUIRED",
        "retryable": False,
    }
    assert payload["summary_error"] == {
        "code": "SUMMARY_GENERATION_FAILED",
        "needs_review": True,
    }
    serialized = str(payload)
    assert "internal operator guidance" not in serialized
    assert "custom_extension" not in serialized
    assert "raw_exception" not in serialized
    assert "secret traceback" not in serialized


def test_case_list_remains_compact_when_client_requests_rich_bulk_data(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    _create_audio_for_task(user_id, case_id, task_id)
    _replace_task_result(
        task_id,
        {
            "transcription": "bulk-private transcript",
            "summary": "bulk-private summary",
            "context_analysis": {"analysis_text": "bulk-private analysis"},
        },
    )
    client = _login_client(username, password)

    response = client.get("/api/v1/cases/", params={"compact": False})

    assert response.status_code == 200, response.text
    case = next(row for row in response.json() if row["id"] == case_id)
    assert "transcripts" in case
    assert case["transcripts"] == ["bulk-private transcript"]
    assert case["summaries"] == ["bulk-private summary"]
    assert case["contexts"] == []


def test_public_endpoint_exceptions_are_not_returned_to_clients(monkeypatch, auth_enabled):
    from src.api.endpoints import tasks as tasks_endpoint

    _, username, password = _create_user()
    client = _login_client(username, password)
    secret = "database-password=super-secret"
    monkeypatch.setattr(tasks_endpoint, "list_tasks", lambda: (_ for _ in ()).throw(RuntimeError(secret)))

    response = client.get("/api/v1/tasks")

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to list tasks"
    assert secret not in response.text


def test_task_result_updates_merge_without_dropping_existing_fields():
    user_id, _, _ = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)

    assert update_task(
        task_id, {"transcript": "hello", "segments": [{"start": 0, "end": 1}]}
    )
    assert update_task(task_id, {"summary": "short summary"})
    assert update_task(
        task_id,
        {"visualization_data": {"nodes": []}, "has_visualization": True},
    )

    db = SessionLocal()
    try:
        result = db.query(Task).filter(Task.id == task_id).first().result
        assert result["transcription"] == "hello"
        assert result["summary"] == "short summary"
        assert result["segments"] == [{"start": 0, "end": 1}]
        assert result["visualization_data"] is None
        assert result["has_visualization"] is False
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


def test_disabled_auth_requires_explicit_development_bypass(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", False)

    with pytest.raises(RuntimeError, match="DEV_AUTH_BYPASS"):
        validate_security_settings()


def test_development_bypass_requires_loopback(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS", True)
    monkeypatch.setattr(settings, "DEV_USER_ID", 1)
    monkeypatch.setattr(settings, "BACKEND_HOST", "0.0.0.0")

    with pytest.raises(RuntimeError, match="loopback"):
        validate_security_settings()


def test_case_patch_rejects_mass_assignment_for_member(auth_enabled):
    owner_id, _, _ = _create_user()
    member_id, member_username, member_password = _create_user()
    case_id = _create_case_for_user(owner_id)

    db = SessionLocal()
    try:
        member_role = db.query(ParticipantRole).filter(
            ParticipantRole.role_name == "member"
        ).first()
        db.add(
            CaseParticipant(
                case_id=case_id,
                user_id=member_id,
                role_id=member_role.id,
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()

    client = _login_client(member_username, member_password)
    headers = _csrf_header(client)
    allowed = client.patch(
        f"/api/v1/cases/{case_id}",
        json={"title": "Member supplied title"},
        headers=headers,
    )
    assert allowed.status_code == 200, allowed.text

    for forbidden_field, value in {
        "created_by": member_id,
        "id": 999999,
        "is_archived": True,
        "case_code": "attacker-controlled",
        "participants": [],
    }.items():
        response = client.patch(
            f"/api/v1/cases/{case_id}",
            json={forbidden_field: value},
            headers=headers,
        )
        assert response.status_code == 422, (forbidden_field, response.text)

    db = SessionLocal()
    try:
        case = db.query(Case).filter(Case.id == case_id).first()
        assert case.created_by == owner_id
        assert case.is_archived is False
        assert case.title == "Member supplied title"
    finally:
        db.close()


def test_thread_worker_owns_and_closes_its_session(monkeypatch):
    from src.api.endpoints import audio as audio_endpoint

    sessions = []

    class FakeSession:
        def __init__(self):
            self.closed = False
            self.rolled_back = False
            sessions.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True

        def rollback(self):
            self.rolled_back = True

    monkeypatch.setattr(audio_endpoint, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        audio_endpoint,
        "process_task",
        lambda task_id, model_name, db: (task_id, model_name, id(db)),
    )

    first = audio_endpoint._process_task_in_worker("task-1", "model")
    second = audio_endpoint._process_task_in_worker("task-2", "model")

    assert first[2] != second[2]
    assert len(sessions) == 2
    assert all(session.closed for session in sessions)


def test_thread_worker_rolls_back_on_failure(monkeypatch):
    from src.api.endpoints import audio as audio_endpoint

    class FakeSession:
        rolled_back = False
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True

        def rollback(self):
            self.rolled_back = True

    session = FakeSession()
    monkeypatch.setattr(audio_endpoint, "SessionLocal", lambda: session)

    def fail(*_args):
        raise RuntimeError("worker failed")

    monkeypatch.setattr(audio_endpoint, "process_task", fail)

    with pytest.raises(RuntimeError, match="worker failed"):
        audio_endpoint._process_task_in_worker("task-1", "model")
    assert session.rolled_back is True
    assert session.closed is True


def test_legacy_celery_task_closes_session(monkeypatch):
    import src.database.config.database as database_module
    from src.worker import tasks as worker_tasks

    class FakeSession:
        rolled_back = False
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True

        def rollback(self):
            self.rolled_back = True

    session = FakeSession()
    monkeypatch.setattr(database_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        worker_tasks.old_tasks,
        "process_task_with_diarization",
        lambda task_id, model_name, db, method: {
            "task_id": task_id,
            "model_name": model_name,
            "method": method,
            "session": id(db),
        },
    )

    result = worker_tasks.process_task_async.run("task-1", "model", "none")

    assert result["session"] == id(session)
    assert session.closed is True
