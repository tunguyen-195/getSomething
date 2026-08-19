"""Reader-safe projection for preliminary investigation analysis payloads."""

from __future__ import annotations

import re
from typing import Any

from .investigation_preview import (
    coerce_public_preview_payload,
    sanitize_legacy_preview_text,
)


PUBLIC_ANALYSIS_SCHEMA_VERSION = "public-investigation-analysis-v1"
SIMPLE_ANALYSIS_SCHEMA_VERSION = "investigation-analysis-simple-v2"

_SAFE_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,80}$")
_SAFE_STATUS_CODE = re.compile(r"^[a-z][a-z0-9_:-]{1,80}$")

_PUBLIC_TASK_RESULT_FIELDS = frozenset(
    {
        "transcription",
        "summary",
        "segments",
        "duration",
        "confidence",
        "language",
        "processing_time",
        "formatted_transcript",
        "has_diarization",
        "num_speakers",
        "degraded",
        "diarization_status",
        "diarization_method_used",
        "diarization_method",
        "speed_factor",
        "transcription_time",
        "diarization_time",
        "caption",
        "model_name",
        "summary_model",
        "summary_type",
        "requested_engine",
        "engine_used",
        "audio_integrity_status",
        "audio_id",
        "download_url",
        "user_context_prompt",
        "summary_state",
    }
)


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _text(item)) is not None]


def _copy_fields(source: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for name in names:
        value = source.get(name)
        if isinstance(value, str):
            value = _text(value)
        if value is not None:
            projected[name] = value
    return projected


def _copy_numeric_fields(
    source: dict[str, Any], names: tuple[str, ...]
) -> dict[str, int | float]:
    return {
        name: value
        for name in names
        if isinstance((value := source.get(name)), (int, float))
        and not isinstance(value, bool)
    }


_SIMPLE_RECORD_FIELDS: dict[str, tuple[str, ...]] = {
    "key_points": ("text", "category", "speaker", "time"),
    "participants": ("name", "role", "description"),
    "events": (
        "description",
        "time",
        "described_time",
        "location",
        "described_location",
        "status",
    ),
    "actions": (
        "description",
        "kind",
        "actor",
        "target",
        "status",
        "deadline",
        "assignee",
        "reason",
        "priority",
    ),
    "entities": ("type", "value", "role"),
    "relationships": ("source", "target", "label", "status"),
    "contradictions": ("description",),
    "follow_ups": ("question", "reason", "priority"),
    "speaker_contributions": ("speaker",),
}


def _project_simple_records(field: str, value: Any) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for item in _records(value):
        row = _copy_fields(item, _SIMPLE_RECORD_FIELDS[field])
        if field == "events":
            participants = _string_list(item.get("participants"))
            if participants:
                row["participants"] = participants
        elif field == "contradictions":
            details = _string_list(item.get("items"))
            if details:
                row["items"] = details
        elif field == "speaker_contributions":
            row.update(
                _copy_numeric_fields(
                    item,
                    (
                        "word_count",
                        "segment_count",
                        "duration_seconds",
                        "word_share",
                    ),
                )
            )
        elif field == "entities":
            row.update(_copy_numeric_fields(item, ("count",)))
        if row:
            projected.append(row)
    return projected


def _project_facts(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _records(knowledge.get("facts")):
        row = _copy_fields(
            item,
            ("category", "statement", "status", "verification_status"),
        )
        if row.get("category") and row.get("statement"):
            rows.append(row)
    return rows


def _project_entities(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _records(knowledge.get("entities")):
        row = _copy_fields(
            item,
            ("entity_type", "value", "role", "verification_status"),
        )
        if row.get("entity_type") and row.get("value"):
            rows.append(row)
    return rows


def _project_events(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _records(knowledge.get("events")):
        row = _copy_fields(
            item,
            (
                "description",
                "status",
                "time_text",
                "location",
                "verification_status",
            ),
        )
        actors = _string_list(item.get("actors"))
        if actors:
            row["actors"] = actors
        if row.get("description"):
            rows.append(row)
    return rows


def _project_relationships(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _records(knowledge.get("relationships")):
        row = _copy_fields(
            item,
            (
                "source",
                "target",
                "label",
                "status",
                "verification_status",
            ),
        )
        if row.get("source") and row.get("target") and row.get("label"):
            rows.append(row)
    return rows


def _coverage_metrics(knowledge: dict[str, Any]) -> dict[str, int]:
    evidence = _records(knowledge.get("evidence_spans"))
    segment_indexes = {
        item.get("segment_index")
        for item in evidence
        if isinstance(item.get("segment_index"), int)
        and not isinstance(item.get("segment_index"), bool)
        and item.get("segment_index") >= 0
    }
    provenance = _record(knowledge.get("provenance"))
    total = provenance.get("transcript_segment_count")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        total = 0
    return {
        "covered_segment_count": len(segment_indexes),
        "total_segment_count": total,
    }


def _project_error(root: dict[str, Any]) -> dict[str, str] | None:
    code = _text(_record(root.get("error")).get("code"))
    if code is None or _SAFE_ERROR_CODE.fullmatch(code) is None:
        return None
    return {
        "code": code,
        "message": "Analysis could not be completed for this file.",
    }


def _public_segments(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _records(value):
        row = _copy_fields(item, ("text", "speaker"))
        row.update(_copy_numeric_fields(item, ("start", "end", "confidence")))
        if row:
            rows.append(row)
    return rows


def _public_summary_authority(value: Any) -> dict[str, Any] | None:
    source = _record(value)
    projected = _copy_fields(source, ("kind", "release_status"))
    if isinstance(source.get("world_facts_released"), bool):
        projected["world_facts_released"] = source["world_facts_released"]
    return projected or None


def _public_summary_signal(value: Any) -> dict[str, Any] | None:
    source = _record(value)
    code = _text(source.get("code"))
    if code is None or _SAFE_ERROR_CODE.fullmatch(code) is None:
        return None
    projected: dict[str, Any] = {"code": code}
    for name in ("retryable", "needs_review"):
        if isinstance(source.get(name), bool):
            projected[name] = source[name]
    return projected


def _public_safe_status(value: Any) -> str | None:
    text = _text(value)
    if text is None or _SAFE_STATUS_CODE.fullmatch(text) is None:
        return None
    lowered = text.casefold()
    if "exception" in lowered or "error" in lowered or "traceback" in lowered:
        return None
    return text


def public_context_analysis_payload(value: Any) -> dict[str, Any] | None:
    """Remove evidence, offsets, speakers, hashes, model metadata, and internal refs."""

    root = _record(value)
    if not root:
        return None

    if root.get("schema_version") == SIMPLE_ANALYSIS_SCHEMA_VERSION:
        projected: dict[str, Any] = {
            "schema_version": SIMPLE_ANALYSIS_SCHEMA_VERSION,
            "analysis_status": _text(root.get("analysis_status")) or "missing",
        }
        for field in ("analysis_text", "overview"):
            if text := _text(root.get(field)):
                projected[field] = text
        for field in (
            "key_points",
            "participants",
            "events",
            "actions",
            "entities",
            "relationships",
            "contradictions",
            "follow_ups",
            "speaker_contributions",
        ):
            projected[field] = _project_simple_records(field, root.get(field))
        projected["uncertainties"] = _string_list(root.get("uncertainties"))
        metrics = _record(root.get("metrics"))
        projected["metrics"] = {
            field: metrics[field]
            for field in (
                "transcript_word_count",
                "transcript_segment_count",
                "transcript_duration_seconds",
            )
            if isinstance(metrics.get(field), (int, float))
            and not isinstance(metrics.get(field), bool)
        }
        if error := _project_error(root):
            projected["error"] = error
        return projected

    if root.get("schema_version") == PUBLIC_ANALYSIS_SCHEMA_VERSION:
        knowledge = root
        analysis_status = _text(root.get("analysis_status")) or "success"
        metrics = _record(root.get("metrics"))
    else:
        knowledge = _record(root.get("investigation_knowledge"))
        if not knowledge:
            return None
        analysis_status = _text(root.get("analysis_status")) or "missing"
        metrics = _coverage_metrics(knowledge)

    projected = {
        "schema_version": PUBLIC_ANALYSIS_SCHEMA_VERSION,
        "analysis_status": analysis_status,
        "facts": _project_facts(knowledge),
        "entities": _project_entities(knowledge),
        "events": _project_events(knowledge),
        "relationships": _project_relationships(knowledge),
        "metrics": {
            "covered_segment_count": int(metrics.get("covered_segment_count") or 0),
            "total_segment_count": int(metrics.get("total_segment_count") or 0),
        },
    }
    error = _project_error(root)
    if error is not None:
        projected["error"] = error
    return projected


def public_task_result_payload(value: Any) -> dict[str, Any]:
    """Return only reader-facing task fields and active visualization data."""

    root = _record(value)
    projected = {
        key: item
        for key, item in root.items()
        if key in _PUBLIC_TASK_RESULT_FIELDS
    }
    projected["summary"] = sanitize_legacy_preview_text(projected.get("summary")) or None
    projected["segments"] = _public_segments(projected.get("segments"))
    if "context_analysis" in root:
        projected["context_analysis"] = public_context_analysis_payload(
            root.get("context_analysis")
        )
    if authority := _public_summary_authority(root.get("summary_authority")):
        projected["summary_authority"] = authority
    if notice := _public_summary_signal(root.get("summary_notice")):
        projected["summary_notice"] = notice
    if error := _public_summary_signal(root.get("summary_error")):
        projected["summary_error"] = error
    projected["summary_preview"] = coerce_public_preview_payload(
        root.get("summary_preview")
    )
    if fallback_reason := _public_safe_status(root.get("fallback_reason")):
        projected["fallback_reason"] = fallback_reason

    # The extractor binds visualization to the current released run, while the
    # release object itself remains internal.
    from src.services.task_service import extract_active_visualization_payload

    visualization = extract_active_visualization_payload(root)
    projected["visualization_data"] = visualization
    projected["has_visualization"] = bool(visualization)
    return projected


def public_task_payload(value: Any) -> dict[str, Any]:
    """Project both nested and compatibility-flattened task result fields."""

    root = _record(value)
    result = public_task_result_payload(root.get("result"))
    projected = {
        key: item
        for key, item in root.items()
        if key in {"id", "filename", "status", "created_at", "updated_at", "case_id"}
    }
    if root.get("error"):
        projected["error"] = "Task processing failed."
    else:
        projected["error"] = None
    projected["result"] = result
    if projected.get("status") == "visualized" and not result.get(
        "has_visualization"
    ):
        projected["status"] = (
            "summarized"
            if result.get("summary")
            else "transcribed"
            if result.get("transcription")
            else "uploaded"
        )
    if "context_analysis" in root or "context_analysis" in result:
        projected["context_analysis"] = result.get("context_analysis")
    return projected


__all__ = [
    "PUBLIC_ANALYSIS_SCHEMA_VERSION",
    "public_context_analysis_payload",
    "public_task_payload",
    "public_task_result_payload",
]
