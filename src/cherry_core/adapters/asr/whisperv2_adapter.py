import logging
import re
import os
import torch
from src.cherry_core.ports.asr_port import ITranscriber
from src.cherry_core.domain.entities import Transcript
from src.cherry_core.config import WHISPER_V2_PATH, MODELS_DIR

logger = logging.getLogger(__name__)

# Optional VAD import
try:
    from src.cherry_core.adapters.vad.silero_adapter import SileroVADAdapter
    VAD_AVAILABLE = True
except ImportError:
    VAD_AVAILABLE = False
    logger.warning("⚠️ Silero VAD not available. Install: pip install silero")


class WhisperV2Adapter(ITranscriber):
    """
    Adapter for Whisper V2 ASR (OpenAI).
    Direct implementation using openai-whisper.

    Anti-Hallucination Features (Generalized):
    1. Decoding parameters: compression_ratio, logprob, no_speech thresholds
    2. condition_on_previous_text=False to prevent cascading errors
    3. Post-processing: Repetition loop detection and removal
    4. Optional: VAD preprocessing to remove silence (reduces hallucination)
    """

    # Regex pattern to detect repetition loops (3+ repetitions of same word/phrase)
    REPETITION_PATTERN = re.compile(r'(\b\w+\b)(\s*[.,]?\s*\1){2,}', re.IGNORECASE)

    def __init__(self, use_vad: bool = True):
        """
        Args:
            use_vad: Enable Silero VAD preprocessing to remove silence
        """
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.use_vad = use_vad and VAD_AVAILABLE
        self._vad = None

        if use_vad and not VAD_AVAILABLE:
            logger.warning("⚠️ VAD requested but not available. Continuing without VAD.")

    def _load_model(self):
        if not self.model:
            pt_file_root = MODELS_DIR / "large-v2.pt"
            pt_file_inner = WHISPER_V2_PATH / "large-v2.pt"

            if pt_file_root.exists():
                model_file = pt_file_root
            elif pt_file_inner.exists():
                model_file = pt_file_inner
            else:
                 logger.error(f"❌ Offline Model file missing. Checked: {pt_file_root} AND {pt_file_inner}")
                 raise FileNotFoundError(f"Offline Model file missing: large-v2.pt")

            logger.info(f"Loading Whisper V2 from {model_file}...")

            try:
                 try:
                     import whisper
                 except ImportError as import_error:
                     raise RuntimeError(
                         "openai-whisper could not be imported. Check the local "
                         "Whisper/Numba/NumPy dependency set; the Docker image pins "
                         "compatible versions."
                     ) from import_error
                 self.model = whisper.load_model(str(model_file), device=self.device)
                 logger.info("✅ Whisper V2 loaded (Offline).")
            except Exception as e:
                logger.error(f"Failed to load Whisper V2: {e}")
                raise

    def _remove_repetitions(self, text: str) -> str:
        """
        Remove repetition loops from transcribed text.
        This is a generalized post-processing step for Whisper outputs.

        Example: "Quyên. Quyên. Quyên. Quyên." -> "Quyên."
        """
        # Pattern 1: Word repeated 3+ times with punctuation/spaces
        # Matches: "word. word. word." or "word word word"
        def replace_repetition(match):
            return match.group(1)  # Keep only first occurrence

        cleaned = self.REPETITION_PATTERN.sub(replace_repetition, text)

        # Pattern 2: Handle Vietnamese-specific repetitions with tones
        # This catches cases like "Quyên. Quyên. Quyên."
        cleaned = re.sub(r'(\b[\w\u00C0-\u1EF9]+\b)(\s*[.,]?\s*\1){2,}', r'\1', cleaned, flags=re.IGNORECASE)

        # Clean up extra whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        if cleaned != text:
            logger.info(f"🔧 Removed {len(text) - len(cleaned)} chars of repetition.")

        return cleaned

    def transcribe(self, audio_path: str) -> Transcript:
        self._load_model()
        logger.info(f"Transcribing {audio_path}...")

        # ============================================
        # VAD PREPROCESSING (Optional)
        # ============================================
        processed_audio = audio_path
        vad_applied = False

        if self.use_vad:
            try:
                if self._vad is None:
                    self._vad = SileroVADAdapter()

                # Remove silence from audio
                processed_audio = self._vad.remove_silence(audio_path)
                vad_applied = True
                logger.info(f"🔊 VAD preprocessing applied.")
            except Exception as e:
                logger.warning(f"⚠️ VAD preprocessing failed: {e}. Using original audio.")
                processed_audio = audio_path

        # ============================================
        # GENERALIZED ANTI-HALLUCINATION CONFIGURATION
        # ============================================
        result = self.model.transcribe(
            processed_audio,
            language="vi",
            beam_size=5,
            best_of=5,
            temperature=0.0,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.0,
            logprob_threshold=-1.0,
            no_speech_threshold=0.5,
        )

        # Clean up temp file if VAD was applied
        if vad_applied and processed_audio != audio_path:
            try:
                os.remove(processed_audio)
            except:
                pass

        # Apply post-processing repetition filter
        raw_text = result["text"].strip()
        cleaned_text = self._remove_repetitions(raw_text)

        # Extract segments
        segments = []
        for seg in result.get("segments", []):
            seg_text = self._remove_repetitions(seg["text"].strip())
            if seg_text:  # Skip empty segments after cleaning
                segments.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg_text
                })

        return Transcript(
            text=cleaned_text,
            segments=segments,
            metadata={
                "model": "whisper-v2",
                "language": "vi",
                "anti_hallucination": True,
                "post_processing": "repetition_filter"
            }
        )
