import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.core.config import settings
from src.database.config.database import SessionLocal
from src.database.models.models import ActivityLog
from src.main import app
from src.services.analysis_intelligence.extractor import extract_core_analysis
from src.services.analysis_intelligence.event_synthesizer import synthesize_events
from src.services.analysis_intelligence.schemas import (
    AnalysisGraphV2,
    ClaimItem,
    DomainFrame,
    EntityItem,
    EventItem,
    EvidenceRef,
    FactItem,
    InsightItem,
    RelationItem,
    RiskFlag,
    SegmentUnit,
    sha256_text,
)
from src.services.analysis_intelligence.service import apply_review_preservation, generate_text_graph
from src.services.task_service import extract_visualization_payload, update_task
from tests.test_security import (
    _create_audio_for_task,
    _create_case_for_user,
    _create_orphan_task_for_user,
    _create_task_for_user,
    _create_user,
    _csrf_header,
    _login_client,
    auth_enabled,
)


def _text_ref(text: str = "Gọi 0912345678", *, source_kind: str = "transcript_text") -> EvidenceRef:
    return EvidenceRef(
        source_kind=source_kind,
        source_text_sha256=sha256_text(text),
        text_span=text,
        char_start=0,
        char_end=len(text),
    )


def _segment_ref(text: str = "Gọi 0912345678") -> EvidenceRef:
    return EvidenceRef(
        source_kind="transcript_segment",
        source_text_sha256=sha256_text(text),
        text_span=text,
        char_start=0,
        char_end=len(text),
        audio_id=1,
        segment_id="seg_1",
        start_time=1.0,
        end_time=3.0,
        speaker_id="SPEAKER_00",
    )


def _entity(entity_id: str = "ent_phone_1", ref: EvidenceRef | None = None, **kwargs) -> EntityItem:
    return EntityItem(
        id=entity_id,
        type=kwargs.pop("type", "phone"),
        label=kwargs.pop("label", "0912345678"),
        value=kwargs.pop("value", "0912345678"),
        confidence=kwargs.pop("confidence", 0.95),
        confidence_reason=kwargs.pop("confidence_reason", "regex"),
        source_method=kwargs.pop("source_method", "regex"),
        evidence_refs=[ref or _text_ref()],
        **kwargs,
    )


def _fact(fact_id: str = "fact_phone_1", ref: EvidenceRef | None = None, **kwargs) -> FactItem:
    return FactItem(
        id=fact_id,
        type=kwargs.pop("type", "phone"),
        label=kwargs.pop("label", "Số điện thoại"),
        label_vi=kwargs.pop("label_vi", "Số điện thoại"),
        value=kwargs.pop("value", "0912345678"),
        normalized_value=kwargs.pop("normalized_value", "0912345678"),
        confidence=kwargs.pop("confidence", 0.95),
        confidence_reason=kwargs.pop("confidence_reason", "regex"),
        source_method=kwargs.pop("source_method", "regex"),
        evidence_refs=[ref or _text_ref()],
        **kwargs,
    )


def test_visualization_service_import_does_not_load_asr_stack():
    code = (
        "import importlib, sys\n"
        "importlib.import_module('src.services.visualization_service')\n"
        "for name in ('torch', 'faster_whisper', 'librosa', 'pyannote.audio'):\n"
        "    print(f'{name}={name in sys.modules}')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    loaded = dict(line.split("=", 1) for line in result.stdout.strip().splitlines() if "=" in line)
    assert loaded == {
        "torch": "False",
        "faster_whisper": "False",
        "librosa": "False",
        "pyannote.audio": "False",
    }


def test_context_analysis_parse_failure_log_is_redacted():
    source = Path("src/speech_to_text/transcriber.py").read_text(encoding="utf-8")
    assert "context_analysis={context_analysis}" not in source
    assert "raw_len" in source


def test_vietnamese_core_extractor_captures_hotel_booking_facts():
    text = (
        "Chị là Nguyễn Thị Quyên. Số điện thoại của chị là 0978 711 253. "
        "Địa chỉ email của chị là quyên24a.gmail.com. "
        "Căn cước công dân của chị là 0912 1212 09012. "
        "Chị ở ngày 15 tháng 2 đến ngày 16 tháng 2. "
        "Chị muốn đặt 2 phòng cho 4 người, 2 nam và 2 nữ. "
        "Chị đi với mục đích công tác. Giá phòng là 3 triệu và tổng số tiền là 6 triệu đồng. "
        "Thế để chị chuyển khoản em nhé. Khách sạn sẽ gửi tới email của chị số tài khoản "
        "và điều khoản đặt phòng. Bữa sáng đã bao gồm trong giá phòng. fitness center free."
    )
    segment = SegmentUnit(
        id="seg_sample",
        source_kind="transcript_text",
        text=text,
        source_text_sha256=sha256_text(text),
    )

    core = extract_core_analysis([segment])
    facts_by_type = {}
    for fact in core.facts:
        facts_by_type.setdefault(fact.type, []).append(fact)

    assert any(fact.normalized_value == "0978711253" for fact in facts_by_type["phone"])
    assert any(fact.normalized_value == "quyên24a.gmail.com" for fact in facts_by_type["email_candidate"])
    assert any(fact.normalized_value == "0912121209012" for fact in facts_by_type["id_number_candidate"])
    assert any(fact.normalized_value["start"]["day"] == 15 and fact.normalized_value["end"]["day"] == 16 for fact in facts_by_type["date_range"])
    assert any(fact.normalized_value == {"quantity": 2, "unit": "phòng"} for fact in facts_by_type["quantity"])
    assert any(fact.normalized_value == {"quantity": 4, "unit": "người"} for fact in facts_by_type["quantity"])
    assert any(fact.normalized_value == {"quantity": 2, "unit": "nam"} for fact in facts_by_type["quantity"])
    assert any(fact.normalized_value == {"quantity": 2, "unit": "nữ"} for fact in facts_by_type["quantity"])
    assert any(fact.normalized_value["amount_vnd"] == 3_000_000 for fact in facts_by_type["money"])
    assert any(fact.normalized_value["amount_vnd"] == 6_000_000 for fact in facts_by_type["money"])
    assert any(fact.type == "payment_method" and fact.normalized_value == "chuyển khoản" for fact in core.facts)
    assert any(fact.type == "purpose" for fact in core.facts)
    assert any(fact.type == "action" and "số tài khoản" in fact.value.lower() for fact in core.facts)
    assert any(fact.type == "policy" for fact in core.facts)
    assert any(fact.type == "offer" and "Bữa sáng" in fact.value for fact in core.facts)
    assert any(fact.type == "offer" and "fitness" in fact.value.lower() for fact in core.facts)
    assert all(fact.evidence_refs for fact in core.facts)
    assert any(risk.type == "noisy_email_candidate" for risk in core.risk_flags)


def test_vietnamese_core_extractor_avoids_sample_false_positives_and_duplicates():
    text = (
        "Chị Quyên vui lòng cho em xin họ tên đầy đủ của mình Số điện thoại, địa chỉ email "
        "và số căn cứ công dân của mình. Chị là Nguyễn Thị Quyên. "
        "Số điện thoại của chị là 0978 711 253. Địa chỉ email của chị là quyên24a.gmail.com. "
        "Còn căn cứ công dân của chị là 0912 1212 09012. "
        "Chị ở ngày 15 tháng 2 đến ngày 16 tháng 2 em ạ. "
        "Dạ thưa chị, vào ngày 15 tháng 2 đến ngày 16 tháng 2 thì bên em vẫn còn phòng. "
        "Chị muốn đặt phòng ở bên khách sạn mình ý vào thời gian nào ạ? "
        "Cảm ơn chị đã lựa chọn khách sạn G.R.P.Marius Hotel Hà Nội."
    )
    segment = SegmentUnit(
        id="seg_full_sample",
        source_kind="transcript_text",
        text=text,
        source_text_sha256=sha256_text(text),
    )

    core = extract_core_analysis([segment])
    id_values = {fact.normalized_value for fact in core.facts if fact.type == "id_number_candidate"}
    org_labels = {entity.label for entity in core.entities if entity.type == "organization"}
    fact_keys = [
        (fact.type, json.dumps(fact.normalized_value, ensure_ascii=False, sort_keys=True, default=str))
        for fact in core.facts
    ]
    date_ranges = [fact for fact in core.facts if fact.type == "date_range"]

    assert "0978711253" not in id_values
    assert "0912121209012" in id_values
    assert not any("mình" in label.lower() or "thời gian" in label.lower() for label in org_labels)
    assert "G.R.P.Marius Hotel Hà Nội" in org_labels
    assert len(fact_keys) == len(set(fact_keys))
    assert len(date_ranges) == 1
    assert len(date_ranges[0].evidence_refs) == 2
    assert not [fact for fact in core.facts if fact.type == "date"]


def test_vietnamese_location_and_address_extractor_captures_places_without_org_bleed():
    text = (
        "Khách sạn G.R.P.Marius Hotel Hà Nội ở phố Huế. "
        "Công ty ABC ở Đà Nẵng gọi đến bệnh viện Bạch Mai. "
        "Địa chỉ là số 12 phố Huế, phường Hàng Bài, quận Hoàn Kiếm, Hà Nội. "
        "Khách muốn đặt phòng tại Mỹ Đình."
    )
    segment = SegmentUnit(
        id="seg_locations",
        source_kind="transcript_text",
        text=text,
        source_text_sha256=sha256_text(text),
    )

    core = extract_core_analysis([segment])
    org_labels = {entity.label for entity in core.entities if entity.type == "organization"}
    location_labels = {entity.label for entity in core.entities if entity.type == "location"}
    address_values = {fact.value for fact in core.facts if fact.type == "address"}

    assert "G.R.P.Marius Hotel Hà Nội" in org_labels
    assert "ABC" in org_labels
    assert not any(label.endswith(" ở") or " ở Đà Nẵng" in label for label in org_labels)
    assert {"Đà Nẵng", "Bạch Mai", "Mỹ Đình"}.issubset(location_labels)
    assert not any("." in label and "Công ty" in label for label in location_labels)
    assert any("số 12 phố Huế" in value and "Hoàn Kiếm" in value for value in address_values)

    abc_org = next(entity for entity in core.entities if entity.type == "organization" and entity.label == "ABC")
    bach_mai_org = next(entity for entity in core.entities if entity.type == "organization" and entity.label == "Bạch Mai")
    assert not any("ở Đà Nẵng" in ref.text_span for ref in abc_org.evidence_refs)
    assert not any(". Địa" in ref.text_span for ref in bach_mai_org.evidence_refs)

    graph = generate_text_graph(text)
    key_pairs = {(item["type"], item["value"]) for item in graph.key_items}
    assert ("location", "Đà Nẵng") in key_pairs
    assert ("location", "Mỹ Đình") in key_pairs
    assert any(item["type"] == "address" and "số 12 phố Huế" in item["value"] for item in graph.key_items)
    assert not any(
        item["type"] == "location" and "." in item["value"] and "Công ty" in item["value"]
        for item in graph.key_items
    )


def test_vietnamese_location_extractor_handles_city_and_full_address_smokes():
    city_graph = generate_text_graph("Chị sẽ nhận phòng tại Hà Nội ngày 15 tháng 2.")
    address_graph = generate_text_graph("Địa chỉ là số 12 phố Huế, phường Hàng Bài, quận Hoàn Kiếm, Hà Nội.")

    assert any(item["type"] == "location" and item["value"] == "Hà Nội" for item in city_graph.key_items)
    assert any(item["type"] == "address" and "quận Hoàn Kiếm" in item["value"] for item in address_graph.key_items)


def test_time_extractor_does_not_treat_breakfast_as_timeline_time():
    text = "Bữa sáng đã bao gồm trong giá phòng. Sáng mai chị chuyển khoản lúc 09:30."
    segment = SegmentUnit(
        id="seg_time_context",
        source_kind="transcript_text",
        text=text,
        source_text_sha256=sha256_text(text),
    )

    core = extract_core_analysis([segment])
    time_values = [fact.value.lower() for fact in core.facts if fact.type == "time"]

    assert "sáng" not in time_values
    assert any("sáng mai" in value or "09:30" in value for value in time_values)

    graph = generate_text_graph(text)
    payment_timeline = next(item for item in graph.timeline if item["type"] == "payment_discussion")
    assert payment_timeline["time"] == "sáng mai, 09:30"
    assert not [item for item in graph.timeline if item["type"] == "temporal_reference"]


def test_canonical_key_items_dedupe_money_and_date_semantics():
    ref = _segment_ref("Ngày 15 tháng 2, số tiền 6 triệu đồng")
    date_fact = _fact(
        "fact_date_1",
        ref,
        type="date",
        label="Ngày/tháng",
        label_vi="Ngày/tháng",
        value="ngày 15 tháng 2",
        normalized_value={"day": 15, "month": 2, "year": None},
    )
    money_fact = _fact(
        "fact_money_1",
        ref,
        type="money",
        label="Số tiền",
        label_vi="Số tiền",
        value="6 triệu đồng",
        normalized_value={"text": "6 triệu đồng", "amount_vnd": 6_000_000},
    )
    date_entity = _entity("ent_date_1", ref, type="date", label="yyyy-02-15", value="yyyy-02-15")
    money_entity = _entity("ent_money_1", ref, type="money", label="6000000", value="6000000")

    segment = SegmentUnit(
        id="seg_1",
        source_kind="transcript_segment",
        text=ref.text_span,
        source_text_sha256=ref.source_text_sha256,
        audio_id=1,
        start_time=1.0,
        end_time=3.0,
        speaker_id="SPEAKER_00",
    )
    graph = AnalysisGraphV2(segments=[segment], facts=[date_fact, money_fact], entities=[date_entity, money_entity])
    canonical_pairs = [(item["type"], item["canonical_value"]) for item in graph.key_items]

    assert canonical_pairs.count(("date", "date:yyyy-02-15")) == 1
    assert canonical_pairs.count(("money", "money:6000000")) == 1


def test_low_value_transfer_does_not_generate_high_value_payment_insight():
    graph = generate_text_graph("Phí giữ chỗ là 50.000 đồng và chị chuyển khoản sau.")

    assert any(event.type == "payment_discussion" for event in graph.events)
    assert not [item for item in graph.insight_items if item.type == "high_value_payment_action"]


def test_evidence_source_kind_rules_and_review_defaults():
    text_entity = _entity(ref=_text_ref())
    assert text_entity.requires_review is True
    assert text_entity.review_status == "needs_review"

    with pytest.raises(ValueError, match="start_time/end_time"):
        EvidenceRef(
            source_kind="transcript_segment",
            source_text_sha256=sha256_text("hello"),
            text_span="hello",
            char_start=0,
            char_end=5,
            audio_id=1,
            segment_id="seg_1",
        )

    with pytest.raises(ValueError, match="requires timestamp and speaker grounding"):
        RelationItem(
            id="rel_owns_phone_1",
            type="owns_phone",
            label="owns phone",
            source_entity_id="ent_person_1",
            target_entity_id="ent_phone_1",
            confidence=0.8,
            confidence_reason="not grounded",
            source_method="test",
            evidence_refs=[_text_ref()],
        )


def test_graph_validation_regenerates_aliases_and_rejects_bad_references():
    segment = SegmentUnit(
        id="seg_1",
        source_kind="transcript_segment",
        text="Gọi 0912345678",
        source_text_sha256=sha256_text("Gọi 0912345678"),
        audio_id=1,
        start_time=1.0,
        end_time=3.0,
        speaker_id="SPEAKER_00",
    )
    active = _entity("ent_phone_active", _segment_ref("Gọi 0987654321"), label="0987654321", value="0987654321")
    rejected = _entity("ent_phone_rejected", _segment_ref(), review_status="rejected")
    graph = AnalysisGraphV2(
        segments=[segment],
        entities=[active, rejected],
        nodes=[{"id": "fake"}],
    )

    assert graph.nodes == graph.legacy_view.nodes
    assert [node["id"] for node in graph.nodes] == ["ent_phone_active"]
    assert "fake" not in {node["id"] for node in graph.nodes}

    with pytest.raises(ValueError, match="Relation references missing entity"):
        AnalysisGraphV2(
            segments=[segment],
            entities=[active],
            relations=[
                RelationItem(
                    id="rel_missing",
                    type="mentions_object",
                    label="mentions",
                    source_entity_id="missing",
                    target_entity_id=active.id,
                    confidence=0.7,
                    confidence_reason="test",
                    source_method="test",
                    evidence_refs=[_segment_ref()],
                )
            ],
        )


def test_graph_regenerates_timeline_insights_and_key_items_from_canonical_sources():
    segment = SegmentUnit(
        id="seg_1",
        source_kind="transcript_segment",
        text="Gọi 0912345678",
        source_text_sha256=sha256_text("Gọi 0912345678"),
        audio_id=1,
        start_time=1.0,
        end_time=3.0,
        speaker_id="SPEAKER_00",
    )
    ref = _segment_ref()
    fact = _fact("fact_phone_1", ref)
    event = EventItem(
        id="evt_call_1",
        type="temporal_reference",
        label="Mốc thời gian được nhắc tới",
        confidence=0.7,
        confidence_reason="test",
        source_method="test",
        evidence_refs=[ref],
        source_fact_ids=[fact.id],
        start_time=1.0,
        end_time=3.0,
    )
    insight = InsightItem(
        id="insight_1",
        type="asr_or_data_quality_risk",
        severity="medium",
        title_vi="Cần kiểm tra",
        description_vi="Có item cần kiểm tra",
        supporting_item_ids=[event.id],
        evidence_refs=[ref],
    )
    graph = AnalysisGraphV2(
        segments=[segment],
        entities=[_entity("ent_phone_1", ref)],
        facts=[fact],
        events=[event],
        insight_items=[insight],
        timeline=[{"id": "fake_timeline", "event": "fake"}],
        insights=["fake insight"],
        key_items=[{"id": "fake_key", "value": "fake"}],
    )

    assert [item["id"] for item in graph.timeline] == [event.id]
    assert graph.insights == [insight.title_vi]
    assert graph.legacy_view.insights == graph.insights
    assert graph.key_items == graph.legacy_view.extracted_entities
    assert "fake_key" not in {item["id"] for item in graph.key_items}


def test_graph_validation_rejects_dangling_event_and_insight_references():
    ref = _segment_ref()
    fact = _fact("fact_phone_1", ref)
    event = EventItem(
        id="evt_bad_fact",
        type="temporal_reference",
        label="Bad",
        confidence=0.7,
        confidence_reason="test",
        source_method="test",
        evidence_refs=[ref],
        source_fact_ids=["missing_fact"],
    )
    with pytest.raises(ValueError, match="Event references missing fact"):
        AnalysisGraphV2(facts=[fact], events=[event])

    good_event = EventItem(
        id="evt_good",
        type="temporal_reference",
        label="Good",
        confidence=0.7,
        confidence_reason="test",
        source_method="test",
        evidence_refs=[ref],
        source_fact_ids=[fact.id],
        entity_ids=["missing_entity"],
    )
    with pytest.raises(ValueError, match="Event references missing entity"):
        AnalysisGraphV2(facts=[fact], events=[good_event])

    insight = InsightItem(
        id="insight_bad",
        type="asr_or_data_quality_risk",
        severity="medium",
        title_vi="Bad",
        description_vi="Bad",
        supporting_item_ids=["missing_item"],
        evidence_refs=[ref],
    )
    with pytest.raises(ValueError, match="Insight references missing supporting item"):
        AnalysisGraphV2(facts=[fact], insight_items=[insight])

    claim = ClaimItem(
        id="claim_bad_fact",
        type="claim",
        label="Bad claim",
        confidence=0.7,
        confidence_reason="test",
        source_method="test",
        evidence_refs=[ref],
        source_fact_ids=["missing_fact"],
    )
    with pytest.raises(ValueError, match="Claim references missing fact"):
        AnalysisGraphV2(facts=[fact], claims=[claim])

    with pytest.raises(ValueError, match="missing_required_slot requires domain_frame_id"):
        InsightItem(
            id="insight_missing_bad",
            type="missing_required_slot",
            severity="medium",
            title_vi="Missing",
            description_vi="Missing",
            evidence_refs=[],
        )


def test_review_preservation_keeps_stable_item_review_metadata():
    ref = _text_ref()
    old_graph = AnalysisGraphV2(
        entities=[
            _entity(
                "ent_phone_same",
                ref,
                review_status="confirmed",
                reviewed_by=7,
                reviewed_at="2026-05-03T00:00:00+00:00",
                review_note="verified",
            )
        ]
    )
    new_graph = AnalysisGraphV2(entities=[_entity("ent_phone_same", ref)])

    preserved = apply_review_preservation(new_graph, old_graph.to_storage_dict())
    item = preserved.entities[0]
    assert item.review_status == "confirmed"
    assert item.reviewed_by == 7
    assert item.review_note == "verified"


def test_generate_text_graph_synthesizes_reviewable_timeline_and_insights():
    graph = generate_text_graph(
        "Khách muốn đặt phòng ngày 15 tháng 2 đến ngày 16 tháng 2. "
        "Tổng số tiền là 6 triệu đồng và sẽ chuyển khoản."
    )

    assert graph.facts
    assert graph.events
    assert graph.timeline
    assert graph.insight_items
    assert all(event.requires_review for event in graph.events)
    assert all(event.review_status == "needs_review" for event in graph.events)
    assert all(insight.review_status == "needs_review" for insight in graph.insight_items if insight.requires_review)


def test_visibility_blocks_derived_outputs_from_rejected_source_fact():
    graph = generate_text_graph("Tổng số tiền là 6 triệu đồng và chị sẽ chuyển khoản.")
    money_fact = next(
        fact
        for fact in graph.facts
        if fact.type == "money" and fact.normalized_value.get("amount_vnd") == 6_000_000
    )
    payment_event = next(event for event in graph.events if event.type == "payment_discussion")
    payment_insight = next(item for item in graph.insight_items if item.type == "high_value_payment_action")

    data = graph.to_storage_dict()
    for fact in data["facts"]:
        if fact["id"] == money_fact.id:
            fact["review_status"] = "rejected"
            fact["reviewed_by"] = 7
            fact["reviewed_at"] = "2026-05-05T00:00:00+00:00"
            break

    updated = AnalysisGraphV2(**data)
    blocked_ids = set(updated.visibility.blocked_item_ids)

    assert money_fact.id in blocked_ids
    assert payment_event.id in blocked_ids
    assert payment_insight.id in blocked_ids
    assert any(event.id == payment_event.id for event in updated.events)
    assert any(item.id == payment_insight.id for item in updated.insight_items)
    assert payment_event.id not in {item["id"] for item in updated.timeline}
    assert payment_insight.title_vi not in updated.insights
    assert money_fact.id not in {item["id"] for item in updated.key_items}
    assert "money:6000000" not in {item.get("canonical_value") for item in updated.key_items}
    assert all(entity.id in blocked_ids for entity in updated.entities if entity.type == "money")
    assert any(
        reason == f"source_fact_blocked:{money_fact.id}"
        for reason in updated.visibility.blocked_reasons[payment_event.id]
    )
    assert all("6 triệu" not in reason for reasons in updated.visibility.blocked_reasons.values() for reason in reasons)


def test_visibility_blocks_risk_supported_insight_and_claim_with_rejected_entity():
    ref = _text_ref("quyên24a.gmail.com")
    risk = RiskFlag(
        id="risk_email_1",
        type="noisy_email_candidate",
        label="Email cần kiểm tra",
        label_vi="Email cần kiểm tra",
        value="quyên24a.gmail.com",
        normalized_value="quyên24a.gmail.com",
        confidence=0.8,
        confidence_reason="test",
        source_method="test",
        evidence_refs=[ref],
        severity="medium",
        category="data_quality",
        reason_vi="Email thiếu ký tự @",
        review_status="rejected",
    )
    risk_insight = InsightItem(
        id="insight_risk_1",
        type="asr_or_data_quality_risk",
        severity="medium",
        title_vi="Email cần kiểm tra",
        description_vi="Email thiếu ký tự @",
        supporting_item_ids=[risk.id],
        evidence_refs=[ref],
        requires_review=True,
    )
    rejected_entity = _entity("ent_customer_1", ref, type="person", label="Nguyễn Thị Quyên", review_status="rejected")
    claim = ClaimItem(
        id="claim_customer_1",
        type="claim",
        label="Khách hàng là Nguyễn Thị Quyên",
        confidence=0.7,
        confidence_reason="test",
        source_method="test",
        evidence_refs=[ref],
        entity_ids=[rejected_entity.id],
    )

    graph = AnalysisGraphV2(entities=[rejected_entity], claims=[claim], risk_flags=[risk], insight_items=[risk_insight])

    assert risk.id in graph.visibility.blocked_item_ids
    assert risk_insight.id in graph.visibility.blocked_item_ids
    assert claim.id in graph.visibility.blocked_item_ids
    assert graph.insights == []
    assert claim.label not in graph.main_events


def test_missing_required_slot_insight_keeps_frame_visible_without_text_evidence():
    frame = DomainFrame(id="frame_hotel_1", domain="hotel_booking", label_vi="Đặt phòng khách sạn")
    insight = InsightItem(
        id="insight_missing_checkout",
        type="missing_required_slot",
        severity="medium",
        title_vi="Thiếu ngày trả phòng",
        description_vi="Mẫu yêu cầu ngày trả phòng nhưng transcript chưa có.",
        domain_frame_id=frame.id,
        template_slot_name="checkout",
        evidence_refs=[],
        requires_review=True,
    )

    graph = AnalysisGraphV2(domain_frames=[frame], insight_items=[insight])

    assert frame.id in graph.visibility.visible_item_ids
    assert insight.id in graph.visibility.visible_item_ids
    assert graph.insights == [insight.title_vi]


def test_key_info_semantic_suppression_blocks_unconfirmed_siblings():
    ref = _text_ref("Chị là Nguyễn Thị Quyên. Gọi 0912345678")
    phone_fact = _fact("fact_phone_rejected", ref, review_status="rejected")
    phone_entity = _entity("ent_phone_sibling", ref)
    person_fact = _fact(
        "fact_person_rejected",
        ref,
        type="person_name",
        label="Tên người",
        label_vi="Tên người",
        value="Nguyễn Thị Quyên",
        normalized_value="Nguyễn Thị Quyên",
        review_status="rejected",
    )
    person_entity = _entity(
        "ent_person_sibling",
        ref,
        type="person",
        label="Nguyễn Thị Quyên",
        value="Nguyễn Thị Quyên",
    )

    graph = AnalysisGraphV2(
        entities=[phone_entity, person_entity],
        facts=[phone_fact, person_fact],
    )

    assert phone_fact.id in graph.visibility.blocked_item_ids
    assert phone_entity.id in graph.visibility.blocked_item_ids
    assert person_fact.id in graph.visibility.blocked_item_ids
    assert person_entity.id in graph.visibility.blocked_item_ids
    assert not [item for item in graph.key_items if item["type"] in {"phone", "person", "person_name"}]


def test_key_info_semantic_suppression_keeps_confirmed_sibling_visible():
    ref = _text_ref("Gọi 0912345678")
    phone_fact = _fact("fact_phone_rejected", ref, review_status="rejected")
    confirmed_entity = _entity("ent_phone_confirmed", ref, review_status="confirmed")

    graph = AnalysisGraphV2(entities=[confirmed_entity], facts=[phone_fact])

    assert phone_fact.id in graph.visibility.blocked_item_ids
    assert confirmed_entity.id in graph.visibility.visible_item_ids
    assert any(item["id"] == confirmed_entity.id and item["type"] == "phone" for item in graph.key_items)


def test_visibility_reason_codes_are_sanitized_and_canonicalized():
    frame = DomainFrame(id="frame_empty", domain="hotel_booking", label_vi="Đặt phòng khách sạn")
    graph = AnalysisGraphV2(domain_frames=[frame])
    allowed_exact = {"own_rejected", "not_effectively_visible"}
    allowed_prefixes = (
        "source_fact_blocked:",
        "entity_blocked:",
        "relation_endpoint_blocked:",
        "slot_blocked:",
        "supporting_item_blocked:",
        "domain_frame_blocked:",
        "semantic_key_blocked:",
    )

    assert graph.visibility.blocked_reasons[frame.id] == ["domain_frame_blocked:no_visible_source"]
    for reasons in graph.visibility.blocked_reasons.values():
        for reason in reasons:
            assert reason != "no_visible_sources"
            assert reason in allowed_exact or reason.startswith(allowed_prefixes)


def test_visibility_state_covers_all_known_item_ids_and_preserves_raw_blocked_items():
    graph = generate_text_graph("Tổng số tiền là 6 triệu đồng và chị sẽ chuyển khoản.")
    data = graph.to_storage_dict()
    rejected_fact_id = next(item["id"] for item in data["facts"] if item["type"] == "money")
    for fact in data["facts"]:
        if fact["id"] == rejected_fact_id:
            fact["review_status"] = "rejected"
    updated = AnalysisGraphV2(**data)
    all_ids = {
        item["id"]
        for key in ("entities", "relations", "events", "claims", "facts", "risk_flags", "slots", "domain_frames", "insight_items")
        for item in updated.to_storage_dict().get(key, [])
    }
    covered_ids = set(updated.visibility.visible_item_ids) | set(updated.visibility.blocked_item_ids)

    assert covered_ids == all_ids
    assert any(item.id == rejected_fact_id for item in updated.facts)
    assert rejected_fact_id not in {item["id"] for item in updated.key_items}
    assert "money:6000000" not in {item.get("canonical_value") for item in updated.key_items}


def test_event_synthesis_keeps_temporal_matching_within_segment():
    date_text = "Ngày 15 tháng 2 vẫn còn phòng."
    request_text = "Khách muốn đặt 2 phòng."
    segments = [
        SegmentUnit(
            id="seg_date",
            source_kind="transcript_segment",
            text=date_text,
            source_text_sha256=sha256_text(date_text),
            audio_id=1,
            start_time=0.0,
            end_time=2.0,
            speaker_id="SPEAKER_00",
        ),
        SegmentUnit(
            id="seg_request",
            source_kind="transcript_segment",
            text=request_text,
            source_text_sha256=sha256_text(request_text),
            audio_id=1,
            start_time=3.0,
            end_time=5.0,
            speaker_id="SPEAKER_01",
        ),
    ]
    core = extract_core_analysis(segments)
    date_fact = next(fact for fact in core.facts if fact.type == "date")
    request_event = next(event for event in synthesize_events(core.facts, core.entities) if event.type == "booking_request")

    assert date_fact.id not in request_event.source_fact_ids
    assert request_event.semantic_time is None


def test_payment_event_uses_matched_evidence_refs_from_same_segment_only():
    first_text = "Tổng số tiền là 6 triệu đồng."
    second_text = "Chị sẽ chuyển khoản 6 triệu đồng."
    segments = [
        SegmentUnit(
            id="seg_money_old",
            source_kind="transcript_segment",
            text=first_text,
            source_text_sha256=sha256_text(first_text),
            audio_id=1,
            start_time=0.0,
            end_time=2.0,
            speaker_id="SPEAKER_00",
        ),
        SegmentUnit(
            id="seg_payment",
            source_kind="transcript_segment",
            text=second_text,
            source_text_sha256=sha256_text(second_text),
            audio_id=1,
            start_time=3.0,
            end_time=5.0,
            speaker_id="SPEAKER_01",
        ),
    ]
    core = extract_core_analysis(segments)
    money_fact = next(
        fact
        for fact in core.facts
        if fact.type == "money" and fact.normalized_value.get("amount_vnd") == 6_000_000
    )
    assert {ref.segment_id for ref in money_fact.evidence_refs} == {"seg_money_old", "seg_payment"}

    payment_event = next(event for event in synthesize_events(core.facts, core.entities) if event.type == "payment_discussion")

    assert money_fact.id in payment_event.source_fact_ids
    assert {ref.segment_id for ref in payment_event.evidence_refs} == {"seg_payment"}


def test_frontend_uses_effective_visibility_for_evidence_lists_and_key_types():
    panel_source = Path("frontend/src/components/AnalysisPanel.tsx").read_text(encoding="utf-8")
    utility_source = Path("frontend/src/utils/visualization.ts").read_text(encoding="utf-8")

    assert "const isEffectivelyVisibleEvidenceItem" in panel_source
    for name in ("entities", "relations", "events", "claims", "facts", "slots", "risk_flags", "insight_items"):
        assert f"graph.{name} || []).filter(item => isEffectivelyVisibleEvidenceItem(item, graph))" in panel_source
    for key_type in ("date_time", "person", "person_name", "organization", "location", "address"):
        assert f"'{key_type}'" in utility_source
    for switch_case in ("case 'person':", "case 'person_name':", "case 'organization':", "case 'location':", "case 'address':"):
        assert switch_case in panel_source
    assert "const isPlaceKeyInfo" in panel_source
    assert "getKeyEntities(f.visualization_data)" in panel_source


def test_extract_visualization_payload_preserves_v2_container():
    graph = AnalysisGraphV2(entities=[_entity()])
    payload = graph.to_storage_dict()

    assert extract_visualization_payload(payload) == payload
    assert extract_visualization_payload({"visualization_data": payload}) == payload


def test_review_endpoint_updates_graph_and_enforces_revision(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    _create_audio_for_task(user_id, case_id, task_id, status="transcribed")
    assert update_task(
        task_id,
        {
            "transcript": "SPEAKER_00 gọi số 0912345678 lúc 10:30",
            "segments": [
                {
                    "id": "seg_1",
                    "text": "SPEAKER_00 gọi số 0912345678 lúc 10:30",
                    "start": 0.0,
                    "end": 4.0,
                    "speaker": "SPEAKER_00",
                }
            ],
        },
    )

    client = _login_client(username, password)
    headers = _csrf_header(client)
    response = client.post(
        f"/api/v1/audio/v2/visualize/{task_id}",
        json={"visualization_type": "all"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    graph = response.json()["visualization_data"]
    entity_id = graph["entities"][0]["id"]

    review = client.patch(
        f"/api/v1/audio/v2/visualize/{task_id}/items/{entity_id}/review",
        json={
            "review_status": "confirmed",
            "expected_revision": graph["graph_revision"],
            "review_note": "checked",
        },
        headers=headers,
    )
    assert review.status_code == 200, review.text
    assert review.headers["cache-control"] == "no-store"
    assert review.headers["pragma"] == "no-cache"
    updated = review.json()["visualization_data"]
    assert updated["graph_revision"] == graph["graph_revision"] + 1
    assert updated["entities"][0]["review_status"] == "confirmed"
    assert updated["nodes"][0]["review_status"] == "confirmed"

    conflict = client.patch(
        f"/api/v1/audio/v2/visualize/{task_id}/items/{entity_id}/review",
        json={"review_status": "rejected", "expected_revision": graph["graph_revision"]},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.headers["cache-control"] == "no-store"
    assert conflict.headers["pragma"] == "no-cache"
    assert conflict.json()["detail"]["current_revision"] == updated["graph_revision"]


def test_visualize_endpoint_accepts_audio_id_for_frontend_fallback(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    audio_id = _create_audio_for_task(user_id, case_id, task_id, status="transcribed")
    assert update_task(
        task_id,
        {
            "transcript": "SPEAKER_00 gọi số 0912345678",
            "segments": [
                {
                    "id": "seg_1",
                    "text": "SPEAKER_00 gọi số 0912345678",
                    "start": 0.0,
                    "end": 2.0,
                    "speaker": "SPEAKER_00",
                }
            ],
        },
    )

    client = _login_client(username, password)
    response = client.post(
        f"/api/v1/audio/v2/visualize/{audio_id}",
        json={"visualization_type": "all"},
        headers=_csrf_header(client),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == task_id
    assert body["visualization_data"]["schema_version"] == "analysis_intelligence.v2"
    assert body["visualization_data"]["selected_template_ids"] == []

    general_with_ids = client.post(
        f"/api/v1/audio/v2/visualize/{audio_id}",
        json={"visualization_type": "all", "analysis_mode": "general", "domain_template_ids": [999999]},
        headers=_csrf_header(client),
    )
    assert general_with_ids.status_code == 200, general_with_ids.text
    assert general_with_ids.json()["visualization_data"]["selected_template_ids"] == []


def test_selected_template_generates_slots_events_timeline_and_reviewable_insights(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    audio_id = _create_audio_for_task(user_id, case_id, task_id, status="transcribed")
    text = (
        "Chị là Nguyễn Thị Quyên. Số điện thoại của chị là 0978 711 253. "
        "Chị ở ngày 15 tháng 2 đến ngày 16 tháng 2. "
        "Chị muốn đặt 2 phòng cho 4 người. Giá phòng là 3 triệu và tổng số tiền là 6 triệu đồng. "
        "Thế để chị chuyển khoản em nhé. Khách sạn sẽ gửi tới email của chị số tài khoản "
        "và điều khoản đặt phòng. Bữa sáng đã bao gồm trong giá phòng."
    )
    assert update_task(
        task_id,
        {
            "transcript": text,
            "audio_id": audio_id,
            "segments": [{"id": "seg_1", "text": text, "start": 0.0, "end": 28.0, "speaker": "SPEAKER_00"}],
        },
    )

    client = _login_client(username, password)
    headers = _csrf_header(client)
    template_key = f"hotel_booking_{uuid.uuid4().hex[:8]}"
    template_payload = {
        "template_key": template_key,
        "name": "Đặt phòng khách sạn",
        "language": "vi",
        "scope": "user",
        "schema_json": {
            "domain_key": template_key,
            "label_vi": "Đặt phòng khách sạn",
            "language": "vi",
            "slots": [
                {"name": "customer_name", "label_vi": "Tên khách hàng", "type": "person", "required": True, "synonyms": ["họ tên"]},
                {"name": "phone", "label_vi": "Số điện thoại", "type": "phone", "required": True, "synonyms": ["điện thoại"]},
                {"name": "checkin", "label_vi": "Ngày nhận phòng", "type": "date_time", "required": True, "synonyms": ["nhận phòng"]},
                {"name": "checkout", "label_vi": "Ngày trả phòng", "type": "date_time", "required": True, "synonyms": ["trả phòng"]},
                {"name": "room_count", "label_vi": "Số phòng", "type": "quantity", "required": True, "synonyms": ["số phòng"]},
                {"name": "guest_count", "label_vi": "Số khách", "type": "quantity", "required": True, "synonyms": ["số người"]},
                {"name": "total_money", "label_vi": "Tổng tiền", "type": "money", "required": False, "synonyms": ["tổng tiền"]},
                {"name": "payment_method", "label_vi": "Thanh toán", "type": "text", "required": False, "synonyms": ["thanh toán"]},
                {"name": "follow_up_action", "label_vi": "Hành động tiếp theo", "type": "text", "required": False, "synonyms": ["hành động"]},
                {"name": "booking_confirmation", "label_vi": "Xác nhận đặt phòng", "type": "text", "required": True, "synonyms": ["xác nhận"]},
            ],
        },
    }
    created = client.post("/api/v1/analysis/templates", json=template_payload, headers=headers)
    assert created.status_code == 200, created.text
    published = client.post(f"/api/v1/analysis/templates/{created.json()['id']}/publish", headers=headers)
    assert published.status_code == 200, published.text
    template_id = published.json()["id"]

    response = client.post(
        f"/api/v1/audio/v2/visualize/{task_id}",
        json={"visualization_type": "all", "analysis_mode": "selected", "domain_template_ids": [template_id]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    graph = response.json()["visualization_data"]
    assert len(graph["facts"]) >= 9
    assert len(graph["events"]) >= 4
    assert len(graph["timeline"]) >= 4
    assert len(graph["slots"]) >= 5
    assert len(graph["domain_frames"]) >= 1
    assert any(item["type"] == "missing_required_slot" for item in graph["insight_items"])
    assert graph["insights"] == graph["legacy_view"]["insights"]
    assert graph["key_items"] == graph["legacy_view"]["extracted_entities"]
    key_pairs = [(item["type"], item.get("canonical_value")) for item in graph["key_items"]]
    assert len(key_pairs) == len(set(key_pairs))
    date_time_items = [item for item in graph["key_items"] if item["type"] == "date_time"]
    assert {
        item["canonical_value"]
        for item in date_time_items
    } >= {"date_time:yyyy-02-15", "date_time:yyyy-02-16"}
    assert {item["source_item_type"] for item in date_time_items} == {"slot"}

    insight = next(item for item in graph["insight_items"] if item["type"] == "missing_required_slot")
    review = client.patch(
        f"/api/v1/audio/v2/visualize/{task_id}/items/{insight['id']}/review",
        json={"review_status": "rejected", "expected_revision": graph["graph_revision"]},
        headers=headers,
    )
    assert review.status_code == 200, review.text
    assert insight["title_vi"] not in review.json()["visualization_data"]["insights"]

    regenerated = client.post(
        f"/api/v1/audio/v2/visualize/{task_id}",
        json={"visualization_type": "all", "analysis_mode": "selected", "domain_template_ids": [template_id]},
        headers=headers,
    )
    assert regenerated.status_code == 200, regenerated.text
    regenerated_graph = regenerated.json()["visualization_data"]
    rejected = next(item for item in regenerated_graph["insight_items"] if item["id"] == insight["id"])
    assert rejected["review_status"] == "rejected"
    assert insight["title_vi"] not in regenerated_graph["legacy_view"]["insights"]


def test_analysis_template_registry_versioning_auth_and_audit(auth_enabled):
    user_id, username, password = _create_user()
    client = _login_client(username, password)
    headers = _csrf_header(client)
    template_key = f"hotel_booking_{uuid.uuid4().hex[:8]}"
    payload = {
        "template_key": template_key,
        "name": "Đặt phòng khách sạn",
        "description": "Mẫu trích xuất thông tin đặt phòng",
        "language": "vi",
        "scope": "user",
        "schema_json": {
            "domain_key": template_key,
            "label_vi": "Đặt phòng khách sạn",
            "description": "Thông tin đặt phòng",
            "language": "vi",
            "slots": [
                {
                    "name": "customer_name",
                    "label_vi": "Tên khách hàng",
                    "type": "person",
                    "required": True,
                    "synonyms": ["tên khách", "họ tên"],
                    "description": "Tên người đặt phòng",
                },
                {
                    "name": "room_count",
                    "label_vi": "Số phòng",
                    "type": "quantity",
                    "required": True,
                    "synonyms": ["số phòng"],
                    "description": "Số lượng phòng cần đặt",
                },
            ],
        },
        "examples_json": [
            {
                "name": "positive",
                "transcript": "Chị Nguyễn Thị Quyên muốn đặt 2 phòng.",
                "expected_slots": {"customer_name": "Nguyễn Thị Quyên", "room_count": 2},
            }
        ],
    }

    forbidden_global = client.post(
        "/api/v1/analysis/templates",
        json={**payload, "scope": "global"},
        headers=headers,
    )
    assert forbidden_global.status_code == 403

    unauth_validate = TestClient(app).post("/api/v1/analysis/templates/validate", json=payload)
    assert unauth_validate.status_code == 401
    authed_validate = client.post("/api/v1/analysis/templates/validate", json=payload, headers=headers)
    assert authed_validate.status_code == 200, authed_validate.text

    created = client.post("/api/v1/analysis/templates", json=payload, headers=headers)
    assert created.status_code == 200, created.text
    template = created.json()
    assert template["version"] == 1
    assert template["status"] == "draft"

    published = client.post(f"/api/v1/analysis/templates/{template['id']}/publish", headers=headers)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    edited = client.patch(
        f"/api/v1/analysis/templates/{template['id']}",
        json={**payload, "name": "Đặt phòng khách sạn v2"},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    edited_body = edited.json()
    assert edited_body["version"] == 2
    assert edited_body["status"] == "draft"
    assert edited_body["parent_template_id"] == template["id"]

    db = SessionLocal()
    try:
        details = [
            row.action_detail
            for row in db.query(ActivityLog).filter(ActivityLog.user_id == user_id).all()
            if (row.action_detail or {}).get("resource") == "analysis_domain_template"
        ]
    finally:
        db.close()

    assert {detail["action"] for detail in details} >= {"create", "publish", "edit"}
    assert all("schema_json" not in detail and "examples_json" not in detail for detail in details)
    assert all("template_key" in detail and "version" in detail for detail in details)


def test_visualize_authorizes_legacy_task_by_linked_audio_case(auth_enabled):
    user_id, username, password = _create_user()
    other_user_id, _, _ = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_orphan_task_for_user(other_user_id)
    audio_id = _create_audio_for_task(user_id, case_id, task_id, status="transcribed")
    assert update_task(
        task_id,
        {
            "transcript": "SPEAKER_00 gọi số 0912345678",
            "segments": [
                {
                    "id": "seg_1",
                    "text": "SPEAKER_00 gọi số 0912345678",
                    "start": 0.0,
                    "end": 2.0,
                    "speaker": "SPEAKER_00",
                }
            ],
        },
    )

    client = _login_client(username, password)
    response = client.post(
        f"/api/v1/audio/v2/visualize/{audio_id}",
        json={"visualization_type": "all"},
        headers=_csrf_header(client),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == task_id
    assert body["visualization_data"]["schema_version"] == "analysis_intelligence.v2"


def test_merge_entities_rejects_self_loop_relations(auth_enabled):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    _create_audio_for_task(user_id, case_id, task_id, status="transcribed")
    text = "A gọi B qua điện thoại"
    segment = SegmentUnit(
        id="seg_1",
        source_kind="transcript_segment",
        text=text,
        source_text_sha256=sha256_text(text),
        audio_id=1,
        start_time=1.0,
        end_time=3.0,
        speaker_id="SPEAKER_00",
    )
    ref = EvidenceRef(
        source_kind="transcript_segment",
        source_text_sha256=sha256_text(text),
        text_span=text,
        char_start=0,
        char_end=len(text),
        audio_id=1,
        segment_id="seg_1",
        start_time=1.0,
        end_time=3.0,
        speaker_id="SPEAKER_00",
    )
    graph = AnalysisGraphV2(
        task_id=task_id,
        segments=[segment],
        entities=[
            _entity("ent_a", ref, type="person", label="A", value="a"),
            _entity("ent_b", ref, type="person", label="B", value="b"),
        ],
        relations=[
            RelationItem(
                id="rel_ab",
                type="called",
                label="called",
                source_entity_id="ent_a",
                target_entity_id="ent_b",
                confidence=0.8,
                confidence_reason="test relation",
                source_method="test",
                evidence_refs=[ref],
            )
        ],
    )
    assert graph.edges[0]["from"] == "ent_a"
    assert graph.edges[0]["to"] == "ent_b"
    assert update_task(task_id, {"visualization_data": graph.to_storage_dict(), "has_visualization": True})

    client = _login_client(username, password)
    headers = _csrf_header(client)
    update_response = client.patch(
        f"/api/v1/audio/v2/visualize/{task_id}/entities/ent_a",
        json={"label": "Alice", "expected_revision": graph.graph_revision},
        headers=headers,
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.headers["cache-control"] == "no-store"
    updated_graph = update_response.json()["visualization_data"]

    response = client.post(
        f"/api/v1/audio/v2/visualize/{task_id}/entities/merge",
        json={"source_entity_ids": ["ent_a", "ent_b"], "expected_revision": updated_graph["graph_revision"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    updated = response.json()["visualization_data"]
    assert updated["relations"][0]["source_entity_id"] == "ent_a"
    assert updated["relations"][0]["target_entity_id"] == "ent_a"
    assert updated["relations"][0]["review_status"] == "rejected"
    assert updated["edges"] == []

    replacement = _entity("ent_a_split_1", _segment_ref(), type="person", label="Alice A", value="alice a")
    split = client.post(
        f"/api/v1/audio/v2/visualize/{task_id}/entities/ent_a/split",
        json={
            "expected_revision": updated["graph_revision"],
            "replacement_entities": [replacement.model_dump(mode="json")],
        },
        headers=headers,
    )
    assert split.status_code == 200, split.text
    assert split.headers["cache-control"] == "no-store"
    split_graph = split.json()["visualization_data"]
    original = next(item for item in split_graph["entities"] if item["id"] == "ent_a")
    assert original["review_status"] == "rejected"


def test_audio_clip_endpoint_streams_with_privacy_headers_and_cleanup(auth_enabled, monkeypatch, tmp_path):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    audio_id = _create_audio_for_task(user_id, case_id, task_id, status="uploaded")
    audio_path = tmp_path / "source.wav"
    audio_path.write_bytes(b"fake-audio")

    monkeypatch.setattr("src.api.endpoints.audio.resolve_audio_path", lambda _path: audio_path)

    created = {}

    class FakePipe:
        def __init__(self, chunks):
            self.chunks = list(chunks)
            self.closed = False

        def read(self, _size):
            return self.chunks.pop(0) if self.chunks else b""

        def close(self):
            self.closed = True

    class FakeProcess:
        def __init__(self, *_args, **kwargs):
            self.stdout = FakePipe([b"RIFF", b"WAVE"])
            self.stderr = None
            self.returncode = None
            self.terminated = False
            self.killed = False
            created["process"] = self
            created["stderr_arg"] = kwargs.get("stderr")

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.killed = True
            self.returncode = -9

    monkeypatch.setattr("src.api.endpoints.audio.subprocess.Popen", FakeProcess)

    client = _login_client(username, password)
    response = client.get(f"/api/v1/audio/{audio_id}/clip?start=0&end=1")
    assert response.status_code == 200, response.text
    assert response.content == b"RIFFWAVE"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"] == 'inline; filename="audio-clip.wav"'
    process = created["process"]
    assert created["stderr_arg"] == subprocess.DEVNULL
    assert process.stdout.closed is True
    assert process.stderr is None
    assert process.terminated is False
    assert process.killed is False


def test_audio_clip_endpoint_handles_caps_and_encoder_start_error(auth_enabled, monkeypatch, tmp_path):
    user_id, username, password = _create_user()
    case_id = _create_case_for_user(user_id)
    task_id = _create_task_for_user(user_id, case_id)
    audio_id = _create_audio_for_task(user_id, case_id, task_id, status="uploaded")
    audio_path = tmp_path / "source.wav"
    audio_path.write_bytes(b"fake-audio")
    monkeypatch.setattr("src.api.endpoints.audio.resolve_audio_path", lambda _path: audio_path)
    monkeypatch.setattr(settings, "ANALYSIS_CLIP_MAX_DURATION_SECONDS", 1)

    client = _login_client(username, password)
    too_long = client.get(f"/api/v1/audio/{audio_id}/clip?start=0&end=2")
    assert too_long.status_code == 400

    def missing_encoder(*_args, **_kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr("src.api.endpoints.audio.subprocess.Popen", missing_encoder)
    unavailable = client.get(f"/api/v1/audio/{audio_id}/clip?start=0&end=1")
    assert unavailable.status_code == 503
