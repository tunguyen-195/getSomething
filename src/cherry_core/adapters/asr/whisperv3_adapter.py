import logging
import torch
from transformers import pipeline
from src.cherry_core.ports.asr_port import ITranscriber
from src.cherry_core.domain.entities import Transcript
from src.cherry_core.config import WHISPER_V3_PATH

logger = logging.getLogger(__name__)

class WhisperV3Adapter(ITranscriber):
    """
    Adapter for Whisper V3 ASR (OpenAI).
    Implementation using Transformers (Safetensors) for strict offline support.
    """
    def __init__(self):
        self.pipe = None
        self.device = 0 if torch.cuda.is_available() else -1
        
    def _load_model(self):
        if not self.pipe:
            logger.info(f"Loading Whisper V3 from {WHISPER_V3_PATH}...")
            try:
                # Use strict offline loading
                self.pipe = pipeline(
                    "automatic-speech-recognition",
                    model=str(WHISPER_V3_PATH),
                    chunk_length_s=30,
                    device=self.device,
                    model_kwargs={"local_files_only": True} 
                )
                logger.info("✅ Whisper V3 (Transformers) loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load Whisper V3: {e}")
                raise RuntimeError("Ensure Whisper V3 is downloaded in models/whisper-large-v3")

    def transcribe(self, audio_path: str) -> Transcript:
        self._load_model()
        logger.info(f"Transcribing {audio_path}...")
        
        result = self.pipe(
            audio_path, 
            generate_kwargs={"language": "vi", "task": "transcribe"},
            return_timestamps=True
        )
        
        return Transcript(
            text=result["text"].strip(),
            segments=[], # Transformers returns chunks if needed, but we keep simple
            metadata={"model": "whisper-v3", "language": "vi", "backend": "transformers"}
        )
