import importlib
import subprocess
import sys
from pathlib import Path


def test_pyannote_loader_import_is_heavy_dependency_safe():
    repo_root = Path(__file__).resolve().parents[1]
    code = """
import sys
import src.services.transcription.models.pyannote_loader as module

assert module.DEFAULT_MODEL_ID == "pyannote/speaker-diarization-community-1"
loaded = {
    name: name in sys.modules
    for name in ("pyannote.audio", "torch", "faster_whisper")
}
if any(loaded.values()):
    print(loaded)
    raise SystemExit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_load_pyannote_pipeline_does_not_download_when_disabled(monkeypatch, tmp_path):
    module = importlib.import_module("src.services.transcription.models.pyannote_loader")
    monkeypatch.setenv("PYANNOTE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PYANNOTE_AUTO_DOWNLOAD", "false")
    monkeypatch.setenv("HF_TOKEN", "fake-token")

    class FakeHub:
        @staticmethod
        def snapshot_download(*args, **kwargs):
            raise AssertionError("snapshot_download should not be called")

    monkeypatch.setitem(sys.modules, "huggingface_hub", FakeHub)

    assert module.load_pyannote_pipeline() is None


def test_normalize_diarization_output_prefers_exclusive_output():
    module = importlib.import_module("src.services.transcription.models.pyannote_loader")

    class Turn:
        def __init__(self, start, end):
            self.start = start
            self.end = end

    class Wrapped:
        exclusive_speaker_diarization = [
            (Turn(2.0, 3.0), "speaker-b"),
            (Turn(0.0, 1.0), "speaker-a"),
            (Turn(4.0, 4.0), "invalid"),
        ]
        speaker_diarization = [
            (Turn(0.0, 10.0), "unused"),
        ]

    assert module.normalize_diarization_output(Wrapped()) == [
        {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_01"},
        {"start": 2.0, "end": 3.0, "speaker": "SPEAKER_00"},
    ]


def test_normalize_diarization_output_supports_annotation_and_dict():
    module = importlib.import_module("src.services.transcription.models.pyannote_loader")

    class Turn:
        def __init__(self, start, end):
            self.start = start
            self.end = end

    class Annotation:
        def itertracks(self, yield_label=True):
            yield Turn(1, 2), "track", "alpha"
            yield Turn(2, 3), "track", "alpha"

    assert module.normalize_diarization_output(Annotation()) == [
        {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_00"},
        {"start": 2.0, "end": 3.0, "speaker": "SPEAKER_00"},
    ]

    assert module.normalize_diarization_output({
        "speaker_diarization": [
            {"start": "0.5", "end": "1.5", "speaker": "beta"},
            {"start": "bad", "end": 2, "speaker": "ignored"},
        ]
    }) == [
        {"start": 0.5, "end": 1.5, "speaker": "SPEAKER_00"},
    ]
