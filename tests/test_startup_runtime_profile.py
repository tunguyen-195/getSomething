from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_primary_startup_uses_single_gpu_safe_worker_without_runtime_install():
    script = (PROJECT_ROOT / "START_ALL_SERVICES.bat").read_text(encoding="utf-8")
    normalized = " ".join(script.casefold().split())

    assert "pip install" not in normalized
    assert "--pool=solo" in normalized
    assert "--concurrency=1" in normalized
    assert "--pool=gevent" not in normalized
    assert "--concurrency=4" not in normalized


def test_celery_application_default_matches_the_startup_profile():
    worker = (PROJECT_ROOT / "src" / "worker" / "worker.py").read_text(encoding="utf-8")

    assert "worker_concurrency=1" in worker
