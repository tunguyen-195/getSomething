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
from src.services.analysis_intelligence.schemas import (
    AnalysisGraphV2,
    EntityItem,
    EvidenceRef,
    RelationItem,
    SegmentUnit,
    sha256_text,
)
from src.services.analysis_intelligence.service import apply_review_preservation
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
    active = _entity("ent_phone_active", _segment_ref())
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
    response = client.post(
        f"/api/v1/audio/v2/visualize/{task_id}/entities/merge",
        json={"source_entity_ids": ["ent_a", "ent_b"], "expected_revision": graph.graph_revision},
        headers=_csrf_header(client),
    )
    assert response.status_code == 200, response.text
    updated = response.json()["visualization_data"]
    assert updated["relations"][0]["source_entity_id"] == "ent_a"
    assert updated["relations"][0]["target_entity_id"] == "ent_a"
    assert updated["relations"][0]["review_status"] == "rejected"
    assert updated["edges"] == []


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
