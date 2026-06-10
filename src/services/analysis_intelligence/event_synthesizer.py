from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schemas import EntityItem, EventItem, FactItem, stable_id


@dataclass(frozen=True)
class MatchDistance:
    distance: int
    anchor_ref: Any
    candidate_ref: Any


def _first_time(refs: list[Any]) -> tuple[float | None, float | None]:
    for ref in refs:
        if ref.start_time is not None and ref.end_time is not None:
            return ref.start_time, ref.end_time
    return None, None


def _semantic_time_from_fact(fact: FactItem) -> dict[str, Any] | None:
    if fact.type == "date_range" and isinstance(fact.normalized_value, dict):
        return {
            "kind": "date_range",
            "start": fact.normalized_value.get("start"),
            "end": fact.normalized_value.get("end"),
            "source_fact_id": fact.id,
        }
    if fact.type == "date" and isinstance(fact.normalized_value, dict):
        return {"kind": "date", "value": fact.normalized_value, "source_fact_id": fact.id}
    if fact.type == "time":
        return {"kind": "time", "value": fact.normalized_value or fact.value, "source_fact_id": fact.id}
    return None


def _semantic_time_from_temporal_facts(facts: list[FactItem]) -> dict[str, Any] | None:
    semantic_times = [item for item in (_semantic_time_from_fact(fact) for fact in facts) if item]
    if not semantic_times:
        return None
    if len(semantic_times) == 1:
        return semantic_times[0]
    return {
        "kind": "compound",
        "items": semantic_times,
        "source_fact_ids": [fact.id for fact in facts],
    }


def _refs_comparable(left_ref: Any, right_ref: Any) -> bool:
    if left_ref.segment_id or right_ref.segment_id:
        return bool(left_ref.segment_id and left_ref.segment_id == right_ref.segment_id)
    return bool(left_ref.source_text_sha256 and left_ref.source_text_sha256 == right_ref.source_text_sha256)


def _match_distance(anchor: FactItem, candidate: FactItem) -> MatchDistance | None:
    best: MatchDistance | None = None
    for anchor_ref in anchor.evidence_refs:
        for candidate_ref in candidate.evidence_refs:
            if not _refs_comparable(anchor_ref, candidate_ref):
                continue
            match = MatchDistance(
                distance=abs(anchor_ref.char_start - candidate_ref.char_start),
                anchor_ref=anchor_ref,
                candidate_ref=candidate_ref,
            )
            if best is None or match.distance < best.distance:
                best = match
    return best


def _nearby_fact_matches(
    anchor: FactItem,
    candidates: list[FactItem],
    *,
    max_char_distance: int = 120,
) -> list[tuple[MatchDistance, FactItem]]:
    nearby: list[tuple[MatchDistance, FactItem]] = []
    for item in candidates:
        match = _match_distance(anchor, item)
        if match and match.distance <= max_char_distance:
            nearby.append((match, item))
    return sorted(nearby, key=lambda pair: pair[0].distance)


def _nearby_temporal_facts(anchor: FactItem, candidates: list[FactItem], *, max_char_distance: int = 120) -> list[FactItem]:
    return [item for _, item in _nearby_fact_matches(anchor, candidates, max_char_distance=max_char_distance)]


def _money_priority(anchor: FactItem, candidates: list[FactItem], *, max_char_distance: int = 120) -> tuple[FactItem, MatchDistance] | None:
    if not candidates:
        return None

    scored: list[tuple[tuple[int, int], FactItem, MatchDistance]] = []
    for item in candidates:
        match = _match_distance(anchor, item)
        if not match or match.distance > max_char_distance:
            continue
        text = " ".join(ref.text_span.lower() for ref in item.evidence_refs)
        keyword_bonus = 0 if any(token in text for token in ("tổng", "đặt cọc", "chuyển khoản")) else 1
        scored.append(((keyword_bonus, match.distance), item, match))
    if not scored:
        return None
    _, item, match = sorted(scored, key=lambda entry: entry[0])[0]
    return item, match


def _dedupe_refs(refs: list[Any]) -> list[Any]:
    seen: set[tuple[Any, ...]] = set()
    selected = []
    for ref in refs:
        key = (ref.segment_id, ref.char_start, ref.char_end, ref.text_span, ref.source_text_sha256)
        if key in seen:
            continue
        seen.add(key)
        selected.append(ref)
    return selected


def _is_high_value_or_contextual_money(fact: FactItem) -> bool:
    amount = None
    if isinstance(fact.normalized_value, dict):
        amount = fact.normalized_value.get("amount_vnd")
    if isinstance(amount, int) and amount >= 1_000_000:
        return True
    context = " ".join(ref.text_span.lower() for ref in fact.evidence_refs)
    return any(token in context for token in ("tổng", "đặt cọc", "chuyển khoản"))


def _money_amounts_from_fact(fact: FactItem) -> list[int]:
    if not isinstance(fact.normalized_value, dict):
        return []
    if fact.type == "money":
        amount = fact.normalized_value.get("amount_vnd")
        return [amount] if isinstance(amount, int) else []
    if fact.type == "money_range":
        amounts = []
        for key in ("from", "to"):
            value = fact.normalized_value.get(key)
            amount = value.get("amount_vnd") if isinstance(value, dict) else None
            if isinstance(amount, int):
                amounts.append(amount)
        return amounts
    return []


def _event_from_facts(
    event_type: str,
    label_vi: str,
    source_facts: list[FactItem],
    *,
    confidence: float | None = None,
    semantic_time: dict[str, Any] | None = None,
    requires_review: bool | None = None,
    matched_evidence_refs: list[Any] | None = None,
) -> EventItem:
    if matched_evidence_refs is None:
        evidence_refs = []
        for fact in source_facts:
            evidence_refs.extend(fact.evidence_refs)
    else:
        evidence_refs = matched_evidence_refs
    evidence_refs = _dedupe_refs(evidence_refs)
    start_time, end_time = _first_time(evidence_refs)
    trigger_fact = source_facts[0]
    money_amounts = [amount for fact in source_facts for amount in _money_amounts_from_fact(fact)]
    return EventItem(
        id=stable_id("evt", event_type, *(fact.id for fact in source_facts)),
        type=event_type,
        label=label_vi,
        label_vi=label_vi,
        trigger_text=str(trigger_fact.value or trigger_fact.label),
        source_fact_ids=[fact.id for fact in source_facts],
        semantic_time=semantic_time,
        start_time=start_time,
        end_time=end_time,
        entity_ids=[],
        confidence=confidence if confidence is not None else min(fact.confidence for fact in source_facts),
        confidence_reason="Sự kiện tổng hợp từ fact deterministic có evidence",
        source_method="deterministic_event_synthesizer",
        evidence_refs=evidence_refs,
        risk_context={"money_amounts_vnd": money_amounts} if money_amounts else None,
        requires_review=requires_review if requires_review is not None else any(fact.requires_review for fact in source_facts),
    )


def synthesize_events(facts: list[FactItem], entities: list[EntityItem] | None = None) -> list[EventItem]:
    del entities  # Reserved for later entity linking without changing the call site.
    events: list[EventItem] = []
    used_temporal_fact_ids: set[str] = set()
    used_money_fact_ids: set[str] = set()
    temporal_facts = [fact for fact in facts if fact.type in {"date_range", "date", "time"}]
    money_facts = [fact for fact in facts if fact.type in {"money", "money_range"}]

    request_facts = [fact for fact in facts if fact.type == "request"]
    for fact in request_facts:
        semantic_matches = _nearby_fact_matches(fact, temporal_facts)
        semantic_facts = [item for _, item in semantic_matches]
        semantic_time = _semantic_time_from_temporal_facts(semantic_facts)
        source_facts = [fact] + semantic_facts
        matched_refs = [ref for match, _ in semantic_matches for ref in (match.anchor_ref, match.candidate_ref)] if semantic_matches else None
        if semantic_facts:
            used_temporal_fact_ids.update(item.id for item in semantic_facts)
        event_type = "booking_request" if "đặt" in str(fact.value).lower() or "phòng" in str(fact.value).lower() else "generic_request"
        events.append(
            _event_from_facts(
                event_type,
                "Yêu cầu đặt phòng" if event_type == "booking_request" else "Yêu cầu",
                source_facts,
                semantic_time=semantic_time,
                matched_evidence_refs=matched_refs,
            )
        )

    for fact in [item for item in facts if item.type == "action"]:
        semantic_matches = _nearby_fact_matches(fact, temporal_facts)
        semantic_facts = [item for _, item in semantic_matches]
        if semantic_facts:
            used_temporal_fact_ids.update(item.id for item in semantic_facts)
        source_facts = [fact] + semantic_facts
        matched_refs = [ref for match, _ in semantic_matches for ref in (match.anchor_ref, match.candidate_ref)] if semantic_matches else None
        events.append(
            _event_from_facts(
                "information_delivery",
                fact.label_vi or "Hành động/cam kết",
                source_facts,
                semantic_time=_semantic_time_from_temporal_facts(semantic_facts),
                matched_evidence_refs=matched_refs,
            )
        )

    for fact in [item for item in facts if item.type == "payment_method"]:
        money_match = _money_priority(fact, money_facts)
        semantic_matches = _nearby_fact_matches(fact, temporal_facts)
        semantic_facts = [item for _, item in semantic_matches]
        money = money_match[0] if money_match else None
        source_facts = [fact] + ([money] if money else []) + semantic_facts
        matched_refs = []
        if money_match:
            matched_refs.extend([money_match[1].anchor_ref, money_match[1].candidate_ref])
        matched_refs.extend(ref for match, _ in semantic_matches for ref in (match.anchor_ref, match.candidate_ref))
        if money:
            used_money_fact_ids.add(money.id)
        if semantic_facts:
            used_temporal_fact_ids.update(item.id for item in semantic_facts)
        events.append(
            _event_from_facts(
                "payment_discussion",
                "Trao đổi thanh toán",
                source_facts,
                semantic_time=_semantic_time_from_temporal_facts(semantic_facts),
                matched_evidence_refs=matched_refs or None,
            )
        )

    for fact in [item for item in facts if item.type == "policy"]:
        events.append(_event_from_facts("policy_notice", "Thông báo điều khoản/chính sách", [fact]))

    for fact in [item for item in facts if item.type == "offer"]:
        events.append(_event_from_facts("offer_notice", "Thông tin ưu đãi/dịch vụ", [fact]))

    for fact in temporal_facts:
        if fact.id in used_temporal_fact_ids:
            continue
        events.append(
            _event_from_facts(
                "temporal_reference",
                "Mốc thời gian được nhắc tới",
                [fact],
                confidence=min(fact.confidence, 0.62),
                semantic_time=_semantic_time_from_fact(fact),
                requires_review=True,
            )
        )

    for fact in money_facts:
        if fact.id in used_money_fact_ids:
            continue
        if not _is_high_value_or_contextual_money(fact):
            continue
        events.append(
            _event_from_facts(
                "financial_reference",
                "Số tiền được nhắc tới",
                [fact],
                confidence=min(fact.confidence, 0.64),
                requires_review=True,
            )
        )

    return events
