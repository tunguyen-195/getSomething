from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]


def _env_from_file(path: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    for key, value in dotenv_values(ROOT / path).items():
        if value is not None:
            env[key] = value
    return env


def _run_import_config(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    code = (
        "import json; "
        "import src.core.config as cfg; "
        "print(json.dumps({"
        "'cors': cfg.settings.CORS_ORIGINS, "
        "'backend_cors': cfg.settings.BACKEND_CORS_ORIGINS, "
        "'trusted_proxy_ips': cfg.settings.TRUSTED_PROXY_IPS"
        "}))"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
    )


@pytest.mark.parametrize("env_file", [".env.example", ".env.lite.example"])
def test_env_examples_import_config_module_cleanly(env_file: str):
    completed = _run_import_config(_env_from_file(env_file))

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["cors"] == ["http://localhost:3000", "http://localhost:8000"]


def test_string_list_settings_accept_comma_strings_for_legacy_deploys():
    env = _env_from_file(".env.lite.example")
    env["CORS_ORIGINS"] = "http://localhost:3000,http://localhost:8000"
    env["BACKEND_CORS_ORIGINS"] = "http://127.0.0.1:3000, http://127.0.0.1:8000"
    env["TRUSTED_PROXY_IPS"] = "127.0.0.1, 10.0.0.1"

    completed = _run_import_config(env)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["cors"] == ["http://localhost:3000", "http://localhost:8000"]
    assert payload["backend_cors"] == ["http://127.0.0.1:3000", "http://127.0.0.1:8000"]
    assert payload["trusted_proxy_ips"] == ["127.0.0.1", "10.0.0.1"]


def test_string_list_settings_reject_invalid_json_list_items():
    env = _env_from_file(".env.lite.example")
    env["CORS_ORIGINS"] = '["http://localhost:3000", 123]'

    completed = _run_import_config(env)

    assert completed.returncode != 0
    assert "all list items must be strings" in completed.stderr


def test_lite_runtime_check_imports_lite_env_example():
    completed = subprocess.run(
        [sys.executable, "scripts/check_lite_runtime.py"],
        cwd=ROOT,
        env=_env_from_file(".env.lite.example"),
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "SpeechToInformation Lite runtime check" in completed.stdout


def test_lite_env_uses_openrouter_without_committed_api_key():
    values = dotenv_values(ROOT / ".env.lite.example")

    assert values["ANALYSIS_INTELLIGENCE_LLM_ENABLED"] == "true"
    assert values["ANALYSIS_LLM_PROVIDER"] == "openrouter"
    assert values["ANALYSIS_LLM_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert values["ANALYSIS_LLM_MODEL"] == "google/gemini-2.5-flash"
    assert values["ANALYSIS_LLM_FALLBACK_MODEL"] == "openai/gpt-5-mini"
    assert values.get("ANALYSIS_LLM_API_KEY", "") == ""


def test_lite_runtime_gpu_smoke_uses_mocked_checker(monkeypatch):
    import scripts.check_lite_runtime as check_lite_runtime

    calls = []

    def fake_gpu_smoke(settings, *, audio_path, offline_models_only):
        calls.append((settings.WHISPER_MODEL, audio_path, offline_models_only))

    monkeypatch.setattr(check_lite_runtime, "run_gpu_smoke", fake_gpu_smoke)
    monkeypatch.setattr(sys, "argv", ["check_lite_runtime.py", "--gpu-smoke", "--offline-models-only"])

    assert check_lite_runtime.main() == 0
    assert calls
    assert calls[0][2] is True


def test_lite_runtime_gpu_smoke_failure_returns_dedicated_code(monkeypatch, capsys):
    import scripts.check_lite_runtime as check_lite_runtime

    def fake_gpu_smoke(settings, *, audio_path, offline_models_only):
        raise RuntimeError("model_unavailable_or_download_failed")

    monkeypatch.setattr(check_lite_runtime, "run_gpu_smoke", fake_gpu_smoke)
    monkeypatch.setattr(sys, "argv", ["check_lite_runtime.py", "--gpu-smoke"])

    assert check_lite_runtime.main() == 3
    assert "gpu_smoke_failed:model_unavailable_or_download_failed" in capsys.readouterr().out


def test_lite_runtime_gpu_smoke_reports_model_artifact_reason(monkeypatch, capsys):
    import scripts.check_lite_runtime as check_lite_runtime
    from src.services.model_artifacts import ModelArtifactError

    def fake_gpu_smoke(settings, *, audio_path, offline_models_only):
        raise ModelArtifactError("model_cache_missing_or_unverified", "setup")

    monkeypatch.setattr(check_lite_runtime, "run_gpu_smoke", fake_gpu_smoke)
    monkeypatch.setattr(sys, "argv", ["check_lite_runtime.py", "--gpu-smoke"])

    assert check_lite_runtime.main() == 3
    assert "gpu_smoke_failed:model_cache_missing_or_unverified" in capsys.readouterr().out


def test_lite_runtime_gpu_smoke_missing_audio_fails_before_gpu_imports():
    import scripts.check_lite_runtime as check_lite_runtime

    missing_audio = ROOT / "tests" / "fixtures" / "missing-gpu-smoke.wav"

    with pytest.raises(RuntimeError, match="gpu_smoke_audio_unavailable"):
        check_lite_runtime.run_gpu_smoke(object(), audio_path=missing_audio, offline_models_only=False)
