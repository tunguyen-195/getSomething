from __future__ import annotations

import re
from collections import OrderedDict
from typing import Iterable

from .schemas import EntityItem, EvidenceRef, SegmentUnit, sha256_text, stable_id


PHONE_RE = re.compile(r"(?<!\d)(\+?84\d{8,10}|0\d{8,10})(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
MONEY_RE = re.compile(r"(?i)\b(\d+(?:[.,]\d+)?\s*(?:triệu|trieu|tỷ|ty|nghìn|nghin|k|đ|vnd|vnđ|usd))\b")
TIME_RE = re.compile(
    r"(?i)\b(\d{1,2}[:h]\d{2}|\d{1,2}\s*giờ(?:\s*\d{1,2}\s*phút)?|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\b"
)


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("84"):
        return "0" + digits[2:]
    return digits


def _evidence(segment: SegmentUnit, match: re.Match[str]) -> EvidenceRef:
    return EvidenceRef(
        source_kind=segment.source_kind,
        source_text_sha256=segment.source_text_sha256 or sha256_text(segment.text),
        text_span=match.group(0),
        char_start=match.start(),
        char_end=match.end(),
        audio_id=segment.audio_id,
        segment_id=segment.id if segment.source_kind in {"audio_segment", "transcript_segment"} else None,
        start_time=segment.start_time,
        end_time=segment.end_time,
        speaker_id=segment.speaker_id,
    )


def _add_entity(
    entities: OrderedDict[str, EntityItem],
    entity_type: str,
    label: str,
    normalized_value: str,
    evidence: EvidenceRef,
    confidence: float,
    reason: str,
) -> None:
    entity_id = stable_id(f"ent_{entity_type}", normalized_value)
    existing = entities.get(entity_id)
    if existing:
        existing.evidence_refs.append(evidence)
        existing.requires_review = existing.requires_review or evidence.source_kind == "transcript_text"
        return
    entities[entity_id] = EntityItem(
        id=entity_id,
        type=entity_type,
        label=label,
        value=normalized_value,
        confidence=confidence,
        confidence_reason=reason,
        source_method="regex",
        evidence_refs=[evidence],
        requires_review=evidence.source_kind == "transcript_text",
    )


def extract_entities(segments: Iterable[SegmentUnit]) -> list[EntityItem]:
    entities: OrderedDict[str, EntityItem] = OrderedDict()
    for segment in segments:
        text = segment.text or ""
        for match in PHONE_RE.finditer(text):
            normalized = normalize_phone(match.group(1))
            if len(normalized) < 9:
                continue
            _add_entity(
                entities,
                "phone",
                match.group(1),
                normalized,
                _evidence(segment, match),
                0.95,
                "High-precision phone regex match",
            )
        for match in EMAIL_RE.finditer(text):
            value = match.group(0).lower()
            _add_entity(
                entities,
                "email",
                match.group(0),
                value,
                _evidence(segment, match),
                0.98,
                "High-precision email regex match",
            )
        for match in MONEY_RE.finditer(text):
            value = re.sub(r"\s+", " ", match.group(1).strip().lower())
            _add_entity(
                entities,
                "money",
                match.group(1),
                value,
                _evidence(segment, match),
                0.85,
                "Money expression regex match",
            )
        for match in TIME_RE.finditer(text):
            value = re.sub(r"\s+", " ", match.group(1).strip().lower())
            _add_entity(
                entities,
                "time",
                match.group(1),
                value,
                _evidence(segment, match),
                0.8,
                "Time expression regex match",
            )
    return list(entities.values())
