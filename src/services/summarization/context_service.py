"""Single-prompt conversation analysis service."""
import json
import logging
from typing import Any, Dict, Optional

from .deterministic_analysis import build_deterministic_transcript_analysis
from .legacy_context_adapter import project_legacy_key_points
from .models.investigation_knowledge import (
    GroundedContextAnalysisPayload,
    build_grounded_context_analysis,
)
from .models.llm_manager import get_llm_manager
from .investigation_scenarios import (
    DEFAULT_INVESTIGATION_SCENARIO,
    InvestigationScenario,
    resolve_investigation_scenario,
)

logger = logging.getLogger(__name__)


_FALLBACK_MODEL_ID = "deterministic-transcript-fallback-v3"
_STALE_FALLBACK_MODEL_IDS = {
    "deterministic-transcript-fallback-v1",
    "deterministic-transcript-fallback-v2",
}


def _deduplicate_records(*collections: object) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for collection in collections:
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def _merge_entity_groups(
    deterministic: object,
    model_value: object,
) -> dict[str, Any]:
    base = deterministic if isinstance(deterministic, dict) else {}
    model = model_value if isinstance(model_value, dict) else {}
    merged: dict[str, Any] = {}
    for field in ("people", "locations", "time", "organizations"):
        merged[field] = _deduplicate_records(base.get(field), model.get(field))

    base_contact = base.get("contact_info")
    model_contact = model.get("contact_info")
    base_contact = base_contact if isinstance(base_contact, dict) else {}
    model_contact = model_contact if isinstance(model_contact, dict) else {}
    contact = {
        field: _deduplicate_records(base_contact.get(field), model_contact.get(field))
        for field in ("phones", "emails", "ids", "bank_accounts", "addresses")
    }
    merged["contact_info"] = contact if any(contact.values()) else None
    return merged


def augment_grounded_context_with_deterministic_inventory(
    context: Dict,
    transcript: str,
    segments: list[dict] | None = None,
    source_metadata: dict | None = None,
    investigation_scenario: InvestigationScenario = DEFAULT_INVESTIGATION_SCENARIO,
) -> Dict:
    """Use a full-source deterministic inventory as the narrative writer backbone."""

    grounded = GroundedContextAnalysisPayload.model_validate(context)
    provenance = grounded.investigation_knowledge.provenance
    metadata = dict(source_metadata or {})
    if provenance.source_task_id is not None:
        metadata.setdefault("task_id", provenance.source_task_id)
    if provenance.source_audio_id is not None:
        metadata.setdefault("audio_id", provenance.source_audio_id)
    if provenance.audio_sha256 is not None:
        metadata.setdefault("audio_sha256", provenance.audio_sha256)
    if provenance.audio_integrity_status is not None:
        metadata.setdefault(
            "audio_integrity_status",
            provenance.audio_integrity_status,
        )
    deterministic = build_deterministic_transcript_analysis(
        transcript,
        segments,
        metadata,
    )
    if deterministic is None:
        return grounded.model_dump(mode="json", exclude_none=True)

    expected_source_units = len(deterministic["summary_sentences"])
    current_source_ids = {
        item.draft_id
        for item in grounded.summary_sentences
        if item.draft_id.startswith("deterministic-source-")
    }
    if len(current_source_ids) == expected_source_units:
        return grounded.model_dump(mode="json", exclude_none=True)

    model_payload = grounded.model_dump(mode="json", exclude_none=True)
    merged = dict(deterministic)
    merged["scenario_profile"] = resolve_investigation_scenario(
        investigation_scenario,
        transcript,
    )
    merged["entities"] = _merge_entity_groups(
        deterministic.get("entities"),
        model_payload.get("entities"),
    )
    for field in (
        "key_points",
        "topics",
        "facts",
        "events",
        "relationships",
        "actions",
        "decisions",
        "contradictions",
        "open_questions",
    ):
        merged[field] = _deduplicate_records(
            deterministic.get(field),
            model_payload.get(field),
        )

    return build_grounded_context_analysis(
        merged,
        transcript,
        segments,
        model_id=provenance.model_id,
        source_metadata=metadata,
        high_risk_enabled=False,
        generated_at=provenance.generated_at,
    )


def is_stale_deterministic_fallback(context: object) -> bool:
    """Return true only for known incomplete deterministic fallback versions."""

    if not isinstance(context, dict):
        return False
    knowledge = context.get("investigation_knowledge")
    if not isinstance(knowledge, dict):
        return False
    provenance = knowledge.get("provenance")
    if not isinstance(provenance, dict):
        return False
    return provenance.get("model_id") in _STALE_FALLBACK_MODEL_IDS


def build_transcript_grounded_fallback(
    transcript: str,
    segments: list[dict] | None = None,
    source_metadata: dict | None = None,
    investigation_scenario: InvestigationScenario = DEFAULT_INVESTIGATION_SCENARIO,
) -> Optional[Dict]:
    """Build a source-only analysis when model output cannot pass grounding."""

    if not transcript or not transcript.strip():
        return None

    raw_analysis = build_deterministic_transcript_analysis(
        transcript,
        segments,
        source_metadata,
    )
    if raw_analysis is None:
        return None
    raw_analysis["scenario_profile"] = resolve_investigation_scenario(
        investigation_scenario,
        transcript,
    )
    return build_grounded_context_analysis(
        raw_analysis,
        transcript,
        segments,
        model_id=_FALLBACK_MODEL_ID,
        source_metadata=source_metadata,
        high_risk_enabled=False,
    )


def analyze_conversation_context(
    transcript: str,
    model_name: str = None,
    user_prompt: str = None,
    segments: list[dict] | None = None,
    source_metadata: dict | None = None,
    investigation_scenario: InvestigationScenario = DEFAULT_INVESTIGATION_SCENARIO,
) -> Optional[Dict]:
    """Analyze the complete transcript once and return the tolerant v2 payload."""
    if not transcript or not transcript.strip():
        from .models.context_analysis import simple_analysis_failure

        return simple_analysis_failure(
            "EMPTY_TRANSCRIPT",
            "Không có nội dung hội thoại để phân tích.",
        )

    try:
        llm_mgr = get_llm_manager()

        if not llm_mgr.check_availability():
            from .models.context_analysis import simple_analysis_failure

            logger.warning("[CONTEXT_SERVICE] LLM unavailable")
            return simple_analysis_failure(
                "LLM_UNAVAILABLE",
                "Dịch vụ mô hình phân tích hiện không khả dụng.",
            )

        logger.info(f"[CONTEXT_SERVICE] Analyzing context | model={model_name or 'auto'}")

        result = llm_mgr.analyze_context(
            transcript,
            model=model_name,
            additional_instructions=user_prompt,
            segments=segments,
            source_metadata=source_metadata,
            investigation_scenario=investigation_scenario,
        )

        if isinstance(result, dict) and result.get("analysis_status") in {
            "success",
            "partial",
        }:
            logger.info("[CONTEXT_SERVICE] Context analysis complete")
            return result

        return result

    except Exception as exc:
        logger.error(
            "[CONTEXT_SERVICE] Analysis failed | error_type=%s",
            type(exc).__name__,
        )
        from .models.context_analysis import simple_analysis_failure

        return simple_analysis_failure(
            "ANALYSIS_SERVICE_FAILED",
            "Không thể hoàn tất phân tích hội thoại.",
        )


def extract_entities(context: Dict) -> Dict:
    """
    Extract entities from context analysis

    Args:
        context: Context analysis dict

    Returns:
        Entities dict with people, locations, time, etc.
    """
    if not context:
        return {"people": [], "locations": [], "time": [], "organizations": []}

    entities = context.get("entities", {})
    if isinstance(entities, list):
        grouped = {
            "people": [],
            "locations": [],
            "time": [],
            "organizations": [],
            "contact_info": [],
        }
        aliases = {
            "person": "people",
            "people": "people",
            "location": "locations",
            "place": "locations",
            "time": "time",
            "date": "time",
            "organization": "organizations",
            "organisation": "organizations",
        }
        for item in entities:
            if not isinstance(item, dict):
                continue
            category = aliases.get(str(item.get("type") or "").strip().casefold())
            if category:
                grouped[category].append(item)
            else:
                grouped["contact_info"].append(item)
        return grouped

    return {
        "people": entities.get("people", []),
        "locations": entities.get("locations", []),
        "time": entities.get("time", []),
        "organizations": entities.get("organizations", []),
        "contact_info": entities.get("contact_info", [])
    }


def extract_relationships(context: Dict) -> list:
    """
    Extract relationships from context analysis

    Args:
        context: Context analysis dict

    Returns:
        List of relationships
    """
    if not context:
        return []

    return context.get("relationships", [])


def extract_key_points(context: Dict) -> list:
    """
    Extract key points from context analysis

    Args:
        context: Context analysis dict

    Returns:
        List of key points
    """
    if not context:
        return []

    return project_legacy_key_points(context)
