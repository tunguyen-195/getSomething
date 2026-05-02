"""
Pyannote Model Manager - Singleton Pattern
Lazy loading with local model support for portability
"""
import logging
from pathlib import Path
from typing import Optional
import torch

logger = logging.getLogger(__name__)


class PyannoteManager:
    """
    Singleton manager for Pyannote diarization model
    Loads from local models/ directory for portability
    """
    _instance: Optional['PyannoteManager'] = None
    _pipeline = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._initialized = True
            logger.info(f"[PYANNOTE_MANAGER] Initialized (lazy load enabled)")

    @property
    def pipeline(self):
        """
        Lazy load Pyannote pipeline on first access
        Tries local models first, falls back to HuggingFace
        """
        if self._pipeline is None:
            self._load_pipeline()
        return self._pipeline

    def _load_pipeline(self):
        """Load Pyannote diarization pipeline"""
        try:
            from pyannote.audio import Pipeline

            # Try local model first (for portability)
            local_model_path = Path("models/pyannote/models--pyannote--speaker-diarization-3.1")

            if local_model_path.exists():
                logger.info(f"[PYANNOTE_MANAGER] Loading from local: {local_model_path}")
                try:
                    self._pipeline = Pipeline.from_pretrained(
                        str(local_model_path),
                        use_auth_token=False
                    )
                    logger.info("[PYANNOTE_MANAGER] Local model loaded successfully")
                except Exception as e:
                    logger.warning(f"[PYANNOTE_MANAGER] Failed to load local model: {e}")
                    self._pipeline = None

            # Fallback to HuggingFace
            if self._pipeline is None:
                logger.info("[PYANNOTE_MANAGER] Loading from HuggingFace")
                from src.core.config import settings

                hf_token = settings.HF_TOKEN if hasattr(settings, 'HF_TOKEN') else None

                if hf_token:
                    self._pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1",
                        use_auth_token=hf_token
                    )
                    logger.info("[PYANNOTE_MANAGER] HuggingFace model loaded")
                else:
                    logger.warning("[PYANNOTE_MANAGER] No HF_TOKEN, pyannote unavailable")
                    self._pipeline = None

            # Move to GPU if available
            if self._pipeline is not None and torch.cuda.is_available():
                self._pipeline = self._pipeline.to(torch.device("cuda"))
                logger.info("[PYANNOTE_MANAGER] Pipeline moved to GPU")

        except ImportError:
            logger.warning("[PYANNOTE_MANAGER] pyannote.audio not installed")
            self._pipeline = None
        except Exception as e:
            logger.error(f"[PYANNOTE_MANAGER] Failed to load: {e}", exc_info=True)
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

            # Check if file format is supported by Pyannote
            # Pyannote uses soundfile which doesn't support .m4a
            audio_path_obj = Path(audio_path)
            file_ext = audio_path_obj.suffix.lower()

            # Convert unsupported formats to WAV
            if file_ext in ['.m4a', '.mp3', '.ogg']:
                logger.info(f"[PYANNOTE_MANAGER] Converting {file_ext} to WAV for diarization...")
                try:
                    from src.audio_processing.processor import AudioProcessor
                    processor = AudioProcessor()
                    temp_wav_path = audio_path_obj.with_suffix('.wav')

                    # Convert to WAV
                    processor.convert_format(audio_path, temp_wav_path, target_format="wav")
                    logger.info(f"[PYANNOTE_MANAGER] Converted to WAV: {temp_wav_path}")

                    # Use converted file for diarization
                    audio_path_to_use = str(temp_wav_path)
                    should_cleanup = True
                except Exception as conv_error:
                    logger.warning(f"[PYANNOTE_MANAGER] Failed to convert audio: {conv_error}. Trying original file...")
                    audio_path_to_use = audio_path
                    should_cleanup = False
            else:
                audio_path_to_use = audio_path
                should_cleanup = False

            try:
                if num_speakers:
                    result = self.pipeline(audio_path_to_use, num_speakers=num_speakers)
                else:
                    result = self.pipeline(audio_path_to_use)

                logger.info(f"[PYANNOTE_MANAGER] Diarization complete")
                return result
            finally:
                # Cleanup temporary WAV file if created
                if should_cleanup and Path(audio_path_to_use).exists():
                    try:
                        Path(audio_path_to_use).unlink()
                        logger.debug(f"[PYANNOTE_MANAGER] Cleaned up temporary WAV file: {audio_path_to_use}")
                    except Exception as cleanup_error:
                        logger.warning(f"[PYANNOTE_MANAGER] Failed to cleanup temp file: {cleanup_error}")

        except Exception as e:
            logger.error(f"[PYANNOTE_MANAGER] Diarization failed: {e}", exc_info=True)
            # If format conversion failed, try to continue without diarization
            if "Format not recognised" in str(e) or "LibsndfileError" in str(type(e).__name__):
                logger.warning(f"[PYANNOTE_MANAGER] Audio format not supported. Skipping diarization.")
            return None

    def is_available(self) -> bool:
        """Check if Pyannote is available"""
        return self.pipeline is not None

    def unload(self):
        """Unload pipeline from memory"""
        if self._pipeline is not None:
            logger.info("[PYANNOTE_MANAGER] Unloading pipeline")
            del self._pipeline
            self._pipeline = None
            torch.cuda.empty_cache() if torch.cuda.is_available() else None

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
