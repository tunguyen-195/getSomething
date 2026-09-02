from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"


def _compose_config(
    tmp_path: Path,
    *,
    llama_url: str | None,
) -> subprocess.CompletedProcess[str]:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is required for Compose interpolation tests")

    values = {
        "SECRET_KEY": "compose-test-secret-key-with-sufficient-length",
        "INITIAL_ADMIN_PASSWORD": "compose-test-admin-password",
        "POSTGRES_USER": "compose_test",
        "POSTGRES_PASSWORD": "compose-test-database-password",
        "POSTGRES_DB": "compose_test",
        "LLAMA_SERVER_API_KEY": "compose-test-api-key",
        "CONTAINER_LLAMA_SERVER_MODEL_PATH": (
            "/models/qwen3/Qwen3-8B-Q4_K_M.gguf"
        ),
    }
    if llama_url is not None:
        values["CONTAINER_LLAMA_SERVER_BASE_URL"] = llama_url
    env_file = tmp_path / "compose.env"
    env_file.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.pop("CONTAINER_LLAMA_SERVER_BASE_URL", None)
    environment.update(values)
    return subprocess.run(
        [
            docker,
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(COMPOSE),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _compose_preflight(
    *,
    llama_url: str | None = "http://llama-sidecar.internal:8088",
    model_path: str | None = "/models/qwen3/Qwen3-8B-Q4_K_M.gguf",
    api_key: str | None = "compose-test-api-key",
) -> subprocess.CompletedProcess[str]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts/preflight_compose_runtime.ps1"),
        "-ConfigOnly",
    ]
    for parameter, value in (
        ("-ContainerLlamaServerBaseUrl", llama_url),
        ("-ContainerLlamaServerModelPath", model_path),
        ("-LlamaServerApiKey", api_key),
    ):
        if value is not None:
            command.extend((parameter, value))
    environment = os.environ.copy()
    values = {
        "SECRET_KEY": "compose-test-secret-key-with-sufficient-length",
        "INITIAL_ADMIN_PASSWORD": "compose-test-admin-password",
        "POSTGRES_USER": "compose_test",
        "POSTGRES_PASSWORD": "compose-test-database-password",
        "POSTGRES_DB": "compose_test",
    }
    for name in (
        "CONTAINER_LLAMA_SERVER_BASE_URL",
        "CONTAINER_LLAMA_SERVER_MODEL_PATH",
        "LLAMA_SERVER_API_KEY",
        *values,
    ):
        environment.pop(name, None)
    environment.update(values)
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_compose_requires_an_explicit_container_llama_server_url(tmp_path: Path) -> None:
    completed = _compose_config(tmp_path, llama_url=None)

    assert completed.returncode != 0
    assert "CONTAINER_LLAMA_SERVER_BASE_URL" in completed.stderr


def test_compose_projects_the_canonical_ai_runtime_to_backend_and_worker(
    tmp_path: Path,
) -> None:
    completed = _compose_config(
        tmp_path,
        llama_url="http://llama-sidecar.internal:8088",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    for service_name in ("backend", "celery_worker"):
        service = payload["services"][service_name]
        environment = service["environment"]
        assert environment["LOCAL_LLM_PROVIDER"] == "llama_cpp_server"
        assert environment["LLAMA_SERVER_BASE_URL"] == (
            "http://llama-sidecar.internal:8088"
        )
        assert environment["LLAMA_SERVER_MODEL"] == "speechintel-qwen3-8b-q4_k_m"
        assert environment["LLAMA_SERVER_API_KEY"] == "compose-test-api-key"
        assert environment["LLAMA_SERVER_MODEL_PATH"] == (
            "/models/qwen3/Qwen3-8B-Q4_K_M.gguf"
        )
        assert environment["OFFLINE_STRICT"] == "true"
        assert environment["GPU_LEASE_ENABLED"] == "true"
        assert environment["TRANSCRIPTION_ENGINE"] == "legacy"
        assert "host.docker.internal" not in json.dumps(service)
        for target in ("/models", "/app/models"):
            model_mount = next(
                volume
                for volume in service["volumes"]
                if volume.get("target") == target
            )
            assert model_mount["read_only"] is True


def test_compose_source_never_routes_container_llm_calls_to_loopback_or_ollama() -> None:
    source = COMPOSE.read_text(encoding="utf-8")

    assert "LOCAL_LLM_PROVIDER: llama_cpp_server" in source
    assert "LLAMA_SERVER_BASE_URL: ${CONTAINER_LLAMA_SERVER_BASE_URL:" in source
    assert "TRANSCRIPTION_ENGINE: ${TRANSCRIPTION_ENGINE:-legacy}" in source
    assert "TRANSCRIPTION_ENGINE: ${TRANSCRIPTION_ENGINE:-auto}" not in source
    assert "LLAMA_SERVER_BASE_URL: http://127.0.0.1" not in source
    assert "LOCAL_LLM_PROVIDER: ollama" not in source
    assert "LLAMA_SERVER_API_KEY: ${LLAMA_SERVER_API_KEY:?" in source
    assert "LLAMA_SERVER_MODEL_PATH: ${CONTAINER_LLAMA_SERVER_MODEL_PATH:?" in source
    assert "./models:/models:ro" in source
    assert "./models:/app/models:ro" in source


@pytest.mark.parametrize(
    "url",
    (
        "http://127.0.0.1:8088",
        "http://localhost:8088",
        "http://[::1]:8088",
    ),
)
def test_compose_preflight_rejects_container_loopback_urls(
    tmp_path: Path,
    url: str,
) -> None:
    completed = _compose_preflight(llama_url=url)

    assert completed.returncode != 0
    assert "loopback" in (completed.stdout + completed.stderr).lower()


def test_compose_preflight_requires_an_api_key_for_external_llama_server() -> None:
    completed = _compose_preflight(api_key=None)

    assert completed.returncode != 0
    assert "api key" in (completed.stdout + completed.stderr).lower()


def test_compose_preflight_requires_container_url() -> None:
    completed = _compose_preflight(llama_url=None)

    assert completed.returncode != 0
    assert "absolute http(s) url" in (completed.stdout + completed.stderr).lower()


@pytest.mark.parametrize(
    "model_path",
    (
        None,
        "models/qwen3/Qwen3-8B-Q4_K_M.gguf",
        "/models/../secrets/model.gguf",
        "/models/qwen3/model.bin",
    ),
)
def test_compose_preflight_rejects_missing_or_unsafe_model_paths(
    model_path: str | None,
) -> None:
    completed = _compose_preflight(model_path=model_path)

    assert completed.returncode != 0
    assert "model path" in (completed.stdout + completed.stderr).lower()


def test_compose_preflight_config_only_passes_without_exposing_api_key() -> None:
    completed = _compose_preflight()

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "PASS"
    assert "compose-test-api-key" not in completed.stdout
