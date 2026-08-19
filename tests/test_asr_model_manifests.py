from pathlib import Path

from src.services.model_runtime.manifest import load_manifest
from src.services.transcription.models.whisper_manager import WHISPER_MODEL_SPECS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = {
    "large-v2": PROJECT_ROOT / "config/models/faster-whisper-large-v2.manifest.json",
    "large-v3": PROJECT_ROOT / "config/models/faster-whisper-large-v3.manifest.json",
    "large-v3-turbo": (
        PROJECT_ROOT / "config/models/faster-whisper-large-v3-turbo.manifest.json"
    ),
}


def test_asr_manifests_match_runtime_pins() -> None:
    for alias, path in MANIFESTS.items():
        manifest = load_manifest(path)
        spec = WHISPER_MODEL_SPECS[alias]

        assert manifest.model.source.repository == spec["provider_id"]
        assert manifest.model.source.revision == spec["revision"]
        assert manifest.model.version == spec["revision"]
        assert manifest.model.tasks == ("transcription",)
        assert spec["cache_name"] in manifest.model.relative_path
        assert manifest.model.relative_path.endswith(f"snapshots/{spec['revision']}")


def test_primary_asr_profile_is_documented_for_gpu_and_cpu() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "WHISPER_MODEL=large-v2" in env_example
    assert "WHISPER_DEVICE=cuda" in env_example
    assert "WHISPER_COMPUTE_TYPE=float16" in env_example
    assert "WHISPER_DEVICE=cpu" in env_example
    assert "WHISPER_COMPUTE_TYPE=int8" in env_example
