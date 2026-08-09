"""Deterministic exact-value detectors for immutable transcript revisions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re
from typing import Any

from .contracts import sha256_canonical_json
from .discovery_common import DETECTOR_VERSION
from .discovery_contracts import DetectedMention, detected_mention_id
from .source_revision import SourceRevision, SourceSegment, _revalidate_source_revision


@dataclass(frozen=True)
class _DetectorRule:
    detector_type: str
    rule_id: str
    pattern: re.Pattern[str]
    group: int = 0
    ambiguous: bool = False


_UPPER = "A-ZÀ-ỴĐ"
_LOWER = "a-zà-ỹđ"
_WORD = rf"[{_UPPER}][{_LOWER}]+"
_DETECTOR_RULES = (
    _DetectorRule(
        "exact_value.email",
        "email-v1",
        re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?!\w)"),
    ),
    _DetectorRule(
        "exact_value.url",
        "url-v1",
        re.compile(r"https?://[^\s<>\]\[\"']+", re.IGNORECASE),
    ),
    _DetectorRule(
        "exact_value.coordinate",
        "coordinate-v1",
        re.compile(
            r"(?<!\d)-?(?:[1-8]?\d(?:\.\d+)?|90(?:\.0+)?)[,;]\s*-?(?:1[0-7]\d(?:\.\d+)?|\d?\d(?:\.\d+)?|180(?:\.0+)?)(?!\d)"
        ),
    ),
    _DetectorRule(
        "exact_value.money",
        "money-v1",
        re.compile(
            r"(?<!\w)\d[\d.,]*(?:\s*)(?:nghìn|ngàn|triệu|tỷ|đồng|vnd|usd|eur)(?!\w)",
            re.IGNORECASE,
        ),
    ),
    _DetectorRule(
        "exact_value.time",
        "time-v1",
        re.compile(r"(?<!\d)(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)"),
    ),
    _DetectorRule(
        "exact_value.date",
        "numeric-date-v1",
        re.compile(
            r"(?<!\d)(?:0?[1-9]|[12]\d|3[01])[/-](?:0?[1-9]|1[0-2])(?:[/-](?:\d{2}|\d{4}))?(?!\d)"
        ),
    ),
    _DetectorRule(
        "exact_value.quantity",
        "quantity-unit-v1",
        re.compile(
            r"(?<!\w)\d+(?:[.,]\d+)?\s*(?:kg|g|tấn|lít|ml|cái|chiếc|bản|hộp|gói|thùng|mét|km)(?!\w)",
            re.IGNORECASE,
        ),
    ),
    _DetectorRule(
        "exact_value.vehicle_identifier",
        "vn-plate-v1",
        re.compile(r"(?<!\w)\d{2}[A-ZĐ]\d?[- ]?\d{3,5}(?:\.\d{2})?(?!\w)"),
    ),
    _DetectorRule(
        "entity.alias",
        "alias-cue-v1",
        re.compile(
            rf"(?:biệt\s+danh|gọi\s+là)\s+[\"']?({_WORD}(?:\s+{_WORD}){{0,3}})[\"']?",
            re.IGNORECASE,
        ),
        group=1,
        ambiguous=True,
    ),
    _DetectorRule(
        "entity.person_mention",
        "person-cue-v1",
        re.compile(
            rf"(?:ông|bà|anh|chị|cô|chú|tên\s+là)\s+({_WORD}(?:\s+{_WORD}){{0,3}})",
            re.IGNORECASE,
        ),
        group=1,
        ambiguous=True,
    ),
    _DetectorRule(
        "entity.location_mention",
        "location-cue-v1",
        re.compile(r"(?:tại|ở|địa\s+chỉ)\s+([^,.;!?\n]{2,80})", re.IGNORECASE),
        group=1,
        ambiguous=True,
    ),
)

_DIGIT_PATTERN = re.compile(r"(?<![\w])(?:\+?\d(?:[ .-]?\d){5,18})(?![\w])")
_CODE_PATTERN = re.compile(
    r"(?:mã|số\s+hiệu|hồ\s+sơ|document|backup\s+code|code)\s*[:#-]?\s*([A-Za-z0-9][A-Za-z0-9._/-]{2,31})",
    re.IGNORECASE,
)


def _digits(value: str) -> str:
    prefix = "+" if value.strip().startswith("+") else ""
    return prefix + "".join(char for char in value if char.isdigit())


def _preceding_cue(
    text: str, start: int, cues: Sequence[str]
) -> tuple[int, str] | None:
    window = text[max(0, start - 48) : start]
    boundary = max(window.rfind(char) for char in ",;.!?\n")
    if boundary >= 0:
        window = window[boundary + 1 :]
    folded = window.casefold()
    matches = [
        (folded.rfind(cue.casefold()), cue)
        for cue in cues
        if folded.rfind(cue.casefold()) >= 0
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: item[0])


def _normalise_detector_value(detector_type: str, surface: str) -> str | None:
    if detector_type in {
        "exact_value.phone",
        "exact_value.account",
        "exact_value.identity_document",
    }:
        return _digits(surface)
    if detector_type in {"exact_value.email", "exact_value.url"}:
        return surface.casefold()
    return " ".join(surface.split())


def _make_mention(
    segment: SourceSegment,
    *,
    detector_type: str,
    rule_id: str,
    surface: str,
    segment_start: int,
    segment_end: int,
    cue: str | None = None,
    ambiguous: bool = False,
) -> DetectedMention:
    payload: dict[str, Any] = {
        "detector_version": DETECTOR_VERSION,
        "detector_type": detector_type,
        "detector_rule_id": rule_id,
        "segment_id": segment.segment_id,
        "surface": surface,
        "normalized": _normalise_detector_value(detector_type, surface),
        "raw_char_start": segment.raw_char_start + segment_start,
        "raw_char_end": segment.raw_char_start + segment_end,
        "segment_char_start": segment_start,
        "segment_char_end": segment_end,
        "cue": cue,
        "ambiguous": ambiguous,
        "candidate_only": True,
        "infers_owner_or_relation": False,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    return DetectedMention(
        mention_id=detected_mention_id(payload),
        **payload,
    )


def detect_exact_mentions(revision: SourceRevision) -> tuple[DetectedMention, ...]:
    """Detect high-recall source mentions without asserting ownership or intent."""

    revision = _revalidate_source_revision(revision)
    detected: dict[tuple[str, str, int, int], DetectedMention] = {}
    for segment in revision.segments:
        text = segment.text
        for rule in _DETECTOR_RULES:
            for match in rule.pattern.finditer(text):
                start, end = match.span(rule.group)
                surface = match.group(rule.group)
                mention = _make_mention(
                    segment,
                    detector_type=rule.detector_type,
                    rule_id=rule.rule_id,
                    surface=surface,
                    segment_start=start,
                    segment_end=end,
                    ambiguous=rule.ambiguous,
                )
                detected[(rule.detector_type, segment.segment_id, start, end)] = mention

        for match in _DIGIT_PATTERN.finditer(text):
            surface = match.group(0)
            digits = _digits(surface).lstrip("+")
            account_match = _preceding_cue(
                text, match.start(), ("tài khoản", "stk", "account")
            )
            id_match = _preceding_cue(text, match.start(), ("cccd", "cmnd", "căn cước"))
            phone_match = _preceding_cue(
                text,
                match.start(),
                ("điện thoại", "số điện thoại", "sđt", "phone", "gọi"),
            )
            typed: list[tuple[str, str, str | None]] = []
            cue_matches = [
                (kind, item)
                for kind, item in (
                    ("identity", id_match),
                    ("account", account_match),
                    ("phone", phone_match),
                )
                if item is not None
            ]
            nearest_kind: str | None = None
            nearest_cue: str | None = None
            if cue_matches:
                nearest_kind, (_, nearest_cue) = max(
                    cue_matches, key=lambda item: item[1][0]
                )
            if nearest_kind == "identity" and len(digits) in {9, 12}:
                typed.append(
                    (
                        "exact_value.identity_document",
                        "identity-cue-v1",
                        nearest_cue,
                    )
                )
            elif nearest_kind == "account" and 6 <= len(digits) <= 19:
                typed.append(("exact_value.account", "account-cue-v1", nearest_cue))
            phone_shape = (
                surface.strip().startswith(("0", "+84")) and 9 <= len(digits) <= 11
            )
            if phone_shape and (nearest_kind == "phone" or nearest_kind is None):
                typed.append(("exact_value.phone", "vn-phone-v1", nearest_cue))
            for detector_type, rule_id, cue in typed:
                mention = _make_mention(
                    segment,
                    detector_type=detector_type,
                    rule_id=rule_id,
                    surface=surface,
                    segment_start=match.start(),
                    segment_end=match.end(),
                    cue=cue,
                    ambiguous=cue is None,
                )
                detected[
                    (detector_type, segment.segment_id, match.start(), match.end())
                ] = mention

        for match in _CODE_PATTERN.finditer(text):
            start, end = match.span(1)
            mention = _make_mention(
                segment,
                detector_type="exact_value.document_or_object_code",
                rule_id="cue-code-v1",
                surface=match.group(1),
                segment_start=start,
                segment_end=end,
                cue=match.group(0)[: match.start(1) - match.start()].strip(" :#-"),
                ambiguous=True,
            )
            detected[(mention.detector_type, segment.segment_id, start, end)] = mention
    return tuple(
        sorted(
            detected.values(),
            key=lambda item: (
                item.raw_char_start,
                item.raw_char_end,
                item.detector_type,
                item.mention_id,
            ),
        )
    )


def detector_registry_sha256() -> str:
    payload = [
        {
            "detector_type": item.detector_type,
            "rule_id": item.rule_id,
            "pattern": item.pattern.pattern,
            "flags": item.pattern.flags,
            "group": item.group,
            "ambiguous": item.ambiguous,
        }
        for item in _DETECTOR_RULES
    ]
    payload.extend(
        [
            {"rule_id": "cue-digits-v1", "pattern": _DIGIT_PATTERN.pattern},
            {"rule_id": "cue-code-v1", "pattern": _CODE_PATTERN.pattern},
        ]
    )
    return sha256_canonical_json(payload)


__all__ = ["detect_exact_mentions", "detector_registry_sha256"]
