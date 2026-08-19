"""
Whisper Model Manager - Singleton Pattern
Lazy loading for better performance
"""
import logging
import torch
from faster_whisper import WhisperModel
from pathlib import Path
from typing import Optional
from src.core.config import settings

logger = logging.getLogger(__name__)


WHISPER_MODEL_SPECS = {
    "large-v2": {
        "cache_name": "models--Systran--faster-whisper-large-v2",
        "provider_id": "Systran/faster-whisper-large-v2",
        "revision": "f0fe81560cb8b68660e564f55dd99207059c092e",
    },
    "large-v3": {
        "cache_name": "models--Systran--faster-whisper-large-v3",
        "provider_id": "Systran/faster-whisper-large-v3",
        "revision": "edaa852ec7e145841d8ffdb056a99866b5f0a478",
    },
    "large-v3-turbo": {
        "cache_name": "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
        "provider_id": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "revision": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
    },
    "turbo": {
        "cache_name": "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
        "provider_id": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "revision": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
    },
}

MODEL_CACHE_NAMES = {
    alias: spec["cache_name"] for alias, spec in WHISPER_MODEL_SPECS.items()
}
MODEL_PROVIDER_IDS = {
    alias: spec["provider_id"] for alias, spec in WHISPER_MODEL_SPECS.items()
}
PINNED_MODEL_REVISIONS = {
    alias: spec["revision"] for alias, spec in WHISPER_MODEL_SPECS.items()
}

REQUIRED_SNAPSHOT_FILES = ("config.json", "model.bin", "tokenizer.json")


class SnapshotResolutionError(RuntimeError):
    """Raised when a local model cache cannot identify one exact valid revision."""


def is_usable_snapshot(snapshot: Path) -> bool:
    return all(
        (snapshot / filename).is_file() and (snapshot / filename).stat().st_size > 0
        for filename in REQUIRED_SNAPSHOT_FILES
    )


def _resolve_main_snapshot(model_root: Path, expected_revision: str) -> Path:
    ref_path = model_root / "refs" / "main"
    if not ref_path.is_file():
        raise SnapshotResolutionError(
            f"Missing exact refs/main revision selector: {model_root}"
        )

    revisions = [
        line.strip()
        for line in ref_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(revisions) != 1:
        raise SnapshotResolutionError(
            f"Ambiguous refs/main revision selector: {ref_path}"
        )
    revision = revisions[0]
    if revision in {".", ".."} or "/" in revision or "\\" in revision:
        raise SnapshotResolutionError(
            f"Invalid refs/main revision selector: {ref_path}"
        )
    if revision != expected_revision:
        raise SnapshotResolutionError(
            "refs/main revision does not match the pinned immutable revision "
            f"for {model_root.name}: expected {expected_revision}, got {revision}"
        )

    snapshots_root = (model_root / "snapshots").resolve()
    snapshot = (snapshots_root / revision).resolve()
    if snapshot.parent != snapshots_root or not snapshot.is_dir():
        raise SnapshotResolutionError(
            f"refs/main points to a missing snapshot: {revision}"
        )
    incomplete = [
        filename
        for filename in REQUIRED_SNAPSHOT_FILES
        if not (snapshot / filename).is_file()
        or (snapshot / filename).stat().st_size <= 0
    ]
    if incomplete:
        raise SnapshotResolutionError(
            "refs/main points to an incomplete snapshot "
            f"({revision}): {', '.join(incomplete)}"
        )
    return snapshot


def resolve_cached_model(model_name: str, cache_root: Path) -> Path | None:
    direct_path = Path(model_name)
    if direct_path.is_dir():
        if not is_usable_snapshot(direct_path):
            raise SnapshotResolutionError(
                f"Explicit Whisper snapshot is incomplete: {direct_path}"
            )
        return direct_path.resolve()

    normalized_name = model_name.casefold()
    spec = WHISPER_MODEL_SPECS.get(normalized_name)
    if not spec:
        return None
    cache_path = cache_root / spec["cache_name"]
    if not cache_path.exists():
        return None
    return _resolve_main_snapshot(cache_path, spec["revision"])


def normalize_whisper_runtime(
    device: str,
    compute_type: str,
    *,
    cuda_available: bool | None = None,
) -> tuple[str, str, str | None]:
    """Return a supported effective runtime and an auditable normalization reason."""

    normalized_device = str(device).strip().casefold()
    normalized_compute_type = str(compute_type).strip().casefold()
    if not normalized_device or not normalized_compute_type:
        raise ValueError("Whisper device and compute_type must be non-empty")

    if normalized_device == "cuda":
        available = torch.cuda.is_available() if cuda_available is None else cuda_available
        if not available:
            return "cpu", "int8", "cuda_unavailable_fallback_to_cpu_int8"
    if normalized_device == "cpu" and normalized_compute_type == "float16":
        return "cpu", "int8", "cpu_float16_unsupported_normalized_to_int8"
    return normalized_device, normalized_compute_type, None


class WhisperManager:
    """
    Singleton manager for Whisper model
    Ensures only one instance is loaded in memory
    """
    _instance: Optional['WhisperManager'] = None
    _model: Optional[WhisperModel] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if not self._initialized:
            self._model_name = settings.WHISPER_MODEL
            self._requested_device = settings.WHISPER_DEVICE
            self._requested_compute_type = settings.WHISPER_COMPUTE_TYPE
            (
                self._device,
                self._compute_type,
                self._runtime_normalization_reason,
            ) = normalize_whisper_runtime(
                self._requested_device,
                self._requested_compute_type,
            )
            self._resolved_model_path: Path | None = None
            self._initialized = True
            logger.info("[WHISPER_MANAGER] Initialized (lazy load enabled)")

    @property
    def model(self) -> WhisperModel:
        """
        Lazy load Whisper model on first access
        Returns cached instance on subsequent calls
        """
        if self._model is None:
            self._load_model()
        return self._model

    def _load_model(self):
        """Load Whisper model with optimal settings"""
        try:
            logger.info(
                f"[WHISPER_MANAGER] Loading model: {self._model_name} | "
                f"device={self._device} | compute_type={self._compute_type}"
            )

            if self._runtime_normalization_reason:
                logger.warning(
                    "[WHISPER_MANAGER] Runtime normalized | requested=%s/%s | "
                    "effective=%s/%s | reason=%s",
                    self._requested_device,
                    self._requested_compute_type,
                    self._device,
                    self._compute_type,
                    self._runtime_normalization_reason,
                )

            # Check if local model cache directory exists
            model_cache_dir = Path(settings.WHISPER_MODEL_PATH)
            if not model_cache_dir.exists():
                model_cache_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"[WHISPER_MANAGER] Created model cache directory: {model_cache_dir}")

            cached_model_path = resolve_cached_model(self._model_name, model_cache_dir)
            if cached_model_path:
                logger.info(
                    "[WHISPER_MANAGER] Exact cached model resolved: %s",
                    cached_model_path,
                )
            elif settings.WHISPER_USE_LOCAL:
                raise FileNotFoundError(
                    f"Offline Whisper model is not cached: {self._model_name} in {model_cache_dir}"
                )
            elif self._model_name.casefold() in PINNED_MODEL_REVISIONS:
                raise FileNotFoundError(
                    "Pinned Whisper snapshot is not installed; automatic floating-ref "
                    f"download is disabled for {self._model_name}. Expected revision: "
                    f"{PINNED_MODEL_REVISIONS[self._model_name.casefold()]}"
                )
            else:
                logger.warning(
                    "[WHISPER_MANAGER] Exact model is not cached; download is allowed | model=%s | cache=%s",
                    self._model_name,
                    model_cache_dir,
                )

            # Load model - faster-whisper will automatically find cached models
            # in HuggingFace format when download_root is set
            # It searches for models in the format: models--{org}--{model-name}
            model_reference = str(cached_model_path) if cached_model_path else self._model_name
            self._model = WhisperModel(
                model_reference,
                device=self._device,
                compute_type=self._compute_type,
                download_root=str(model_cache_dir.absolute()),
                local_files_only=settings.WHISPER_USE_LOCAL,
            )
            self._resolved_model_path = cached_model_path or resolve_cached_model(
                self._model_name,
                model_cache_dir,
            )

            logger.info(
                "[WHISPER_MANAGER] Model loaded | model=%s | local_only=%s",
                self._model_name,
                settings.WHISPER_USE_LOCAL,
            )

        except Exception as e:
            self._model = None
            self._resolved_model_path = None
            logger.error(f"[WHISPER_MANAGER] Failed to load model: {e}", exc_info=True)
            raise

    def transcribe(
        self,
        audio_path: str,
        language: str = "vi",
        beam_size: int = None,
        vad_filter: bool = False,
        **kwargs
    ):
        """
        Transcribe audio file

        Args:
            audio_path: Path to audio file
            language: Language code (default: vi)
            beam_size: Beam search size (default: from config)
            vad_filter: Enable VAD filtering (default: False to avoid cutting content)
            **kwargs: Additional arguments for Whisper

        Returns:
            Generator of transcription segments
        """
        if beam_size is None:
            beam_size = settings.WHISPER_BEAM_SIZE

        logger.info(
            f"[WHISPER_MANAGER] Transcribing: {Path(audio_path).name} | "
            f"language={language} | beam_size={beam_size} | vad_filter={vad_filter}"
        )

        segments, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            **kwargs
        )

        return segments, info

    def provenance(self) -> dict:
        cache_root = Path(settings.WHISPER_MODEL_PATH)
        snapshot = self._resolved_model_path or resolve_cached_model(
            self._model_name,
            cache_root,
        )
        revision = snapshot.name if snapshot is not None else None
        expected_revision = PINNED_MODEL_REVISIONS.get(self._model_name.casefold())
        repository_root = Path(__file__).resolve().parents[4]
        artifact_path = None
        if snapshot is not None:
            try:
                artifact_path = snapshot.relative_to(repository_root).as_posix()
            except ValueError:
                artifact_path = snapshot.name
        return {
            "provider": "faster-whisper",
            "model_id": MODEL_PROVIDER_IDS.get(
                self._model_name.casefold(),
                self._model_name,
            ),
            "model_revision": revision,
            "expected_model_revision": expected_revision,
            "model_revision_matches_pin": (
                revision == expected_revision
                if expected_revision is not None and revision is not None
                else False
            ),
            "revision_policy": (
                "pinned_immutable" if expected_revision is not None else "explicit_unpinned"
            ),
            "artifact_path": artifact_path,
            "artifact_verified": snapshot is not None,
            "requested_device": self._requested_device,
            "requested_compute_type": self._requested_compute_type,
            "device": self._device,
            "compute_type": self._compute_type,
            "runtime_normalized": self._runtime_normalization_reason is not None,
            "runtime_normalization_reason": self._runtime_normalization_reason,
        }

    def unload(self):
        """Unload model from memory (for cleanup)"""
        if self._model is not None:
            logger.info("[WHISPER_MANAGER] Unloading model")
            del self._model
            self._model = None
            torch.cuda.empty_cache() if torch.cuda.is_available() else None

    @classmethod
    def get_instance(cls) -> 'WhisperManager':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# Global accessor
def get_whisper_manager() -> WhisperManager:
    """Get global Whisper manager instance"""
    return WhisperManager.get_instance()
