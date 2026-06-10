import importlib
import subprocess
import sys
import types
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


def test_pipeline_from_pretrained_uses_local_config_file(monkeypatch, tmp_path):
    module = importlib.import_module("src.services.transcription.models.pyannote_loader")
    model_dir = tmp_path / "pyannote--speaker-diarization-community-1"
    model_dir.mkdir()
    (model_dir / "config.yaml").write_text("pipeline:\n  name: fake\n", encoding="utf-8")
    calls = []

    class FakePipeline:
        @staticmethod
        def from_pretrained(checkpoint_path, **kwargs):
            calls.append((checkpoint_path, kwargs))
            return "pipeline"

    monkeypatch.setitem(sys.modules, "pyannote.audio", types.SimpleNamespace(Pipeline=FakePipeline))

    assert module._pipeline_from_pretrained(model_dir) == "pipeline"
    assert calls == [(str(model_dir / "config.yaml"), {})]


def test_load_pyannote_pipeline_does_not_runtime_download_when_enabled(monkeypatch, tmp_path):
    module = importlib.import_module("src.services.transcription.models.pyannote_loader")
    monkeypatch.setenv("PYANNOTE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PYANNOTE_AUTO_DOWNLOAD", "true")
    monkeypatch.setenv("HF_TOKEN", "fake-token")

    class FakeHub:
        @staticmethod
        def snapshot_download(*args, **kwargs):
            raise AssertionError("runtime snapshot_download should not be called")

    monkeypatch.setitem(sys.modules, "huggingface_hub", FakeHub)

    assert module.load_pyannote_pipeline() is None


def test_pyannote_model_override_must_be_manifested(monkeypatch, tmp_path):
    module = importlib.import_module("src.services.transcription.models.pyannote_loader")
    monkeypatch.setenv("PYANNOTE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PYANNOTE_MODEL_ID", "pyannote/speaker-diarization-3.1")
    monkeypatch.setenv("PYANNOTE_AUTO_DOWNLOAD", "true")
    monkeypatch.setenv("HF_TOKEN", "fake-token")

    class FakeHub:
        @staticmethod
        def snapshot_download(*args, **kwargs):
            raise AssertionError("unmanifested Pyannote override should not download")

    monkeypatch.setitem(sys.modules, "huggingface_hub", FakeHub)

    assert module.load_pyannote_pipeline() is None


def test_pyannote_downloader_rejects_unmanifested_fallback(monkeypatch):
    script = importlib.import_module("download_pyannote_model")
    monkeypatch.setenv("HF_TOKEN", "fake-token")
    monkeypatch.setenv("PYANNOTE_MODEL_ID", "pyannote/speaker-diarization-3.1")
    monkeypatch.setattr(sys, "argv", ["download_pyannote_model.py", "--no-dotenv"])

    assert script.main() == 2


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
