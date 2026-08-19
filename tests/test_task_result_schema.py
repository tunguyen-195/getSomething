from src.database.models.schemas import TaskResult


def test_task_result_does_not_claim_one_speaker_without_diarization() -> None:
    result = TaskResult()

    assert result.has_diarization is False
    assert result.num_speakers is None
    assert result.diarization_status is None
    assert result.speaker_provenance == {}


def test_task_result_preserves_diarization_provenance() -> None:
    result = TaskResult(
        has_diarization=True,
        num_speakers=2,
        diarization_status="success",
        diarization_method_used="pyannote",
        speaker_provenance={"model_revision": "revision"},
    )

    assert result.num_speakers == 2
    assert result.diarization_method_used == "pyannote"
    assert result.speaker_provenance["model_revision"] == "revision"
