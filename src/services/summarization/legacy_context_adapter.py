"""Versioned adapter for persisted context created before the strict schema."""

from __future__ import annotations

import copy
import re
from typing import Any

from .models.context_analysis import CONTEXT_PROMPT_VERSION, ContextAnalysisPayload


LEGACY_CONTEXT_ADAPTER_VERSION = "legacy-context-v1"


class LegacyContextAdapterError(ValueError):
    """Raised when legacy data cannot be upgraded without inventing evidence."""


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _exact_transcript_quote(value: Any, transcript: str) -> str:
    candidate = _normalize_text(str(value or ""))
    normalized_transcript = _normalize_text(transcript)
    if not candidate:
        raise LegacyContextAdapterError("legacy evidence candidate is empty")
    start = normalized_transcript.casefold().find(candidate.casefold())
    if start == -1:
        raise LegacyContextAdapterError(
            "legacy value cannot be upgraded because it is absent from transcript"
        )
    return normalized_transcript[start : start + len(candidate)]


def _upgrade_evidence_item(
    item: Any,
    *,
    transcript: str,
    text_key: str,
) -> dict[str, Any]:
    if isinstance(item, str):
        quote = _exact_transcript_quote(item, transcript)
        return {text_key: item, "evidence_quote": quote}
    if not isinstance(item, dict):
        raise LegacyContextAdapterError("legacy evidence item must be text or object")

    upgraded = copy.deepcopy(item)
    if not upgraded.get("evidence_quote"):
        upgraded["evidence_quote"] = _exact_transcript_quote(
            upgraded.get(text_key),
            transcript,
        )
    return upgraded


def adapt_legacy_context_analysis(
    value: dict[str, Any],
    *,
    transcript: str,
) -> dict[str, Any]:
    """Upgrade persisted legacy data only when transcript evidence is exact."""

    if not isinstance(value, dict):
        raise LegacyContextAdapterError("legacy context must be an object")

    upgraded = copy.deepcopy(value)
    upgraded["key_points"] = [
        _upgrade_evidence_item(item, transcript=transcript, text_key="statement")
        for item in upgraded.get("key_points", [])
    ]

    entities = upgraded.get("entities")
    if not isinstance(entities, dict):
        entities = {}
    if "contact" in entities:
        if "contact_info" in entities:
            raise LegacyContextAdapterError(
                "legacy entities cannot contain both contact and contact_info"
            )
        entities["contact_info"] = entities.pop("contact")

    for group_name in ("people", "locations", "time", "organizations"):
        rows = entities.get(group_name, [])
        upgraded_rows = []
        for item in rows:
            if isinstance(item, str):
                quote = _exact_transcript_quote(item, transcript)
                upgraded_rows.append({"value": item, "evidence_quote": quote})
                continue
            if not isinstance(item, dict):
                raise LegacyContextAdapterError(
                    f"legacy entity group {group_name!r} contains a non-object"
                )
            row = copy.deepcopy(item)
            if not row.get("evidence_quote"):
                candidate = next(
                    (
                        row.get(key)
                        for key in ("name", "value", "account_number", "address")
                        if row.get(key)
                    ),
                    None,
                )
                row["evidence_quote"] = _exact_transcript_quote(
                    candidate,
                    transcript,
                )
            upgraded_rows.append(row)
        entities[group_name] = upgraded_rows

    contact_info = entities.get("contact_info")
    if contact_info is not None:
        if not isinstance(contact_info, dict):
            raise LegacyContextAdapterError("legacy contact_info must be an object")
        for group_name in ("phones", "emails", "ids", "bank_accounts", "addresses"):
            rows = contact_info.get(group_name, [])
            if not isinstance(rows, list):
                rows = [rows] if rows else []
            upgraded_rows = []
            for item in rows:
                if isinstance(item, str):
                    quote = _exact_transcript_quote(item, transcript)
                    upgraded_rows.append({"value": item, "evidence_quote": quote})
                    continue
                if not isinstance(item, dict):
                    raise LegacyContextAdapterError(
                        f"legacy contact group {group_name!r} contains a non-object"
                    )
                row = copy.deepcopy(item)
                if not row.get("evidence_quote"):
                    candidate = next(
                        (
                            row.get(key)
                            for key in ("name", "value", "account_number", "address")
                            if row.get(key)
                        ),
                        None,
                    )
                    row["evidence_quote"] = _exact_transcript_quote(
                        candidate,
                        transcript,
                    )
                upgraded_rows.append(row)
            contact_info[group_name] = upgraded_rows
        entities["contact_info"] = contact_info
    upgraded["entities"] = entities

    risk_assessment = upgraded.get("risk_assessment")
    if not isinstance(risk_assessment, dict):
        risk_assessment = {}
    risk_assessment["overall_risk"] = "unverified"
    risk_assessment.setdefault("crime_indicators", [])
    risk_assessment.setdefault("recommended_actions", [])
    upgraded["risk_assessment"] = risk_assessment

    if not upgraded.get("summary_sentences"):
        sentence_rows = []
        for index, point in enumerate(upgraded["key_points"], start=1):
            sentence_rows.append(
                {
                    "draft_id": f"legacy-summary-{index}",
                    "text": point["statement"],
                    "sentence_role": "overview" if index == 1 else "event",
                    "evidence_quotes": [point["evidence_quote"]],
                }
            )
        if not sentence_rows:
            summary = str(upgraded.get("summary") or "").strip()
            quote = _exact_transcript_quote(summary, transcript)
            sentence_rows.append(
                {
                    "draft_id": "legacy-summary-1",
                    "text": summary,
                    "sentence_role": "overview",
                    "evidence_quotes": [quote],
                }
            )
        upgraded["summary_sentences"] = sentence_rows

    upgraded["summary"] = " ".join(
        str(item["text"]).strip() for item in upgraded["summary_sentences"]
    )
    upgraded.setdefault("analysis_status", "success")
    upgraded["prompt_version"] = CONTEXT_PROMPT_VERSION
    upgraded.setdefault("model_generated", True)
    upgraded.setdefault("requires_human_verification", True)

    return ContextAnalysisPayload.model_validate(upgraded).model_dump(
        mode="json",
        exclude_none=True,
    )


def project_legacy_key_points(context: dict[str, Any] | None) -> list[str]:
    """Project strict key-point objects for older string-list consumers."""

    if not isinstance(context, dict):
        return []
    rows = context.get("key_points")
    if not isinstance(rows, list):
        return []
    projected = []
    for item in rows:
        if isinstance(item, str) and item.strip():
            projected.append(item.strip())
        elif isinstance(item, dict) and str(item.get("statement") or "").strip():
            projected.append(str(item["statement"]).strip())
    return projected
