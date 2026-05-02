from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from src.core.config import settings
from src.services.task_service import get_task

from .extractor import extract_entities
from .schemas import AnalysisGraphV2, EvidenceRef, EntityItem, SegmentUnit, sha256_text, stable_id
from .segment_builder import build_segments, transcript_from_task


def _model_info(source_method: str = "regex") -> dict[str, Any]:
    return {
        "engine": "analysis_intelligence",
        "version": "v2",
        "source_method": source_method,
        "llm_enabled": bool(getattr(settings, "ANALYSIS_INTELLIGENCE_LLM_ENABLED", False)),
    }


def apply_review_preservation(graph: AnalysisGraphV2, previous: dict[str, Any] | None) -> AnalysisGraphV2:
    if not isinstance(previous, dict) or previous.get("schema_version") != graph.schema_version:
        return graph
    previous_items: dict[str, dict[str, Any]] = {}
    for key in ("entities", "relations", "events", "claims"):
        for item in previous.get(key, []) or []:
            if isinstance(item, dict) and item.get("id"):
                previous_items[item["id"]] = item

    changed = graph.to_storage_dict()
    for key in ("entities", "relations", "events", "claims"):
        for item in changed.get(key, []) or []:
            previous_item = previous_items.get(item.get("id"))
            if not previous_item:
                continue
            if previous_item.get("review_status") in {"confirmed", "rejected"}:
                for field in (
                    "review_status",
                    "reviewed_by",
                    "reviewed_at",
                    "review_note",
                    "original_label",
                    "original_type",
                    "source_item_ids",
                ):
                    if field in previous_item:
                        item[field] = previous_item[field]
    changed["graph_revision"] = int(previous.get("graph_revision") or graph.graph_revision)
    return AnalysisGraphV2(**changed)


def generate_task_graph(task_id: str, visualization_type: str = "all") -> AnalysisGraphV2:
    if not getattr(settings, "ANALYSIS_INTELLIGENCE_V2_ENABLED", True):
        raise HTTPException(status_code=503, detail="Analysis intelligence V2 is disabled")

    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    transcript = transcript_from_task(task)
    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="Task must be transcribed first. Please run transcription before visualization.",
        )
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    segments = build_segments(task)
    entities = extract_entities(segments)
    previous = result.get("visualization_data") if isinstance(result, dict) else None
    graph = AnalysisGraphV2(
        task_id=task_id,
        audio_id=result.get("audio_id") if isinstance(result, dict) else None,
        source_file=task.get("filename"),
        model_info=_model_info(),
        segments=segments,
        entities=entities,
        relations=[],
        events=[],
        claims=[],
    )
    return apply_review_preservation(graph, previous)


def generate_text_graph(
    text: str,
    source_kind: str = "summary_text",
    source_method: str = "legacy_summary_derived",
) -> AnalysisGraphV2:
    clean_text = (text or "").strip()
    if not clean_text:
        return AnalysisGraphV2(model_info=_model_info(source_method=source_method))
    segment = SegmentUnit(
        id=stable_id("seg", source_kind, clean_text[:120]),
        source_kind=source_kind,  # type: ignore[arg-type]
        text=clean_text,
        source_text_sha256=sha256_text(clean_text),
    )
    entities = extract_entities([segment])
    for entity in entities:
        entity.source_method = source_method
        entity.requires_review = True
        if entity.review_status == "machine_suggested":
            entity.review_status = "needs_review"
        for ref in entity.evidence_refs:
            ref.source_kind = source_kind  # type: ignore[assignment]
            ref.audio_id = None
            ref.segment_id = None
            ref.start_time = None
            ref.end_time = None
            ref.speaker_id = None
    return AnalysisGraphV2(
        model_info=_model_info(source_method=source_method),
        segments=[segment],
        entities=entities,
        relations=[],
        events=[],
        claims=[],
    )
