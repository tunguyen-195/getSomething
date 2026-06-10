from __future__ import annotations

from .schemas import EventItem, InsightItem, RiskFlag, stable_id


HIGH_VALUE_PAYMENT_THRESHOLD_VND = 1_000_000


def _has_high_value_payment(event: EventItem) -> bool:
    risk_context = event.risk_context or {}
    amounts = risk_context.get("money_amounts_vnd") if isinstance(risk_context, dict) else None
    if not isinstance(amounts, list):
        return False
    return any(isinstance(amount, int) and amount >= HIGH_VALUE_PAYMENT_THRESHOLD_VND for amount in amounts)


def generate_insights(
    events: list[EventItem],
    risk_flags: list[RiskFlag],
    seed_insights: list[InsightItem] | None = None,
) -> list[InsightItem]:
    insights = list(seed_insights or [])

    for event in events:
        if event.type != "payment_discussion":
            continue
        money_fact_ids = [fact_id for fact_id in event.source_fact_ids if "money" in fact_id]
        if not money_fact_ids:
            continue
        if not _has_high_value_payment(event):
            continue
        insights.append(
            InsightItem(
                id=stable_id("insight_payment_review", event.id, *money_fact_ids),
                type="high_value_payment_action",
                severity="medium",
                title_vi="Thanh toán/số tiền cần kiểm tra",
                description_vi="Hội thoại có nhắc tới phương thức thanh toán kèm số tiền; cần kiểm tra lại evidence trước khi dùng làm kết luận.",
                supporting_item_ids=[event.id],
                source_fact_ids=event.source_fact_ids,
                evidence_refs=event.evidence_refs,
                requires_review=True,
                recommended_action_vi="Mở evidence của sự kiện thanh toán và xác nhận số tiền, điều kiện thanh toán.",
                source_method="deterministic_insight_engine",
            )
        )
        break

    for risk in risk_flags:
        insights.append(
            InsightItem(
                id=stable_id("insight_risk_review", risk.id),
                type="asr_or_data_quality_risk",
                severity=risk.severity,
                title_vi=risk.label_vi or risk.label,
                description_vi=risk.reason_vi,
                supporting_item_ids=[risk.id],
                source_fact_ids=[],
                evidence_refs=risk.evidence_refs,
                requires_review=True,
                recommended_action_vi="Kiểm tra lại transcript/audio tại evidence trước khi sử dụng thông tin này.",
                source_method="deterministic_insight_engine",
            )
        )

    selected: dict[str, InsightItem] = {}
    for insight in insights:
        selected.setdefault(insight.id, insight)
    return list(selected.values())
