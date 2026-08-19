"""
Pyannote Model Manager - Singleton Pattern
Lazy loading with local model support for portability
"""
import logging
import re
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Optional
import torch

from src.core.config import settings
from src.services.model_runtime import resolve_huggingface_snapshot

logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
PYANNOTE_MODEL_ROOT = (PROJECT_ROOT / "models" / "pyannote").resolve()
PYANNOTE_31_MODEL_ID = "pyannote/speaker-diarization-3.1"
PYANNOTE_31_REVISION = "84fd25912480287da0247647c3d2b4853cb3ee5d"
PYANNOTE_SEGMENTATION_MODEL_ID = "pyannote/segmentation-3.0"
PYANNOTE_SEGMENTATION_REVISION = "e66f3d3b9eb0873085418a7b813d3b369bf160bb"
PYANNOTE_EMBEDDING_MODEL_ID = "pyannote/wespeaker-voxceleb-resnet34-LM"
PYANNOTE_EMBEDDING_REVISION = "837717ddb9ff5507820346191109dc79c958d614"
PYANNOTE_COMMUNITY_MODEL_ID = "pyannote/speaker-diarization-community-1"
PYANNOTE_COMMUNITY_REVISION = "3533c8cf8e369892e6b79ff1bf80f7b0286a54ee"

PYANNOTE_31_REQUIRED_FILES = ("config.yaml",)
PYANNOTE_31_DEPENDENCIES = (
    (
        PYANNOTE_SEGMENTATION_MODEL_ID,
        PYANNOTE_SEGMENTATION_REVISION,
        ("config.yaml", "pytorch_model.bin"),
    ),
    (
        PYANNOTE_EMBEDDING_MODEL_ID,
        PYANNOTE_EMBEDDING_REVISION,
        ("config.yaml", "pytorch_model.bin"),
    ),
)
PYANNOTE_COMMUNITY_REQUIRED_FILES = (
    "config.yaml",
    "embedding/pytorch_model.bin",
    "plda/plda.npz",
    "plda/xvec_transform.npz",
    "segmentation/pytorch_model.bin",
)


def _pyannote_audio_major() -> int:
    try:
        return int(version("pyannote.audio").split(".", 1)[0])
    except (PackageNotFoundError, ValueError):
        return 0


def compatible_model_spec() -> tuple[str, str, tuple[str, ...]]:
    """Return the model contract compatible with the installed runtime."""

    if _pyannote_audio_major() >= 4:
        return (
            PYANNOTE_COMMUNITY_MODEL_ID,
            PYANNOTE_COMMUNITY_REVISION,
            PYANNOTE_COMMUNITY_REQUIRED_FILES,
        )
    return PYANNOTE_31_MODEL_ID, PYANNOTE_31_REVISION, PYANNOTE_31_REQUIRED_FILES


def resolve_compatible_local_snapshot(
    model_root: Path = PYANNOTE_MODEL_ROOT,
) -> tuple[Path, str, str] | None:
    """Resolve only a complete snapshot compatible with the installed stack."""

    model_id, expected_revision, required_files = compatible_model_spec()
    snapshot = resolve_huggingface_snapshot(
        model_root.resolve(),
        model_id,
        required_files=required_files,
    )
    if snapshot is None:
        return None
    if any((snapshot / relative_path).stat().st_size <= 0 for relative_path in required_files):
        logger.warning("[PYANNOTE_MANAGER] Pipeline snapshot contains an empty artifact")
        return None

    revision = snapshot.name if re.fullmatch(r"[0-9a-f]{40}", snapshot.name) else None
    if revision is not None and revision != expected_revision:
        logger.warning(
            "[PYANNOTE_MANAGER] Snapshot revision mismatch | expected=%s actual=%s",
            expected_revision,
            revision,
        )
        return None

    if model_id == PYANNOTE_31_MODEL_ID:
        for dependency_id, dependency_revision, dependency_files in PYANNOTE_31_DEPENDENCIES:
            dependency = resolve_huggingface_snapshot(
                model_root.resolve(),
                dependency_id,
                required_files=dependency_files,
            )
            if dependency is None or dependency.name != dependency_revision:
                logger.warning(
                    "[PYANNOTE_MANAGER] Missing or unpinned dependency | model=%s revision=%s",
                    dependency_id,
                    dependency_revision,
                )
                return None
            if any(
                (dependency / relative_path).stat().st_size <= 0
                for relative_path in dependency_files
            ):
                logger.warning(
                    "[PYANNOTE_MANAGER] Dependency contains an empty artifact | model=%s",
                    dependency_id,
                )
                return None
    return snapshot.resolve(), model_id, revision or expected_revision


def required_artifact_files() -> list[str]:
    model_id, _revision, required_files = compatible_model_spec()
    required = [f"{model_id}:{path}" for path in required_files]
    if model_id == PYANNOTE_31_MODEL_ID:
        for dependency_id, _dependency_revision, dependency_files in PYANNOTE_31_DEPENDENCIES:
            required.extend(f"{dependency_id}:{path}" for path in dependency_files)
    return required


def unwrap_diarization_annotation(output: Any) -> Any:
    """Normalize Pyannote 3.x annotations and 4.x pipeline output objects."""

    exclusive = getattr(output, "exclusive_speaker_diarization", None)
    if exclusive is not None:
        return exclusive
    regular = getattr(output, "speaker_diarization", None)
    if regular is not None:
        return regular
    return output


class PyannoteManager:
    """
    Singleton manager for Pyannote diarization model
    Loads from local models/ directory for portability
    """
    _instance: Optional['PyannoteManager'] = None
    _pipeline = None
    _initialized: bool = False
    _load_attempted: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._initialized = True
            self._load_error: Optional[str] = None
            self._model_id: Optional[str] = None
            self._model_revision: Optional[str] = None
            self._artifact_verified = False
            logger.info("[PYANNOTE_MANAGER] Initialized (lazy load enabled)")

    @property
    def pipeline(self):
        """
        Lazy load Pyannote pipeline on first access
        Tries local models first, falls back to HuggingFace
        """
        if self._pipeline is None and not self._load_attempted:
            self._load_pipeline()
        return self._pipeline

    def _load_pipeline(self):
        """Load Pyannote diarization pipeline"""
        self._load_attempted = True
        self._load_error = None
        try:
            from pyannote.audio import Pipeline

            local_snapshot = resolve_compatible_local_snapshot()

            if local_snapshot is not None:
                local_model_path, model_id, model_revision = local_snapshot
                logger.info("[PYANNOTE_MANAGER] Loading local snapshot: %s", local_model_path)
                try:
                    self._pipeline = Pipeline.from_pretrained(
                        local_model_path / "config.yaml",
                        use_auth_token=False,
                        cache_dir=str(PYANNOTE_MODEL_ROOT),
                    )
                    self._model_id = model_id
                    self._model_revision = model_revision
                    self._artifact_verified = True
                    logger.info("[PYANNOTE_MANAGER] Local model loaded successfully")
                except Exception as e:
                    logger.warning(f"[PYANNOTE_MANAGER] Failed to load local model: {e}")
                    self._load_error = f"local_load_failed: {type(e).__name__}: {e}"[:500]
                    self._pipeline = None

            if self._pipeline is None and settings.OFFLINE_STRICT:
                if self._load_error is None:
                    model_id, _revision, _required = compatible_model_spec()
                    self._load_error = f"complete_local_snapshot_missing: {model_id}"
                logger.warning(
                    "[PYANNOTE_MANAGER] No complete local snapshot; offline strict mode refuses provider fallback"
                )
            elif self._pipeline is None:
                logger.info("[PYANNOTE_MANAGER] Loading from HuggingFace")
                hf_token = settings.HF_TOKEN if hasattr(settings, 'HF_TOKEN') else None
                model_id, model_revision, _required = compatible_model_spec()

                if hf_token:
                    self._pipeline = Pipeline.from_pretrained(
                        model_id,
                        use_auth_token=hf_token
                    )
                    self._model_id = model_id
                    self._model_revision = model_revision
                    self._artifact_verified = False
                    logger.info("[PYANNOTE_MANAGER] HuggingFace model loaded")
                else:
                    logger.warning("[PYANNOTE_MANAGER] No HF_TOKEN, pyannote unavailable")
                    self._load_error = "hf_token_missing"
                    self._pipeline = None

            # Move to GPU if available
            if self._pipeline is not None and torch.cuda.is_available():
                self._pipeline = self._pipeline.to(torch.device("cuda"))
                logger.info("[PYANNOTE_MANAGER] Pipeline moved to GPU")

        except ImportError:
            logger.warning("[PYANNOTE_MANAGER] pyannote.audio not installed")
            self._load_error = "pyannote_audio_not_installed"
            self._pipeline = None
        except Exception as e:
            logger.error(f"[PYANNOTE_MANAGER] Failed to load: {e}", exc_info=True)
            self._load_error = f"pipeline_load_failed: {type(e).__name__}: {e}"[:500]
            self._pipeline = None

    def diarize(self, audio_path: str, num_speakers: int = None):
        """
        Perform speaker diarization

        Args:
            audio_path: Path to audio file
            num_speakers: Number of speakers (None = auto-detect)

        Returns:
            Diarization result or None if not available
        """
        if self.pipeline is None:
            logger.warning("[PYANNOTE_MANAGER] Pipeline not available")
            return None

        try:
            logger.info(
                f"[PYANNOTE_MANAGER] Diarizing: {Path(audio_path).name} | "
                f"num_speakers={num_speakers or 'auto'}"
            )

            audio_path_obj = Path(audio_path)
            file_ext = audio_path_obj.suffix.lower()

            if file_ext in ['.m4a', '.mp3', '.ogg']:
                logger.info(f"[PYANNOTE_MANAGER] Converting {file_ext} to WAV for diarization...")
                with tempfile.TemporaryDirectory(prefix="stt-diarization-") as temp_dir:
                    from src.audio_processing.processor import AudioProcessor

                    processor = AudioProcessor()
                    temp_wav_path = Path(temp_dir) / "audio.wav"
                    processor.convert_format(audio_path, temp_wav_path, target_format="wav")
                    logger.info(f"[PYANNOTE_MANAGER] Converted to WAV: {temp_wav_path}")
                    result = self._run_pipeline(str(temp_wav_path), num_speakers)
            else:
                result = self._run_pipeline(audio_path, num_speakers)

            logger.info("[PYANNOTE_MANAGER] Diarization complete")
            return unwrap_diarization_annotation(result)

        except Exception as e:
            logger.error(f"[PYANNOTE_MANAGER] Diarization failed: {e}", exc_info=True)
            self._load_error = f"diarization_failed: {type(e).__name__}: {e}"[:500]
            return None

    def _run_pipeline(self, audio_path: str, num_speakers: int | None):
        if num_speakers is not None:
            return self.pipeline(audio_path, num_speakers=num_speakers)
        return self.pipeline(audio_path)

    def provenance(self) -> dict[str, Any]:
        model_id, expected_revision, _required_files = compatible_model_spec()
        return {
            "provider": "pyannote",
            "model_id": self._model_id or model_id,
            "model_revision": self._model_revision or expected_revision,
            "artifact_root": str(PYANNOTE_MODEL_ROOT),
            "artifact_verified": self._artifact_verified,
            "required_files": required_artifact_files(),
            "load_error": self._load_error,
            "assignment_method": "segment_max_overlap",
        }

    def is_available(self) -> bool:
        """Check if Pyannote is available"""
        return self.pipeline is not None

    def unload(self):
        """Unload pipeline from memory"""
        if self._pipeline is not None:
            logger.info("[PYANNOTE_MANAGER] Unloading pipeline")
            del self._pipeline
            self._pipeline = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        self._load_attempted = False
        self._load_error = None
        self._model_id = None
        self._model_revision = None
        self._artifact_verified = False

    @classmethod
    def get_instance(cls) -> 'PyannoteManager':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# Global accessor
def get_pyannote_manager() -> PyannoteManager:
    """Get global Pyannote manager instance"""
    return PyannoteManager.get_instance()
