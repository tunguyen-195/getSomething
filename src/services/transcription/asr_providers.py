from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from src.core.config import settings
from src.core.logging import logger
from src.services.model_artifacts import (
    ModelArtifactError,
    normalize_model_name,
    require_faster_whisper_runtime_ready,
    verify_artifact_id_for_health,
    verify_faster_whisper_runtime_health,
)
from src.services.hallucination_filter import guard_transcript_segments


class ASRProviderError(RuntimeError):
    pass


_PHOWHISPER_VALIDATION_CACHE: dict[str, Any] = {}


ASR_PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "rtx2050_safe": {
        "label_vi": "Nhanh (small)",
        "provider": "faster_whisper_ct2",
        "model": "small",
        "device": "cuda",
        "compute_type": "int8",
        "beam_size": 5,
        "enable_diarization": False,
        "description": "Small/cuda/int8/batch 1. Dùng khi cần tốc độ hoặc máy yếu; không phải profile chất lượng tiếng Việt.",
    },
    "rtx2050_fast": {
        "label_vi": "Nhanh benchmark",
        "provider": "faster_whisper_ct2",
        "model": "small",
        "device": "cuda",
        "compute_type": "int8_float16",
        "beam_size": 5,
        "enable_diarization": False,
        "description": "Only promote after no-OOM benchmark on the target RTX2050 machine.",
    },
    "balanced": {
        "label_vi": "Tiếng Việt cân bằng",
        "provider": "faster_whisper_ct2",
        "model": "medium",
        "device": "cuda",
        "compute_type": "int8",
        "beam_size": 5,
        "enable_diarization": False,
        "description": "Medium/cuda/int8. Mặc định khuyến nghị cho tiếng Việt trên RTX2050 nếu model đã verify.",
    },
    "cpu_safe": {
        "label_vi": "CPU an toàn (small)",
        "provider": "faster_whisper_ct2",
        "model": "small",
        "device": "cpu",
        "compute_type": "int8",
        "beam_size": 5,
        "enable_diarization": False,
        "description": "CPU fallback profile.",
    },
    "offline_cpp": {
        "label_vi": "Offline CPP",
        "provider": "whisper_cpp_cli",
        "model": "whisper_cpp",
        "description": "whisper.cpp CLI provider using configured GGML model.",
    },
    "phowhisper_cpp_candidate": {
        "label_vi": "PhoWhisper CPP candidate",
        "provider": "phowhisper_cpp_cli",
        "model": "phowhisper-large-q5_0",
        "description": "Hidden unless source manifest and smoke test are valid.",
    },
    "quality_local": {
        "label_vi": "Chất lượng cao",
        "provider": "faster_whisper_ct2",
        "model": "large-v3-turbo",
        "device": "cuda",
        "compute_type": "int8",
        "beam_size": 5,
        "enable_diarization": False,
        "description": "Higher quality local ASR profile; benchmark before using as default.",
    },
}

AUTO_LANGUAGE_VALUES = {"", "auto", "detect", "mixed", "multilingual"}

ASR_LANGUAGE_OPTIONS = [
    {
        "value": "vi",
        "label_vi": "Tiếng Việt + thuật ngữ Anh",
        "description": "Ép nhận dạng tiếng Việt; khuyến nghị cho hội thoại Việt có xen thuật ngữ tiếng Anh.",
    },
    {
        "value": "en",
        "label_vi": "English",
        "description": "Ép nhận dạng tiếng Anh.",
    },
    {
        "value": "auto",
        "label_vi": "Tự động",
        "description": "Chỉ dùng khi chưa biết ngôn ngữ; có thể nhận nhầm với audio ngắn/nhiễu hoặc Anh-Việt.",
    },
]


def _warnings(*items: str | None) -> list[str]:
    return [item for item in items if item]


def _normalize_requested_language(language: str | None) -> tuple[str | None, bool, str]:
    requested = (language or settings.DEFAULT_LANGUAGE or "vi").strip().lower()
    if requested in AUTO_LANGUAGE_VALUES:
        return None, True, "auto"
    return requested, False, requested


def _segment_words(segment: Any) -> list[dict[str, Any]]:
    words = getattr(segment, "words", None) or []
    output = []
    for word in words:
        output.append(
            {
                "word": getattr(word, "word", ""),
                "start": getattr(word, "start", None),
                "end": getattr(word, "end", None),
                "probability": getattr(word, "probability", None),
            }
        )
    return output


def _avg_word_probability(words: list[dict[str, Any]]) -> float | None:
    probabilities = []
    for word in words:
        value = word.get("probability")
        if value is None:
            continue
        try:
            probabilities.append(float(value))
        except (TypeError, ValueError):
            continue
    if not probabilities:
        return None
    return sum(probabilities) / len(probabilities)


def _merge_segment_pair(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    words = list(left.get("words") or []) + list(right.get("words") or [])
    merged = {
        **left,
        "end": right.get("end", left.get("end")),
        "text": " ".join(
            item
            for item in [
                str(left.get("text", "")).strip(),
                str(right.get("text", "")).strip(),
            ]
            if item
        ),
        "words": words,
    }
    avg_word_probability = _avg_word_probability(words)
    if avg_word_probability is not None:
        merged["avg_word_probability"] = avg_word_probability
    return merged


def _normalize_asr_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not segments:
        return []

    normalized: list[dict[str, Any]] = []
    max_seconds = float(getattr(settings, "ASR_SEGMENT_MAX_SECONDS", 18.0) or 18.0)
    merge_gap = float(getattr(settings, "ASR_SEGMENT_MERGE_GAP_SECONDS", 0.7) or 0.7)

    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or start)
        duration = max(0.0, end - start)
        previous = normalized[-1] if normalized else None
        previous_end = float(previous.get("end") or 0.0) if previous else 0.0
        gap = start - previous_end

        if (
            previous
            and gap <= merge_gap
            and (
                duration < 0.75
                or len(text) <= 6
                or max(0.0, previous_end - float(previous.get("start") or previous_end)) < 0.75
            )
        ):
            normalized[-1] = _merge_segment_pair(previous, segment)
            continue

        if duration > max_seconds and segment.get("words"):
            chunk: list[dict[str, Any]] = []
            chunk_start: float | None = None
            for word in segment["words"]:
                word_text = str(word.get("word", "")).strip()
                if not word_text:
                    continue
                word_start = float(word.get("start") if word.get("start") is not None else start)
                word_end = float(word.get("end") if word.get("end") is not None else word_start)
                if chunk_start is None:
                    chunk_start = word_start
                chunk.append(word)
                chunk_duration = word_end - chunk_start
                boundary = word_text.endswith((".", "?", "!", ";", ":"))
                forced_boundary = chunk_duration >= max_seconds * 1.5
                if chunk_duration >= max_seconds and (boundary or forced_boundary):
                    text_chunk = " ".join(str(item.get("word", "")).strip() for item in chunk).strip()
                    split_segment = {
                        **segment,
                        "start": chunk_start,
                        "end": word_end,
                        "text": text_chunk,
                        "words": list(chunk),
                    }
                    avg_word_probability = _avg_word_probability(split_segment["words"])
                    if avg_word_probability is not None:
                        split_segment["avg_word_probability"] = avg_word_probability
                    normalized.append(split_segment)
                    chunk = []
                    chunk_start = None
            if chunk:
                chunk_end = float(chunk[-1].get("end") if chunk[-1].get("end") is not None else end)
                text_chunk = " ".join(str(item.get("word", "")).strip() for item in chunk).strip()
                split_segment = {
                    **segment,
                    "start": chunk_start if chunk_start is not None else start,
                    "end": chunk_end,
                    "text": text_chunk,
                    "words": list(chunk),
                }
                avg_word_probability = _avg_word_probability(split_segment["words"])
                if avg_word_probability is not None:
                    split_segment["avg_word_probability"] = avg_word_probability
                normalized.append(split_segment)
            continue

        normalized.append(segment)

    return normalized


def _from_segments(segments: list[dict[str, Any]], *, duration: float, language: str, provider: str, model_info: dict[str, Any], warnings: list[str], processing_time: float) -> dict[str, Any]:
    text = " ".join(str(seg.get("text", "")).strip() for seg in segments if str(seg.get("text", "")).strip()).strip()
    return {
        "text": text,
        "segments": segments,
        "duration": duration,
        "language": language,
        "provider": provider,
        "model_info": model_info,
        "warnings": warnings,
        "processing_time": processing_time,
    }


def _is_oom(exc: Exception) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or "cuda" in text and "memory" in text


def _load_verified_faster_whisper_model(model_name: str, *, device: str, compute_type: str):
    verified_model_path = require_faster_whisper_runtime_ready(
        model_name,
        cache_root=settings.WHISPER_MODEL_PATH,
    )
    from faster_whisper import WhisperModel

    return WhisperModel(str(verified_model_path), device=device, compute_type=compute_type)


def resolve_asr_runtime(profile: str | None) -> dict[str, Any]:
    profile_name = profile or settings.ASR_PROFILE
    preset = ASR_PROFILE_PRESETS.get(profile_name, {})
    return {
        "profile": profile_name,
        "provider": preset.get("provider") or settings.ASR_PROVIDER,
        "model": preset.get("model") or settings.WHISPER_MODEL,
        "device": preset.get("device") or settings.WHISPER_DEVICE,
        "compute_type": preset.get("compute_type") or settings.WHISPER_COMPUTE_TYPE,
        "beam_size": int(preset.get("beam_size") or settings.WHISPER_BEAM_SIZE),
        "enable_diarization": preset.get("enable_diarization"),
        "description": preset.get("description"),
    }


def _faster_whisper_result(
    audio_path: str,
    *,
    language: str,
    runtime: dict[str, Any],
    warning_prefix: str | None = None,
    force_cpu: bool = False,
) -> dict[str, Any]:
    start = time.time()

    model_name = runtime["model"]
    runtime_device = runtime["device"]
    runtime_compute_type = runtime["compute_type"]

    if runtime_device == "cuda":
        try:
            import torch

            if not torch.cuda.is_available():
                runtime_device = "cpu"
                runtime_compute_type = "int8"
                warning_prefix = warning_prefix or "cuda_unavailable_retry_cpu_int8"
        except Exception:
            runtime_device = "cpu"
            runtime_compute_type = "int8"
            warning_prefix = warning_prefix or "cuda_probe_failed_retry_cpu_int8"

    if force_cpu:
        model = _load_verified_faster_whisper_model(
            model_name,
            device="cpu",
            compute_type="int8",
        )
        transcribe = model.transcribe
        device = "cpu"
        compute_type = "int8"
    elif (
        model_name != settings.WHISPER_MODEL
        or runtime_device != settings.WHISPER_DEVICE
        or runtime_compute_type != settings.WHISPER_COMPUTE_TYPE
    ):
        model = _load_verified_faster_whisper_model(
            model_name,
            device=runtime_device,
            compute_type=runtime_compute_type,
        )
        transcribe = model.transcribe
        device = runtime_device
        compute_type = runtime_compute_type
    else:
        from src.services.transcription.models.whisper_manager import get_whisper_manager

        manager = get_whisper_manager()
        transcribe = manager.transcribe
        device = settings.WHISPER_DEVICE
        compute_type = settings.WHISPER_COMPUTE_TYPE

    transcribe_language, multilingual, requested_language = _normalize_requested_language(language)

    segments_iter, info = transcribe(
        audio_path,
        language=transcribe_language,
        task="transcribe",
        beam_size=runtime["beam_size"],
        vad_filter=settings.WHISPER_VAD_FILTER,
        temperature=0.0,
        compression_ratio_threshold=settings.WHISPER_COMPRESSION_RATIO_THRESHOLD,
        log_prob_threshold=settings.WHISPER_LOG_PROB_THRESHOLD,
        no_speech_threshold=settings.WHISPER_NO_SPEECH_THRESHOLD,
        initial_prompt=settings.WHISPER_INITIAL_PROMPT,
        hotwords=settings.WHISPER_HOTWORDS,
        vad_parameters={
            "threshold": settings.WHISPER_VAD_THRESHOLD,
            "min_speech_duration_ms": settings.WHISPER_VAD_MIN_SPEECH_MS,
            "min_silence_duration_ms": settings.WHISPER_VAD_MIN_SILENCE_MS,
            "speech_pad_ms": settings.WHISPER_VAD_SPEECH_PAD_MS,
        },
        word_timestamps=True,
        multilingual=multilingual,
        condition_on_previous_text=settings.WHISPER_CONDITION_ON_PREVIOUS_TEXT,
    )

    segments = []
    for segment in segments_iter:
        text = str(getattr(segment, "text", "")).strip()
        if not text:
            continue
        lower = text.lower()
        if any(prompt in lower and len(text) < 50 for prompt in ["tiếng việt", "hãy chuyển đổi"]):
            continue
        if any(pattern in lower and len(text) < 100 for pattern in ["subscribe", "đăng ký kênh", "thanks for watching"]):
            continue
        words = _segment_words(segment)
        avg_word_probability = _avg_word_probability(words)
        item = {
            "start": getattr(segment, "start", 0.0),
            "end": getattr(segment, "end", 0.0),
            "text": text,
            "speaker": None,
            "confidence": getattr(segment, "avg_logprob", None),
            "avg_logprob": getattr(segment, "avg_logprob", None),
            "no_speech_prob": getattr(segment, "no_speech_prob", None),
            "compression_ratio": getattr(segment, "compression_ratio", None),
            "words": words,
        }
        if avg_word_probability is not None:
            item["avg_word_probability"] = avg_word_probability
        segments.append(item)

    detected_language = getattr(info, "language", language) or language
    guard_language = transcribe_language or (
        settings.DEFAULT_LANGUAGE
        if str(settings.DEFAULT_LANGUAGE).strip().lower() not in AUTO_LANGUAGE_VALUES
        else "vi"
    )
    warnings = _warnings(warning_prefix)
    if requested_language == "auto" and str(detected_language).lower() not in {"vi", "en"}:
        warnings.append(f"detected_language_unexpected:{detected_language}")

    segments = _normalize_asr_segments(segments)
    guard_report: dict[str, Any] | None = None
    if settings.ASR_GUARD_ENABLED:
        segments, guard_report = guard_transcript_segments(
            segments,
            language=str(guard_language).lower(),
            min_avg_logprob=settings.ASR_GUARD_MIN_AVG_LOGPROB,
            max_no_speech_prob=settings.ASR_GUARD_MAX_NO_SPEECH_PROB,
            max_compression_ratio=settings.ASR_GUARD_MAX_COMPRESSION_RATIO,
        )
        if guard_report.get("removed_segments"):
            warnings.append(f"asr_guard_removed_segments:{guard_report['removed_segments']}")

    return _from_segments(
        segments,
        duration=float(getattr(info, "duration", 0.0) or 0.0),
        language=detected_language,
        provider="faster_whisper_ct2",
        model_info={
            "model": model_name,
            "device": device,
            "compute_type": compute_type,
            "profile": runtime["profile"],
            "requested_language": requested_language,
            "multilingual": multilingual,
            "vad_filter": settings.WHISPER_VAD_FILTER,
            "condition_on_previous_text": settings.WHISPER_CONDITION_ON_PREVIOUS_TEXT,
            "guard": guard_report or {"enabled": False},
        },
        warnings=warnings,
        processing_time=time.time() - start,
    )


def transcribe_faster_whisper_ct2(audio_path: str, *, language: str, runtime: dict[str, Any], **_: Any) -> dict[str, Any]:
    try:
        return _faster_whisper_result(audio_path, language=language, runtime=runtime)
    except ModelArtifactError:
        raise
    except Exception as exc:
        if not _is_oom(exc):
            raise
        logger.warning("[ASR] CUDA OOM or memory failure; retrying faster-whisper on CPU/int8")
        try:
            from src.services.transcription.models.whisper_manager import get_whisper_manager

            get_whisper_manager().unload()
        except Exception:
            pass
        return _faster_whisper_result(
            audio_path,
            language=language,
            runtime=runtime,
            warning_prefix="cuda_oom_retry_cpu_int8",
            force_cpu=True,
        )


def transcribe_cherry_whisper_v2(audio_path: str, *, language: str, enable_diarization: bool, diarization_method: str, **_: Any) -> dict[str, Any]:
    start = time.time()
    from src.services.transcription.cherry_transcription_service import get_cherry_transcriber

    result = get_cherry_transcriber().transcribe(
        audio_path=audio_path,
        language=language,
        enable_diarization=enable_diarization,
        model_type="whisper",
    )
    segments = result.get("segments", [])
    return _from_segments(
        segments,
        duration=float(result.get("duration") or 0.0),
        language=result.get("language") or language,
        provider="cherry_whisper_v2",
        model_info={"model": result.get("model_used", "whisper")},
        warnings=[] if diarization_method != "none" else ["diarization_disabled"],
        processing_time=time.time() - start,
    )


def transcribe_phowhisper_torch(audio_path: str, *, language: str, enable_diarization: bool, diarization_method: str, **_: Any) -> dict[str, Any]:
    start = time.time()
    from src.services.transcription.cherry_transcription_service import get_cherry_transcriber

    result = get_cherry_transcriber().transcribe(
        audio_path=audio_path,
        language=language,
        enable_diarization=enable_diarization,
        model_type="phowhisper",
    )
    segments = result.get("segments", [])
    return _from_segments(
        segments,
        duration=float(result.get("duration") or 0.0),
        language=result.get("language") or language,
        provider="phowhisper_torch",
        model_info={"model": result.get("model_used", "phowhisper")},
        warnings=[] if diarization_method != "none" else ["diarization_disabled"],
        processing_time=time.time() - start,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _reason_code(exc: Exception) -> str:
    text = str(exc).strip().lower()
    allowed = "".join(ch if ch.isalnum() else "_" for ch in text)
    compact = "_".join(part for part in allowed.split("_") if part)
    if not compact:
        compact = exc.__class__.__name__.lower()
    return compact[:120]


def _artifact_result_reason(artifact_id: str) -> str | None:
    result = verify_artifact_id_for_health(artifact_id)
    if result.ok:
        return None
    return result.errors[0] if result.errors else "model_cache_missing_or_unverified"


def _profile_availability(
    key: str,
    preset: dict[str, Any],
    *,
    phowhisper_valid: bool,
    faster_whisper_health: dict[str, tuple[bool, str | None]],
) -> tuple[bool, str | None]:
    provider = preset.get("provider")
    if provider == "faster_whisper_ct2":
        model_name = str(preset.get("model") or settings.WHISPER_MODEL)
        health_key = f"{normalize_model_name(model_name)}:{settings.WHISPER_MODEL_PATH}"
        if health_key not in faster_whisper_health:
            result = verify_faster_whisper_runtime_health(
                model_name,
                cache_root=settings.WHISPER_MODEL_PATH,
            )
            reason = None if result.ok else (result.errors[0] if result.errors else "model_cache_missing_or_unverified")
            faster_whisper_health[health_key] = (result.ok, reason)
        return faster_whisper_health[health_key]
    if provider == "whisper_cpp_cli":
        reason = _artifact_result_reason("whisper_cpp_small_q5")
        if reason:
            return False, reason
        if not Path(settings.WHISPER_CPP_BIN).exists():
            return False, "whisper_cpp_binary_missing"
        return True, None
    if provider == "phowhisper_cpp_cli":
        if phowhisper_valid:
            return True, None
        return False, "phowhisper_cpp_candidate_invalid"
    return True, None


def _validate_phowhisper_cpp_model(model_path: Path) -> list[str]:
    warnings = []
    if not model_path.exists():
        raise ASRProviderError("PhoWhisper.cpp model is missing")
    size = model_path.stat().st_size
    if size != settings.PHOWHISPER_CPP_SIZE_BYTES:
        raise ASRProviderError("PhoWhisper.cpp model size mismatch")
    if _sha256(model_path) != settings.PHOWHISPER_CPP_SHA256.upper():
        raise ASRProviderError("PhoWhisper.cpp model SHA256 mismatch")
    manifest_path = model_path.with_suffix(model_path.suffix + ".manifest.json")
    if not manifest_path.exists():
        raise ASRProviderError("PhoWhisper.cpp validation manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ASRProviderError("PhoWhisper.cpp validation manifest is invalid JSON") from exc

    required_strings = [
        "source_url",
        "source_license",
        "whisper_cpp_binary_sha256",
        "whisper_cpp_version",
        "model_architecture",
    ]
    for key in required_strings:
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ASRProviderError(f"PhoWhisper.cpp validation manifest missing {key}")
    if manifest.get("whisper_cpp_compatible") is not True:
        raise ASRProviderError("PhoWhisper.cpp compatibility has not been confirmed")

    bin_path = Path(settings.WHISPER_CPP_BIN)
    if not bin_path.exists():
        raise ASRProviderError("whisper.cpp binary is missing")
    if _sha256(bin_path) != manifest["whisper_cpp_binary_sha256"].upper():
        raise ASRProviderError("whisper.cpp binary SHA256 mismatch")

    smoke_test = manifest.get("smoke_test")
    if not isinstance(smoke_test, dict):
        raise ASRProviderError("PhoWhisper.cpp validation manifest missing smoke_test")
    if smoke_test.get("status") != "pass":
        raise ASRProviderError("PhoWhisper.cpp smoke test has not passed")
    if smoke_test.get("json_parse_pass") is not True:
        raise ASRProviderError("PhoWhisper.cpp JSON parse smoke test has not passed")
    duration = smoke_test.get("duration_seconds")
    if not isinstance(duration, (int, float)) or duration < 10 or duration > 30:
        raise ASRProviderError("PhoWhisper.cpp smoke test must use a 10-30 second Vietnamese sample")
    if not str(smoke_test.get("language", "")).lower().startswith("vi"):
        raise ASRProviderError("PhoWhisper.cpp smoke test must use Vietnamese audio")

    benchmark = manifest.get("benchmark")
    if not isinstance(benchmark, dict) or benchmark.get("status") != "pass":
        raise ASRProviderError("PhoWhisper.cpp benchmark gate has not passed")
    if benchmark.get("baseline") != "faster_whisper_ct2_small_int8":
        raise ASRProviderError("PhoWhisper.cpp benchmark baseline must be faster_whisper_ct2_small_int8")
    if benchmark.get("keyword_recall_pass") is not True:
        raise ASRProviderError("PhoWhisper.cpp keyword recall benchmark has not passed")
    if not isinstance(benchmark.get("max_relative_wer_regression"), (int, float)):
        raise ASRProviderError("PhoWhisper.cpp benchmark missing max_relative_wer_regression")
    return warnings


def _validate_phowhisper_cpp_model_cached(model_path: Path) -> list[str]:
    if not model_path.exists():
        raise ASRProviderError("PhoWhisper.cpp model is missing")
    stat = model_path.stat()
    cache_key = f"{model_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    cached = _PHOWHISPER_VALIDATION_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)
    warnings = _validate_phowhisper_cpp_model(model_path)
    _PHOWHISPER_VALIDATION_CACHE.clear()
    _PHOWHISPER_VALIDATION_CACHE[cache_key] = list(warnings)
    return warnings


def _run_ffmpeg_to_wav(input_path: str, output_path: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-ar",
        "16000",
        "-ac",
        "1",
        "-acodec",
        "pcm_s16le",
        str(output_path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _parse_whisper_cpp_output(temp_dir: Path, wav_path: Path, stdout: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    warnings = []
    json_candidates = [
        temp_dir / f"{wav_path.name}.json",
        temp_dir / f"{wav_path.stem}.json",
        wav_path.with_suffix(wav_path.suffix + ".json"),
        wav_path.with_suffix(".json"),
    ]
    for candidate in json_candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            segments_payload = payload.get("transcription") or payload.get("segments") or []
            segments = []
            for item in segments_payload:
                offsets = item.get("offsets") or {}
                start = item.get("start") or offsets.get("from") or 0
                end = item.get("end") or offsets.get("to") or start
                if isinstance(start, int):
                    start = start / 1000
                if isinstance(end, int):
                    end = end / 1000
                segments.append(
                    {
                        "start": float(start or 0),
                        "end": float(end or 0),
                        "text": str(item.get("text", "")).strip(),
                        "speaker": None,
                        "confidence": None,
                    }
                )
            text = " ".join(seg["text"] for seg in segments if seg["text"]).strip()
            return text, segments, warnings
        except Exception:
            warnings.append("whisper_cpp_json_parse_failed")

    text_lines = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("whisper_") and not stripped.startswith("system_info"):
            text_lines.append(stripped)
    text = " ".join(text_lines).strip()
    return text, [{"start": 0.0, "end": 0.0, "text": text, "speaker": None, "confidence": None}] if text else [], warnings + ["whisper_cpp_text_only"]


def transcribe_whisper_cpp_cli(audio_path: str, *, language: str, provider: str = "whisper_cpp_cli", runtime: dict[str, Any], **_: Any) -> dict[str, Any]:
    start = time.time()
    bin_path = Path(settings.WHISPER_CPP_BIN)
    model_path = Path(settings.WHISPER_CPP_MODEL)
    warnings = []
    if provider == "phowhisper_cpp_cli":
        model_path = Path(settings.PHOWHISPER_CPP_MODEL)
        warnings.extend(_validate_phowhisper_cpp_model_cached(model_path))
    if not bin_path.exists():
        raise ASRProviderError("whisper.cpp binary is missing")
    if not model_path.exists():
        raise ASRProviderError("whisper.cpp model is missing")

    with tempfile.TemporaryDirectory(prefix="sti-whispercpp-") as temp_name:
        temp_dir = Path(temp_name)
        wav_path = temp_dir / "input.wav"
        _run_ffmpeg_to_wav(audio_path, wav_path)
        command = [
            str(bin_path),
            "-m",
            str(model_path),
            "-f",
            str(wav_path),
            "-l",
            _normalize_requested_language(language)[0] or settings.WHISPER_CPP_LANGUAGE,
            "-t",
            str(settings.WHISPER_CPP_THREADS),
            "-oj",
        ]
        completed = subprocess.run(
            command,
            cwd=str(temp_dir),
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.WHISPER_CPP_TIMEOUT_SECONDS,
            shell=False,
        )
        text, segments, parse_warnings = _parse_whisper_cpp_output(temp_dir, wav_path, completed.stdout)
        warnings.extend(parse_warnings)

    return _from_segments(
        segments,
        duration=segments[-1]["end"] if segments else 0.0,
        language=language,
        provider=provider,
        model_info={
            "model": str(model_path),
            "binary": str(bin_path),
            "threads": settings.WHISPER_CPP_THREADS,
            "profile": runtime["profile"],
        },
        warnings=warnings,
        processing_time=time.time() - start,
    )


PROVIDERS = {
    "cherry_whisper_v2": transcribe_cherry_whisper_v2,
    "faster_whisper_ct2": transcribe_faster_whisper_ct2,
    "whisper_cpp_cli": transcribe_whisper_cpp_cli,
    "phowhisper_cpp_cli": lambda audio_path, **kwargs: transcribe_whisper_cpp_cli(
        audio_path,
        provider="phowhisper_cpp_cli",
        **kwargs,
    ),
    "phowhisper_torch": transcribe_phowhisper_torch,
}


def transcribe_with_provider(
    *,
    audio_path: str,
    language: str,
    profile: str,
    enable_diarization: bool,
    diarization_method: str,
    task_id: str,
) -> dict[str, Any]:
    runtime = resolve_asr_runtime(profile)
    provider_name = runtime["provider"]
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        raise ASRProviderError(f"Unsupported ASR provider: {provider_name}")
    if provider_name == "phowhisper_cpp_cli":
        health = provider_health()
        if not health.get("phowhisper_cpp_candidate_valid"):
            raise ASRProviderError("PhoWhisper.cpp candidate is not valid; run source manifest and smoke test first")
    return provider(
        audio_path,
        language=language,
        profile=runtime["profile"],
        runtime=runtime,
        enable_diarization=enable_diarization,
        diarization_method=diarization_method,
        task_id=task_id,
    )


def provider_health() -> dict[str, Any]:
    phowhisper_model = Path(settings.PHOWHISPER_CPP_MODEL)
    whisper_cpp_bin = Path(settings.WHISPER_CPP_BIN)
    phowhisper_valid = False
    phowhisper_warnings: list[str] = []
    if phowhisper_model.exists():
        try:
            phowhisper_warnings = _validate_phowhisper_cpp_model_cached(phowhisper_model)
            phowhisper_valid = not phowhisper_warnings
        except Exception as exc:
            phowhisper_warnings = [_reason_code(exc)]
    profiles = []
    faster_whisper_health: dict[str, tuple[bool, str | None]] = {}
    for key, preset in ASR_PROFILE_PRESETS.items():
        available, reason = _profile_availability(
            key,
            preset,
            phowhisper_valid=phowhisper_valid,
            faster_whisper_health=faster_whisper_health,
        )
        profiles.append(
            {
                "value": key,
                "label_vi": preset["label_vi"],
                "provider": preset["provider"],
                "description": preset["description"],
                "available": available,
                "availability_reason": reason,
            }
        )

    return {
        "asr_provider": settings.ASR_PROVIDER,
        "asr_profile": settings.ASR_PROFILE,
        "whisper_model": settings.WHISPER_MODEL,
        "whisper_device": settings.WHISPER_DEVICE,
        "whisper_compute_type": settings.WHISPER_COMPUTE_TYPE,
        "default_language": settings.DEFAULT_LANGUAGE,
        "language_options": ASR_LANGUAGE_OPTIONS,
        "whisper_cpp_binary_available": whisper_cpp_bin.exists(),
        "whisper_cpp_model_available": Path(settings.WHISPER_CPP_MODEL).exists(),
        "phowhisper_cpp_model_available": phowhisper_model.exists(),
        "phowhisper_cpp_candidate_valid": phowhisper_valid,
        "phowhisper_cpp_warnings": phowhisper_warnings,
        "profiles": profiles,
    }
