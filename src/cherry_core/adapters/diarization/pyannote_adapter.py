"""
Pyannote Community-1 (4.0) Speaker Diarization Adapter.
Upgraded from 3.1 for better speaker assignment and counting.
SOTA End-to-End Neural Diarization with 16ms resolution.
"""
import logging
from typing import List, Optional

from src.cherry_core.ports.diarization_port import ISpeakerDiarizer
from src.cherry_core.domain.entities import SpeakerSegment
from src.services.transcription.models.pyannote_loader import (
    load_pyannote_pipeline,
    normalize_diarization_output,
)

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
        self.hf_token = hf_token
        self.num_speakers = num_speakers
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers
        self.device = device
        self._pipeline = None

    def _ensure_pipeline(self):
        """Lazy load Pyannote pipeline."""
        if self._pipeline is None:
            logger.info("🔊 Loading Pyannote Speaker Diarization Pipeline...")
            self._pipeline = load_pyannote_pipeline(device=self.device, hf_token=self.hf_token)
            if self._pipeline is None:
                logger.warning("Pyannote unavailable; continuing without diarization")

    def diarize(self, audio_path: str) -> List[SpeakerSegment]:
        """
        Perform speaker diarization using Pyannote 3.1.

        Args:
            audio_path: Path to audio file

        Returns:
            List of SpeakerSegment with start_time, end_time, speaker_id
        """
        self._ensure_pipeline()
        if self._pipeline is None:
            return []

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
        raw_diarization = self._pipeline(audio_path, **params)
        diarization = normalize_diarization_output(raw_diarization)

        # Convert to SpeakerSegment format
        segments = []
        speakers = set()
        for diarization_segment in diarization:
            speakers.add(diarization_segment["speaker"])
            segments.append(SpeakerSegment(
                start_time=diarization_segment["start"],
                end_time=diarization_segment["end"],
                speaker_id=diarization_segment["speaker"]
            ))

        logger.info(f"✅ Pyannote Diarization complete: {len(segments)} segments ({len(speakers)} speakers)")

        return segments
