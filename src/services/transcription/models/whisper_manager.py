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
            self._device = settings.WHISPER_DEVICE
            self._compute_type = settings.WHISPER_COMPUTE_TYPE
            self._initialized = True
            logger.info(f"[WHISPER_MANAGER] Initialized (lazy load enabled)")

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

            # Check if GPU is available
            if self._device == "cuda" and not torch.cuda.is_available():
                logger.warning("[WHISPER_MANAGER] CUDA not available, falling back to CPU")
                self._device = "cpu"
                self._compute_type = "int8"

            # Check if local model cache directory exists
            model_cache_dir = Path(settings.WHISPER_MODEL_PATH)
            if not model_cache_dir.exists():
                model_cache_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"[WHISPER_MANAGER] Created model cache directory: {model_cache_dir}")

            # Check if model is cached in HuggingFace format
            # faster-whisper stores models as: models--{org}--{model-name}
            # Example: models--mobiuslabsgmbh--faster-whisper-large-v3-turbo
            cache_found = False
            cached_model_name = None
            if model_cache_dir.exists():
                # Normalize model name for matching (remove "faster-whisper-" prefix if present)
                model_name_normalized = self._model_name.lower().replace("faster-whisper-", "").replace("-", "")
                # Look for any cached model that matches our model name
                for cached_dir in model_cache_dir.iterdir():
                    if cached_dir.is_dir() and cached_dir.name.startswith("models--"):
                        # Check if the cached model name contains our model name
                        cached_name_normalized = cached_dir.name.lower().replace("-", "").replace("_", "")
                        if model_name_normalized in cached_name_normalized:
                            cache_found = True
                            cached_model_name = cached_dir.name
                            logger.info(f"[WHISPER_MANAGER] Found cached model: {cached_dir.name}")
                            break

            if cache_found:
                logger.info(f"[WHISPER_MANAGER] Loading from local cache: {model_cache_dir}")
            else:
                logger.warning(
                    f"[WHISPER_MANAGER] Model not found in cache. "
                    f"Will attempt to use cached model or download if needed. "
                    f"Cache directory: {model_cache_dir}"
                )

            # Load model - faster-whisper will automatically find cached models
            # in HuggingFace format when download_root is set
            # It searches for models in the format: models--{org}--{model-name}
            self._model = WhisperModel(
                self._model_name,
                device=self._device,
                compute_type=self._compute_type,
                download_root=str(model_cache_dir.absolute())
            )

            logger.info(f"[WHISPER_MANAGER] Model loaded successfully from local cache")

        except Exception as e:
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
