from fastapi.testclient import TestClient

from src.database.config.database import SessionLocal
from src.database.models.models import Task
from src.main import app
from src.services.task_service import update_task


client = TestClient(app)


def _create_case(title: str) -> int:
    response = client.post("/api/v1/cases/", json={"title": title})
    assert response.status_code == 201
    return response.json()["id"]


def test_compact_case_list_supports_pagination_and_search():
    _create_case("Performance Alpha")
    _create_case("Performance Needle")
    _create_case("Performance Omega")

    response = client.get(
        "/api/v1/cases/",
        params={"compact": True, "limit": 1, "offset": 0, "search": "Needle"},
    )

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "1"
    assert len(response.json()) == 1
    case = response.json()[0]
    assert case["title"] == "Performance Needle"
    assert "transcripts" not in case
    assert "summaries" not in case
    assert "contexts" not in case


def test_lean_v2_status_does_not_return_large_result_payload():
    case_id = _create_case("Lean Polling")
    task_response = client.post(
        "/api/v1/tasks",
        json={"filename": "polling.wav", "case_id": case_id},
    )
    assert task_response.status_code == 200
    task_id = task_response.json()["task_id"]

    with SessionLocal() as db:
        task = db.query(Task).filter(Task.id == task_id).one()
        task.status = "transcribed"
        task.result = {
            "transcription": "sensitive transcript",
            "segments": [{"start": 0.0, "end": 1.0, "text": "sensitive transcript"}],
        }
        db.commit()

    lean = client.get(
        f"/api/v1/audio/v2/tasks/{task_id}/status",
        params={"include_result": False},
    )
    assert lean.status_code == 200
    assert lean.json()["status"] == "transcribed"
    assert "result" not in lean.json()
    assert "transcript" not in lean.json()
    assert "segments" not in lean.json()

    full = client.get(f"/api/v1/audio/v2/tasks/{task_id}/status")
    assert full.status_code == 200
    assert full.json()["transcript"] == "sensitive transcript"
    assert full.json()["result"]["segments"]


def test_retrying_task_clears_stale_failure_error():
    case_id = _create_case("Retry State")
    task_response = client.post(
        "/api/v1/tasks",
        json={"filename": "retry.wav", "case_id": case_id},
    )
    task_id = task_response.json()["task_id"]

    assert update_task(task_id, {"status": "failed", "error": "stale failure"})
    assert update_task(task_id, {"status": "transcribing"})

    with SessionLocal() as db:
        task = db.query(Task).filter(Task.id == task_id).one()
        assert task.status == "transcribing"
        assert task.error is None
