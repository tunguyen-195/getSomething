import sys
import types


def test_assign_speakers_from_diarization_segments_uses_best_overlap():
    from src.services.transcription import transcribe_service_v2 as module

    transcript_segments = [
        {"start": 0.0, "end": 1.0, "text": "xin chao"},
        {"start": 1.0, "end": 2.0, "text": "toi can dat phong"},
    ]
    diarization_segments = [
        {"start": 0.0, "end": 0.9, "speaker": "SPEAKER_00"},
        {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"},
    ]

    speakers = module._assign_speakers_from_diarization_segments(transcript_segments, diarization_segments)

    assert speakers == {"SPEAKER_00", "SPEAKER_01"}
    assert [segment["speaker"] for segment in transcript_segments] == ["SPEAKER_00", "SPEAKER_01"]


def test_requested_pyannote_diarization_falls_back_to_simple_vad(monkeypatch, tmp_path):
    from src.services.transcription import transcribe_service_v2 as module

    class FakePyannoteManager:
        def is_available(self):
            return False

    fake_manager_module = types.SimpleNamespace(get_pyannote_manager=lambda: FakePyannoteManager())
    monkeypatch.setitem(
        sys.modules,
        "src.services.transcription.models.pyannote_manager",
        fake_manager_module,
    )

    def fake_simple_vad(segments, audio_path):
        assigned = [dict(segment, speaker="SPEAKER_00") for segment in segments]
        return assigned, {"SPEAKER_00"}

    monkeypatch.setattr(module, "_run_simple_vad_diarization", fake_simple_vad)

    warnings: list[str] = []
    segments, used, num_speakers, method, elapsed = module._run_requested_diarization(
        segments=[{"start": 0.0, "end": 1.0, "text": "xin chao"}],
        audio_path=tmp_path / "audio.wav",
        requested_method="pyannote",
        warnings=warnings,
    )

    assert used is True
    assert num_speakers == 1
    assert method == "simple_vad_fallback"
    assert elapsed >= 0
    assert segments[0]["speaker"] == "SPEAKER_00"
    assert "diarization_pyannote_unavailable" in warnings
    assert "diarization_fallback_simple_vad" in warnings
