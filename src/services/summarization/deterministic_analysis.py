"""Deterministic transcript-only semantic extraction for degraded analysis."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any, Iterable

from src.services.investigation.claim_semantics import extract_semantic_roles
from src.services.investigation.exact_detectors import detect_exact_mentions
from src.services.investigation.source_revision import build_source_revision


logger = logging.getLogger(__name__)


_WORD_TOKEN = r"[^\W\d_]+(?:[-'][^\W\d_]+)?"
_PERSON_NAME = rf"{_WORD_TOKEN}(?:\s+{_WORD_TOKEN}){{0,4}}"
_ROLE_VALUES = (
    "phó trưởng phòng",
    "phó giám đốc",
    "phó chủ tịch",
    "phó bí thư",
    "chủ tài khoản",
    "người đại diện",
    "điều tra viên",
    "trưởng phòng",
    "giám đốc",
    "chủ tịch",
    "lãnh đạo",
    "chuyên viên",
    "nhân viên",
    "kế toán",
    "thủ quỹ",
    "luật sư",
    "tài xế",
    "lái xe",
    "quản lý",
    "phụ trách",
    "cán bộ",
    "đồng chí",
    "bí thư",
)
_ROLE_PATTERN = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(item) for item in _ROLE_VALUES) + r")(?!\w)",
    re.IGNORECASE,
)
_PERSON_PATTERNS = (
    re.compile(
        rf"(?i:tôi|tao|mình|em|anh|chị)\s+"
        rf"(?:(?:tên|họ\s+tên)(?:\s+là)?|là)\s+(?P<value>{_PERSON_NAME})"
    ),
    re.compile(
        rf"(?i:ông|bà|anh|chị|cô|chú|đồng chí)\s+(?P<value>{_PERSON_NAME})"
    ),
    re.compile(
        rf"(?i:{'|'.join(re.escape(item) for item in _ROLE_VALUES)})\s+"
        rf"(?P<value>{_PERSON_NAME})"
    ),
    re.compile(
        rf"(?:^|(?<=[.!?])\s+)(?P<value>{_PERSON_NAME})(?=\s+"
        r"(?i:nói|cho biết|yêu cầu|đề nghị|khai|báo|gọi|gặp|chuyển|gửi|"
        r"giao|nhận|cung cấp|phủ nhận|xác nhận))"
    ),
    re.compile(
        rf"(?i:cho|với|gặp|gọi|liên hệ|từ)\s+(?P<value>{_PERSON_NAME})"
    ),
)
_PERSON_SINGLE_TOKEN_STOP_WORDS = {
    "bữa",
    "bên",
    "có",
    "giá",
    "không",
    "mỗi",
    "ngay",
    "nhưng",
    "phòng",
    "phục",
    "số",
    "thế",
    "thời",
    "tinh",
    "tổng",
    "tội",
    "về",
}
_ORGANIZATION_PREFIXES = (
    "Ủy ban nhân dân",
    "Viện kiểm sát",
    "Ban giám đốc",
    "Khu công nghiệp",
    "Hợp tác xã",
    "Phòng",
    "Công an",
    "Đảng ủy",
    "Công ty",
    "Tập đoàn",
    "Ngân hàng",
    "Bệnh viện",
    "Tòa án",
    "Trường",
    "UBND",
    "HĐND",
    "Viện",
    "Sở",
    "Ban",
    "Bộ",
)
_SINGLE_TOKEN_ORGANIZATION_PREFIXES = {"Phòng", "Sở", "Ban", "Bộ", "Viện", "Trường"}
_BARE_ORGANIZATION_PREFIXES = {
    "ủy ban nhân dân",
    "viện kiểm sát",
    "ban giám đốc",
    "công an",
    "đảng ủy",
    "ubnd",
    "hđnd",
}
_ORGANIZATION_DESCRIPTOR_TOKENS = {
    "an",
    "ninh",
    "kinh",
    "tế",
    "chính",
    "trị",
    "nội",
    "bộ",
}
_ORGANIZATION_CUE_PATTERN = re.compile(
    r"(?<!\w)(?P<prefix>"
    + "|".join(re.escape(item) for item in _ORGANIZATION_PREFIXES)
    + r")(?!\w)",
    re.IGNORECASE,
)
_ASR_CLAUSE_BOUNDARY_TOKENS = {
    "bên",
    "có",
    "đẩy",
    "lực",
    "mỗi",
    "nhưng",
    "phục",
    "song",
    "thiếu",
    "tội",
    "về",
}
_LOCATION_CUE_PATTERN = re.compile(
    r"(?i:(?<!\w)(?:tại|ở|địa chỉ)\s+)"
    r"(?P<value>[^,.;!?\n]{2,100})"
)
_GENERIC_LOCATION_PATTERN = re.compile(
    r"(?<!\w)(?P<value>(?:khu công nghiệp|khu vực)"
    r"(?:\s+[^,.;!?\n]{1,80})?)",
    re.IGNORECASE,
)
_ADMIN_LOCATION_PATTERN = re.compile(
    rf"(?<!\w)(?P<prefix>(?i:thành phố|tỉnh|quận|huyện|phường|xã))\s+"
    rf"(?P<name>{_WORD_TOKEN}(?:\s+{_WORD_TOKEN}){{0,3}})"
)
_ADDRESS_PATTERN = re.compile(
    rf"(?<![\w:/-])(?P<number>\d{{1,5}})\s+"
    rf"(?:(?P<street_type>(?i:đường|phố))\s+)?"
    rf"(?P<name>{_WORD_TOKEN}(?:\s+{_WORD_TOKEN}){{0,4}})"
)
_VEHICLE_PATTERN = re.compile(
    r"(?<!\w)(?P<value>xe(?:\s+(?:ô tô|máy|tải|khách))?"
    r"(?:\s+[A-Za-zÀ-ỹĐđ0-9.-]+){0,4})",
    re.IGNORECASE,
)
_TEMPORAL_TEXT_PATTERN = re.compile(
    r"(?<!\w)(?:hôm nay|ngày mai|hôm qua|sáng nay|sáng mai|chiều nay|"
    r"chiều mai|tối nay|tối mai|trong năm qua|năm qua|"
    r"ngày\s+\d{1,2}\s+tháng\s+\d{1,2}(?:\s+năm\s+\d{2,4})?)(?!\w)",
    re.IGNORECASE,
)
_EXTENDED_QUANTITY_PATTERN = re.compile(
    r"(?<![\w:])\d+(?:[.,]\d+)?\s*(?:người|đối tượng|cuộc|lần|hồ sơ|"
    r"tài liệu|đơn|mẫu|máy|thiết bị|xe|chuyến|ngày|tháng|năm|giờ|phút|%)(?!\w)",
    re.IGNORECASE,
)
_FULL_MONEY_PATTERN = re.compile(
    r"(?<!\w)\d[\d.,]*\s*(?:nghìn|ngàn|triệu|tỷ)"
    r"(?:\s+(?:đồng|vnd|usd|eur))?(?!\w)|"
    r"(?<!\w)\d[\d.,]*\s*(?:đồng|vnd|usd|eur)(?!\w)",
    re.IGNORECASE,
)
_EVENT_PATTERN = re.compile(
    r"(?<!\w)(?:nói|cho biết|yêu cầu|đề nghị|khai|xác nhận|phủ nhận|"
    r"chuyển|gửi|giao|nhận|mua|bán|thuê|gặp|gọi|liên hệ|nhắn|"
    r"cung cấp|thanh toán|rút|nộp|hẹn|bắt giữ|thu giữ)(?!\w)",
    re.IGNORECASE,
)
_PLANNED_PATTERN = re.compile(
    r"(?<!\w)(?:sẽ|dự kiến|kế hoạch|chuẩn bị|định|hẹn)(?!\w)",
    re.IGNORECASE,
)
_SOURCE_FUTURE_MODALITY_PATTERN = re.compile(
    r"(?<!\w)(?:sẽ|dự kiến|dự tính|dự định|định|chuẩn bị|sắp)(?!\w)",
    re.IGNORECASE,
)
_SOURCE_COMPLETED_MODALITY_PATTERN = re.compile(
    r"(?<!\w)(?:đã|vừa|xong|hoàn tất|completed)(?!\w)",
    re.IGNORECASE,
)
_SOURCE_NEGATED_MODALITY_PATTERN = re.compile(
    r"(?<!\w)(?:không|chưa|chẳng|không có|not|never)(?!\w)",
    re.IGNORECASE,
)
_SOURCE_CONDITIONAL_MODALITY_PATTERN = re.compile(
    r"(?<!\w)(?:nếu|giả sử|trong trường hợp)(?!\w)",
    re.IGNORECASE,
)
_SOURCE_INTERROGATIVE_TRANSITION_PATTERN = re.compile(
    r"(?:^|\s)(?:nhưng\s+mà\s+|và\s+|vậy\s+)?"
    r"(?:em\s+|chị\s+|anh\s+|mình\s+)?"
    r"(?:không\s+biết|muốn\s+biết|muốn\s+hỏi|xin\s+hỏi|"
    r"bao\s+nhiêu|ngày\s+nào|phòng\s+nào|hình\s+thức\s+nào|"
    r"như\s+thế\s+nào|đúng\s+không)(?:\s|$)",
    re.IGNORECASE,
)
_NEGATED_PATTERN = re.compile(
    r"(?<!\w)(?:không|chưa|phủ nhận|không hề|không có)(?!\w)",
    re.IGNORECASE,
)
_COMPLETED_PATTERN = re.compile(
    r"(?<!\w)(?:đã|vừa|hoàn tất|hoàn thành|xong)(?!\w)",
    re.IGNORECASE,
)
_UNCERTAIN_PATTERN = re.compile(
    r"(?<!\w)(?:có thể|có lẽ|dường như|khả năng|chưa rõ|không chắc)(?!\w)",
    re.IGNORECASE,
)
_REPORTING_PATTERN = re.compile(
    r"(?<!\w)(?:nói|cho biết|khai|báo|kể|theo lời|xác nhận|phủ nhận)(?!\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceUnit:
    index: int
    text: str
    start: float | None
    end: float | None
    speaker: str | None


@dataclass(frozen=True)
class SurfaceMention:
    kind: str
    value: str
    unit_index: int
    start: int
    end: int
    normalized_value: str | None = None
    ambiguous: bool = False
    role: str | None = None


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _is_title_token(value: str) -> bool:
    token = value.strip(".,;:!?()[]{}\"'")
    return bool(token) and token[0].isupper() and any(char.isalpha() for char in token)


def _validated_person_name(
    value: str,
    *,
    explicit_identity_cue: bool = False,
) -> str | None:
    accepted: list[str] = []
    for token in _clean_text(value).split():
        if not _is_title_token(token):
            break
        accepted.append(token.strip(",.;:!?"))
        if len(accepted) == 4:
            break
    candidate = " ".join(accepted)
    if len(candidate) < 2:
        return None
    if (
        len(accepted) == 1
        and not explicit_identity_cue
        and candidate.casefold() in _PERSON_SINGLE_TOKEN_STOP_WORDS
    ):
        return None
    return candidate


def _optional_nonnegative_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def _source_modality_signature(text: str) -> tuple[bool, bool, bool, bool]:
    return (
        _SOURCE_FUTURE_MODALITY_PATTERN.search(text) is not None,
        _SOURCE_COMPLETED_MODALITY_PATTERN.search(text) is not None,
        _SOURCE_NEGATED_MODALITY_PATTERN.search(text) is not None,
        _SOURCE_CONDITIONAL_MODALITY_PATTERN.search(text) is not None,
    )


def _crosses_source_semantic_boundary(left: str, right: str) -> bool:
    # Questions that start in a new ASR window must not lend their modality to
    # the preceding assertion (for example, a quoted price plus "không biết...").
    if (
        _SOURCE_INTERROGATIVE_TRANSITION_PATTERN.search(right) is not None
        and _SOURCE_INTERROGATIVE_TRANSITION_PATTERN.search(left) is None
    ):
        return True

    left_signature = _source_modality_signature(left)
    right_signature = _source_modality_signature(right)
    left_future, left_completed, _, _ = left_signature
    right_future, right_completed, _, _ = right_signature
    crosses_exclusive_modality = (
        left_completed
        and not left_future
        and right_future
        and not right_completed
    ) or (
        left_future
        and not left_completed
        and right_completed
        and not right_future
    )
    if crosses_exclusive_modality:
        return True

    left_roles = extract_semantic_roles(left)
    right_roles = extract_semantic_roles(right)
    if not (
        left_roles.complete
        and not left_roles.ambiguous
        and right_roles.complete
        and not right_roles.ambiguous
    ):
        return False
    left_binding = (
        left_roles.actor,
        left_roles.action,
        left_roles.object,
        left_roles.recipient,
    )
    right_binding = (
        right_roles.actor,
        right_roles.action,
        right_roles.object,
        right_roles.recipient,
    )
    return left_signature != right_signature or left_binding != right_binding


def _source_units(transcript: str, segments: list[dict] | None) -> list[SourceUnit]:
    units: list[SourceUnit] = []
    for index, segment in enumerate(segments or []):
        text = _clean_text(segment.get("text"))
        if not text:
            continue
        speaker = _clean_text(segment.get("speaker") or segment.get("speaker_id"))
        units.append(
            SourceUnit(
                index=index,
                text=text,
                start=_optional_nonnegative_number(segment.get("start")),
                end=_optional_nonnegative_number(segment.get("end")),
                speaker=speaker or None,
            )
        )
    if units:
        # ASR segments are decoding windows, not narrative units. Join adjacent
        # fragments from the same speaker so the writer receives complete ideas
        # instead of being forced to paraphrase arbitrary timestamp cuts.
        merged: list[SourceUnit] = []
        current = units[0]
        for unit in units[1:]:
            current_words = len(current.text.split())
            next_words = len(unit.text.split())
            gap = (
                unit.start - current.end
                if unit.start is not None and current.end is not None
                else 0.0
            )
            boundary = (
                current.speaker != unit.speaker
                or current.speaker is None
                or unit.speaker is None
                or re.search(r"[.!?][\"')\]]?$", current.text) is not None
                or current_words + next_words > 60
                or gap > 3.0
                or _crosses_source_semantic_boundary(current.text, unit.text)
            )
            if boundary:
                merged.append(current)
                current = unit
                continue
            current = SourceUnit(
                index=current.index,
                text=f"{current.text} {unit.text}",
                start=current.start,
                end=unit.end,
                speaker=current.speaker,
            )
        merged.append(current)
        return merged

    parts = [
        _clean_text(part)
        for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", transcript)
        if _clean_text(part)
    ]
    return [
        SourceUnit(index=index, text=text, start=None, end=None, speaker=None)
        for index, text in enumerate(parts)
    ]


def _valid_audio_sha256(value: object) -> str | None:
    candidate = str(value or "")
    if re.fullmatch(r"[0-9a-f]{64}", candidate):
        return candidate
    return None


def _exact_mentions(
    units: list[SourceUnit],
    source_metadata: dict[str, Any],
) -> list[SurfaceMention]:
    synthetic_transcript = " ".join(unit.text for unit in units)
    scope_seed = _clean_text(
        source_metadata.get("task_id")
        or source_metadata.get("audio_id")
        or source_metadata.get("file_name")
        or "deterministic-preview"
    )
    try:
        segment_drafts = []
        for unit in units:
            has_audio_range = (
                unit.start is not None
                and unit.end is not None
                and unit.end > unit.start
            )
            segment_drafts.append(
                {
                    "text": unit.text,
                    "speaker_id": unit.speaker,
                    "start_seconds": unit.start if has_audio_range else None,
                    "end_seconds": unit.end if has_audio_range else None,
                }
            )
        revision = build_source_revision(
            scope={
                "case_id": _clean_text(source_metadata.get("case_id")) or scope_seed,
                "file_id": _clean_text(
                    source_metadata.get("audio_id")
                    or source_metadata.get("file_name")
                )
                or scope_seed,
                "source_id": scope_seed,
            },
            raw_transcript=synthetic_transcript,
            segments=segment_drafts,
            audio_sha256=_valid_audio_sha256(source_metadata.get("audio_sha256")),
        )
    except Exception as exc:
        logger.warning(
            "[DETERMINISTIC_ANALYSIS] Exact detector harness unavailable: %s",
            type(exc).__name__,
        )
        return []

    segment_indexes = {
        segment.segment_id: units[segment.order_index].index
        for segment in revision.segments
    }
    mentions: list[SurfaceMention] = []
    for mention in detect_exact_mentions(revision):
        if not mention.detector_type.startswith("exact_value."):
            continue
        if (
            mention.detector_type == "exact_value.document_or_object_code"
            and not re.search(r"\d|[A-Z].*[A-Z]|[_./-]", mention.surface)
        ):
            continue
        unit_index = segment_indexes[mention.segment_id]
        mentions.append(
            SurfaceMention(
                kind=mention.detector_type,
                value=mention.surface,
                unit_index=unit_index,
                start=mention.segment_char_start,
                end=mention.segment_char_end,
                normalized_value=mention.normalized,
                ambiguous=mention.ambiguous,
            )
        )
    return mentions


def _deduplicate_mentions(mentions: Iterable[SurfaceMention]) -> list[SurfaceMention]:
    result: list[SurfaceMention] = []
    seen: set[tuple[str, str, int, int]] = set()
    ordered = sorted(
        mentions,
        key=lambda item: (
            item.unit_index,
            item.start,
            -(item.end - item.start),
            item.kind,
        ),
    )
    for mention in ordered:
        key = (mention.kind, mention.value.casefold(), mention.unit_index, mention.start)
        if key in seen:
            continue
        overlap_index = next(
            (
                index
                for index, existing in enumerate(result)
                if existing.kind == mention.kind
                and existing.unit_index == mention.unit_index
                and existing.start < mention.end
                and mention.start < existing.end
            ),
            None,
        )
        if overlap_index is not None:
            existing = result[overlap_index]
            if (mention.end - mention.start) <= (existing.end - existing.start):
                continue
            result[overlap_index] = mention
            continue
        seen.add(key)
        result.append(mention)
    return sorted(result, key=lambda item: (item.unit_index, item.start, item.end))


def _person_mentions(unit: SourceUnit) -> list[SurfaceMention]:
    mentions: list[SurfaceMention] = []
    role_matches = list(_ROLE_PATTERN.finditer(unit.text))
    for pattern_index, pattern in enumerate(_PERSON_PATTERNS):
        for match in pattern.finditer(unit.text):
            value = _validated_person_name(
                match.group("value"),
                explicit_identity_cue=pattern_index in {0, 2},
            )
            if value is None:
                continue
            value_tail = unit.text[match.start("value") :]
            if not value or any(
                value.casefold().startswith(prefix.casefold())
                for prefix in _ORGANIZATION_PREFIXES
            ) or any(
                value_tail.casefold().startswith(prefix.casefold())
                for prefix in _ORGANIZATION_PREFIXES
            ):
                continue
            role = None
            for role_match in role_matches:
                before_name = unit.text[
                    role_match.end() : match.start("value")
                ]
                after_name = unit.text[
                    match.start("value") + len(value) : role_match.start()
                ]
                if role_match.end() <= match.start("value") and not before_name.strip():
                    role = role_match.group(0)
                    break
                if (
                    role_match.start() >= match.start("value") + len(value)
                    and re.fullmatch(
                        r"(?:\s*,\s*|\s+(?:là|giữ\s+chức\s+vụ)\s+)",
                        after_name,
                        re.IGNORECASE,
                    )
                ):
                    role = role_match.group(0)
                    break
            mentions.append(
                SurfaceMention(
                    kind="entity.person_mention",
                    value=value,
                    unit_index=unit.index,
                    start=match.start("value"),
                    end=match.start("value") + len(value),
                    ambiguous=True,
                    role=role,
                )
            )
    return _deduplicate_mentions(mentions)


def _organization_mentions(unit: SourceUnit) -> list[SurfaceMention]:
    mentions: list[SurfaceMention] = []
    token_pattern = re.compile(_WORD_TOKEN)
    for match in _ORGANIZATION_CUE_PATTERN.finditer(unit.text):
        prefix = match.group("prefix")
        canonical_single = next(
            (
                item
                for item in _SINGLE_TOKEN_ORGANIZATION_PREFIXES
                if item.casefold() == prefix.casefold()
            ),
            None,
        )
        following_tokens = list(token_pattern.finditer(unit.text, match.end()))
        if canonical_single is not None:
            if prefix != canonical_single or not following_tokens:
                continue
            if not _is_title_token(following_tokens[0].group(0)):
                continue

        value_end = match.end()
        for token_match in following_tokens[:4]:
            between = unit.text[value_end : token_match.start()]
            if any(char in between for char in ",.;!?\n"):
                break
            token = token_match.group(0)
            if token.casefold() in _ASR_CLAUSE_BOUNDARY_TOKENS:
                break
            if _is_title_token(token):
                value_end = token_match.end()
                continue
            if token.casefold() in {
                "tỉnh",
                "thành",
                "phố",
                *_ORGANIZATION_DESCRIPTOR_TOKENS,
            }:
                value_end = token_match.end()
                continue
            break
        value = _clean_text(unit.text[match.start() : value_end]).strip(",.;:!?")
        if (
            value_end == match.end()
            and prefix.casefold() not in _BARE_ORGANIZATION_PREFIXES
        ):
            continue
        mentions.append(
            SurfaceMention(
                kind="entity.organization_mention",
                value=value,
                unit_index=unit.index,
                start=match.start(),
                end=value_end,
                ambiguous=True,
            )
        )
    return _deduplicate_mentions(mentions)


def _truncate_location(value: str) -> str:
    candidate = re.split(
        r"\s+(?:lúc|vào|bằng|để|khi|nhưng|do|với|nói|cho biết|sẽ|đã|đang)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return _clean_text(candidate).strip(",.;:!?")


def _location_mentions(unit: SourceUnit) -> list[SurfaceMention]:
    mentions: list[SurfaceMention] = []
    for pattern in (
        _LOCATION_CUE_PATTERN,
        _GENERIC_LOCATION_PATTERN,
    ):
        for match in pattern.finditer(unit.text):
            value = _truncate_location(match.group("value"))
            if len(value) < 2:
                continue
            relative = match.group("value").find(value)
            start = match.start("value") + max(0, relative)
            mentions.append(
                SurfaceMention(
                    kind="entity.location_mention",
                    value=value,
                    unit_index=unit.index,
                    start=start,
                    end=start + len(value),
                    ambiguous=True,
                )
            )
    for match in _ADDRESS_PATTERN.finditer(unit.text):
        proper_name = _validated_person_name(match.group("name"))
        if proper_name is None:
            continue
        parts = [match.group("number")]
        if match.group("street_type"):
            parts.append(match.group("street_type"))
        parts.append(proper_name)
        value = " ".join(parts)
        mentions.append(
            SurfaceMention(
                kind="entity.location_mention",
                value=value,
                unit_index=unit.index,
                start=match.start(),
                end=match.start() + len(value),
                ambiguous=True,
            )
        )
    for match in _ADMIN_LOCATION_PATTERN.finditer(unit.text):
        proper_name = _validated_person_name(match.group("name"))
        if proper_name is None:
            continue
        value = f"{match.group('prefix')} {proper_name}"
        mentions.append(
            SurfaceMention(
                kind="entity.location_mention",
                value=value,
                unit_index=unit.index,
                start=match.start(),
                end=match.start() + len(value),
                ambiguous=True,
            )
        )
    return _deduplicate_mentions(mentions)


def _supplemental_mentions(unit: SourceUnit) -> list[SurfaceMention]:
    mentions: list[SurfaceMention] = []
    for match in _ROLE_PATTERN.finditer(unit.text):
        mentions.append(
            SurfaceMention(
                kind="mention.role",
                value=match.group(0),
                unit_index=unit.index,
                start=match.start(),
                end=match.end(),
                ambiguous=True,
            )
        )
    for match in _VEHICLE_PATTERN.finditer(unit.text):
        value = _truncate_location(match.group("value"))
        mentions.append(
            SurfaceMention(
                kind="mention.vehicle",
                value=value,
                unit_index=unit.index,
                start=match.start("value"),
                end=match.start("value") + len(value),
                ambiguous=True,
            )
        )
    for match in _TEMPORAL_TEXT_PATTERN.finditer(unit.text):
        mentions.append(
            SurfaceMention(
                kind="exact_value.time_expression",
                value=match.group(0),
                unit_index=unit.index,
                start=match.start(),
                end=match.end(),
            )
        )
    for match in _EXTENDED_QUANTITY_PATTERN.finditer(unit.text):
        mentions.append(
            SurfaceMention(
                kind="exact_value.quantity",
                value=match.group(0),
                unit_index=unit.index,
                start=match.start(),
                end=match.end(),
                normalized_value=_clean_text(match.group(0)),
            )
        )
    for match in _FULL_MONEY_PATTERN.finditer(unit.text):
        mentions.append(
            SurfaceMention(
                kind="exact_value.money",
                value=match.group(0),
                unit_index=unit.index,
                start=match.start(),
                end=match.end(),
                normalized_value=_clean_text(match.group(0)),
            )
        )
    return _deduplicate_mentions(mentions)


def _epistemic_status(text: str) -> str:
    if _NEGATED_PATTERN.search(text):
        return "negated"
    uncertainty_text = re.sub(
        r"\bcó\s+thể\s+nói\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if _UNCERTAIN_PATTERN.search(uncertainty_text):
        return "uncertain"
    if _PLANNED_PATTERN.search(text):
        return "planned"
    if _COMPLETED_PATTERN.search(text):
        return "completed"
    if _REPORTING_PATTERN.search(text):
        return "reported"
    return "reported"


def _has_concrete_event(text: str) -> bool:
    for match in _EVENT_PATTERN.finditer(text):
        verb = match.group(0).casefold()
        before = text[max(0, match.start() - 16) : match.start()].casefold()
        after = text[match.end() : match.end() + 12].casefold()
        if verb == "nói" and re.search(r"có thể\s*$", before):
            continue
        if verb == "nhận" and re.match(r"\s+thức\b", after):
            continue
        if verb == "giao" and re.search(r"được\s*$", before):
            continue
        return True
    return False


def _entity_groups(
    units_by_index: dict[int, SourceUnit],
    mentions: list[SurfaceMention],
) -> dict[str, Any]:
    groups: dict[str, Any] = {
        "people": [],
        "locations": [],
        "time": [],
        "organizations": [],
        "contact_info": {
            "phones": [],
            "emails": [],
            "ids": [],
            "bank_accounts": [],
            "addresses": [],
        },
    }
    seen: set[tuple[str, str]] = set()
    for mention in mentions:
        quote = units_by_index[mention.unit_index].text
        target: list[dict[str, Any]] | None = None
        payload: dict[str, Any]
        if mention.kind == "entity.person_mention":
            target = groups["people"]
            payload = {
                "name": mention.value,
                "role": mention.role,
                "evidence_quote": quote,
            }
        elif mention.kind == "entity.organization_mention":
            target = groups["organizations"]
            payload = {"name": mention.value, "evidence_quote": quote}
        elif mention.kind in {
            "entity.location_mention",
            "exact_value.coordinate",
        }:
            target = groups["locations"]
            payload = {
                "value": mention.value,
                "normalized_value": mention.normalized_value,
                "evidence_quote": quote,
            }
        elif mention.kind in {
            "exact_value.time",
            "exact_value.date",
            "exact_value.time_expression",
        }:
            target = groups["time"]
            payload = {
                "value": mention.value,
                "normalized_value": mention.normalized_value,
                "evidence_quote": quote,
            }
        elif mention.kind == "exact_value.phone":
            target = groups["contact_info"]["phones"]
            payload = {
                "value": mention.value,
                "normalized_value": mention.normalized_value,
                "evidence_quote": quote,
            }
        elif mention.kind == "exact_value.email":
            target = groups["contact_info"]["emails"]
            payload = {
                "value": mention.value,
                "normalized_value": mention.normalized_value,
                "evidence_quote": quote,
            }
        elif mention.kind == "exact_value.identity_document":
            target = groups["contact_info"]["ids"]
            payload = {
                "value": mention.value,
                "normalized_value": mention.normalized_value,
                "evidence_quote": quote,
            }
        elif mention.kind == "exact_value.account":
            target = groups["contact_info"]["bank_accounts"]
            payload = {
                "account_number": mention.value,
                "normalized_value": mention.normalized_value,
                "evidence_quote": quote,
            }
        else:
            continue

        key = (mention.kind, mention.value.casefold())
        if key in seen:
            continue
        seen.add(key)
        target.append({key: value for key, value in payload.items() if value})
    if not any(groups["contact_info"].values()):
        groups["contact_info"] = None
    return groups


def _relationships(
    units: list[SourceUnit],
    mentions_by_unit: dict[int, list[SurfaceMention]],
) -> list[dict[str, Any]]:
    relationships: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, int]] = set()
    for unit in units:
        unit_mentions = mentions_by_unit[unit.index]
        people = [item for item in unit_mentions if item.kind == "entity.person_mention"]
        organizations = [
            item
            for item in unit_mentions
            if item.kind == "entity.organization_mention"
        ]
        status = _epistemic_status(unit.text)

        for person in people:
            if not person.role or not organizations:
                continue
            organization = min(
                organizations,
                key=lambda item: abs(item.start - person.end),
            )
            if abs(organization.start - person.end) > 120:
                continue
            key = (person.value, organization.value, person.role.casefold(), unit.index)
            if key not in seen:
                seen.add(key)
                relationships.append(
                    {
                        "source": person.value,
                        "target": organization.value,
                        "label": person.role,
                        "status": "reported",
                        "evidence_quote": unit.text,
                    }
                )

        affiliation = re.search(
            r"\blà\s+đơn vị\s+trực thuộc\b", unit.text, re.IGNORECASE
        )
        if len(organizations) >= 2 and affiliation is not None:
            sources = [item for item in organizations if item.end <= affiliation.start()]
            targets = [item for item in organizations if item.start >= affiliation.end()]
            if sources and targets:
                source = max(sources, key=lambda item: item.end)
                target = min(targets, key=lambda item: item.start)
                key = (source.value, target.value, "đơn vị trực thuộc", unit.index)
                if key not in seen:
                    seen.add(key)
                    relationships.append(
                        {
                            "source": source.value,
                            "target": target.value,
                            "label": "đơn vị trực thuộc",
                            "status": "reported",
                            "evidence_quote": unit.text,
                        }
                    )

        if len(people) >= 2:
            interaction = re.search(
                r"(?<!\w)(chuyển|gửi|giao|gọi|gặp|liên hệ|nhắn)(?!\w)",
                unit.text,
                re.IGNORECASE,
            )
            if interaction:
                source, target = people[0], people[-1]
                label = interaction.group(1)
                key = (source.value, target.value, label.casefold(), unit.index)
                if key not in seen:
                    seen.add(key)
                    relationships.append(
                        {
                            "source": source.value,
                            "target": target.value,
                            "label": label,
                            "status": status,
                            "evidence_quote": unit.text,
                        }
                    )
    return relationships


def _sentence_role(
    index: int,
    total: int,
    mentions: list[SurfaceMention],
    has_event: bool,
    has_relationship: bool,
) -> str:
    kinds = {item.kind for item in mentions}
    if any(kind == "exact_value.money" for kind in kinds):
        return "financial"
    if any(kind in {"exact_value.phone", "exact_value.email"} for kind in kinds):
        return "contact"
    if any(
        kind
        in {
            "exact_value.account",
            "exact_value.identity_document",
            "exact_value.vehicle_identifier",
            "exact_value.document_or_object_code",
            "mention.vehicle",
        }
        for kind in kinds
    ):
        return "identifier"
    if any(
        kind in {"exact_value.time", "exact_value.date", "exact_value.time_expression"}
        for kind in kinds
    ):
        return "time"
    if any(kind in {"entity.location_mention", "exact_value.coordinate"} for kind in kinds):
        return "location"
    if has_relationship:
        return "relationship"
    if any(kind.startswith("entity.") for kind in kinds):
        return "participant"
    if has_event:
        return "event"
    if index == 0:
        return "overview"
    if index == total - 1:
        return "outcome"
    return "uncertainty"


def build_deterministic_transcript_analysis(
    transcript: str,
    segments: list[dict] | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Extract source mentions without asserting released world facts."""

    if not transcript or not transcript.strip():
        return None
    units = _source_units(transcript, segments)
    if not units:
        return None
    metadata = dict(source_metadata or {})
    mentions = _exact_mentions(units, metadata)
    for unit in units:
        mentions.extend(_person_mentions(unit))
        mentions.extend(_organization_mentions(unit))
        mentions.extend(_location_mentions(unit))
        mentions.extend(_supplemental_mentions(unit))
    mentions = _deduplicate_mentions(mentions)

    units_by_index = {unit.index: unit for unit in units}
    mentions_by_unit = {unit.index: [] for unit in units}
    for mention in mentions:
        mentions_by_unit[mention.unit_index].append(mention)

    relationships = _relationships(units, mentions_by_unit)
    relationship_units = {
        unit.index
        for unit in units
        if any(item["evidence_quote"] == unit.text for item in relationships)
    }
    events: list[dict[str, Any]] = []
    for unit in units:
        if not _has_concrete_event(unit.text):
            continue
        unit_mentions = mentions_by_unit[unit.index]
        actors = [
            item.value
            for item in unit_mentions
            if item.kind in {"entity.person_mention", "entity.organization_mention"}
        ]
        temporal = [
            item.value
            for item in unit_mentions
            if item.kind
            in {"exact_value.time", "exact_value.date", "exact_value.time_expression"}
        ]
        locations = [
            item.value
            for item in unit_mentions
            if item.kind in {"entity.location_mention", "exact_value.coordinate"}
        ]
        event: dict[str, Any] = {
            "description": unit.text,
            "actors": list(dict.fromkeys(actors)),
            "status": _epistemic_status(unit.text),
            "evidence_quote": unit.text,
        }
        if temporal:
            event["time"] = "; ".join(dict.fromkeys(temporal))
        if locations:
            event["location"] = locations[0]
        events.append(event)

    exact_and_role_facts = []
    for mention in mentions:
        if mention.kind.startswith("entity.") or mention.kind in {
            "exact_value.phone",
            "exact_value.email",
            "exact_value.account",
            "exact_value.identity_document",
            "exact_value.time",
            "exact_value.date",
            "exact_value.time_expression",
            "exact_value.coordinate",
        }:
            continue
        exact_and_role_facts.append(
            {
                "statement": mention.value,
                "category": mention.kind,
                "status": (
                    "reported"
                    if mention.kind == "mention.role"
                    else _epistemic_status(units_by_index[mention.unit_index].text)
                ),
                "evidence_quote": units_by_index[mention.unit_index].text,
            }
        )

    open_questions: list[dict[str, str]] = []
    for mention in mentions:
        if mention.kind not in {
            "exact_value.phone",
            "exact_value.account",
            "exact_value.identity_document",
            "exact_value.document_or_object_code",
        }:
            continue
        open_questions.append(
            {
                "question": f"Cần xác minh chủ thể và ý nghĩa gắn với {mention.value}.",
                "evidence_quote": units_by_index[mention.unit_index].text,
            }
        )
    # Without diarized segments every sentence is naturally speakerless; that
    # is not itself a useful follow-up. Only surface this warning when a
    # segment stream was supplied and at least one segment lacks a speaker.
    first_unknown_speaker = (
        next((unit for unit in units if unit.speaker is None), None)
        if segments
        else None
    )
    if first_unknown_speaker is not None:
        open_questions.append(
            {
                "question": "Cần xác minh danh tính người nói cho các đoạn chưa được gán speaker.",
                "evidence_quote": first_unknown_speaker.text,
            }
        )

    summary_sentences = []
    for position, unit in enumerate(units):
        summary_sentences.append(
            {
                "draft_id": f"deterministic-source-{unit.index}",
                "text": unit.text,
                "sentence_role": _sentence_role(
                    position,
                    len(units),
                    mentions_by_unit[unit.index],
                    any(item["evidence_quote"] == unit.text for item in events),
                    unit.index in relationship_units,
                ),
                "evidence_quotes": [unit.text],
            }
        )

    return {
        "summary": " ".join(unit.text for unit in units),
        "summary_sentences": summary_sentences,
        "key_points": [
            {"statement": unit.text, "evidence_quote": unit.text} for unit in units
        ],
        "entities": _entity_groups(units_by_index, mentions),
        "facts": exact_and_role_facts,
        "events": events,
        "relationships": relationships,
        "open_questions": open_questions,
        "hypotheses": [],
        "risk_assessment": {
            "overall_risk": "unverified",
            "crime_indicators": [],
            "recommended_actions": [],
        },
    }


__all__ = ["build_deterministic_transcript_analysis"]
