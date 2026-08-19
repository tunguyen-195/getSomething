from src.api.endpoints.audio_v2 import _summary_response_result
from src.services.summarization.public_projection import (
    PUBLIC_ANALYSIS_SCHEMA_VERSION,
    public_context_analysis_payload,
    public_task_payload,
    public_task_result_payload,
)


FORBIDDEN_KEYS = {
    "audio_sha256",
    "entity_id",
    "event_id",
    "evidence_id",
    "evidence_ids",
    "evidence_quote",
    "evidence_quotes",
    "evidence_spans",
    "fact_id",
    "model_id",
    "quote",
    "quote_exact",
    "quote_sha256",
    "relationship_id",
    "segment_id",
    "segment_index",
    "source_sha256",
    "speaker_id",
    "start_seconds",
    "end_seconds",
    "transcript_sha256",
}


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value))
    return set()


def _internal_context() -> dict:
    return {
        "analysis_status": "success",
        "investigation_knowledge": {
            "provenance": {
                "model_id": "internal-model",
                "transcript_sha256": "a" * 64,
                "transcript_segment_count": 2,
            },
            "evidence_spans": [
                {
                    "evidence_id": "ev-1",
                    "quote": "Lan se chuyen 15 trieu dong cho Minh.",
                    "segment_id": "seg-1",
                    "segment_index": 0,
                    "start_seconds": 0.0,
                    "end_seconds": 5.0,
                    "speaker_id": "SPEAKER_00",
                    "quote_sha256": "b" * 64,
                    "source_sha256": "c" * 64,
                }
            ],
            "facts": [
                {
                    "fact_id": "fact-1",
                    "category": "financial.plan",
                    "statement": "Lan du kien chuyen 15 trieu dong cho Minh.",
                    "status": "planned",
                    "verification_status": "unverified",
                    "evidence_ids": ["ev-1"],
                }
            ],
            "entities": [
                {
                    "entity_id": "entity-1",
                    "entity_type": "person",
                    "value": "Lan",
                    "role": "nguoi chuyen tien du kien",
                    "verification_status": "unverified",
                    "evidence_ids": ["ev-1"],
                }
            ],
            "events": [
                {
                    "event_id": "event-1",
                    "description": "Lan du kien chuyen tien cho Minh.",
                    "status": "planned",
                    "actors": ["Lan", "Minh"],
                    "time_text": "ngay mai",
                    "verification_status": "unverified",
                    "evidence_ids": ["ev-1"],
                }
            ],
            "relationships": [
                {
                    "relationship_id": "rel-1",
                    "source": "Lan",
                    "target": "Minh",
                    "label": "du kien chuyen tien cho",
                    "status": "planned",
                    "verification_status": "unverified",
                    "evidence_ids": ["ev-1"],
                }
            ],
        },
    }


def test_public_context_projection_keeps_analysis_and_removes_internal_trails() -> None:
    projected = public_context_analysis_payload(_internal_context())

    assert projected is not None
    assert projected["schema_version"] == PUBLIC_ANALYSIS_SCHEMA_VERSION
    assert projected["facts"][0]["statement"].startswith("Lan du kien")
    assert projected["entities"][0]["value"] == "Lan"
    assert projected["events"][0]["time_text"] == "ngay mai"
    assert projected["metrics"] == {
        "covered_segment_count": 1,
        "total_segment_count": 2,
    }
    assert _all_keys(projected).isdisjoint(FORBIDDEN_KEYS)


def test_summary_response_never_returns_raw_context() -> None:
    response = _summary_response_result(
        {
            "available": True,
            "summary": "Ban tin dieu tra.",
            "context": _internal_context(),
            "summary_type": "investigation",
        }
    )

    assert response["context"]["schema_version"] == PUBLIC_ANALYSIS_SCHEMA_VERSION
    assert _all_keys(response["context"]).isdisjoint(FORBIDDEN_KEYS)


def test_public_projection_preserves_simple_v2_partial_analysis() -> None:
    projected = public_context_analysis_payload(
        {
            "schema_version": "investigation-analysis-simple-v2",
            "analysis_status": "partial",
            "analysis_generation": "single_prompt_llm",
            "prompt_version": "investigation-analysis-simple-v2",
            "analysis_text": "Phân tích dạng văn bản vẫn dùng được.",
            "key_points": [],
            "metrics": {
                "transcript_word_count": 12,
                "transcript_sha256": "a" * 64,
                "segments_sha256": "b" * 64,
                "source_task_id": "task-secret",
            },
            "runtime": {"llm_call_count": 1},
        }
    )

    assert projected is not None
    assert projected["schema_version"] == "investigation-analysis-simple-v2"
    assert projected["analysis_status"] == "partial"
    assert projected["analysis_text"].startswith("Phân tích")
    assert projected["metrics"] == {"transcript_word_count": 12}
    assert "runtime" not in projected
    assert projected["events"] == []
    assert _all_keys(projected).isdisjoint(
        {"transcript_sha256", "segments_sha256", "source_task_id"}
    )


def test_public_projection_rejects_unversioned_analysis_payload() -> None:
    projected = public_context_analysis_payload(
        {"analysis_text": "Client or legacy payload without a public schema."}
    )

    assert projected is None


def test_simple_projection_allowlists_every_nested_record() -> None:
    projected = public_context_analysis_payload(
        {
            "schema_version": "investigation-analysis-simple-v2",
            "analysis_status": "success",
            "analysis_text": "Phan tich hop le.",
            "key_points": [
                {
                    "text": "Chi tiet chinh.",
                    "category": "event",
                    "evidence_quote": "noi bo",
                    "custom_extension": {"secret": True},
                }
            ],
            "events": [
                {
                    "description": "Su kien.",
                    "participants": ["Lan"],
                    "evidence_quote": "noi bo",
                    "custom_extension": "drop-me",
                }
            ],
            "speaker_contributions": [
                {
                    "speaker": "SPEAKER_00",
                    "word_count": 12,
                    "segment_count": 2,
                    "duration_seconds": 4.5,
                    "word_share": 1.0,
                    "raw_segments": [{"text": "secret"}],
                }
            ],
        }
    )

    assert projected is not None
    assert projected["key_points"] == [
        {"text": "Chi tiet chinh.", "category": "event"}
    ]
    assert projected["events"] == [
        {"description": "Su kien.", "participants": ["Lan"]}
    ]
    assert projected["speaker_contributions"][0]["word_count"] == 12
    assert _all_keys(projected).isdisjoint(
        {"evidence_quote", "custom_extension", "raw_segments", "secret"}
    )


def test_task_projection_removes_attestation_and_projects_raw_analysis() -> None:
    raw = {
        "transcription": "Noi dung nguon.",
        "context_analysis": {
            "schema_version": "investigation-analysis-simple-v2",
            "analysis_status": "success",
            "analysis_text": "Phan tich.",
            "key_points": [
                {"text": "Diem chinh.", "evidence_quote": "noi bo"}
            ],
        },
        "context_analysis_attestation": {
            "signature": "server-secret",
            "transcript_sha256": "a" * 64,
        },
    }

    result = public_task_result_payload(raw)
    task = public_task_payload(
        {
            "id": "task-1",
            "result": raw,
            "context_analysis": raw["context_analysis"],
            "context_analysis_attestation": raw["context_analysis_attestation"],
        }
    )

    assert "context_analysis_attestation" not in result
    assert "context_analysis_attestation" not in task
    assert "context_analysis_attestation" not in task["result"]
    assert _all_keys(result).isdisjoint({"evidence_quote", "signature"})
    assert _all_keys(task).isdisjoint({"evidence_quote", "signature"})


def test_task_projection_downgrades_stale_visualized_status() -> None:
    summarized = public_task_payload(
        {
            "id": "task-summary",
            "status": "visualized",
            "result": {
                "transcription": "Noi dung nguon.",
                "summary": "Tom tat.",
                "visualization_data": {"nodes": [{"id": "stale"}]},
            },
        }
    )
    transcribed = public_task_payload(
        {
            "id": "task-transcript",
            "status": "visualized",
            "result": {"transcription": "Noi dung nguon."},
        }
    )
    empty = public_task_payload(
        {"id": "task-empty", "status": "visualized", "result": {}}
    )

    assert summarized["status"] == "summarized"
    assert summarized["result"]["visualization_data"] is None
    assert transcribed["status"] == "transcribed"
    assert empty["status"] == "uploaded"
