from __future__ import annotations

import importlib
import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.cherry_core.domain.entities import SpeakerSegment, Transcript
from src.services.transcription import cherry_transcription_service
from src.services.transcription import transcribe_service_v2 as service
from src.services.transcription.models import whisper_manager
from src.services.transcription.models.whisper_manager import resolve_cached_model


class FakeAudioFile:
    file_path = "audio.wav"
    status = "uploaded"
    duration = None
    extra_metadata = {}


def test_investigation_accuracy_is_the_service_default():
    signature = inspect.signature(service.transcribe_audio_v2)

    assert signature.parameters["fast_mode"].default is False
    profile, parameters = service._whisper_decode_profile(False)
    assert profile == "investigation-accuracy-v1"
    assert parameters["beam_size"] == 5


def test_large_v2_is_the_product_model_default():
    from src.core.config import Settings

    assert Settings.model_fields["WHISPER_MODEL"].default == "large-v2"


class FakeQuery:
    def __init__(self, audio_file):
        self.audio_file = audio_file

    def filter(self, *_args):
        return self

    def first(self):
        return self.audio_file


class FakeDb:
    def __init__(self):
        self.audio_file = FakeAudioFile()
        self.commits = 0

    def query(self, *_args):
        return FakeQuery(self.audio_file)

    def commit(self):
        self.commits += 1


class FakeWhisperManager:
    def transcribe(self, *_args, **_kwargs):
        segment = SimpleNamespace(
            start=0.0,
            end=1.25,
            text="Noi dung legacy",
            avg_logprob=-0.1,
        )
        return [segment], SimpleNamespace(duration=1.25, language="vi")

    def unload(self):
        return None


def _prepare_transcription(monkeypatch, tmp_path: Path):
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"synthetic-audio-placeholder")
    updates = []
    monkeypatch.setattr(service.settings, "GPU_LEASE_ENABLED", False)
    monkeypatch.setattr(service, "get_task", lambda _task_id: {"id": "task-1"})
    monkeypatch.setattr(service, "resolve_audio_path", lambda _path: audio_path)
    monkeypatch.setattr(service, "update_task", lambda task_id, data: updates.append((task_id, data)) or True)
    monkeypatch.setattr(service, "get_whisper_manager", lambda: FakeWhisperManager())
    return FakeDb(), updates


def _write_cached_snapshot(
    cache_root: Path,
    cache_name: str,
    revision: str,
    *,
    contents: bytes = b"model-data",
) -> Path:
    model_root = cache_root / cache_name
    snapshot = model_root / "snapshots" / revision
    snapshot.mkdir(parents=True)
    for filename in ("config.json", "model.bin", "tokenizer.json"):
        (snapshot / filename).write_bytes(contents)
    ref_path = model_root / "refs" / "main"
    ref_path.parent.mkdir(parents=True)
    ref_path.write_text(revision + "\n", encoding="utf-8")
    return snapshot


def test_tracked_cherry_modules_import_offline():
    tracked = subprocess.check_output(
        ["git", "ls-files", "src/cherry_core/**/*.py", "src/cherry_core/*.py"],
        text=True,
    ).splitlines()
    modules = [path.removesuffix(".py").replace("/", ".") for path in tracked]

    for module in modules:
        importlib.import_module(module)


def test_workspace_cherry_modules_import_offline():
    repo_root = Path(__file__).resolve().parents[1]
    modules = sorted(
        ".".join(path.relative_to(repo_root).with_suffix("").parts)
        for path in (repo_root / "src" / "cherry_core").rglob("*.py")
    )

    for module in modules:
        importlib.import_module(module)


def test_cherry_transcriber_constructs_without_loading_weights():
    instance = cherry_transcription_service.CherryTranscriberService()
    assert instance.whisper_adapter.model is None
    assert instance.phowhisper_adapter._model is None
    assert instance.diarizer._pipeline is None


def test_legacy_mode_does_not_attempt_cherry(monkeypatch, tmp_path):
    db, updates = _prepare_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "legacy")
    monkeypatch.setattr(
        cherry_transcription_service,
        "get_cherry_transcriber",
        lambda: pytest.fail("legacy mode must not import or call Cherry"),
    )

    result = service.transcribe_audio_v2(
        "task-1",
        db,
        enable_diarization=False,
    )

    assert result["requested_engine"] == "legacy"
    assert result["engine_used"] == "legacy"
    assert result["fallback_reason"] is None
    assert any(update[1].get("status") == "transcribed" for update in updates)


@pytest.mark.parametrize(
    ("fast_mode", "expected_profile", "expected_beam", "expected_temperature"),
    [
        (True, "fast-v1", 1, 0.0),
        (False, "investigation-accuracy-v1", 5, 0.0),
    ],
)
def test_legacy_asr_profile_is_explicit_and_auditable(
    monkeypatch,
    tmp_path,
    fast_mode,
    expected_profile,
    expected_beam,
    expected_temperature,
):
    db, _updates = _prepare_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "legacy")
    captured = {}

    class RecordingWhisper(FakeWhisperManager):
        def transcribe(self, *_args, **kwargs):
            captured.update(kwargs)
            return super().transcribe()

        def provenance(self):
            return {
                "provider": "faster-whisper",
                "model_id": "Systran/faster-whisper-large-v3",
                "model_revision": "revision",
                "artifact_verified": True,
            }

    monkeypatch.setattr(service, "get_whisper_manager", lambda: RecordingWhisper())

    result = service.transcribe_audio_v2(
        "task-1",
        db,
        enable_diarization=False,
        fast_mode=fast_mode,
    )

    assert result["asr_profile"] == expected_profile
    assert captured["beam_size"] == expected_beam
    assert captured["temperature"] == expected_temperature
    assert "initial_prompt" not in captured
    assert result["asr_provenance"]["model_revision"] == "revision"
    if fast_mode:
        assert "hallucination_silence_threshold" not in captured
    else:
        assert captured["hallucination_silence_threshold"] == 1.5


def test_leading_gap_rescue_recovers_confident_audio_before_vad_anchor(
    monkeypatch,
    tmp_path,
):
    db, _updates = _prepare_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "legacy")
    monkeypatch.setattr(
        service,
        "_detect_speech_intervals",
        lambda _audio_path: [(11.0, 20.34)],
    )
    calls = []

    class LeadingGapWhisper(FakeWhisperManager):
        def transcribe(self, *_args, **kwargs):
            calls.append(kwargs)
            if "clip_timestamps" in kwargs:
                rescue = SimpleNamespace(
                    start=11.38,
                    end=20.28,
                    text="Hay subscribe cho kenh de khong bo lo noi dung",
                    avg_logprob=-0.14,
                    no_speech_prob=0.44,
                    compression_ratio=1.1,
                )
                return [rescue], SimpleNamespace(duration=20.34, language="vi")
            primary = SimpleNamespace(
                start=20.34,
                end=23.0,
                text="Chao em, chi muon dat phong",
                avg_logprob=-0.1,
                no_speech_prob=0.05,
                compression_ratio=1.0,
            )
            return [primary], SimpleNamespace(duration=30.0, language="vi")

    monkeypatch.setattr(service, "get_whisper_manager", lambda: LeadingGapWhisper())

    result = service.transcribe_audio_v2(
        "task-1",
        db,
        enable_diarization=False,
        fast_mode=False,
    )

    assert len(calls) == 2
    assert calls[1]["clip_timestamps"] == "0,20.340"
    assert result["segments"][0]["transcription_source"] == "leading_gap_rescue"
    assert result["transcript"].startswith("Hay subscribe")
    assert result["coverage_rescue"]["status"] == "applied"
    assert result["coverage_rescue"]["accepted_segments"] == 1


def test_leading_gap_rescue_rejects_probable_silence_hallucination(
    monkeypatch,
    tmp_path,
):
    db, _updates = _prepare_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "legacy")
    monkeypatch.setattr(service, "_detect_speech_intervals", lambda _audio_path: [])

    class LowConfidenceGapWhisper(FakeWhisperManager):
        def transcribe(self, *_args, **kwargs):
            if "clip_timestamps" in kwargs:
                rescue = SimpleNamespace(
                    start=0.0,
                    end=10.0,
                    text="Probable hallucination",
                    avg_logprob=-1.2,
                    no_speech_prob=0.91,
                    compression_ratio=3.2,
                )
                return [rescue], SimpleNamespace(duration=20.0, language="vi")
            primary = SimpleNamespace(
                start=12.0,
                end=14.0,
                text="Noi dung that",
                avg_logprob=-0.1,
                no_speech_prob=0.05,
                compression_ratio=1.0,
            )
            return [primary], SimpleNamespace(duration=20.0, language="vi")

    monkeypatch.setattr(service, "get_whisper_manager", lambda: LowConfidenceGapWhisper())

    result = service.transcribe_audio_v2(
        "task-1",
        db,
        enable_diarization=False,
        fast_mode=False,
    )

    assert result["transcript"] == "Noi dung that"
    assert result["coverage_rescue"]["status"] == "rejected"
    reasons = result["coverage_rescue"]["rejected_segments"][0]["reasons"]
    assert "low_log_probability" in reasons
    assert "high_no_speech_probability" in reasons
    assert "insufficient_vad_speech_overlap" in reasons


def test_leading_gap_rescue_rejects_threshold_edge_text_outside_voiced_audio(
    monkeypatch,
    tmp_path,
):
    db, _updates = _prepare_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "legacy")
    monkeypatch.setattr(service, "decode_audio", lambda *_args, **_kwargs: object())
    observed_speech_padding = []

    def adversarial_vad(_audio, *, vad_options, sampling_rate):
        observed_speech_padding.append(vad_options.speech_pad_ms)
        core_start = 20.0
        padded_start = core_start - (vad_options.speech_pad_ms / 1000.0)
        return [
            {
                "start": int(padded_start * sampling_rate),
                "end": int(21.0 * sampling_rate),
            }
        ]

    monkeypatch.setattr(service, "get_speech_timestamps", adversarial_vad)

    class ThresholdEdgeWhisper(FakeWhisperManager):
        def transcribe(self, *_args, **kwargs):
            if "clip_timestamps" in kwargs:
                rescue = SimpleNamespace(
                    start=19.0,
                    end=20.0,
                    text="Hay subscribe cho kenh de khong bo lo noi dung",
                    avg_logprob=-0.14,
                    no_speech_prob=0.4746,
                    compression_ratio=0.89,
                )
                return [rescue], SimpleNamespace(duration=20.14, language="vi")
            primary = SimpleNamespace(
                start=20.5,
                end=24.52,
                text="Chao em, chi muon dat phong",
                avg_logprob=-0.1,
                no_speech_prob=0.05,
                compression_ratio=1.0,
            )
            return [primary], SimpleNamespace(duration=30.0, language="vi")

    monkeypatch.setattr(service, "get_whisper_manager", lambda: ThresholdEdgeWhisper())

    result = service.transcribe_audio_v2(
        "task-1",
        db,
        enable_diarization=False,
        fast_mode=False,
    )

    assert observed_speech_padding == [0]
    assert result["transcript"] == "Chao em, chi muon dat phong"
    rejected = result["coverage_rescue"]["rejected_segments"][0]
    assert rejected["vad_speech_overlap_ratio"] == 0.0
    assert "insufficient_vad_speech_overlap" in rejected["reasons"]


def test_primary_transcript_does_not_censor_subscription_language(
    monkeypatch,
    tmp_path,
):
    db, _updates = _prepare_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "legacy")

    class SubscriptionWhisper(FakeWhisperManager):
        def transcribe(self, *_args, **_kwargs):
            segment = SimpleNamespace(
                start=0.0,
                end=2.0,
                text="Hay subscribe cho kenh",
                avg_logprob=-0.1,
                no_speech_prob=0.05,
                compression_ratio=1.0,
            )
            return [segment], SimpleNamespace(duration=2.0, language="vi")

    monkeypatch.setattr(service, "get_whisper_manager", lambda: SubscriptionWhisper())

    result = service.transcribe_audio_v2(
        "task-1",
        db,
        enable_diarization=False,
        fast_mode=False,
    )

    assert result["transcript"] == "Hay subscribe cho kenh"
    assert result["coverage_rescue"]["reason"] == "no_material_leading_gap"


def test_legacy_pyannote_unavailable_is_not_reported_as_one_speaker(
    monkeypatch,
    tmp_path,
):
    db, _updates = _prepare_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "legacy")

    class UnavailablePyannote:
        def is_available(self):
            return False

        def provenance(self):
            return {
                "provider": "pyannote",
                "model_id": "pyannote/speaker-diarization-3.1",
                "artifact_verified": False,
                "load_error": "complete_local_snapshot_missing",
            }

        def unload(self):
            return None

    pyannote = UnavailablePyannote()
    monkeypatch.setattr(service, "get_pyannote_manager", lambda: pyannote)

    result = service.transcribe_audio_v2(
        "task-1",
        db,
        enable_diarization=True,
        diarization_method="pyannote",
    )

    assert result["num_speakers"] is None
    assert result["has_diarization"] is False
    assert result["diarization_status"] == "unavailable"
    assert result["degraded"] is True
    assert result["fallback_reason"] == "complete_local_snapshot_missing"
    assert result["segments"][0]["speaker"] is None
    assert result["speaker_provenance"]["artifact_verified"] is False


def test_legacy_pyannote_counts_raw_speakers_and_assigns_mocked_turns(
    monkeypatch,
    tmp_path,
):
    db, _updates = _prepare_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "legacy")

    class TwoSegmentWhisper(FakeWhisperManager):
        def transcribe(self, *_args, **_kwargs):
            segments = [
                SimpleNamespace(
                    start=0.0,
                    end=0.5,
                    text="Nguoi thu nhat",
                    avg_logprob=-0.1,
                ),
                SimpleNamespace(
                    start=0.5,
                    end=1.25,
                    text="Nguoi thu hai",
                    avg_logprob=-0.1,
                ),
            ]
            return segments, SimpleNamespace(duration=1.25, language="vi")

    class Turn:
        def __init__(self, start, end):
            self.start = start
            self.end = end

    class Annotation:
        def itertracks(self, yield_label=False):
            assert yield_label is True
            return iter(
                [
                    (Turn(0.0, 0.5), None, "SPEAKER_00"),
                    (Turn(0.5, 1.25), None, "SPEAKER_01"),
                ]
            )

    class AvailablePyannote:
        def is_available(self):
            return True

        def diarize(self, _audio_path):
            return Annotation()

        def provenance(self):
            return {
                "provider": "pyannote",
                "model_id": "pyannote/speaker-diarization-3.1",
                "model_revision": "84fd25912480287da0247647c3d2b4853cb3ee5d",
                "artifact_verified": True,
                "load_error": None,
            }

        def unload(self):
            return None

    monkeypatch.setattr(service, "get_whisper_manager", lambda: TwoSegmentWhisper())
    pyannote = AvailablePyannote()
    monkeypatch.setattr(service, "get_pyannote_manager", lambda: pyannote)

    result = service.transcribe_audio_v2(
        "task-1",
        db,
        enable_diarization=True,
        diarization_method="pyannote",
    )

    assert result["num_speakers"] == 2
    assert result["has_diarization"] is True
    assert result["diarization_status"] == "success"
    assert result["degraded"] is False
    assert result["diarization_method_used"] == "pyannote"
    assert [segment["speaker"] for segment in result["segments"]] == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    assert result["speaker_provenance"]["speaker_count"] == 2


def test_invalid_diarization_method_fails_before_asr(monkeypatch):
    monkeypatch.setattr(
        service,
        "get_task",
        lambda _task_id: pytest.fail("invalid method must fail before task/ASR use"),
    )

    with pytest.raises(ValueError, match="Unsupported diarization method"):
        service._transcribe_audio_v2_unlocked(
            "task-1",
            FakeDb(),
            enable_diarization=True,
            diarization_method="simple_vad",
        )


def test_auto_mode_exposes_cherry_fallback(monkeypatch, tmp_path):
    db, _updates = _prepare_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "auto")
    monkeypatch.setattr(
        cherry_transcription_service,
        "get_cherry_transcriber",
        lambda: (_ for _ in ()).throw(RuntimeError("synthetic Cherry failure")),
    )

    result = service.transcribe_audio_v2(
        "task-1",
        db,
        enable_diarization=False,
    )

    assert result["requested_engine"] == "auto"
    assert result["engine_used"] == "legacy"
    assert result["fallback_reason"] == "RuntimeError: synthetic Cherry failure"


def test_cherry_mode_fails_without_legacy_fallback(monkeypatch, tmp_path):
    db, updates = _prepare_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "cherry")
    legacy_transcribed = False

    class TrackingWhisperManager(FakeWhisperManager):
        def transcribe(self, *_args, **_kwargs):
            nonlocal legacy_transcribed
            legacy_transcribed = True
            return super().transcribe(*_args, **_kwargs)

    def legacy_manager():
        return TrackingWhisperManager()

    monkeypatch.setattr(service, "get_whisper_manager", legacy_manager)
    monkeypatch.setattr(
        cherry_transcription_service,
        "get_cherry_transcriber",
        lambda: (_ for _ in ()).throw(RuntimeError("synthetic Cherry failure")),
    )

    with pytest.raises(HTTPException) as exc_info:
        service.transcribe_audio_v2("task-1", db, enable_diarization=False)

    assert exc_info.value.status_code == 500
    assert legacy_transcribed is False
    failed_update = next(data for _, data in updates if data.get("status") == "failed")
    assert failed_update["result"]["requested_engine"] == "cherry"
    assert failed_update["result"]["engine_used"] is None


def test_cherry_mode_reports_cherry_provenance(monkeypatch, tmp_path):
    db, _updates = _prepare_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "cherry")

    class FakeCherry:
        def transcribe(self, **_kwargs):
            return {
                "segments": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "text": "Noi dung Cherry",
                        "speaker": "SPEAKER_1",
                    }
                ],
                "duration": 1.0,
                "num_speakers": 1,
                "diarization_time": 0.0,
            }

    monkeypatch.setattr(
        cherry_transcription_service,
        "get_cherry_transcriber",
        lambda: FakeCherry(),
    )

    result = service.transcribe_audio_v2(
        "task-1",
        db,
        enable_diarization=False,
    )

    assert result["requested_engine"] == "cherry"
    assert result["engine_used"] == "cherry"
    assert result["fallback_reason"] is None
    assert result["transcript"] == "Noi dung Cherry"


def test_cherry_diarization_failure_remains_unknown_instead_of_one_speaker(
    tmp_path,
):
    class FakeAsr:
        def transcribe(self, _audio_path):
            return Transcript(
                text="Noi dung",
                segments=[{"start": 0.0, "end": 1.0, "text": "Noi dung"}],
            )

    class FailingDiarizer:
        def diarize(self, _audio_path):
            raise FileNotFoundError("complete local snapshot missing")

        def provenance(self):
            return {
                "provider": "pyannote",
                "artifact_verified": False,
                "load_error": "complete local snapshot missing",
            }

    instance = cherry_transcription_service.CherryTranscriberService.__new__(
        cherry_transcription_service.CherryTranscriberService
    )
    instance.whisper_adapter = FakeAsr()
    instance.phowhisper_adapter = FakeAsr()
    instance.diarizer = FailingDiarizer()

    result = instance.transcribe(
        str(tmp_path / "audio.wav"),
        enable_diarization=True,
        model_type="whisper",
    )

    assert result["num_speakers"] is None
    assert result["has_diarization"] is False
    assert result["diarization_status"] == "unavailable"
    assert result["degraded"] is True
    assert "FileNotFoundError" in result["diarization_fallback_reason"]
    assert "speaker" not in result["segments"][0]


def test_cherry_counts_speakers_from_diarization_turns(tmp_path):
    class FakeAsr:
        def transcribe(self, _audio_path):
            return Transcript(
                text="Mot Hai",
                segments=[
                    {"start": 0.0, "end": 0.5, "text": "Mot"},
                    {"start": 0.5, "end": 1.0, "text": "Hai"},
                ],
            )

    class TwoSpeakerDiarizer:
        def diarize(self, _audio_path):
            return [
                SpeakerSegment(0.0, 0.5, "SPEAKER_1"),
                SpeakerSegment(0.5, 1.0, "SPEAKER_2"),
            ]

        def provenance(self):
            return {
                "provider": "pyannote",
                "artifact_verified": True,
                "load_error": None,
            }

    instance = cherry_transcription_service.CherryTranscriberService.__new__(
        cherry_transcription_service.CherryTranscriberService
    )
    instance.whisper_adapter = FakeAsr()
    instance.phowhisper_adapter = FakeAsr()
    instance.diarizer = TwoSpeakerDiarizer()

    result = instance.transcribe(
        str(tmp_path / "audio.wav"),
        enable_diarization=True,
        model_type="whisper",
    )

    assert result["num_speakers"] == 2
    assert result["has_diarization"] is True
    assert result["diarization_status"] == "success"
    assert [segment["speaker"] for segment in result["segments"]] == [
        "SPEAKER_1",
        "SPEAKER_2",
    ]


def test_v2_celery_task_closes_session(monkeypatch):
    from src.worker.tasks import transcribe_task

    class FakeSession:
        closed = False
        rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True

        def rollback(self):
            self.rolled_back = True

    session = FakeSession()
    monkeypatch.setattr(transcribe_task, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        service,
        "transcribe_audio_v2",
        lambda **_kwargs: {"num_speakers": 1, "processing_time": 0.25},
    )

    result = transcribe_task.transcribe_audio_task.run("task-1")

    assert result["status"] == "success"
    assert session.closed is True


def test_transcription_rejects_modified_audio(monkeypatch, tmp_path):
    db, updates = _prepare_transcription(monkeypatch, tmp_path)
    db.audio_file.extra_metadata = {"sha256": "0" * 64}
    monkeypatch.setattr(service.settings, "TRANSCRIPTION_ENGINE", "legacy")

    with pytest.raises(HTTPException) as exc_info:
        service.transcribe_audio_v2("task-1", db, enable_diarization=False)

    assert exc_info.value.status_code == 500
    assert "integrity" in exc_info.value.detail.lower()
    assert any(update[1].get("status") == "failed" for update in updates)


def test_whisper_cache_resolution_requires_exact_model(tmp_path):
    turbo_snapshot = _write_cached_snapshot(
        tmp_path,
        "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
        whisper_manager.PINNED_MODEL_REVISIONS["large-v3-turbo"],
    )

    assert resolve_cached_model("large-v3", tmp_path) is None
    assert resolve_cached_model("large-v3-turbo", tmp_path) == turbo_snapshot.resolve()


def test_whisper_cache_resolution_finds_large_v3_snapshot(tmp_path):
    large_v3_snapshot = _write_cached_snapshot(
        tmp_path,
        "models--Systran--faster-whisper-large-v3",
        whisper_manager.PINNED_MODEL_REVISIONS["large-v3"],
    )

    assert resolve_cached_model("large-v3", tmp_path) == large_v3_snapshot.resolve()


def test_whisper_cache_resolution_rejects_zero_byte_migration_snapshot(tmp_path):
    _write_cached_snapshot(
        tmp_path,
        "models--Systran--faster-whisper-large-v2",
        whisper_manager.PINNED_MODEL_REVISIONS["large-v2"],
        contents=b"",
    )

    with pytest.raises(
        whisper_manager.SnapshotResolutionError,
        match="incomplete snapshot",
    ):
        resolve_cached_model("large-v2", tmp_path)


def test_whisper_cache_resolution_fails_closed_without_refs_main(tmp_path):
    model_root = tmp_path / "models--Systran--faster-whisper-large-v2"
    for revision in ("revision-a", "revision-b"):
        snapshot = model_root / "snapshots" / revision
        snapshot.mkdir(parents=True)
        for filename in ("config.json", "model.bin", "tokenizer.json"):
            (snapshot / filename).write_bytes(b"model-data")

    with pytest.raises(
        whisper_manager.SnapshotResolutionError,
        match="Missing exact refs/main",
    ):
        resolve_cached_model("large-v2", tmp_path)


def test_whisper_cache_resolution_rejects_valid_unpromoted_revision(tmp_path):
    model_root = tmp_path / "models--Systran--faster-whisper-large-v2"
    unpromoted_revision = "1" * 40
    valid = model_root / "snapshots" / unpromoted_revision
    valid.mkdir(parents=True)
    for filename in ("config.json", "model.bin", "tokenizer.json"):
        (valid / filename).write_bytes(b"model-data")
    ref_path = model_root / "refs" / "main"
    ref_path.parent.mkdir(parents=True)
    ref_path.write_text(unpromoted_revision + "\n", encoding="utf-8")

    with pytest.raises(
        whisper_manager.SnapshotResolutionError,
        match="does not match the pinned immutable revision",
    ):
        resolve_cached_model("large-v2", tmp_path)


def test_whisper_manager_loads_the_verified_snapshot_path(monkeypatch, tmp_path):
    snapshot = _write_cached_snapshot(
        tmp_path,
        "models--Systran--faster-whisper-large-v2",
        whisper_manager.PINNED_MODEL_REVISIONS["large-v2"],
    )

    captured = {}

    class RecordingWhisperModel:
        def __init__(self, model_reference, **kwargs):
            captured["model_reference"] = model_reference
            captured["kwargs"] = kwargs

    monkeypatch.setattr(whisper_manager.settings, "WHISPER_MODEL", "large-v2")
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_MODEL_PATH", str(tmp_path))
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_USE_LOCAL", True)
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_DEVICE", "cpu")
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_COMPUTE_TYPE", "int8")
    monkeypatch.setattr(whisper_manager, "WhisperModel", RecordingWhisperModel)
    monkeypatch.setattr(whisper_manager.WhisperManager, "_instance", None)
    monkeypatch.setattr(whisper_manager.WhisperManager, "_model", None)
    monkeypatch.setattr(whisper_manager.WhisperManager, "_initialized", False)

    manager = whisper_manager.WhisperManager()
    assert manager.model is not None
    assert captured["model_reference"] == str(snapshot.resolve())
    assert captured["kwargs"]["local_files_only"] is True


def test_whisper_manager_refuses_floating_download_for_pinned_alias(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_MODEL", "large-v2")
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_MODEL_PATH", str(tmp_path))
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_USE_LOCAL", False)
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_DEVICE", "cpu")
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_COMPUTE_TYPE", "int8")
    monkeypatch.setattr(
        whisper_manager,
        "WhisperModel",
        lambda *_args, **_kwargs: pytest.fail(
            "pinned aliases must not download through a floating model name"
        ),
    )
    monkeypatch.setattr(whisper_manager.WhisperManager, "_instance", None)
    monkeypatch.setattr(whisper_manager.WhisperManager, "_model", None)
    monkeypatch.setattr(whisper_manager.WhisperManager, "_initialized", False)

    manager = whisper_manager.WhisperManager()
    expected_revision = whisper_manager.PINNED_MODEL_REVISIONS["large-v2"]
    with pytest.raises(FileNotFoundError, match=expected_revision):
        _ = manager.model

    assert manager._model is None


def test_whisper_manager_normalizes_explicit_cpu_float16_truthfully(
    monkeypatch,
    tmp_path,
):
    _write_cached_snapshot(
        tmp_path,
        "models--Systran--faster-whisper-large-v2",
        whisper_manager.PINNED_MODEL_REVISIONS["large-v2"],
    )
    captured = {}

    class RecordingWhisperModel:
        def __init__(self, _model_reference, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(whisper_manager.settings, "WHISPER_MODEL", "large-v2")
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_MODEL_PATH", str(tmp_path))
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_USE_LOCAL", True)
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_DEVICE", "cpu")
    monkeypatch.setattr(whisper_manager.settings, "WHISPER_COMPUTE_TYPE", "float16")
    monkeypatch.setattr(whisper_manager, "WhisperModel", RecordingWhisperModel)
    monkeypatch.setattr(whisper_manager.WhisperManager, "_instance", None)
    monkeypatch.setattr(whisper_manager.WhisperManager, "_model", None)
    monkeypatch.setattr(whisper_manager.WhisperManager, "_initialized", False)

    manager = whisper_manager.WhisperManager()
    assert manager.model is not None
    provenance = manager.provenance()

    assert captured["device"] == "cpu"
    assert captured["compute_type"] == "int8"
    assert provenance["requested_compute_type"] == "float16"
    assert provenance["compute_type"] == "int8"
    assert provenance["expected_model_revision"] == (
        whisper_manager.PINNED_MODEL_REVISIONS["large-v2"]
    )
    assert provenance["model_revision_matches_pin"] is True
    assert provenance["revision_policy"] == "pinned_immutable"
    assert provenance["runtime_normalized"] is True
    assert provenance["runtime_normalization_reason"] == (
        "cpu_float16_unsupported_normalized_to_int8"
    )
