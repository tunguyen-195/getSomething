from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _canonical_runbook_environment() -> dict[str, str]:
    setup = _read("docs/NEW_MACHINE_SETUP.md")
    start = setup.index("```dotenv\n") + len("```dotenv\n")
    end = setup.index("\n```", start)
    values: dict[str, str] = {}
    for raw_line in setup[start:end].splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    values["SECRET_KEY"] = "onboarding-test-secret-with-enough-entropy-1234567890"
    values["INITIAL_ADMIN_PASSWORD"] = "onboarding-admin-password-1234"
    return values


def _validate_security_environment(**overrides: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "ENVIRONMENT": "development",
            "DEBUG": "true",
            "AUTH_ENABLED": "true",
            "DEV_AUTH_BYPASS": "false",
            "DEV_USER_ID": "0",
            "BACKEND_HOST": "127.0.0.1",
            "SECRET_KEY": "onboarding-test-secret-with-enough-entropy-1234567890",
            "COOKIE_SECURE": "false",
        }
    )
    env.update(overrides)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from src.core.config import validate_security_settings; "
                "validate_security_settings()"
            ),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_staging_installer_is_explicit_pinned_and_fail_closed():
    script = _read("scripts/install_local_llm_staging.ps1")
    model = json.loads(_read("config/models/qwen3-8b-q4_k_m.manifest.json"))["model"]
    runtime = json.loads(
        _read("config/runtimes/llama.cpp-b10331-windows-cuda-12.4.runtime.json")
    )["runtime"]

    assert "ValidateSet('gpu12gb', 'cpu')" in script
    assert "[switch]$Force" in script
    assert model["source"]["repository"] in script
    assert model["source"]["revision"] in script
    assert runtime["source"]["release_url"] in script
    assert "Invoke-WebRequest" in script
    assert "/resolve/" in script
    assert "-replace '/tag/', '/download/'" in script
    assert "Get-FileHash" in script and "SHA256" in script
    assert "Refusing overwrite without -Force" in script
    assert ".partial-" in script
    assert "verify_llama_runtime.py" in script
    assert "model_store.py" in script
    assert "npm" not in script


def test_preflight_covers_pinned_stack_env_services_and_json_report():
    script = _read("scripts/preflight_new_machine.ps1")

    for version in (
        "2.1.1",
        "0.16.1",
        "0.3.16",
        "0.36.0",
        "3.1.1",
        "1.2.1",
        "4.6.0",
        "5.3.4",
        "5.0.1",
    ):
        assert version in script
    assert "requirements-constraints-py311.txt" in script
    assert "missing-manifest:" in script
    assert "dependency.requirements-manifest" in script
    assert "dependency.constraints-manifest" in script
    assert "dependency.pip-check" in script
    assert "'diart' =" not in script
    for setting in (
        "ENVIRONMENT",
        "DEBUG",
        "AUTH_ENABLED",
        "DEV_AUTH_BYPASS",
        "BACKEND_HOST",
        "LOCAL_LLM_PROVIDER",
        "LLAMA_SERVER_BASE_URL",
        "LLAMA_SERVER_MODEL",
        "LLAMA_SERVER_MODEL_PATH",
        "LLAMA_SERVER_CONTEXT_SIZE",
        "LLAMA_SERVER_MINIMUM_FREE_VRAM_MIB",
        "OFFLINE_STRICT",
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "LLM_SEED",
    ):
        assert setting in script
    for port in ("5432", "6379", "8088", "8000", "3000"):
        assert port in script
    assert "frontend\\node_modules" in script
    assert "ffmpeg" in script and "ffprobe" in script
    assert "verify_llama_runtime.py" in script
    assert "model_store.py" in script
    assert "default_generation_settings.n_ctx" in script
    assert "systran.faster-whisper-large-v2" in script
    assert "pyannote-3.1-offline.manifest.json" in script
    assert "refs\\main" in script
    assert "production_offline_bundle_status = 'BLOCKED'" in script
    assert "validate_security_settings" in script
    assert "config.security-contract" in script
    assert "ConvertTo-Json" in script
    assert "exit 1" in script

    compose_preflight = _read("scripts/preflight_compose_runtime.ps1")
    assert "CONTAINER_LLAMA_SERVER_BASE_URL" in compose_preflight
    assert "LLAMA_SERVER_API_KEY" in compose_preflight
    assert "compose.llama-url-not-loopback" in compose_preflight


def test_onboarding_docs_keep_production_blocked_and_use_reproducible_frontend_install():
    setup = _read("docs/NEW_MACHINE_SETUP.md")
    readme = _read("README.md")

    assert "npm ci" in setup
    assert "AUTH_ENABLED=true" in setup
    assert "DEV_AUTH_BYPASS=false" in setup
    assert "BACKEND_HOST=127.0.0.1" in setup
    assert "AUTH_ENABLED=false\nINIT_DB_ON_STARTUP" not in setup
    assert "install_local_llm_staging.ps1" in setup
    assert "install_audio_models_staging.py" in setup
    assert "--accept-pyannote-terms" in setup
    assert "HF_TOKEN" in setup
    assert "preflight_new_machine.ps1" in setup
    assert "preflight_compose_runtime.ps1" in setup
    assert "127.0.0.1" in setup and "loopback" in setup
    assert "probe_celery_worker_contract.py" in setup
    assert "benchmark_summary_runtime.py" in setup
    assert "BLOCKED" in setup
    assert "production" in setup.lower()
    assert "requirements-constraints-py311.txt" in setup
    assert "Khong dung `pip install .`" in setup
    assert "diart==" not in setup
    assert "docs/NEW_MACHINE_SETUP.md" in readme
    assert "BLOCKED" in readme


def test_backend_image_uses_constraints_after_selecting_torch_profile():
    dockerfile = _read("Dockerfile.backend")

    constraints_copy = dockerfile.index("COPY requirements-constraints-py311.txt .")
    torch_install = dockerfile.index("-r requirements-torch-cu121.txt")
    runtime_install = dockerfile.index("-r requirements.txt")
    assert constraints_copy < torch_install < runtime_install
    assert "--no-deps -r requirements-torch-cu121.txt" in dockerfile


def test_setup_py_is_metadata_only_and_blocks_noncanonical_install():
    setup_source = _read("setup.py")
    metadata = subprocess.run(
        [sys.executable, "setup.py", "--name"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    blocked = subprocess.run(
        [sys.executable, "setup.py", "bdist_wheel"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert metadata.returncode == 0, metadata.stderr
    assert metadata.stdout.strip() == "speech_to_information"
    assert "install_requires=[]" in setup_source
    assert blocked.returncode != 0
    assert "requirements.txt" in (blocked.stdout + blocked.stderr)


def test_application_security_contract_accepts_canonical_authenticated_clone_config():
    completed = _validate_security_environment(**_canonical_runbook_environment())

    assert completed.returncode == 0, completed.stderr


def test_application_security_contract_accepts_only_explicit_loopback_dev_bypass():
    accepted = _validate_security_environment(
        AUTH_ENABLED="false",
        DEV_AUTH_BYPASS="true",
        DEV_USER_ID="1",
        BACKEND_HOST="127.0.0.1",
    )
    missing_flag = _validate_security_environment(
        AUTH_ENABLED="false",
        DEV_AUTH_BYPASS="false",
        DEV_USER_ID="1",
        BACKEND_HOST="127.0.0.1",
    )
    missing_user = _validate_security_environment(
        AUTH_ENABLED="false",
        DEV_AUTH_BYPASS="true",
        DEV_USER_ID="0",
        BACKEND_HOST="127.0.0.1",
    )
    exposed_host = _validate_security_environment(
        AUTH_ENABLED="false",
        DEV_AUTH_BYPASS="true",
        DEV_USER_ID="1",
        BACKEND_HOST="0.0.0.0",
    )

    assert accepted.returncode == 0, accepted.stderr
    assert missing_flag.returncode != 0
    assert "DEV_AUTH_BYPASS" in missing_flag.stderr
    assert missing_user.returncode != 0
    assert "DEV_USER_ID" in missing_user.stderr
    assert exposed_host.returncode != 0
    assert "loopback" in exposed_host.stderr


def test_legacy_entrypoint_fails_closed_and_points_to_canonical_runbook():
    launcher = _read("entrypoint.bat")

    assert "intentionally disabled" in launcher
    assert "docs\\NEW_MACHINE_SETUP.md" in launcher
    assert "preflight_new_machine.ps1" in launcher
    assert "exit /b 2" in launcher
    assert "0.0.0.0" not in launcher
    assert "start \"\"" not in launcher.lower()


def test_audio_installer_requires_explicit_gated_terms_and_pinned_hashes():
    script = _read("scripts/install_audio_models_staging.py")

    assert "hf_hub_download" in script
    assert "--accept-pyannote-terms" in script
    assert 'os.getenv("HF_TOKEN")' in script
    assert "f0fe81560cb8b68660e564f55dd99207059c092e" in script
    assert "84fd25912480287da0247647c3d2b4853cb3ee5d" in script
    assert "hashlib.sha256" in script
    assert "refs" in script and "main" in script
    assert "refusing overwrite" in script
