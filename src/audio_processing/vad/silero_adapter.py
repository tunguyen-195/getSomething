"""
Silero VAD Adapter for Audio Preprocessing.
Removes silence segments before ASR to reduce Whisper hallucination.

TUNING PHILOSOPHY:
- Conservative mode: Prioritize NOT missing any speech
- Better to include some silence than miss speech
- All information must be preserved
"""
import logging
import torch
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional
import soundfile as sf
import tempfile
import os
import requests

logger = logging.getLogger(__name__)


class SileroVADAdapter:
    """
    Voice Activity Detection using Silero VAD.
    Preprocesses audio to remove silence before ASR.

    CONSERVATIVE TUNING (Prioritize information preservation):
    - Lower threshold = more sensitive to speech (less likely to miss)
    - Shorter min_speech_duration = catch short utterances
    - Speech padding = add margin around detected speech
    """

    def __init__(self,
                 threshold: float = 0.3,          # LOWERED from 0.5 - more sensitive
                 sampling_rate: int = 16000,
                 min_speech_duration_ms: int = 100,  # LOWERED from 250 - catch short sounds
                 min_silence_duration_ms: int = 300, # RAISED from 100 - need longer silence to cut
                 speech_pad_ms: int = 200):          # NEW: padding around speech for safety
        """
        Args:
            threshold: VAD confidence threshold (0.0-1.0). Lower = more conservative.
            sampling_rate: Audio sample rate (Whisper uses 16kHz)
            min_speech_duration_ms: Minimum speech segment duration (shorter = safer)
            min_silence_duration_ms: Minimum silence to consider as gap (longer = safer)
            speech_pad_ms: Padding added before/after speech segments (for safety)
        """
        self.threshold = threshold
        self.sampling_rate = sampling_rate
        self.min_speech_duration_ms = min_speech_duration_ms
        self.min_silence_duration_ms = min_silence_duration_ms
        self.speech_pad_ms = speech_pad_ms

        self._model = None
        self._utils = None

        # Define model paths
        from src.core.config import settings
        self.models_dir = Path(getattr(settings, 'MODELS_DIR', 'models')) / "silero"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.model_path = self.models_dir / "silero_vad.jit"
        self.utils_path = self.models_dir / "utils_vad.py"


    def _load_model(self):
        """Lazy load Silero VAD model."""
        if self._model is None:
            logger.info("🔊 Loading Silero VAD model (Offline Mode)...")
            import sys

            try:
                if not self.model_path.exists():
                     raise FileNotFoundError(f"Silero model not found at {self.model_path}. Please copy 'models/silero' from cherry_core.")

                self._model = torch.jit.load(str(self.model_path))
                self._model.eval()

                # Load Utils manually
                if not self.utils_path.exists():
                     raise FileNotFoundError(f"Silero utils not found at {self.utils_path}")

                # Dynamic import of utils_vad
                import importlib.util
                spec = importlib.util.spec_from_file_location("utils_vad", str(self.utils_path))
                utils_module = importlib.util.module_from_spec(spec)
                sys.modules["utils_vad"] = utils_module
                spec.loader.exec_module(utils_module)

                self._utils = (utils_module.get_speech_timestamps,
                               utils_module.save_audio,
                               utils_module.read_audio,
                               utils_module.VADIterator,
                               utils_module.collect_chunks)

                logger.info("✅ Silero VAD loaded (Offline).")
            except Exception as e:
                logger.error(f"❌ Failed to load Silero VAD: {e}")
                raise

    def get_speech_timestamps(self, audio_path: str) -> List[dict]:
        """
        Get timestamps of speech segments in audio.

        Returns:
            List of {'start': float, 'end': float} in seconds
        """
        self._load_model()

        # Load audio
        import librosa
        wav, _ = librosa.load(audio_path, sr=self.sampling_rate)
        wav_tensor = torch.from_numpy(wav).float()

        # Get VAD utilities
        (get_speech_timestamps, _, read_audio, _, _) = self._utils

        # Get speech timestamps
        speech_timestamps = get_speech_timestamps(
            wav_tensor,
            self._model,
            threshold=self.threshold,
            sampling_rate=self.sampling_rate,
            min_speech_duration_ms=self.min_speech_duration_ms,
            min_silence_duration_ms=self.min_silence_duration_ms
        )

        # Convert to seconds
        result = []
        for ts in speech_timestamps:
            result.append({
                'start': ts['start'] / self.sampling_rate,
                'end': ts['end'] / self.sampling_rate
            })

        return result

    def remove_silence(self, audio_path: str, output_path: Optional[str] = None) -> str:
        """
        Remove silence from audio and save to new file.

        Args:
            audio_path: Path to input audio
            output_path: Path to output audio (optional, creates temp file if None)

        Returns:
            Path to processed audio file
        """
        self._load_model()

        # Load audio
        import librosa
        wav, sr = librosa.load(audio_path, sr=self.sampling_rate)

        # Get speech timestamps
        speech_timestamps = self.get_speech_timestamps(audio_path)

        if not speech_timestamps:
            logger.warning("⚠️ No speech detected in audio!")
            return audio_path

        # Calculate padding in samples
        pad_samples = int(self.speech_pad_ms * sr / 1000)

        # Extract speech segments WITH PADDING for safety
        speech_segments = []
        for ts in speech_timestamps:
            # Add padding before and after (clipped to audio bounds)
            start_sample = max(0, int(ts['start'] * sr) - pad_samples)
            end_sample = min(len(wav), int(ts['end'] * sr) + pad_samples)
            speech_segments.append(wav[start_sample:end_sample])

        # Concatenate with small gaps
        gap = np.zeros(int(0.1 * sr))  # 100ms gap between segments
        processed = []
        for i, seg in enumerate(speech_segments):
            processed.append(seg)
            if i < len(speech_segments) - 1:
                processed.append(gap)

        processed_audio = np.concatenate(processed)

        # Save to file
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix='.wav')
            os.close(fd) # Close file descriptor

        sf.write(output_path, processed_audio, sr)

        original_duration = len(wav) / sr
        processed_duration = len(processed_audio) / sr
        reduction = (1 - processed_duration / original_duration) * 100

        logger.info(f"🔇 Removed silence: {original_duration:.1f}s → {processed_duration:.1f}s ({reduction:.1f}% reduction)")

        return output_path
