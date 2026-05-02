"""
Pyannote Community-1 (4.0) Speaker Diarization Adapter.
Upgraded from 3.1 for better speaker assignment and counting.
SOTA End-to-End Neural Diarization with 16ms resolution.
"""
import logging
import os
from typing import List, Optional

from src.cherry_core.ports.diarization_port import ISpeakerDiarizer
from src.cherry_core.domain.entities import SpeakerSegment

logger = logging.getLogger(__name__)


class PyannoteAdapter(ISpeakerDiarizer):
    """
    Speaker Diarization using Pyannote Community-1 (4.0) End-to-End Neural Pipeline.

    Upgraded from 3.1 for:
    - Better speaker assignment (reduced confusion)
    - Improved speaker counting accuracy
    - 16ms frame resolution (vs 1.2s windows)
    - Native overlap handling
    - ~17% DER on AMI benchmark (vs 18.8% in 3.1)
    """

    def __init__(self,
                 hf_token: Optional[str] = None,
                 num_speakers: Optional[int] = None,
                 min_speakers: Optional[int] = None,
                 max_speakers: Optional[int] = None,
                 device: str = "cpu"):
        """
        Args:
            hf_token: HuggingFace token for model download (required first time)
            num_speakers: Exact number of speakers (if known)
            min_speakers: Minimum expected speakers
            max_speakers: Maximum expected speakers
            device: "cpu" or "cuda"
        """
        self.hf_token = hf_token or os.getenv("HF_TOKEN")
        self.num_speakers = num_speakers
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers
        self.device = device
        self._pipeline = None

    def _ensure_pipeline(self):
        """Lazy load Pyannote pipeline."""
        if self._pipeline is None:
            logger.info("🔊 Loading Pyannote Speaker Diarization Pipeline...")

            try:
                from pyannote.audio import Pipeline
                import torch

                # Try Community-1 first (4.0), fallback to 3.1 if not available
                try:
                    self._pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-community-1",
                        use_auth_token=self.hf_token
                    )
                    if self._pipeline is not None:
                        logger.info("✅ Using Pyannote Community-1 (4.0) - Better speaker assignment")
                    else:
                        raise ValueError("Pipeline returned None")
                except Exception as e:
                    logger.warning(f"⚠️ Community-1 not available ({e}), falling back to 3.1")
                    self._pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1",
                        use_auth_token=self.hf_token
                    )
                    logger.info("✅ Using Pyannote 3.1")

                if self._pipeline is None:
                    raise ValueError("Failed to load any Pyannote model")

                # Move to device
                if self.device == "cuda" and torch.cuda.is_available():
                    self._pipeline.to(torch.device("cuda"))
                    logger.info("✅ Pyannote loaded on CUDA.")
                else:
                    logger.info("✅ Pyannote loaded on CPU.")

            except Exception as e:
                logger.error(f"❌ Failed to load Pyannote: {e}")
                logger.error("💡 Make sure you have accepted the model license at:")
                logger.error("   https://huggingface.co/pyannote/speaker-diarization-3.1")
                logger.error("   And set HF_TOKEN environment variable or pass hf_token parameter.")
                raise

    def diarize(self, audio_path: str) -> List[SpeakerSegment]:
        """
        Perform speaker diarization using Pyannote 3.1.

        Args:
            audio_path: Path to audio file

        Returns:
            List of SpeakerSegment with start_time, end_time, speaker_id
        """
        self._ensure_pipeline()

        logger.info(f"🎤 Pyannote Diarization: {audio_path}")

        # Build pipeline parameters
        params = {}
        if self.num_speakers is not None:
            params["num_speakers"] = self.num_speakers
        if self.min_speakers is not None:
            params["min_speakers"] = self.min_speakers
        if self.max_speakers is not None:
            params["max_speakers"] = self.max_speakers

        # Run diarization
        diarization = self._pipeline(audio_path, **params)

        # Convert to SpeakerSegment format
        segments = []
        speaker_map = {}  # Map pyannote speaker labels to SPEAKER_X format
        speaker_counter = 1

        for turn, _, speaker in diarization.itertracks(yield_label=True):
            # Normalize speaker labels
            if speaker not in speaker_map:
                speaker_map[speaker] = f"SPEAKER_{speaker_counter}"
                speaker_counter += 1

            segments.append(SpeakerSegment(
                start_time=turn.start,
                end_time=turn.end,
                speaker_id=speaker_map[speaker]
            ))

        logger.info(f"✅ Pyannote Diarization complete: {len(segments)} segments ({len(speaker_map)} speakers)")

        return segments
