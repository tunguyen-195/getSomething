"""File-scoped diarization provenance helpers.

Speaker labels emitted by Pyannote are intentionally local to one audio
source.  A case can contain several files, so using ``SPEAKER_00`` as a
case-wide key would incorrectly merge unrelated speakers.  This module keeps
the familiar local label while exposing a stable, file-scoped key for any
cross-file projection.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DIARIZATION_PROVENANCE_SCHEMA_VERSION = "diarization-file-scope-v1"
FILE_PROVENANCE_SCHEMA_VERSION = "audio-file-provenance-v1"


def _identifier(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, str)):
        text = str(value).strip()
        if text:
            return text
    return None


def file_scope_id(*, audio_id: object = None, task_id: object = None) -> str:
    """Return a deterministic scope id, preferring the immutable audio row id."""

    audio = _identifier(audio_id)
    if audio is not None:
        return f"audio:{audio}"
    task = _identifier(task_id)
    if task is not None:
        return f"task:{task}"
    return "file:unknown"


def scoped_speaker_key(scope_id: str, speaker_label: object) -> str | None:
    """Build a stable cross-file key without changing the local label."""

    label = _identifier(speaker_label)
    if label is None:
        return None
    return f"{scope_id}:speaker:{label}"


def build_file_provenance(
    *,
    task_id: object,
    audio_id: object,
    case_id: object,
    filename: object,
    batch_id: object = None,
    batch_item_id: object = None,
    position: object = None,
) -> dict[str, Any]:
    """Return JSON-safe immutable source identity for one audio task."""

    scope_id = file_scope_id(audio_id=audio_id, task_id=task_id)
    result: dict[str, Any] = {
        "schema_version": FILE_PROVENANCE_SCHEMA_VERSION,
        "scope": "file",
        "scope_id": scope_id,
        "task_id": _identifier(task_id),
        "audio_id": audio_id if isinstance(audio_id, int) else _identifier(audio_id),
        "case_id": case_id if isinstance(case_id, int) else _identifier(case_id),
        "filename": _identifier(filename),
    }
    for key, value in (
        ("batch_id", batch_id),
        ("batch_item_id", batch_item_id),
        ("position", position),
    ):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                continue
            result[key] = value if isinstance(value, int) else str(value).strip()
    return result


def annotate_segments_with_file_scope(
    segments: object,
    *,
    task_id: object,
    audio_id: object,
    case_id: object,
    filename: object,
    batch_id: object = None,
    batch_item_id: object = None,
    position: object = None,
) -> list[dict[str, Any]]:
    """Attach source and speaker scope to each segment.

    The input list is copied.  ``speaker`` remains the local diarizer label;
    ``speaker_key`` is the only value consumers should use when combining
    multiple files.
    """

    scope_id = file_scope_id(audio_id=audio_id, task_id=task_id)
    source_task_id = _identifier(task_id)
    source_audio_id = audio_id if isinstance(audio_id, int) else _identifier(audio_id)
    source_case_id = case_id if isinstance(case_id, int) else _identifier(case_id)
    source_filename = _identifier(filename)
    annotated: list[dict[str, Any]] = []
    if not isinstance(segments, list):
        return annotated
    for raw in segments:
        if not isinstance(raw, dict):
            continue
        segment = deepcopy(raw)
        speaker = segment.get("speaker") or segment.get("speaker_id")
        if speaker is not None:
            # Keep both aliases in sync for older analysis adapters.
            label = _identifier(speaker)
            if label is not None:
                segment["speaker"] = label
                segment["speaker_id"] = label
                segment["speaker_scope_id"] = scope_id
                segment["speaker_key"] = scoped_speaker_key(scope_id, label)
        segment["source_task_id"] = source_task_id
        segment["source_audio_id"] = source_audio_id
        segment["source_case_id"] = source_case_id
        segment["source_filename"] = source_filename
        segment["source_scope"] = "file"
        for key, value in (
            ("source_batch_id", batch_id),
            ("source_batch_item_id", batch_item_id),
            ("source_position", position),
        ):
            if value is not None and not isinstance(value, bool):
                if isinstance(value, (int, str)):
                    segment[key] = value
        annotated.append(segment)
    return annotated


def build_diarization_provenance(
    *,
    segments: object,
    task_id: object,
    audio_id: object,
    case_id: object,
    filename: object,
    speaker_count: object = None,
    status: object = None,
    method: object = None,
    batch_id: object = None,
    batch_item_id: object = None,
    position: object = None,
) -> dict[str, Any]:
    """Build a compact top-level per-file diarization projection."""

    scope_id = file_scope_id(audio_id=audio_id, task_id=task_id)
    rows = annotate_segments_with_file_scope(
        segments,
        task_id=task_id,
        audio_id=audio_id,
        case_id=case_id,
        filename=filename,
        batch_id=batch_id,
        batch_item_id=batch_item_id,
        position=position,
    )
    labels = sorted(
        {
            str(item.get("speaker"))
            for item in rows
            if item.get("speaker") is not None and str(item.get("speaker")).strip()
        }
    )
    speakers = [
        {"speaker_id": label, "speaker_key": scoped_speaker_key(scope_id, label)}
        for label in labels
    ]
    result: dict[str, Any] = {
        "schema_version": DIARIZATION_PROVENANCE_SCHEMA_VERSION,
        "scope": "file",
        "scope_id": scope_id,
        "source": build_file_provenance(
            task_id=task_id,
            audio_id=audio_id,
            case_id=case_id,
            filename=filename,
            batch_id=batch_id,
            batch_item_id=batch_item_id,
            position=position,
        ),
        "speaker_count": speaker_count if isinstance(speaker_count, int) else None,
        "speaker_ids": labels,
        "speakers": speakers,
        "segments": rows,
    }
    if isinstance(status, str) and status.strip():
        result["status"] = status.strip()
    if isinstance(method, str) and method.strip():
        result["method"] = method.strip()
    if batch_id is not None or batch_item_id is not None or position is not None:
        result["batch"] = {
            key: value
            for key, value in (
                ("batch_id", batch_id),
                ("batch_item_id", batch_item_id),
                ("position", position),
            )
            if value is not None and not isinstance(value, bool)
        }
    return result


__all__ = [
    "DIARIZATION_PROVENANCE_SCHEMA_VERSION",
    "FILE_PROVENANCE_SCHEMA_VERSION",
    "annotate_segments_with_file_scope",
    "build_diarization_provenance",
    "build_file_provenance",
    "file_scope_id",
    "scoped_speaker_key",
]
