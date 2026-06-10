"""
Whisper Model Manager - Singleton Pattern
Lazy loading for better performance
"""
import logging
import torch
from pathlib import Path
from typing import Any, Optional
from src.core.config import settings
from src.services.model_artifacts import ModelArtifactError, require_faster_whisper_runtime_ready

logger = logging.getLogger(__name__)


class WhisperManager:
    """
    Singleton manager for Whisper model
    Ensures only one instance is loaded in memory
    """
    _instance: Optional['WhisperManager'] = None
    _model: Optional[Any] = None
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
    def model(self) -> Any:
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

            verified_model_path = require_faster_whisper_runtime_ready(
                self._model_name,
                cache_root=settings.WHISPER_MODEL_PATH,
            )
            logger.info("[WHISPER_MANAGER] Loading verified local model artifact")

            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                str(verified_model_path),
                device=self._device,
                compute_type=self._compute_type,
            )

            logger.info(f"[WHISPER_MANAGER] Model loaded successfully from local cache")

        except ModelArtifactError as e:
            logger.error("[WHISPER_MANAGER] Model artifact unavailable: reason=%s", e.reason_code)
            raise
        except Exception as e:
            logger.error("[WHISPER_MANAGER] Failed to load model: error_class=%s", e.__class__.__name__)
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
