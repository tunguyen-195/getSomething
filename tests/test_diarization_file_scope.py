from __future__ import annotations

import json

from src.services.summarization.public_projection import public_task_result_payload
from src.services.transcription.diarization_scope import (
    annotate_segments_with_file_scope,
    build_diarization_provenance,
    build_file_provenance,
)


def test_same_local_speaker_labels_are_distinct_across_files() -> None:
    first = annotate_segments_with_file_scope(
        [{"start": 0.0, "end": 1.0, "text": "A", "speaker": "SPEAKER_00"}],
        task_id="task-a",
        audio_id=10,
        case_id=7,
        filename="first.mp3",
    )
    second = annotate_segments_with_file_scope(
        [{"start": 0.0, "end": 1.0, "text": "B", "speaker": "SPEAKER_00"}],
        task_id="task-b",
        audio_id=11,
        case_id=7,
        filename="second.mp3",
    )

    assert first[0]["speaker"] == second[0]["speaker"] == "SPEAKER_00"
    assert first[0]["speaker_key"] != second[0]["speaker_key"]
    assert first[0]["speaker_key"] == "audio:10:speaker:SPEAKER_00"
    assert second[0]["speaker_key"] == "audio:11:speaker:SPEAKER_00"
    assert first[0]["source_task_id"] == "task-a"
    assert second[0]["source_filename"] == "second.mp3"


def test_file_diarization_projection_is_json_safe_and_batch_ordered() -> None:
    projection = build_diarization_provenance(
        segments=[
            {"start": 0.0, "end": 1.0, "text": "A", "speaker": "SPEAKER_00"},
            {"start": 1.0, "end": 2.0, "text": "B", "speaker": "SPEAKER_01"},
        ],
        task_id="task-a",
        audio_id=10,
        case_id=7,
        filename="first.mp3",
        speaker_count=2,
        status="success",
        method="pyannote",
        batch_id="batch-1",
        batch_item_id=23,
        position=0,
    )

    assert projection["scope"] == "file"
    assert projection["scope_id"] == "audio:10"
    assert projection["source"]["batch_id"] == "batch-1"
    assert projection["source"]["position"] == 0
    assert projection["batch"]["batch_item_id"] == 23
    assert [item["speaker_key"] for item in projection["speakers"]] == [
        "audio:10:speaker:SPEAKER_00",
        "audio:10:speaker:SPEAKER_01",
    ]
    json.dumps(projection, ensure_ascii=False)


def test_public_projection_preserves_file_scope_without_raw_internal_fields() -> None:
    raw = {
        "transcription": "Noi dung",
        "segments": [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "Noi dung",
                "speaker": "SPEAKER_00",
                "speaker_key": "audio:10:speaker:SPEAKER_00",
                "speaker_scope_id": "audio:10",
                "source_task_id": "task-a",
                "source_audio_id": 10,
                "provider_secret": "must-not-leak",
            }
        ],
        "file_provenance": build_file_provenance(
            task_id="task-a", audio_id=10, case_id=7, filename="first.mp3"
        ),
        "diarization": build_diarization_provenance(
            segments=[],
            task_id="task-a",
            audio_id=10,
            case_id=7,
            filename="first.mp3",
            speaker_count=1,
            status="success",
            method="pyannote",
        ),
    }

    projected = public_task_result_payload(raw)
    assert projected["file_provenance"]["scope"] == "file"
    assert projected["diarization"]["scope_id"] == "audio:10"
    assert projected["segments"][0]["speaker_key"] == "audio:10:speaker:SPEAKER_00"
    assert "provider_secret" not in projected["segments"][0]
