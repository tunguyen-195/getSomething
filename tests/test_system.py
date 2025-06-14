import os
import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.database.config.database import get_db
from src.database.init_db import init_db
from src.core.config import settings

client = TestClient(app)

@pytest.fixture(scope="session")
def test_db():
    """Create test database."""
    init_db()
    return get_db()

def test_health_check():
    """Test health check endpoint."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_audio_upload():
    """Test audio file upload."""
    # Create test audio file
    test_file = "test.wav"
    with open(test_file, "wb") as f:
        f.write(b"test audio content")

    try:
        # Upload file
        with open(test_file, "rb") as f:
            response = client.post(
                "/api/v1/audio/upload",
                files={"file": ("test.wav", f, "audio/wav")},
                data={"options": '{"language": "vi", "model_type": "whisper"}'}
            )

        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "success"
        assert "result" in data
    finally:
        # Clean up
        if os.path.exists(test_file):
            os.remove(test_file)

def test_task_status():
    """Test task status endpoint."""
    # Create test task
    response = client.post(
        "/api/v1/tasks",
        json={
            "file_path": "test.wav",
            "options": {"language": "vi", "model_type": "whisper"}
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data
    task_id = data["task_id"]

    # Check task status
    response = client.get(f"/api/v1/tasks/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["pending", "processing", "completed"]

def test_batch_processing():
    """Test batch processing endpoint."""
    # Create test files
    test_files = ["test1.wav", "test2.wav"]
    try:
        for file in test_files:
            with open(file, "wb") as f:
                f.write(b"test audio content")

        # Mở tất cả file và giữ chúng mở khi gửi request
        file_objs = [open(file, "rb") for file in test_files]
        files = [("files", (file.name, file, "audio/wav")) for file in file_objs]

        response = client.post(
            "/api/v1/audio/batch",
            files=files,
            data={"options": '{"language": "vi", "model_type": "whisper"}'}
        )

        for f in file_objs:
            f.close()

        assert response.status_code == 200
        data = response.json()
        assert "task_ids" in data
        assert len(data["task_ids"]) == len(test_files)
        assert data["status"] == "success"
        assert "results" in data
        assert len(data["results"]) == len(test_files)
    finally:
        # Clean up
        for file in test_files:
            if os.path.exists(file):
                os.remove(file)

def test_result_retrieval():
    """Test result retrieval endpoint."""
    # Create test task
    response = client.post(
        "/api/v1/tasks",
        json={
            "file_path": "test.wav",
            "options": {"language": "vi", "model_type": "whisper"}
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data
    task_id = data["task_id"]

    # Wait for task to complete
    import time
    time.sleep(3)

    # Get result
    response = client.get(f"/api/v1/results/{task_id}")
    assert response.status_code == 200
    data = response.json()
    assert "task_id" in data
    assert data["status"] == "completed"
    assert "result" in data 