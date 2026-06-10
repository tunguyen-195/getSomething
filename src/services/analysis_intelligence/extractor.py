from __future__ import annotations

import re
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Iterable

from .schemas import EntityItem, EvidenceRef, FactItem, RiskFlag, SegmentUnit, sha256_text, stable_id


CORE_EXTRACTOR_VERSION = "deterministic_vi_core.2026-05-03"

PHONE_RE = re.compile(r"(?<!\d)((?:\+?84|0)(?:[\s.\-]?\d){8,10})(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
EMAIL_CANDIDATE_RE = re.compile(
    r"(?i)\b([A-Za-zÀ-ỹĐđ0-9._%+-]+(?:\s+[A-Za-zÀ-ỹĐđ0-9._%+-]+)?"
    r"\.(?:gmail|yahoo|outlook|hotmail)\.com)\b"
)
ID_CONTEXT_RE = re.compile(
    r"(?i)\b(?:cccd|cmnd|căn\s*cước|căn\s*cứ\s*công\s*dân|chứng\s*minh)\b"
    r"(?P<context>.{0,80}?)(?P<number>(?:\d[\s.\-]?){9,13})(?!\d)"
)
ID_CONTEXT_BLOCK_RE = re.compile(r"(?i)\b(?:số\s*điện\s*thoại|điện\s*thoại|email|mail|địa\s*chỉ\s*email)\b")
ID_CONTEXT_CONNECTOR_RE = re.compile(
    r"(?i)(?:^|\s)(?:của\s+(?:chị|anh|em|tôi|mình)\s+)?(?:là|:|số(?:\s+là)?)\s*$"
)
DATE_RANGE_RE = re.compile(
    r"(?i)\b(?:từ\s*)?(?:ngày\s*)?(?P<d1>\d{1,2})\s*(?:tháng|/)\s*(?P<m1>\d{1,2})"
    r"(?:\s*(?:đến|tới|-)\s*(?:ngày\s*)?(?P<d2>\d{1,2})\s*(?:tháng|/)\s*(?P<m2>\d{1,2})"
    r"(?:\s*(?:năm|/)\s*(?P<y>\d{2,4}))?)"
)
DATE_RE = re.compile(
    r"(?i)\b(?:ngày\s*)?(?P<day>\d{1,2})\s*(?:tháng|/)\s*(?P<month>\d{1,2})"
    r"(?:\s*(?:năm|/)\s*(?P<year>\d{2,4}))?\b"
)
TIME_RE = re.compile(
    r"(?i)\b("
    r"\d{1,2}[:h]\d{2}"
    r"|\d{1,2}\s*giờ(?:\s*\d{1,2}\s*phút)?"
    r"|hôm nay|ngày mai|hôm qua"
    r"|(?:buổi|vào|lúc|khoảng|tầm)\s+(?:sáng|chiều|tối|đêm)"
    r"|(?:sáng|chiều|tối|đêm)\s+(?:nay|mai|hôm qua)"
    r")\b"
)
MONEY_WORD_RE = re.compile(
    r"(?i)(?<!\w)(\d+(?:[.,]\d+)?\s*(?:triệu|trieu|tỷ|ty)"
    r"(?:\s+\d+(?:[.,]\d+)?\s*(?:nghìn|nghin|ngàn|ngan))?"
    r"(?:\s*(?:đồng|vnd|vnđ))?)"
)
MONEY_THOUSANDS_RE = re.compile(r"(?i)(?<!\d)(\d{1,3}(?:\.\d{3})+)(?:\s*(?:đồng|vnd|vnđ))?(?!\d)")
QUANTITY_RE = re.compile(r"(?i)(?<!\d)(\d+)\s*(phòng|người|nam|nữ|đêm|suất|ngày)\b")
PERSON_NAME_RE = re.compile(
    r"(?i)\b(?:chị|anh|em|tôi)\s+(?:tên\s+là|là)\s+"
    r"([A-ZÀ-ỸĐ][A-Za-zÀ-ỹĐđ]*(?:\s+[A-ZÀ-ỸĐ][A-Za-zÀ-ỹĐđ]*){0,5})"
)
LOCATION_SEED_PATTERN = (
    r"Hà\s*Nội|Đà\s*Nẵng|TP\.?\s*HCM|TP\.?\s*Hồ\s*Chí\s*Minh|Hồ\s*Chí\s*Minh|"
    r"Mỹ\s*Đình|Hoàn\s*Kiếm|Hàng\s*Bài|Đống\s*Đa|phố\s*Huế|Nguyễn\s*Chí\s*Thanh|Bạch\s*Mai"
)
LOCATION_STOP_PATTERN = (
    r"[,.;:!?\n]|$|"
    r"\b(?:công\s*ty|khách\s*sạn|bệnh\s*viện|trường|địa\s*chỉ|gọi|ngày|lúc|vào|"
    r"để|cho|liên\s*hệ|ở|tại|đến|tới)\b"
)
LOCATION_COMPONENT_PATTERN = (
    r"(?:phố|đường|phường|xã|quận|huyện)\s+"
    r"[A-Za-zÀ-ỹĐđ0-9 '-]+?"
)
VI_UPPERCASE_CHARS = "A-ZĐÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ"
ORG_NAME_TOKEN_PATTERN = (
    r"(?!(?:ở|tại|đến|tới|địa|gọi|ngày|lúc|vào|để|cho|liên)\b)"
    rf"[{VI_UPPERCASE_CHARS}][A-Za-zÀ-ỹĐđ0-9&-]*(?:\.[A-Za-zÀ-ỹĐđ0-9&-]+)*"
)
ADDRESS_RE = re.compile(
    rf"(?i)\b(?P<address>(?:địa\s*chỉ\s*(?:là|:)?\s*)?(?:số\s*)?\d+[A-Za-zÀ-ỹĐđ0-9/.-]*\s+"
    rf"(?:phố|đường)\s+[A-Za-zÀ-ỹĐđ0-9 '-]+?"
    rf"(?:,\s*(?:phường|xã|quận|huyện|thành\s*phố|tp\.?|tỉnh)\s+[A-Za-zÀ-ỹĐđ0-9 '-]+?)*"
    rf"(?:,\s*(?:{LOCATION_SEED_PATTERN}))?)(?=\s*(?:{LOCATION_STOP_PATTERN}))"
)
LOCATION_CONTEXT_RE = re.compile(
    rf"(?i)\b(?:tại|ở|đến|tới|khu\s*vực)\s+"
    rf"(?P<location>(?:{LOCATION_SEED_PATTERN}|{LOCATION_COMPONENT_PATTERN}))(?=\s*(?:{LOCATION_STOP_PATTERN}))"
)
LOCATION_COMPONENT_RE = re.compile(
    rf"(?i)\b(?P<location>(?:{LOCATION_COMPONENT_PATTERN}|(?:{LOCATION_SEED_PATTERN})))(?=\s*(?:{LOCATION_STOP_PATTERN}))"
)
ORG_RE = re.compile(
    r"\b(?P<kind>(?i:khách\s*sạn|công\s*ty|doanh\s*nghiệp|bệnh\s*viện|trường))\s+"
    rf"(?P<name>{ORG_NAME_TOKEN_PATTERN}(?:\s+{ORG_NAME_TOKEN_PATTERN}){{0,6}})"
    rf"(?=\s*(?:{LOCATION_STOP_PATTERN}))"
)

PAYMENT_PATTERNS = [
    ("chuyển khoản", "Chuyển khoản", "payment_method"),
    ("tiền mặt", "Tiền mặt", "payment_method"),
    ("thẻ tín dụng", "Thẻ tín dụng", "payment_method"),
    ("quẹt thẻ", "Quẹt thẻ", "payment_method"),
]
PURPOSE_PATTERNS = [
    (r"(?i)\bmục\s*đích\s+(?:gì\s+)?(?:là\s+)?(.{0,40}?\bcông\s*tác\b)", "Mục đích công tác", "purpose"),
    (r"(?i)\bđi\s+với\s+mục\s*đích\s+công\s*tác\b", "Mục đích công tác", "purpose"),
    (r"(?i)\bđi\s+du\s*lịch\b", "Mục đích du lịch", "purpose"),
]
ACTION_PATTERNS = [
    (r"(?i)\bmuốn\s+đặt\s+\d+\s*phòng\b", "Yêu cầu đặt phòng", "request"),
    (r"(?i)\bđặt\s*cọc\s+trước\b", "Yêu cầu đặt cọc trước", "obligation"),
    (r"(?i)\bgửi\s+(?:tới|đến)\s+email.{0,80}?\bsố\s+tài\s*khoản\b", "Sẽ gửi số tài khoản qua email", "action"),
    (r"(?i)\bđiều\s*khoản.{0,80}?(?:đặt\s*phòng|hoàn|hủy|huỷ|quỷ\s*trả)\b", "Điều khoản đặt phòng/hoàn hủy cần đọc kỹ", "policy"),
    (r"(?i)\bbữa\s*sáng.{0,120}?(?:bao\s*gồm|không\s+phải\s+mất\s+thêm\s+tiền|buffet)\b", "Bữa sáng đã bao gồm trong giá", "offer"),
    (r"(?i)\bfitness\s*center.{0,80}?(?:free|miễn\s*phí|không\s*mất\s*phí)\b", "Ưu đãi sử dụng fitness center miễn phí", "offer"),
]


@dataclass
class CoreExtractionResult:
    entities: list[EntityItem] = field(default_factory=list)
    facts: list[FactItem] = field(default_factory=list)
    risk_flags: list[RiskFlag] = field(default_factory=list)


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("84"):
        return "0" + digits[2:]
    return digits


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _evidence(segment: SegmentUnit, match: re.Match[str], group: int | str = 0) -> EvidenceRef:
    start, end = match.span(group)
    text_span = segment.text[start:end]
    return EvidenceRef(
        source_kind=segment.source_kind,
        source_text_sha256=segment.source_text_sha256 or sha256_text(segment.text),
        text_span=text_span,
        char_start=start,
        char_end=end,
        audio_id=segment.audio_id,
        segment_id=segment.id if segment.source_kind in {"audio_segment", "transcript_segment"} else None,
        start_time=segment.start_time,
        end_time=segment.end_time,
        speaker_id=segment.speaker_id,
    )


def _append_unique_evidence(refs: list[EvidenceRef], evidence: EvidenceRef) -> None:
    key = (
        evidence.source_text_sha256,
        evidence.char_start,
        evidence.char_end,
        evidence.segment_id,
        evidence.text_span,
    )
    if not any(
        (
            ref.source_text_sha256,
            ref.char_start,
            ref.char_end,
            ref.segment_id,
            ref.text_span,
        )
        == key
        for ref in refs
    ):
        refs.append(evidence)


def _stable_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return str(value or "").strip().lower()


def _add_entity(
    entities: OrderedDict[str, EntityItem],
    entity_type: str,
    label: str,
    normalized_value: str,
    evidence: EvidenceRef,
    confidence: float,
    reason: str,
    *,
    source_method: str = "deterministic_regex",
    requires_review: bool | None = None,
) -> str:
    entity_id = stable_id(f"ent_{entity_type}", normalized_value)
    needs_review = requires_review if requires_review is not None else evidence.source_kind == "transcript_text"
    existing = entities.get(entity_id)
    if existing:
        _append_unique_evidence(existing.evidence_refs, evidence)
        existing.requires_review = existing.requires_review or needs_review
        return entity_id
    entities[entity_id] = EntityItem(
        id=entity_id,
        type=entity_type,
        label=label,
        value=normalized_value,
        confidence=confidence,
        confidence_reason=reason,
        source_method=source_method,
        evidence_refs=[evidence],
        requires_review=needs_review,
    )
    return entity_id


def _add_fact(
    facts: OrderedDict[str, FactItem],
    fact_type: str,
    label_vi: str,
    value: Any,
    normalized_value: Any,
    evidence: EvidenceRef,
    confidence: float,
    reason: str,
    *,
    source_method: str = "deterministic_regex",
    requires_review: bool | None = None,
) -> str:
    fact_id = stable_id(f"fact_{fact_type}", _stable_value(normalized_value))
    needs_review = requires_review if requires_review is not None else evidence.source_kind == "transcript_text"
    existing = facts.get(fact_id)
    if existing:
        _append_unique_evidence(existing.evidence_refs, evidence)
        existing.requires_review = existing.requires_review or needs_review
        existing.confidence = max(existing.confidence, confidence)
        return fact_id
    facts[fact_id] = FactItem(
        id=fact_id,
        type=fact_type,
        label=label_vi,
        label_vi=label_vi,
        value=value,
        normalized_value=normalized_value,
        confidence=confidence,
        confidence_reason=reason,
        source_method=source_method,
        evidence_refs=[evidence],
        requires_review=needs_review,
    )
    return fact_id


def _add_risk(
    risk_flags: OrderedDict[str, RiskFlag],
    risk_type: str,
    label_vi: str,
    value: Any,
    evidence: EvidenceRef,
    reason_vi: str,
    *,
    severity: str = "medium",
    category: str = "data_quality",
) -> None:
    risk_id = stable_id(f"risk_{risk_type}", _stable_value(value))
    if risk_id in risk_flags:
        _append_unique_evidence(risk_flags[risk_id].evidence_refs, evidence)
        return
    risk_flags[risk_id] = RiskFlag(
        id=risk_id,
        type=risk_type,
        label=label_vi,
        label_vi=label_vi,
        value=value,
        normalized_value=value,
        confidence=0.8,
        confidence_reason="Nội dung có dấu hiệu nhiễu ASR hoặc cần xác minh thủ công",
        source_method="deterministic_quality_check",
        evidence_refs=[evidence],
        requires_review=True,
        severity=severity,  # type: ignore[arg-type]
        category=category,
        reason_vi=reason_vi,
    )


def _money_to_number(value: str) -> int | None:
    text = value.lower().replace(",", ".")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text.strip()):
        return int(text.replace(".", ""))
    first = re.search(r"(\d+(?:\.\d+)?)\s*(triệu|trieu|tỷ|ty)", text)
    if not first:
        return None
    amount = float(first.group(1))
    multiplier = 1_000_000_000 if first.group(2) in {"tỷ", "ty"} else 1_000_000
    total = int(amount * multiplier)
    second = re.search(r"(\d+(?:\.\d+)?)\s*(nghìn|nghin|ngàn|ngan)", text)
    if second:
        total += int(float(second.group(1)) * 1000)
    return total


def _date_value(day: str, month: str, year: str | None = None) -> dict[str, int | None]:
    normalized_year = int(year) if year and len(year) == 4 else (2000 + int(year) if year else None)
    return {"day": int(day), "month": int(month), "year": normalized_year}


def _clean_name(value: str) -> str:
    stop_words = {"số", "địa", "còn", "chị", "anh", "em", "dạ", "phòng", "với", "và", "ở", "tại", "đến", "tới"}
    parts: list[str] = []
    for token in _normalize_space(value).split():
        if token.lower() in stop_words:
            break
        parts.append(token)
    return " ".join(parts).strip(" ,.;:")


def _clean_address(value: str) -> str:
    cleaned = re.sub(r"(?i)^địa\s*chỉ\s*(?:là|:)?\s*", "", _normalize_space(value))
    return cleaned.strip(" ,.;:")


def _clean_location(value: str) -> str:
    cleaned = _normalize_space(value)
    cleaned = re.sub(r"(?i)\s+(?:ngày|lúc|vào|để|cho|gọi|liên\s*hệ)\b.*$", "", cleaned)
    return cleaned.strip(" ,.;:")


def _clean_email_candidate(value: str) -> str:
    parts = _normalize_space(value).split()
    while parts and parts[0].lower() in {"là", "email", "mail"}:
        parts.pop(0)
    return " ".join(parts).strip(" ,.;:")


def _valid_id_context(context: str) -> bool:
    if not context:
        return True
    if ID_CONTEXT_BLOCK_RE.search(context):
        return False
    if re.search(r"[.!?]", context):
        return False
    clean = _normalize_space(context)
    if len(clean) > 45:
        return False
    return bool(ID_CONTEXT_CONNECTOR_RE.search(clean)) or len(clean) <= 4


def _span_inside(span: tuple[int, int], containers: list[tuple[int, int]]) -> bool:
    return any(start <= span[0] and span[1] <= end for start, end in containers)


def _extract_money_matches(
    segment: SegmentUnit,
    entities: OrderedDict[str, EntityItem],
    facts: OrderedDict[str, FactItem],
) -> None:
    seen_spans: set[tuple[int, int]] = set()
    matches = list(MONEY_WORD_RE.finditer(segment.text)) + list(MONEY_THOUSANDS_RE.finditer(segment.text))
    money_records: list[dict[str, Any]] = []
    for match in sorted(matches, key=lambda item: item.start()):
        if match.span(1) in seen_spans:
            continue
        seen_spans.add(match.span(1))
        raw_value = _normalize_space(match.group(1))
        normalized_number = _money_to_number(raw_value)
        evidence = _evidence(segment, match, 1)
        normalized = {"text": raw_value.lower(), "amount_vnd": normalized_number}
        money_records.append(
            {
                "span": match.span(1),
                "evidence": evidence,
                "normalized": normalized,
            }
        )
        _add_entity(
            entities,
            "money",
            raw_value,
            str(normalized_number or raw_value.lower()),
            evidence,
            0.87,
            "Biểu thức tiền tệ tiếng Việt hoặc số tiền dạng nhóm nghìn",
        )
        _add_fact(
            facts,
            "money",
            "Số tiền",
            raw_value,
            normalized,
            evidence,
            0.87,
            "Trích xuất bằng luật tiền tệ tiếng Việt",
        )

    for left, right in zip(money_records, money_records[1:]):
        left_ref = left["evidence"]
        right_ref = right["evidence"]
        between = segment.text[left_ref.char_end:right_ref.char_start].lower()
        if 0 <= len(between) <= 20 and re.search(r"\b(đến|tới|-)\b", between):
            start, end = left_ref.char_start, right_ref.char_end
            class _Span:
                def __init__(self, start: int, end: int) -> None:
                    self._start = start
                    self._end = end

                def span(self, _group: int = 0) -> tuple[int, int]:
                    return self._start, self._end

            evidence = _evidence(segment, _Span(start, end))  # type: ignore[arg-type]
            _add_fact(
                facts,
                "money_range",
                "Khoảng giá/số tiền",
                evidence.text_span,
                {
                    "from": left["normalized"],
                    "to": right["normalized"],
                },
                evidence,
                0.82,
                "Hai số tiền xuất hiện gần nhau với từ nối khoảng giá",
            )


def _extract_location_matches(
    segment: SegmentUnit,
    entities: OrderedDict[str, EntityItem],
    facts: OrderedDict[str, FactItem],
) -> None:
    address_spans: list[tuple[int, int]] = []
    location_spans: set[tuple[int, int]] = set()

    for match in ADDRESS_RE.finditer(segment.text):
        value = _clean_address(match.group("address"))
        if len(value) < 5:
            continue
        evidence = _evidence(segment, match, "address")
        address_spans.append(match.span("address"))
        _add_entity(
            entities,
            "address",
            value,
            value.lower(),
            evidence,
            0.78,
            "Địa chỉ có số nhà và phố/đường hoặc đơn vị hành chính",
            requires_review=evidence.source_kind == "transcript_text",
        )
        _add_fact(
            facts,
            "address",
            "Địa chỉ",
            value,
            value,
            evidence,
            0.78,
            "Địa chỉ được trích xuất bằng luật địa chỉ tiếng Việt",
            requires_review=evidence.source_kind == "transcript_text",
        )

    for regex in (LOCATION_CONTEXT_RE, LOCATION_COMPONENT_RE):
        for match in regex.finditer(segment.text):
            span = match.span("location")
            if _span_inside(span, address_spans) or span in location_spans:
                continue
            value = _clean_location(match.group("location"))
            if len(value) < 3:
                continue
            evidence = _evidence(segment, match, "location")
            location_spans.add(span)
            _add_entity(
                entities,
                "location",
                value,
                value.lower(),
                evidence,
                0.72,
                "Địa danh/đơn vị hành chính xuất hiện trong ngữ cảnh địa điểm",
                requires_review=evidence.source_kind == "transcript_text",
            )
            _add_fact(
                facts,
                "location",
                "Địa điểm",
                value,
                value,
                evidence,
                0.72,
                "Địa danh/đơn vị hành chính được trích xuất bằng luật địa điểm tiếng Việt",
                requires_review=evidence.source_kind == "transcript_text",
            )


def extract_core_analysis(segments: Iterable[SegmentUnit]) -> CoreExtractionResult:
    entities: OrderedDict[str, EntityItem] = OrderedDict()
    facts: OrderedDict[str, FactItem] = OrderedDict()
    risk_flags: OrderedDict[str, RiskFlag] = OrderedDict()

    for segment in segments:
        text = segment.text or ""

        for match in PHONE_RE.finditer(text):
            normalized = normalize_phone(match.group(1))
            if not (9 <= len(normalized) <= 11):
                continue
            evidence = _evidence(segment, match, 1)
            _add_entity(
                entities,
                "phone",
                _normalize_space(match.group(1)),
                normalized,
                evidence,
                0.96,
                "Số điện thoại Việt Nam, cho phép khoảng trắng/dấu gạch/dấu chấm",
            )
            _add_fact(
                facts,
                "phone",
                "Số điện thoại",
                _normalize_space(match.group(1)),
                normalized,
                evidence,
                0.96,
                "Số điện thoại được trích xuất bằng luật định dạng Việt Nam",
            )

        for match in EMAIL_RE.finditer(text):
            value = match.group(0).lower()
            evidence = _evidence(segment, match)
            _add_entity(entities, "email", match.group(0), value, evidence, 0.98, "Email hợp lệ có ký tự @")
            _add_fact(facts, "email", "Email", match.group(0), value, evidence, 0.98, "Email hợp lệ có ký tự @")

        for match in EMAIL_CANDIDATE_RE.finditer(text):
            candidate = _clean_email_candidate(match.group(1))
            if "@" in candidate:
                continue
            normalized = re.sub(r"\s+", "", candidate).lower()
            evidence = _evidence(segment, match, 1)
            _add_entity(
                entities,
                "email_candidate",
                candidate,
                normalized,
                evidence,
                0.68,
                "Chuỗi giống email nhưng thiếu ký tự @ hoặc có nhiễu ASR",
                requires_review=True,
            )
            _add_fact(
                facts,
                "email_candidate",
                "Email candidate",
                candidate,
                normalized,
                evidence,
                0.68,
                "Chuỗi giống email nhưng thiếu ký tự @ hoặc có nhiễu ASR",
                requires_review=True,
            )
            _add_risk(
                risk_flags,
                "noisy_email_candidate",
                "Email cần kiểm tra",
                candidate,
                evidence,
                "Email có vẻ bị ASR làm mất ký tự @ hoặc tách khoảng trắng, cần xác minh trước khi sử dụng.",
            )

        for match in ID_CONTEXT_RE.finditer(text):
            if not _valid_id_context(match.group("context")):
                continue
            raw_number = _normalize_space(match.group("number")).strip(" .,-")
            digits = re.sub(r"\D", "", raw_number)
            if not (9 <= len(digits) <= 13):
                continue
            evidence = _evidence(segment, match, "number")
            confidence = 0.78 if len(digits) == 12 else 0.62
            _add_entity(
                entities,
                "id_number_candidate",
                raw_number,
                digits,
                evidence,
                confidence,
                "Số định danh xuất hiện gần từ khóa CCCD/CMND/căn cước",
                requires_review=True,
            )
            _add_fact(
                facts,
                "id_number_candidate",
                "CCCD/CMND candidate",
                raw_number,
                digits,
                evidence,
                confidence,
                "Số định danh xuất hiện gần từ khóa CCCD/CMND/căn cước",
                requires_review=True,
            )
            if len(digits) != 12:
                _add_risk(
                    risk_flags,
                    "id_number_length",
                    "Số định danh cần kiểm tra",
                    raw_number,
                    evidence,
                    "Độ dài số định danh không đúng chuẩn CCCD 12 số hoặc transcript có dấu hiệu nhiễu.",
                )

        date_range_spans: list[tuple[int, int]] = []
        for match in DATE_RANGE_RE.finditer(text):
            date_range_spans.append(match.span())
            evidence = _evidence(segment, match)
            normalized = {
                "start": _date_value(match.group("d1"), match.group("m1"), match.group("y")),
                "end": _date_value(match.group("d2"), match.group("m2"), match.group("y")),
            }
            _add_fact(
                facts,
                "date_range",
                "Khoảng thời gian",
                evidence.text_span,
                normalized,
                evidence,
                0.88,
                "Khoảng ngày tiếng Việt có từ nối đến/tới",
            )

        for match in DATE_RE.finditer(text):
            if _span_inside(match.span(), date_range_spans):
                continue
            evidence = _evidence(segment, match)
            normalized = _date_value(match.group("day"), match.group("month"), match.group("year"))
            _add_entity(
                entities,
                "date",
                evidence.text_span,
                f"{normalized.get('year') or 'yyyy'}-{normalized['month']:02d}-{normalized['day']:02d}",
                evidence,
                0.84,
                "Ngày tháng tiếng Việt",
            )
            _add_fact(
                facts,
                "date",
                "Ngày/tháng",
                evidence.text_span,
                normalized,
                evidence,
                0.84,
                "Ngày tháng tiếng Việt",
            )

        for match in TIME_RE.finditer(text):
            evidence = _evidence(segment, match, 1)
            value = _normalize_space(match.group(1).lower())
            _add_entity(entities, "time", match.group(1), value, evidence, 0.78, "Biểu thức thời gian tiếng Việt")
            _add_fact(facts, "time", "Thời gian", match.group(1), value, evidence, 0.78, "Biểu thức thời gian tiếng Việt")

        _extract_money_matches(segment, entities, facts)

        for match in QUANTITY_RE.finditer(text):
            evidence = _evidence(segment, match)
            number = int(match.group(1))
            unit = match.group(2).lower()
            normalized = {"quantity": number, "unit": unit}
            _add_fact(
                facts,
                "quantity",
                f"Số lượng {unit}",
                evidence.text_span,
                normalized,
                evidence,
                0.86,
                "Số lượng kèm đơn vị nghiệp vụ phổ biến",
            )

        for match in PERSON_NAME_RE.finditer(text):
            next_char = text[match.end(1):match.end(1) + 1]
            if next_char and next_char in "0123456789.@":
                continue
            name = _clean_name(match.group(1))
            if len(name) < 2:
                continue
            evidence = _evidence(segment, match, 1)
            _add_entity(
                entities,
                "person",
                name,
                name.lower(),
                evidence,
                0.72,
                "Tên người xuất hiện sau mẫu tự giới thiệu",
                requires_review=evidence.source_kind == "transcript_text",
            )
            _add_fact(
                facts,
                "person_name",
                "Tên người",
                name,
                name,
                evidence,
                0.72,
                "Tên người xuất hiện sau mẫu tự giới thiệu",
                requires_review=evidence.source_kind == "transcript_text",
            )

        for match in ORG_RE.finditer(text):
            org = _clean_name(match.group("name"))
            if len(org) < 3 or org.lower() in {"mình", "em", "chị"}:
                continue
            evidence = _evidence(segment, match, "name")
            _add_entity(entities, "organization", org, org.lower(), evidence, 0.66, "Tên tổ chức xuất hiện sau từ khóa tổ chức")
            _add_fact(facts, "organization", "Tổ chức/địa điểm", org, org, evidence, 0.66, "Tên tổ chức xuất hiện sau từ khóa tổ chức")
            if re.search(r"(?i)khách\s*sạn|bệnh\s*viện|trường", match.group("kind")):
                _add_entity(
                    entities,
                    "location",
                    org,
                    org.lower(),
                    evidence,
                    0.58,
                    "Venue có thể vừa là tổ chức vừa là địa điểm",
                    requires_review=True,
                )
                _add_fact(
                    facts,
                    "location",
                    "Địa điểm",
                    org,
                    org,
                    evidence,
                    0.58,
                    "Venue được trích xuất từ từ khóa khách sạn/bệnh viện/trường",
                    requires_review=True,
                )

        _extract_location_matches(segment, entities, facts)

        lower_text = text.lower()
        for keyword, label, fact_type in PAYMENT_PATTERNS:
            idx = lower_text.find(keyword)
            if idx < 0:
                continue
            class _Span:
                def span(self, _group: int = 0) -> tuple[int, int]:
                    return idx, idx + len(keyword)

            evidence = _evidence(segment, _Span())  # type: ignore[arg-type]
            _add_fact(
                facts,
                fact_type,
                "Hình thức thanh toán",
                label,
                keyword,
                evidence,
                0.85,
                "Từ khóa phương thức thanh toán rõ ràng",
            )

        for pattern, label, fact_type in PURPOSE_PATTERNS:
            for match in re.finditer(pattern, text):
                evidence = _evidence(segment, match)
                _add_fact(
                    facts,
                    fact_type,
                    "Mục đích",
                    label,
                    label.lower(),
                    evidence,
                    0.78,
                    "Cụm từ mục đích được nêu trực tiếp",
                )

        for pattern, label, fact_type in ACTION_PATTERNS:
            for match in re.finditer(pattern, text):
                evidence = _evidence(segment, match)
                _add_fact(
                    facts,
                    fact_type,
                    label,
                    evidence.text_span,
                    label.lower(),
                    evidence,
                    0.76,
                    "Yêu cầu/cam kết/hành động được nêu trực tiếp trong hội thoại",
                )

    return CoreExtractionResult(
        entities=list(entities.values()),
        facts=list(facts.values()),
        risk_flags=list(risk_flags.values()),
    )


def extract_entities(segments: Iterable[SegmentUnit]) -> list[EntityItem]:
    return extract_core_analysis(segments).entities
