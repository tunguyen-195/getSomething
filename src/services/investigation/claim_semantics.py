"""Deterministic Vietnamese-first semantic checks for T4 candidates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Literal

from .contracts import JsonValue, sha256_canonical_json
from .evidence_selector import EvidenceSelector
from .run_contracts import DiscoveryCandidate
from .source_revision import normalize_transcript
from .verification_contracts import (
    DeterministicCheckRecord,
    ExactValueBinding,
    SEMANTIC_POLICY_VERSION,
    SemanticClaimFrame,
    SemanticRoleBinding,
    canonical_id,
)

_WORD_RE = re.compile(r"[0-9A-Za-zÀ-Ỵà-ỹĐđ]+", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"\s*;\s*|(?<=[.!?])\s+(?=\S)")
_CLAUSE_CONNECTOR_RE = re.compile(
    r",\s*(?:và|nhưng|còn|rồi|sau\s+đó)\s+", re.IGNORECASE
)
_GENERIC_STATEMENT_PREFIXES = (
    "explicit source mention",
    "explicit entity mention",
)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "source",
        "the",
        "to",
        "was",
        "were",
        "và",
        "là",
        "của",
        "cho",
        "đã",
        "đang",
        "sẽ",
        "một",
        "những",
        "các",
        "rằng",
        "thì",
        "này",
        "đó",
    }
)
_NEGATION_RE = re.compile(
    r"\b(?:không|chưa|chẳng|chả|đừng|không\s+phải)\b", re.IGNORECASE
)
_UNCERTAIN_RE = re.compile(
    r"\b(?:có\s+thể|có\s+lẽ|hình\s+như|dường\s+như|không\s+chắc|chắc\s+là)\b",
    re.IGNORECASE,
)
_UNKNOWN_RE = re.compile(
    r"\b(?:không\s+biết|chưa\s+biết|không\s+rõ|chưa\s+rõ)\b", re.IGNORECASE
)
_CONDITIONAL_RE = re.compile(
    r"(?:^|[\s,])(?:nếu|giả\s+sử|trong\s+trường\s+hợp)\b", re.IGNORECASE
)
_INSTRUCTION_RE = re.compile(
    r"(?:^|[.!?]\s*)(?:hãy|đừng|phải|cần|nhớ|gọi|gửi|chuyển|đưa|mang)\b",
    re.IGNORECASE,
)
_REPORTED_SPEECH_RE = re.compile(
    r"\b(?:theo\s+(?:như\s+)?lời(?:\s+kể)?|theo\s+(?:cáo\s+buộc|"
    r"tố\s+cáo|tố\s+giác|phản\s+ánh|trình\s+bày)|"
    r"theo\s+(?:nguồn\s+tin|nguồn\s+thạo\s+tin|tin\s+báo|báo\s+cáo)|"
    r"theo\s+[^,.;:!?]{1,80}(?=\s*[,;:])|được\s+cho\s+là|"
    r"nói|cho\s+biết|"
    r"cho\s+rằng|khẳng\s+định|kể|báo|nhắn|thông\s+báo|tiết\s+lộ|"
    r"thừa\s+nhận|phủ\s+nhận|cáo\s+buộc|tố(?:\s+cáo|\s+giác)?|"
    r"nghi\s+ngờ|trình\s+bày|khai(?:\s+rằng)?|said|told|reported|claimed|"
    r"alleged|accused)\b",
    re.IGNORECASE,
)
_EXACT_VALUE_RE = re.compile(
    r"(?<!\w)(?:\+?\d[\d .,:/-]{1,24}\d|\d+(?:[.,]\d+)?\s*(?:nghìn|ngàn|triệu|tỷ|đồng|vnd|usd|eur|kg|g|tấn|lít|ml|km|mét|cái|chiếc|hộp|gói|thùng))(?!\w)",
    re.IGNORECASE,
)
_UNIT_RE = re.compile(
    r"\b(?:nghìn|ngàn|triệu|tỷ|đồng|vnd|usd|eur|kg|g|tấn|lít|ml|km|mét|cái|chiếc|hộp|gói|thùng)\b",
    re.IGNORECASE,
)
_EXACT_ATTRIBUTE_KEYS = frozenset(
    {
        "surface",
        "source_surface",
        "target_surface",
        "value",
        "amount",
        "date",
        "time",
        "location",
        "owner",
        "owner_surface",
        "unit",
        "identifier",
        "code",
    }
)
_SAFE_ATTRIBUTE_KEYS = frozenset(
    {
        "candidate_channel",
        "candidate_kind",
        "detector_version",
        "detector_rule_id",
        "surface",
        "normalized",
        "cue",
        "ambiguous",
        "entity_type",
        "role",
    }
)
_ROLE_ACTIONS = frozenset(
    {
        "báo",
        "bán",
        "bảo",
        "bắt",
        "buy",
        "call",
        "called",
        "chuyển",
        "đến",
        "đánh",
        "đưa",
        "gặp",
        "giao",
        "gọi",
        "gửi",
        "giữ",
        "hẹn",
        "hứa",
        "khai",
        "khẳng",
        "kể",
        "ký",
        "lấy",
        "leave",
        "mang",
        "mặc",
        "mượn",
        "mua",
        "nhắn",
        "nhận",
        "nghi",
        "nói",
        "phủ",
        "pay",
        "rời",
        "said",
        "sell",
        "send",
        "sent",
        "thanh",
        "thông",
        "thừa",
        "trao",
        "trả",
        "trộm",
        "transfer",
        "transferred",
        "tới",
        "vay",
        "yêu",
        "đội",
    }
)
_ROLE_RECIPIENT_MARKERS = frozenset({"cho", "tới", "với", "to"})
_RANGE_UNITS = frozenset(
    {
        "%",
        "cái",
        "chiếc",
        "chỗ",
        "đồng",
        "đêm",
        "điểm",
        "eur",
        "g",
        "giờ",
        "gói",
        "hộp",
        "kg",
        "km",
        "lần",
        "lít",
        "mét",
        "ml",
        "năm",
        "ngàn",
        "nghìn",
        "ngày",
        "người",
        "phòng",
        "phút",
        "suất",
        "tháng",
        "thùng",
        "triệu",
        "tỷ",
        "tấn",
        "usd",
        "vé",
        "vnd",
    }
)
_RANGE_CUES = frozenset({"giá", "khoảng", "mức"})
_RANGE_CLAUSE_BOUNDARY = re.compile(r"[;,!?]|(?<!\d)\.(?!\d)")
_LEADING_ROLE_ADJUNCT = re.compile(
    r"^\s*(?:từ|trong\s+khoảng|khoảng|lúc|vào|ngày|tại|ở)\b",
    re.IGNORECASE,
)
_LEADING_TEMPORAL_ROLE_ADJUNCT = re.compile(
    r"^\s*(?:hôm\s+(?:nay|qua|kia)|(?:sáng|trưa|chiều|tối|đêm)\s+nay)\b"
    r"\s*,?\s*",
    re.IGNORECASE,
)
_PASSIVE_MARKERS = frozenset({"bị", "được", "was", "were"})
_PASSIVE_AGENT_MARKERS = frozenset({"bởi", "by"})
_ROLE_ADJUNCT_MARKERS = frozenset(
    {"lúc", "vào", "tại", "ở", "ngày", "hôm", "when", "at", "on"}
)
_ROLE_ACTOR_RESET_MARKERS = frozenset({"để", "thì"})
_AMBIGUOUS_PRONOUNS = frozenset(
    {
        "anh",
        "cô",
        "chị",
        "em",
        "hắn",
        "họ",
        "mình",
        "nó",
        "ông",
        "ta",
        "tôi",
        "chúng",
        "he",
        "her",
        "him",
        "it",
        "she",
        "they",
        "we",
    }
)
CheckStatus = Literal["pass", "fail", "review", "not_applicable"]


@dataclass(frozen=True)
class SemanticAssessment:
    checks: tuple[DeterministicCheckRecord, ...]
    failure_codes: tuple[str, ...]
    review_codes: tuple[str, ...]

    @property
    def supported(self) -> bool:
        return not self.failure_codes and not self.review_codes


def _fold(value: str) -> str:
    return normalize_transcript(unicodedata.normalize("NFKC", value))


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _WORD_RE.findall(_fold(value)))


def _semantic_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in _tokens(value) if token not in _STOPWORDS)


def _normalized_exact(value: str) -> str:
    return "".join(char for char in _fold(value) if char.isalnum() or char == "+")


def candidate_sha256(candidate: DiscoveryCandidate) -> str:
    resolved = DiscoveryCandidate.model_validate_json(
        candidate.model_dump_json(exclude_none=True)
    )
    return sha256_canonical_json(resolved.model_dump(mode="json", exclude_none=True))


def split_atomic_units(source_assertion: str) -> tuple[str, ...]:
    units = tuple(
        part.strip()
        for part in _SENTENCE_SPLIT_RE.split(source_assertion)
        if part.strip()
    )
    return units or (source_assertion.strip(),)


def classify_atomicity(source_assertion: str) -> tuple[str, tuple[str, ...]]:
    units = split_atomic_units(source_assertion)
    if len(units) > 1:
        return "compound", units
    connector_parts = tuple(
        part.strip()
        for part in _CLAUSE_CONNECTOR_RE.split(source_assertion)
        if part.strip()
    )
    if len(connector_parts) > 1 and all(
        len(_semantic_tokens(part)) >= 2 for part in connector_parts
    ):
        return "ambiguous", connector_parts
    return "atomic", units


def infer_source_modality(candidate: DiscoveryCandidate, source_assertion: str) -> str:
    folded = _fold(source_assertion)
    if candidate.claim_type.startswith("entity_mention."):
        return "reported"
    if _UNKNOWN_RE.search(folded):
        return "explicit_unknown"
    if _CONDITIONAL_RE.search(folded):
        return "conditional"
    if "?" in source_assertion:
        return "question"
    if _REPORTED_SPEECH_RE.search(folded):
        return "reported"
    if candidate.polarity == "quoted_instruction" or _INSTRUCTION_RE.search(folded):
        return "quoted_instruction"
    if _UNCERTAIN_RE.search(folded):
        return "uncertain"
    if _NEGATION_RE.search(folded) and "không chỉ" not in folded:
        return "negated"
    if candidate.polarity == "reported":
        return "reported"
    return "affirmed"


def _role_phrase(tokens: tuple[str, ...]) -> str | None:
    content = tuple(
        token
        for token in tokens
        if token not in _STOPWORDS.difference({"a", "an"})
        and token not in _PASSIVE_MARKERS
        and token not in _PASSIVE_AGENT_MARKERS
        and token not in _ROLE_ADJUNCT_MARKERS
    )
    return " ".join(content) or None


def _actor_tokens_before_action(
    value: str,
    tokens: tuple[str, ...],
    action_index: int,
) -> tuple[str, ...]:
    normalized = _fold(value)
    token_spans = tuple(_WORD_RE.finditer(normalized))
    if len(token_spans) != len(tokens):
        return tokens[:action_index]
    action_start = token_spans[action_index].start()
    prefix = normalized[:action_start]
    hard_boundary = max(prefix.rfind(";"), prefix.rfind("."), prefix.rfind("!"), prefix.rfind("?"))
    comma_boundary = prefix.rfind(",")
    boundary = hard_boundary
    if comma_boundary > hard_boundary:
        comma_prefix = prefix[hard_boundary + 1 : comma_boundary]
        if _LEADING_ROLE_ADJUNCT.search(comma_prefix):
            boundary = comma_boundary
    actor_start = 0
    if boundary >= 0:
        actor_start = next(
            (
                index
                for index, match in enumerate(token_spans)
                if match.start() > boundary
            ),
            action_index,
        )
    else:
        temporal_prefix = _LEADING_TEMPORAL_ROLE_ADJUNCT.match(prefix)
        if temporal_prefix is not None:
            actor_start = sum(
                1
                for match in token_spans[:action_index]
                if match.end() <= temporal_prefix.end()
            )
    reset_indexes = [
        index
        for index in range(actor_start, action_index)
        if tokens[index] in _ROLE_ACTOR_RESET_MARKERS
    ]
    if reset_indexes and reset_indexes[-1] + 1 < action_index:
        actor_start = reset_indexes[-1] + 1
    return tokens[actor_start:action_index]


def extract_semantic_roles(
    value: str,
    *,
    allowed_actions: Iterable[str] | None = None,
) -> SemanticRoleBinding:
    """Extract only roles that are safe enough for deterministic order checks."""

    tokens = _tokens(value)
    action_indexes = _role_action_indexes(
        value,
        allowed_actions=allowed_actions,
    )
    action_index = action_indexes[0] if action_indexes else None
    if action_index is None:
        return SemanticRoleBinding()

    action = tokens[action_index]
    before = _actor_tokens_before_action(value, tokens, action_index)
    after = tokens[action_index + 1 :]
    passive = any(
        token in _PASSIVE_MARKERS
        and tuple(before[index : index + 4]) != ("được", "nhắc", "đến", "là")
        for index, token in enumerate(before)
    )
    if passive:
        agent_index = next(
            (
                index
                for index, token in enumerate(after)
                if token in _PASSIVE_AGENT_MARKERS
            ),
            None,
        )
        if agent_index is None:
            return SemanticRoleBinding(
                action=action,
                object=_role_phrase(before),
                voice="passive",
                complete=False,
                ambiguous=True,
            )
        actor = _role_phrase(after[agent_index + 1 :])
        object_value = _role_phrase(before)
        ambiguous = not actor or not object_value
        return SemanticRoleBinding(
            actor=actor,
            action=action,
            object=object_value,
            voice="passive",
            complete=not ambiguous,
            ambiguous=ambiguous,
        )

    adjunct_index = next(
        (index for index, token in enumerate(after) if token in _ROLE_ADJUNCT_MARKERS),
        len(after),
    )
    role_tail = after[:adjunct_index]
    recipient_index = next(
        (
            index
            for index, token in enumerate(role_tail)
            if token in _ROLE_RECIPIENT_MARKERS
        ),
        None,
    )
    if recipient_index is None:
        object_value = _role_phrase(role_tail)
        recipient = None
    else:
        object_value = _role_phrase(role_tail[:recipient_index])
        recipient = _role_phrase(role_tail[recipient_index + 1 :])
    actor = _role_phrase(before)
    role_values = tuple(
        value for value in (actor, object_value, recipient) if value is not None
    )
    ambiguous = not actor or any(
        token in _AMBIGUOUS_PRONOUNS
        for role_value in role_values
        for token in role_value.split()
    )
    return SemanticRoleBinding(
        actor=actor,
        action=action,
        object=object_value,
        recipient=recipient,
        voice="active",
        complete=bool(actor and action),
        ambiguous=ambiguous,
    )


def extract_semantic_action_sequence(
    value: str,
    *,
    allowed_actions: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Return source-order action tokens used by deterministic role checks."""

    tokens = _tokens(value)
    return tuple(
        tokens[index]
        for index in _role_action_indexes(
            value,
            allowed_actions=allowed_actions,
        )
    )


def _is_quantitative_range_connector(
    normalized: str,
    token_spans: tuple[tuple[str, int, int], ...],
    index: int,
) -> bool:
    """Distinguish range ``đến`` from the movement verb ``đến``."""

    _, connector_start, connector_end = token_spans[index]
    clause_start = 0
    clause_end = len(normalized)
    for boundary in _RANGE_CLAUSE_BOUNDARY.finditer(normalized):
        if boundary.end() <= connector_start:
            clause_start = boundary.end()
            continue
        if boundary.start() >= connector_end:
            clause_end = boundary.start()
            break
    clause_indexes = tuple(
        token_index
        for token_index, (_, start, end) in enumerate(token_spans)
        if start >= clause_start and end <= clause_end
    )
    left_indexes = tuple(item for item in clause_indexes if item < index)
    right_indexes = tuple(item for item in clause_indexes if item > index)
    left_numbers = tuple(
        item
        for item in left_indexes
        if any(char.isdigit() for char in token_spans[item][0])
    )
    right_numbers = tuple(
        item
        for item in right_indexes
        if any(char.isdigit() for char in token_spans[item][0])
    )
    if not left_numbers or not right_numbers:
        return False

    clause_first = clause_indexes[0]
    clause_last = clause_indexes[-1] + 1
    left_number = left_numbers[-1]
    right_number = right_numbers[0]

    def endpoint_units(number_index: int) -> set[str]:
        units = {
            token_spans[item][0]
            for item in range(
                max(clause_first, number_index - 2),
                min(clause_last, number_index + 3),
            )
            if token_spans[item][0] in _RANGE_UNITS
        }
        _, number_start, number_end = token_spans[number_index]
        if "%" in normalized[max(clause_start, number_start - 1) : min(clause_end, number_end + 2)]:
            units.add("%")
        return units

    left_units = endpoint_units(left_number)
    right_units = endpoint_units(right_number)
    if left_units.intersection(right_units):
        return True
    clause_prefix = tuple(token_spans[item][0] for item in left_indexes)
    has_range_cue = bool(_RANGE_CUES.intersection(clause_prefix)) or (
        "số" in clause_prefix and "lượng" in clause_prefix
    ) or ("dao" in clause_prefix and "động" in clause_prefix)
    if has_range_cue:
        return True
    previous = token_spans[index - 1][0] if index else None
    following = token_spans[index + 1][0] if index + 1 < len(token_spans) else None
    if previous and following and previous.isdigit() and following.isdigit():
        return True
    has_from_cue = "từ" in tuple(
        token_spans[item][0]
        for item in left_indexes
        if item <= left_number
    )
    return bool(
        has_from_cue
        and (
            (not left_units and not right_units)
            or not left_units
            or not right_units
        )
    )


def _role_action_indexes(
    value: str,
    *,
    allowed_actions: Iterable[str] | None = None,
) -> tuple[int, ...]:
    normalized = _fold(value)
    token_spans = tuple(
        (match.group(0).casefold(), match.start(), match.end())
        for match in _WORD_RE.finditer(normalized)
    )
    tokens = tuple(item[0] for item in token_spans)
    actions = frozenset(allowed_actions) if allowed_actions is not None else _ROLE_ACTIONS
    indexes: list[int] = []
    for index, token in enumerate(tokens):
        if token not in actions:
            continue
        previous = tokens[index - 1] if index else None
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if token == "bảo" and (previous == "đảm" or following in {"đảm", "vệ"}):
            continue
        if token == "báo" and following == "cáo":
            continue
        if token == "thông" and following in {"báo", "tin"}:
            continue
        if token == "nhận" and following == "thức":
            continue
        if token == "bắt" and previous == "nắm":
            continue
        if token == "trao" and following == "đổi":
            continue
        if token == "nói" and previous == "thể":
            continue
        if token == "gọi" and previous == "cuộc":
            continue
        if token == "yêu" and following == "đãi":
            continue
        if token == "trả" and (
            previous in {"hủy", "quỷ"}
            or (
                "điều" in tokens[max(0, index - 6) : index]
                and "khoản" in tokens[max(0, index - 6) : index]
            )
        ):
            continue
        if token == "đến":
            preceding_scope = set(tokens[max(0, index - 6) : index])
            if (
                _is_quantitative_range_connector(normalized, token_spans, index)
                or (
                    previous == "nhắc"
                    and following == "là"
                    and "được" in tokens[max(0, index - 3) : index]
                )
                or (previous == "tế" and following == "xã")
                or previous == "quan"
                or preceding_scope.intersection({"khối", "lĩnh", "vực", "phụ", "trách"})
            ):
                continue
        indexes.append(index)
    return tuple(indexes)


def _iter_attribute_values(
    value: Any,
    path: tuple[str, ...] = (),
) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _iter_attribute_values(item, (*path, str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _iter_attribute_values(item, (*path, str(index)))
    else:
        yield path, value


def _safe_attributes(candidate: DiscoveryCandidate) -> dict[str, JsonValue] | None:
    safe: dict[str, JsonValue] = {}
    for key, value in (candidate.attributes or {}).items():
        if key in _SAFE_ATTRIBUTE_KEYS and value is not None:
            safe[key] = value
    safe.update(
        {
            "semantic_policy_version": SEMANTIC_POLICY_VERSION,
            "candidate_sha256": candidate_sha256(candidate),
        }
    )
    return safe


def _exact_value_kind(candidate: DiscoveryCandidate) -> str:
    if candidate.claim_type.startswith("exact_value."):
        return candidate.claim_type
    return "exact_value.untyped"


def extract_exact_values(
    candidate: DiscoveryCandidate,
    selector: EvidenceSelector,
) -> tuple[ExactValueBinding, ...]:
    values: dict[tuple[str, str], ExactValueBinding] = {}
    attributes = candidate.attributes or {}
    explicit_surface = attributes.get("surface")
    if isinstance(explicit_surface, str) and explicit_surface.strip():
        unit_match = _UNIT_RE.search(explicit_surface)
        binding = ExactValueBinding(
            kind=_exact_value_kind(candidate),
            surface=explicit_surface,
            normalized=str(
                attributes.get("normalized") or _normalized_exact(explicit_surface)
            ),
            evidence_ref=selector.evidence_id,
            unit=unit_match.group(0) if unit_match else None,
            owner_cue=(
                str(attributes["cue"])
                if isinstance(attributes.get("cue"), str)
                else None
            ),
            ambiguous=bool(attributes.get("ambiguous", False)),
        )
        values[(binding.kind, binding.surface)] = binding
    for match in _EXACT_VALUE_RE.finditer(selector.quote_exact):
        surface = match.group(0).strip()
        unit_match = _UNIT_RE.search(surface)
        binding = ExactValueBinding(
            kind=_exact_value_kind(candidate),
            surface=surface,
            normalized=_normalized_exact(surface),
            evidence_ref=selector.evidence_id,
            unit=unit_match.group(0) if unit_match else None,
            ambiguous=True,
        )
        values.setdefault((binding.kind, binding.surface), binding)
    return tuple(
        sorted(
            values.values(),
            key=lambda item: (item.kind, item.surface, item.evidence_ref),
        )
    )


def build_semantic_frame(
    candidate: DiscoveryCandidate,
    selector: EvidenceSelector,
) -> SemanticClaimFrame:
    candidate = DiscoveryCandidate.model_validate_json(
        candidate.model_dump_json(exclude_none=True)
    )
    selector = EvidenceSelector.model_validate_json(
        selector.model_dump_json(exclude_none=True)
    )
    atomicity, atomic_units = classify_atomicity(selector.quote_exact)
    payload: dict[str, Any] = {
        "semantic_policy_version": SEMANTIC_POLICY_VERSION,
        "candidate_ref": candidate.candidate_id,
        "candidate_sha256": candidate_sha256(candidate),
        "source_revision_id": selector.source_revision_id,
        "segment_id": selector.segment_id,
        "raw_char_start": selector.raw_char_start,
        "raw_char_end": selector.raw_char_end,
        "quote_sha256": selector.quote_sha256,
        "claim_type": candidate.claim_type,
        "candidate_statement": candidate.statement,
        "source_assertion": selector.quote_exact,
        "polarity": candidate.polarity,
        "source_modality": infer_source_modality(candidate, selector.quote_exact),
        "atomicity": atomicity,
        "atomic_units": atomic_units,
        "evidence_refs": (selector.evidence_id,),
        "speaker_id": selector.speaker_id,
        "exact_values": tuple(
            item.model_dump(mode="json", exclude_none=True)
            for item in extract_exact_values(candidate, selector)
        ),
        "source_roles": extract_semantic_roles(selector.quote_exact).model_dump(
            mode="json",
            exclude_none=True,
        ),
        "safe_attributes": _safe_attributes(candidate),
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    frame_hash = sha256_canonical_json(payload)
    return SemanticClaimFrame(
        frame_id=f"semv1:{frame_hash}",
        frame_sha256=frame_hash,
        **payload,
    )


def _check(
    *,
    code: str,
    status: CheckStatus,
    subject_ref: str,
    detail: str,
    refs: tuple[str, ...] = (),
) -> DeterministicCheckRecord:
    payload = {
        "code": code,
        "status": status,
        "subject_ref": subject_ref,
        "detail": detail,
        "refs": refs,
    }
    return DeterministicCheckRecord(
        check_id=canonical_id("chkv1", payload),
        code=code,
        status=status,
        subject_ref=subject_ref,
        detail=detail,
        refs=refs,
    )


def _statement_alignment(
    candidate: DiscoveryCandidate, frame: SemanticClaimFrame
) -> CheckStatus:
    statement_folded = _fold(candidate.statement)
    quote_folded = _fold(frame.source_assertion)
    if statement_folded == quote_folded:
        return "pass"
    if any(
        statement_folded.startswith(prefix) for prefix in _GENERIC_STATEMENT_PREFIXES
    ):
        surface = (candidate.attributes or {}).get("surface")
        if isinstance(surface, str) and _normalized_exact(surface) in _normalized_exact(
            frame.source_assertion
        ):
            return "pass"
        return "fail"
    statement_tokens = _semantic_tokens(candidate.statement)
    quote_tokens = _semantic_tokens(frame.source_assertion)
    if not statement_tokens:
        return "fail"
    quote_index = 0
    ordered_matches = 0
    for token in statement_tokens:
        while quote_index < len(quote_tokens) and quote_tokens[quote_index] != token:
            quote_index += 1
        if quote_index >= len(quote_tokens):
            break
        ordered_matches += 1
        quote_index += 1
    ordered_coverage = ordered_matches / len(statement_tokens)
    if ordered_coverage == 1.0:
        return "pass"
    unordered_coverage = len(set(statement_tokens) & set(quote_tokens)) / len(
        set(statement_tokens)
    )
    if unordered_coverage == 1.0:
        return "fail"
    if ordered_coverage >= 0.75:
        return "review"
    return "fail"


def _semantic_role_status(
    candidate: DiscoveryCandidate,
    frame: SemanticClaimFrame,
) -> CheckStatus:
    if _fold(candidate.statement) == _fold(frame.source_assertion):
        return "pass"
    candidate_roles = extract_semantic_roles(candidate.statement)
    source_roles = frame.source_roles
    if not candidate_roles.complete or not source_roles.complete:
        return "review"
    if candidate_roles.ambiguous or source_roles.ambiguous:
        return "review"
    comparable = ("actor", "action", "object", "recipient")
    return (
        "pass"
        if all(
            getattr(candidate_roles, field) == getattr(source_roles, field)
            for field in comparable
        )
        else "fail"
    )


def _attribute_binding_status(
    candidate: DiscoveryCandidate,
    frame: SemanticClaimFrame,
) -> CheckStatus:
    quote_normalized = _normalized_exact(frame.source_assertion)
    for path, value in _iter_attribute_values(candidate.attributes or {}):
        if not path or path[-1].casefold() not in _EXACT_ATTRIBUTE_KEYS:
            continue
        if isinstance(value, (str, int, float)):
            normalized = _normalized_exact(str(value))
            if normalized and normalized not in quote_normalized:
                return "fail"
    return "pass"


def _exact_value_status(
    candidate: DiscoveryCandidate,
    frame: SemanticClaimFrame,
) -> CheckStatus:
    quote_normalized = _normalized_exact(frame.source_assertion)
    for surface in _EXACT_VALUE_RE.findall(candidate.statement):
        if _normalized_exact(surface) not in quote_normalized:
            return "fail"
    for binding in frame.exact_values:
        if _normalized_exact(binding.surface) not in quote_normalized:
            return "fail"
        if binding.unit and _fold(binding.unit) not in _fold(binding.surface):
            return "fail"
    return "pass"


def _polarity_status(
    candidate: DiscoveryCandidate, frame: SemanticClaimFrame
) -> CheckStatus:
    if candidate.claim_type.startswith("entity_mention."):
        return "pass"
    compatible = {
        "affirmed": {"affirmed"},
        "negated": {"negated"},
        "uncertain": {"uncertain"},
        "reported": {"reported"},
        "quoted_instruction": {"quoted_instruction"},
    }
    return "pass" if frame.source_modality in compatible[candidate.polarity] else "fail"


def _factual_modality_status(
    candidate: DiscoveryCandidate,
    frame: SemanticClaimFrame,
) -> CheckStatus:
    if candidate.claim_type.startswith("entity_mention."):
        return "not_applicable"
    if candidate.polarity not in {"affirmed", "negated"}:
        return "fail"
    return "pass" if frame.source_modality in {"affirmed", "negated"} else "fail"


def assess_semantic_frame(
    candidate: DiscoveryCandidate,
    frame: SemanticClaimFrame,
) -> SemanticAssessment:
    candidate = DiscoveryCandidate.model_validate_json(
        candidate.model_dump_json(exclude_none=True)
    )
    frame = SemanticClaimFrame.model_validate_json(
        frame.model_dump_json(exclude_none=True)
    )
    statuses: dict[str, CheckStatus] = {
        "atomicity": (
            "pass"
            if frame.atomicity == "atomic"
            else "fail"
            if frame.atomicity == "compound"
            else "review"
        ),
        "statement_alignment": _statement_alignment(candidate, frame),
        "semantic_role_order": _semantic_role_status(candidate, frame),
        "polarity_modality": _polarity_status(candidate, frame),
        "factual_modality": _factual_modality_status(candidate, frame),
        "exact_values": _exact_value_status(candidate, frame),
        "owner_unit_binding": _attribute_binding_status(candidate, frame),
        "evidence_bound_statement": (
            "pass" if frame.source_assertion.strip() else "fail"
        ),
    }
    details = {
        "atomicity": f"source assertion classified as {frame.atomicity}",
        "statement_alignment": "candidate semantic tokens must be source-bound",
        "semantic_role_order": (
            "actor, action, object, and recipient roles must preserve source order"
        ),
        "polarity_modality": (
            f"candidate polarity={candidate.polarity}; source modality={frame.source_modality}"
        ),
        "factual_modality": (
            "only direct affirmed or negated source assertions may become facts"
        ),
        "exact_values": "candidate exact values must occur in the evidence quote",
        "owner_unit_binding": "typed owner/value/unit fields must occur in source",
        "evidence_bound_statement": "canonical assertion must retain exact source text",
    }
    checks = tuple(
        _check(
            code=code,
            status=status,
            subject_ref=frame.frame_id,
            detail=details[code],
            refs=(candidate.candidate_id, *frame.evidence_refs),
        )
        for code, status in statuses.items()
    )
    failures = tuple(
        sorted(code for code, status in statuses.items() if status == "fail")
    )
    reviews = tuple(
        sorted(code for code, status in statuses.items() if status == "review")
    )
    return SemanticAssessment(
        checks=checks,
        failure_codes=failures,
        review_codes=reviews,
    )


def proposition_core(frame: SemanticClaimFrame) -> str:
    source = _fold(frame.candidate_statement)
    source = _NEGATION_RE.sub(" ", source)
    source = _UNCERTAIN_RE.sub(" ", source)
    tokens = tuple(token for token in _semantic_tokens(source) if token not in {"not"})
    return " ".join(tokens)


def semantic_merge_key(frame: SemanticClaimFrame) -> tuple[Any, ...]:
    exact_values = tuple(
        (item.kind, item.normalized, item.unit, item.owner_cue, item.ambiguous)
        for item in frame.exact_values
    )
    return (
        frame.claim_type,
        _fold(frame.candidate_statement),
        frame.polarity,
        frame.source_modality,
        frame.speaker_id,
        frame.source_assertion,
        frame.segment_id,
        frame.raw_char_start,
        frame.raw_char_end,
        frame.quote_sha256,
        exact_values,
    )


__all__ = [
    "SemanticAssessment",
    "assess_semantic_frame",
    "build_semantic_frame",
    "candidate_sha256",
    "classify_atomicity",
    "extract_exact_values",
    "extract_semantic_action_sequence",
    "extract_semantic_roles",
    "infer_source_modality",
    "proposition_core",
    "semantic_merge_key",
    "split_atomic_units",
]
