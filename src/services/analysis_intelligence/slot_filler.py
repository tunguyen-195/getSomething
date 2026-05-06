from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schemas import DomainFrame, FactItem, InsightItem, SlotItem, SlotType, stable_id


@dataclass
class SlotFillResult:
    slots: list[SlotItem] = field(default_factory=list)
    domain_frames: list[DomainFrame] = field(default_factory=list)
    insight_items: list[InsightItem] = field(default_factory=list)


def _tokens(slot: dict[str, Any]) -> str:
    values = [slot.get("name"), slot.get("label_vi"), *(slot.get("synonyms") or [])]
    return " ".join(str(value or "").lower() for value in values)


def _date_part(value: Any, part: str) -> Any:
    if isinstance(value, dict) and isinstance(value.get(part), dict):
        return value[part]
    return value


def _candidate_score(slot: dict[str, Any], fact: FactItem) -> tuple[int, float]:
    name_text = _tokens(slot)
    slot_type = slot.get("type")
    fact_type = fact.type
    if slot_type == "phone" and fact_type == "phone":
        return 0, -fact.confidence
    if slot_type == "email" and fact_type in {"email", "email_candidate"}:
        return 0 if fact_type == "email" else 1, -fact.confidence
    if slot_type == "id_number" and fact_type == "id_number_candidate":
        return 0, -fact.confidence
    if slot_type == "person" and fact_type == "person_name":
        return 0, -fact.confidence
    if slot_type == "organization" and fact_type == "organization":
        return 0, -fact.confidence
    if slot_type == "location" and fact_type in {"location", "address", "organization"}:
        return 0 if fact_type in {"location", "address"} else 2, -fact.confidence
    if slot_type == "text" and any(token in name_text for token in ("address", "địa chỉ")) and fact_type == "address":
        return 0, -fact.confidence
    if slot_type == "date_time" and fact_type in {"date_range", "date", "time"}:
        if any(token in name_text for token in ("checkout", "check_out", "trả", "end", "kết thúc")) and fact_type == "date_range":
            return 0, -fact.confidence
        if any(token in name_text for token in ("checkin", "check_in", "nhận", "start", "bắt đầu")) and fact_type == "date_range":
            return 0, -fact.confidence
        return 1, -fact.confidence
    if slot_type == "quantity" and fact_type == "quantity":
        unit = ""
        if isinstance(fact.normalized_value, dict):
            unit = str(fact.normalized_value.get("unit") or "").lower()
        if any(token in name_text for token in ("room", "phòng")) and unit == "phòng":
            return 0, -fact.confidence
        if any(token in name_text for token in ("guest", "người", "khách")) and unit == "người":
            return 0, -fact.confidence
        return 2, -fact.confidence
    if slot_type == "money" and fact_type in {"money_range", "money"}:
        amount = fact.normalized_value.get("amount_vnd") if isinstance(fact.normalized_value, dict) else None
        total_bonus = 0 if any(token in name_text for token in ("total", "tổng")) else 1
        return 0 if fact_type == "money_range" else total_bonus, -(amount or 0)
    if slot_type in {"text", "enum"}:
        if "payment" in name_text or "thanh toán" in name_text:
            return (0, -fact.confidence) if fact_type == "payment_method" else (99, 0.0)
        if any(token in name_text for token in ("action", "follow", "hành động", "cam kết")):
            return (0, -fact.confidence) if fact_type == "action" else (99, 0.0)
        if "purpose" in name_text or "mục đích" in name_text:
            return (0, -fact.confidence) if fact_type == "purpose" else (99, 0.0)
    return 99, 0.0


def _best_fact(slot: dict[str, Any], facts: list[FactItem], used_fact_ids: set[str]) -> FactItem | None:
    candidates = []
    for fact in facts:
        score = _candidate_score(slot, fact)
        if score[0] >= 99:
            continue
        reuse_penalty = 5 if fact.id in used_fact_ids else 0
        candidates.append(((score[0] + reuse_penalty, score[1]), fact))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[0][1]


def _slot_value(slot: dict[str, Any], fact: FactItem) -> tuple[Any, Any]:
    value = fact.value
    normalized = fact.normalized_value
    name_text = _tokens(slot)
    if slot.get("type") == "date_time" and fact.type == "date_range":
        if any(token in name_text for token in ("checkout", "check_out", "trả", "end", "kết thúc")):
            return _date_part(fact.normalized_value, "end"), _date_part(fact.normalized_value, "end")
        if any(token in name_text for token in ("checkin", "check_in", "nhận", "start", "bắt đầu")):
            return _date_part(fact.normalized_value, "start"), _date_part(fact.normalized_value, "start")
    return value, normalized


def fill_slots_from_templates(
    facts: list[FactItem],
    templates: list[dict[str, Any]] | None,
) -> SlotFillResult:
    result = SlotFillResult()
    for template in templates or []:
        schema = template.get("schema_json") if isinstance(template.get("schema_json"), dict) else {}
        schema_slots = schema.get("slots") if isinstance(schema.get("slots"), list) else []
        frame_id = stable_id("frame", template.get("template_key"), template.get("version"), template.get("schema_hash"))
        slot_ids: list[str] = []
        source_fact_ids: list[str] = []
        used_fact_ids: set[str] = set()

        for slot in schema_slots:
            if not isinstance(slot, dict) or not slot.get("name"):
                continue
            fact = _best_fact(slot, facts, used_fact_ids)
            if not fact:
                if slot.get("required"):
                    result.insight_items.append(
                        InsightItem(
                            id=stable_id("insight_missing_required_slot", frame_id, slot.get("name")),
                            type="missing_required_slot",
                            severity="medium",
                            title_vi=f"Thiếu trường bắt buộc: {slot.get('label_vi') or slot.get('name')}",
                            description_vi="Mẫu phân tích yêu cầu trường này nhưng extractor deterministic chưa tìm thấy evidence phù hợp.",
                            domain_frame_id=frame_id,
                            template_slot_name=slot.get("name"),
                            evidence_refs=[],
                            requires_review=True,
                            recommended_action_vi="Nghe lại audio/transcript quanh các đoạn nghiệp vụ chính và bổ sung thủ công nếu cần.",
                        )
                    )
                continue
            used_fact_ids.add(fact.id)
            source_fact_ids.append(fact.id)
            value, normalized_value = _slot_value(slot, fact)
            slot_type = slot.get("type") if slot.get("type") in SlotType.__args__ else "text"  # type: ignore[attr-defined]
            item = SlotItem(
                id=stable_id("slot", frame_id, slot.get("name"), fact.id),
                type=slot_type,
                label=slot.get("label_vi") or slot.get("name"),
                label_vi=slot.get("label_vi") or slot.get("name"),
                template_slot_name=slot.get("name"),
                slot_type=slot_type,
                value=value,
                normalized_value=normalized_value,
                required=bool(slot.get("required")),
                source_fact_ids=[fact.id],
                confidence=fact.confidence,
                confidence_reason=f"Slot deterministic map từ fact {fact.type}",
                source_method="deterministic_slot_filler",
                evidence_refs=fact.evidence_refs,
                requires_review=fact.requires_review,
            )
            result.slots.append(item)
            slot_ids.append(item.id)

        result.domain_frames.append(
            DomainFrame(
                id=frame_id,
                domain=schema.get("domain_key") or template.get("template_key") or "selected_template",
                label_vi=schema.get("label_vi") or template.get("name") or "Mẫu phân tích",
                confidence=0.75 if slot_ids else 0.25,
                source_method="deterministic_slot_filler",
                domain_template_id=template.get("id"),
                domain_template_key=template.get("template_key"),
                domain_template_version=template.get("version"),
                schema_hash=template.get("schema_hash"),
                slot_ids=slot_ids,
                source_fact_ids=sorted(set(source_fact_ids)),
                requires_review=bool(result.insight_items),
            )
        )
    return result
