from __future__ import annotations

import json
from typing import Any

from .schemas import SegmentUnit, sha256_text, stable_id


def _result_dict(task: dict[str, Any]) -> dict[str, Any]:
    result = task.get("result") or {}
    if isinstance(result, str):
        try:
            return json.loads(result)
        except Exception:
            return {}
    return result if isinstance(result, dict) else {}


def transcript_from_task(task: dict[str, Any]) -> str:
    result = _result_dict(task)
    return (
        result.get("transcription")
        or result.get("transcript")
        or result.get("text")
        or task.get("transcript")
        or ""
    )


def build_segments(task: dict[str, Any]) -> list[SegmentUnit]:
    result = _result_dict(task)
    transcript = transcript_from_task(task)
    audio_id = result.get("audio_id")
    raw_segments = result.get("segments")
    segments: list[SegmentUnit] = []

    if isinstance(raw_segments, list):
        for index, raw in enumerate(raw_segments):
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or raw.get("transcription") or "").strip()
            if not text:
                continue
            start = raw.get("start")
            end = raw.get("end")
            has_time = isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start
            source_kind = "transcript_segment" if has_time and audio_id is not None else "transcript_text"
            segment_id = str(raw.get("id") or raw.get("segment_id") or stable_id("seg", index, text[:80], start, end))
            segments.append(
                SegmentUnit(
                    id=segment_id,
                    source_kind=source_kind,
                    text=text,
                    source_text_sha256=sha256_text(text),
                    audio_id=audio_id,
                    start_time=float(start) if has_time else None,
                    end_time=float(end) if has_time else None,
                    speaker_id=str(raw.get("speaker") or raw.get("speaker_id") or "") or None,
                    words=raw.get("words") if isinstance(raw.get("words"), list) else [],
                )
            )

    if segments:
        return segments

    text = transcript.strip()
    if not text:
        return []
    return [
        SegmentUnit(
            id=stable_id("seg", "transcript_text", text[:120]),
            source_kind="transcript_text",
            text=text,
            source_text_sha256=sha256_text(text),
            audio_id=audio_id,
        )
    ]
