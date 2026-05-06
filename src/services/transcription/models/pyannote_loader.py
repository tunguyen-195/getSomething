"""Shared Pyannote loading and output normalization helpers.

The module is intentionally import-safe: optional heavy dependencies such as
pyannote.audio, torch, and huggingface_hub are imported only inside functions.
"""

from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "pyannote/speaker-diarization-community-1"
DEFAULT_FALLBACK_MODEL_ID = "pyannote/speaker-diarization-3.1"
DEFAULT_CACHE_DIR = "models/pyannote"


def _env_or_setting(name: str, default: Any) -> Any:
    value = os.getenv(name)
    if value not in (None, ""):
        return value
    try:
        from src.core.config import settings

        return getattr(settings, name, default)
    except Exception:
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def model_local_dir(model_id: str, cache_dir: str | Path | None = None) -> Path:
    """Return the stable local snapshot directory for a Pyannote model id."""
    base_dir = Path(cache_dir or _env_or_setting("PYANNOTE_CACHE_DIR", DEFAULT_CACHE_DIR))
    return base_dir / model_id.replace("/", "--")


def _pipeline_from_pretrained(checkpoint_path: str | Path, hf_token: str | None = None):
    from pyannote.audio import Pipeline

    kwargs: dict[str, Any] = {}
    if hf_token:
        params = inspect.signature(Pipeline.from_pretrained).parameters
        if "token" in params:
            kwargs["token"] = hf_token
        elif "use_auth_token" in params:
            kwargs["use_auth_token"] = hf_token
    return Pipeline.from_pretrained(str(checkpoint_path), **kwargs)


def _move_to_device(pipeline: Any, device: Any = None) -> Any:
    try:
        import torch

        target = device
        if target is None and torch.cuda.is_available():
            target = "cuda"
        if target is not None and hasattr(pipeline, "to"):
            pipeline.to(torch.device(target) if isinstance(target, str) else target)
    except Exception as exc:
        logger.warning("Pyannote pipeline loaded but device move failed: %s", exc)
    return pipeline


def load_pyannote_pipeline(
    device: Any = None,
    hf_token: str | None = None,
    cache_dir: str | Path | None = None,
    auto_download: bool | None = None,
):
    """Load a Pyannote pipeline from a verified local artifact.

    Runtime auto-download is intentionally disabled. Prepare the gated model with
    download_pyannote_model.py so revision and file hashes are checked before use.
    """
    primary = str(_env_or_setting("PYANNOTE_MODEL_ID", DEFAULT_MODEL_ID))
    fallback = str(_env_or_setting("PYANNOTE_FALLBACK_MODEL_ID", DEFAULT_FALLBACK_MODEL_ID))
    cache_dir = Path(cache_dir or str(_env_or_setting("PYANNOTE_CACHE_DIR", DEFAULT_CACHE_DIR)))
    if auto_download is None:
        auto_download = _as_bool(_env_or_setting("PYANNOTE_AUTO_DOWNLOAD", False))
    hf_token = str(hf_token or _env_or_setting("HF_TOKEN", "") or "")

    model_ids = [primary]
    if fallback and fallback != primary:
        model_ids.append(fallback)

    if auto_download:
        logger.warning("Pyannote runtime auto-download is disabled; run download_pyannote_model.py first")

    for model_id in model_ids:
        try:
            from src.services.model_artifacts import ModelArtifactError, require_pyannote_runtime_ready

            local_dir = require_pyannote_runtime_ready(model_id, cache_root=cache_dir)
        except ModelArtifactError as exc:
            logger.warning("Pyannote unavailable for %s: %s", model_id, exc.reason_code)
            continue

        try:
            pipeline = _pipeline_from_pretrained(local_dir)
            logger.info("Loaded Pyannote model %s from %s", model_id, local_dir)
            return _move_to_device(pipeline, device=device)
        except Exception as exc:
            logger.warning("Pyannote local load failed for %s: %s", model_id, exc.__class__.__name__)

    logger.warning("Pyannote unavailable; continuing without diarization")
    return None


def _pick_wrapped_output(raw: Any) -> Any:
    if raw is None:
        return None
    if hasattr(raw, "exclusive_speaker_diarization"):
        value = getattr(raw, "exclusive_speaker_diarization")
        if value is not None:
            return value
    if isinstance(raw, dict):
        value = raw.get("exclusive_speaker_diarization")
        if value is not None:
            return value
    if hasattr(raw, "speaker_diarization"):
        value = getattr(raw, "speaker_diarization")
        if value is not None:
            return value
    if isinstance(raw, dict):
        value = raw.get("speaker_diarization")
        if value is not None:
            return value
    return raw


def _iter_diarization_items(raw: Any) -> Iterable[tuple[Any, Any]]:
    if raw is None:
        return []
    if isinstance(raw, dict) and {"start", "end", "speaker"}.issubset(raw):
        return [(raw, raw.get("speaker"))]
    if hasattr(raw, "itertracks"):
        return raw.itertracks(yield_label=True)
    try:
        return iter(raw)
    except TypeError:
        return []


def _item_to_bounds_and_speaker(item: Any) -> tuple[float | None, float | None, Any]:
    if isinstance(item, dict):
        return item.get("start"), item.get("end"), item.get("speaker")

    if not isinstance(item, (tuple, list)):
        return None, None, None

    if len(item) == 2:
        turn, speaker = item
    elif len(item) >= 3:
        turn, speaker = item[0], item[2]
    else:
        return None, None, None

    return getattr(turn, "start", None), getattr(turn, "end", None), speaker


def normalize_diarization_output(raw: Any) -> list[dict[str, Any]]:
    """Normalize Pyannote outputs to [{start, end, speaker}]."""
    diarization = _pick_wrapped_output(raw)
    speaker_map: dict[str, str] = {}
    segments: list[dict[str, Any]] = []

    for item in _iter_diarization_items(diarization):
        start, end, speaker = _item_to_bounds_and_speaker(item)
        try:
            start_f = float(start)
            end_f = float(end)
        except (TypeError, ValueError):
            continue
        if end_f <= start_f or speaker in (None, ""):
            continue

        speaker_key = str(speaker)
        if speaker_key not in speaker_map:
            speaker_map[speaker_key] = f"SPEAKER_{len(speaker_map):02d}"
        segments.append({
            "start": start_f,
            "end": end_f,
            "speaker": speaker_map[speaker_key],
        })

    segments.sort(key=lambda seg: (seg["start"], seg["end"], seg["speaker"]))
    return segments
