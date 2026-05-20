from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from src.core.config import settings
from src.services.task_service import get_task

from .extractor import CORE_EXTRACTOR_VERSION, extract_core_analysis
from .event_synthesizer import synthesize_events
from .insight_engine import generate_insights
from .schemas import AnalysisGraphV2, EvidenceRef, EntityItem, SegmentUnit, sha256_text, stable_id
from .segment_builder import build_segments, transcript_from_task
from .slot_filler import fill_slots_from_templates


def _model_info(source_method: str = "deterministic_regex", llm_status: str | None = None) -> dict[str, Any]:
    llm_enabled = bool(getattr(settings, "ANALYSIS_INTELLIGENCE_LLM_ENABLED", False))
    return {
        "engine": "analysis_intelligence",
        "version": "v2",
        "source_method": source_method,
        "llm_enabled": llm_enabled,
        "llm_status": llm_status or ("disabled" if not llm_enabled else "not_implemented_for_v2_extraction"),
    }


def apply_review_preservation(graph: AnalysisGraphV2, previous: dict[str, Any] | None) -> AnalysisGraphV2:
    if not isinstance(previous, dict) or previous.get("schema_version") != graph.schema_version:
        return graph
    previous_items: dict[str, dict[str, Any]] = {}
    item_keys = (
        "entities",
        "relations",
        "events",
        "claims",
        "facts",
        "risk_flags",
        "slots",
        "domain_frames",
        "insight_items",
    )
    for key in item_keys:
        for item in previous.get(key, []) or []:
            if isinstance(item, dict) and item.get("id"):
                previous_items[item["id"]] = item

    changed = graph.to_storage_dict()
    for key in item_keys:
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
                    "source_fact_ids",
                    "supporting_item_ids",
                    "domain_frame_id",
                    "template_slot_name",
                ):
                    if field in previous_item:
                        item[field] = previous_item[field]
    changed["graph_revision"] = int(previous.get("graph_revision") or graph.graph_revision)
    return AnalysisGraphV2(**changed)


def generate_task_graph(
    task_id: str,
    visualization_type: str = "all",
    analysis_mode: str = "general",
    domain_template_ids: list[int] | None = None,
    template_version_refs: list[dict[str, Any]] | None = None,
    analysis_templates: list[dict[str, Any]] | None = None,
) -> AnalysisGraphV2:
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
    core = extract_core_analysis(segments)
    events = synthesize_events(core.facts, core.entities)
    slot_result = fill_slots_from_templates(core.facts, analysis_templates)
    insight_items = generate_insights(events, core.risk_flags, slot_result.insight_items)
    previous = result.get("visualization_data") if isinstance(result, dict) else None
    warnings: list[str] = []
    normalized_mode = analysis_mode if analysis_mode in {"general", "selected"} else "general"
    if analysis_mode not in {"general", "selected"}:
        warnings.append("analysis_mode không hợp lệ, đã fallback về general")
    selected_template_ids = (domain_template_ids or []) if normalized_mode == "selected" else []
    template_refs = (template_version_refs or []) if normalized_mode == "selected" else []
    if normalized_mode == "selected" and not selected_template_ids:
        warnings.append("Chưa chọn mẫu phân tích; kết quả chỉ gồm phân tích tổng quát deterministic.")
    if selected_template_ids and not getattr(settings, "ANALYSIS_INTELLIGENCE_LLM_ENABLED", False):
        warnings.append("LLM analysis đang tắt; mẫu phân tích được ghi nhận nhưng chưa chạy slot extraction LLM.")
    if selected_template_ids and getattr(settings, "ANALYSIS_INTELLIGENCE_LLM_ENABLED", False):
        warnings.append("LLM provider đã cấu hình nhưng V2 slot extraction LLM chưa được bật trong build này; kết quả vẫn là deterministic.")
    asr_reliability = result.get("asr_reliability") if isinstance(result, dict) else None
    if isinstance(asr_reliability, dict) and asr_reliability.get("review_required"):
        warnings.append("Transcript có cảnh báo chất lượng ASR; các fact/entity từ analysis cần review thủ công.")
    source_warnings = result.get("warnings") if isinstance(result, dict) else None
    if isinstance(source_warnings, list):
        for warning in source_warnings:
            warning_text = str(warning)
            if warning_text.startswith(("detected_language_unexpected", "asr_guard_removed_segments")):
                warnings.append(f"ASR warning: {warning_text}")

    graph = AnalysisGraphV2(
        task_id=task_id,
        audio_id=result.get("audio_id") if isinstance(result, dict) else None,
        source_file=task.get("filename"),
        model_info=_model_info(),
        analysis_mode=normalized_mode,  # type: ignore[arg-type]
        extractor_versions={"core": CORE_EXTRACTOR_VERSION},
        selected_template_ids=selected_template_ids,
        template_version_refs=template_refs,
        warnings=warnings,
        segments=segments,
        entities=core.entities,
        relations=[],
        events=events,
        claims=[],
        facts=core.facts,
        risk_flags=core.risk_flags,
        slots=slot_result.slots,
        domain_frames=slot_result.domain_frames,
        insight_items=insight_items,
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
    core = extract_core_analysis([segment])
    entities = core.entities
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
    for item in [*core.facts, *core.risk_flags]:
        item.source_method = source_method
        item.requires_review = True
        if item.review_status == "machine_suggested":
            item.review_status = "needs_review"
        for ref in item.evidence_refs:
            ref.source_kind = source_kind  # type: ignore[assignment]
            ref.audio_id = None
            ref.segment_id = None
            ref.start_time = None
            ref.end_time = None
            ref.speaker_id = None
    events = synthesize_events(core.facts, entities)
    for event in events:
        event.source_method = source_method
        event.requires_review = True
        if event.review_status == "machine_suggested":
            event.review_status = "needs_review"
        for ref in event.evidence_refs:
            ref.source_kind = source_kind  # type: ignore[assignment]
            ref.audio_id = None
            ref.segment_id = None
            ref.start_time = None
            ref.end_time = None
            ref.speaker_id = None
    insight_items = generate_insights(events, core.risk_flags)
    return AnalysisGraphV2(
        model_info=_model_info(source_method=source_method),
        segments=[segment],
        entities=entities,
        relations=[],
        events=events,
        claims=[],
        facts=core.facts,
        risk_flags=core.risk_flags,
        insight_items=insight_items,
    )
