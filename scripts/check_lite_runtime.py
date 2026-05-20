from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.services.model_artifacts import ModelArtifactError, require_faster_whisper_runtime_ready  # noqa: E402


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


def reason_code(value: object) -> str:
    text = str(value).strip().lower()
    compact = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return compact[:120] or "unknown_error"


def _normalized_model_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower().replace("faster-whisper-", ""))


def model_available_locally(model_name: str, cache_root: Path) -> bool:
    model_path = Path(model_name)
    if model_path.exists():
        return True
    root_model_path = (ROOT / model_name).resolve()
    if root_model_path.exists():
        return True
    cache_root = cache_root.resolve()
    if not cache_root.exists():
        return False
    target = _normalized_model_name(model_name)
    for cached_dir in cache_root.iterdir():
        if not cached_dir.is_dir():
            continue
        cached_name = _normalized_model_name(cached_dir.name)
        if target and target in cached_name:
            return True
    return False


def transcribe_language_arg(value: object) -> str | None:
    language = str(value or "").strip().lower()
    if language in {"", "auto", "detect", "mixed", "multilingual"}:
        return None
    return language


def run_gpu_smoke(settings, *, audio_path: Path | None, offline_models_only: bool) -> None:
    if audio_path and not audio_path.is_file():
        raise RuntimeError("gpu_smoke_audio_unavailable")

    try:
        import torch
        import ctranslate2
    except Exception as exc:
        raise RuntimeError("gpu_dependencies_unavailable") from exc

    if not torch.cuda.is_available():
        raise RuntimeError("torch_cuda_unavailable")
    if ctranslate2.get_cuda_device_count() <= 0:
        raise RuntimeError("ctranslate2_cuda_device_unavailable")
    supported = ctranslate2.get_supported_compute_types("cuda")
    if "int8" not in supported:
        raise RuntimeError("ctranslate2_cuda_int8_unavailable")

    verified_model_path = require_faster_whisper_runtime_ready(
        settings.WHISPER_MODEL,
        root=ROOT,
        cache_root=settings.WHISPER_MODEL_PATH,
    )

    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            str(verified_model_path),
            device="cuda",
            compute_type="int8",
        )
        if audio_path:
            segments, _info = model.transcribe(
                str(audio_path),
                language=transcribe_language_arg(settings.DEFAULT_LANGUAGE),
                beam_size=1,
                vad_filter=True,
            )
            first_segment = next(iter(segments), None)
            if first_segment is None:
                raise RuntimeError("gpu_smoke_no_segments")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("model_unavailable_or_download_failed") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SpeechToInformation Lite runtime readiness.")
    parser.add_argument("--gpu-smoke", action="store_true", help="Load faster-whisper on CUDA/int8.")
    parser.add_argument("--gpu-smoke-audio", type=Path, help="Optional short Vietnamese audio for real CUDA inference.")
    parser.add_argument("--offline-models-only", action="store_true", help="Fail before model load if cache/path is missing.")
    args = parser.parse_args()

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

    if args.gpu_smoke:
        try:
            run_gpu_smoke(settings, audio_path=args.gpu_smoke_audio, offline_models_only=args.offline_models_only)
            status_line("GPU ASR smoke", True, "faster-whisper cuda/int8")
        except ModelArtifactError as exc:
            print(f"[ERROR] gpu_smoke_failed:{exc.reason_code}")
            return 3
        except Exception as exc:
            print(f"[ERROR] gpu_smoke_failed:{reason_code(exc)}")
            return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
