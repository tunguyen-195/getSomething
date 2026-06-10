from .base import SpeakerDiarizationPipeline
from typing import List, Dict, Any
import logging

from src.services.transcription.models.pyannote_loader import (
    load_pyannote_pipeline,
    normalize_diarization_output,
)

logger = logging.getLogger(__name__)

class WhisperXPipeline(SpeakerDiarizationPipeline):
    """
    Native implementation using pyannote.audio for speaker diarization
    Compatible with faster-whisper transcription results
    """

    def __init__(self):
        try:
            self.diarization_pipeline = load_pyannote_pipeline()
            if self.diarization_pipeline is None:
                raise RuntimeError("Pyannote pipeline unavailable")
            logger.info("[DIARIZATION] Initialized pyannote pipeline")
        except Exception as e:
            logger.error(f"[DIARIZATION] Failed to load pyannote pipeline: {e}")
            logger.info("[DIARIZATION] Falling back to SimpleVAD diarizer (100% offline)")
            self.diarization_pipeline = None

            # Load simple VAD-based diarizer as fallback
            try:
                from src.audio_processing.diarization.simple_vad import get_simple_diarizer
                self.simple_diarizer = get_simple_diarizer()
                logger.info("[DIARIZATION] SimpleVAD diarizer loaded successfully")
            except Exception as e2:
                logger.error(f"[DIARIZATION] Failed to load SimpleVAD: {e2}")
                self.simple_diarizer = None

    def run(self, audio_path: str) -> List[Dict[str, Any]]:
        """
        Run speaker diarization on audio file
        Returns list of segments with speaker labels
        """
        if self.diarization_pipeline is None:
            logger.warning("[DIARIZATION] Pyannote pipeline not available")

            # Try using simple diarizer as fallback
            if hasattr(self, 'simple_diarizer') and self.simple_diarizer:
                logger.info("[DIARIZATION] Using SimpleVAD fallback")
                return []  # Will use assign_speakers_to_segments instead
            else:
                logger.warning("[DIARIZATION] No diarization method available, returning empty")
                return []

        try:
            # Run diarization
            logger.info(f"[DIARIZATION] Processing: {audio_path}")
            diarization = self.diarization_pipeline(audio_path)
            segments = normalize_diarization_output(diarization)

            logger.info(f"[DIARIZATION] Found {len(segments)} speaker segments")
            return segments

        except Exception as e:
            logger.error(f"[DIARIZATION] Error during processing: {e}")
            return []

    def assign_speakers_to_transcript(
        self,
        transcript_segments: List[Dict[str, Any]],
        speaker_segments: List[Dict[str, Any]],
        audio_path: str = None
    ) -> List[Dict[str, Any]]:
        """
        Assign speaker labels to transcript segments based on time overlap

        If speaker_segments is empty and SimpleVAD is available, use it instead

        Args:
            transcript_segments: List of segments from Whisper with 'start', 'end', 'text'
            speaker_segments: List of speaker segments from diarization with 'start', 'end', 'speaker'

        Returns:
            Combined segments with speaker labels
        """
        # Fallback to SimpleVAD if no speaker segments and audio_path provided
        if len(speaker_segments) == 0 and audio_path and hasattr(self, 'simple_diarizer') and self.simple_diarizer:
            logger.info("[DIARIZATION] Using SimpleVAD fallback for speaker assignment")
            try:
                return self.simple_diarizer.assign_speakers_to_segments(transcript_segments, audio_path)
            except Exception as e:
                logger.error(f"[DIARIZATION] SimpleVAD failed: {e}")
                # Continue with default assignment below

        result = []

        for t_seg in transcript_segments:
            t_start = t_seg.get('start', 0)
            t_end = t_seg.get('end', 0)
            t_mid = (t_start + t_end) / 2

            # Find speaker with maximum overlap
            best_speaker = "SPEAKER_00"  # Default
            max_overlap = 0

            for s_seg in speaker_segments:
                s_start = s_seg['start']
                s_end = s_seg['end']

                # Calculate overlap
                overlap_start = max(t_start, s_start)
                overlap_end = min(t_end, s_end)
                overlap = max(0, overlap_end - overlap_start)

                if overlap > max_overlap:
                    max_overlap = overlap
                    best_speaker = s_seg['speaker']

            result.append({
                'start': t_start,
                'end': t_end,
                'text': t_seg.get('text', ''),
                'speaker': best_speaker
            })

        return result
