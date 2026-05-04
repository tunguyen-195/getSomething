from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def status_line(name: str, ok: bool, detail: str = "") -> None:
    marker = "OK" if ok else "WARN"
    suffix = f" - {detail}" if detail else ""
    print(f"[{marker}] {name}{suffix}")


def main() -> int:
    try:
        from src.core.config import settings
        from src.services.transcription.asr_providers import provider_health
    except Exception as exc:
        print(f"[ERROR] Cannot import project settings: {exc}")
        return 2

    print("SpeechToInformation Lite runtime check")
    print(f"root={ROOT}")
    print(f"edition={settings.APP_EDITION}")
    print(f"runner={settings.PROCESSING_RUNNER}")
    print(f"profile={settings.RUNTIME_PROFILE}")

    status_line("Lite runner", settings.PROCESSING_RUNNER == "single_job_db_lease", settings.PROCESSING_RUNNER)
    status_line("Rate limit disabled", not settings.RATE_LIMIT_ENABLED, f"RATE_LIMIT_ENABLED={settings.RATE_LIMIT_ENABLED}")
    status_line("Uvicorn reload disabled", not settings.UVICORN_RELOAD, f"UVICORN_RELOAD={settings.UVICORN_RELOAD}")

    status_line("ffmpeg on PATH", shutil.which("ffmpeg") is not None, shutil.which("ffmpeg") or "missing")

    whisper_cpp_bin = (ROOT / settings.WHISPER_CPP_BIN).resolve()
    whisper_cpp_model = (ROOT / settings.WHISPER_CPP_MODEL).resolve()
    phowhisper_model = (ROOT / settings.PHOWHISPER_CPP_MODEL).resolve()

    status_line("whisper.cpp binary", whisper_cpp_bin.exists(), str(whisper_cpp_bin))
    status_line("whisper.cpp model", whisper_cpp_model.exists(), str(whisper_cpp_model))

    if phowhisper_model.exists():
        size_ok = phowhisper_model.stat().st_size == settings.PHOWHISPER_CPP_SIZE_BYTES
        sha_ok = sha256(phowhisper_model) == settings.PHOWHISPER_CPP_SHA256.upper()
        manifest_ok = Path(str(phowhisper_model) + ".manifest.json").exists()
        status_line("PhoWhisper.cpp size", size_ok, str(phowhisper_model.stat().st_size))
        status_line("PhoWhisper.cpp sha256", sha_ok, settings.PHOWHISPER_CPP_SHA256)
        status_line(
            "PhoWhisper.cpp validation manifest",
            manifest_ok,
            str(Path(str(phowhisper_model) + ".manifest.json")),
        )
    else:
        status_line("PhoWhisper.cpp model", False, str(phowhisper_model))

    health = provider_health()
    print("ASR provider health:")
    for key, value in health.items():
        if key == "profiles":
            continue
        print(f"  {key}={value}")

    llm_configured = bool(settings.ANALYSIS_LLM_API_KEY) or settings.ANALYSIS_LLM_PROVIDER in {"ollama", "llama_cpp_server"}
    status_line("Analysis LLM configured", llm_configured, settings.ANALYSIS_LLM_PROVIDER)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
