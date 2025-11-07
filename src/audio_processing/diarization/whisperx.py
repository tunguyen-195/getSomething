from .base import SpeakerDiarizationPipeline
from typing import List, Dict, Any
import logging
import torch
import numpy as np

logger = logging.getLogger(__name__)

class WhisperXPipeline(SpeakerDiarizationPipeline):
    """
    Native implementation using pyannote.audio for speaker diarization
    Compatible with faster-whisper transcription results
    """
    
    def __init__(self):
        try:
            import os
            from pyannote.audio import Pipeline
            from src.core.config import settings
            
            # Get HF token from settings or env
            hf_token = getattr(settings, 'HF_TOKEN', None) or os.getenv('HF_TOKEN')
            
            logger.info(f"[DIARIZATION] Loading pyannote pipeline (token: {'present' if hf_token else 'missing'})")
            
            self.diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=hf_token  # Will use cached version if already downloaded
            )
            # Use GPU if available
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.diarization_pipeline.to(device)
            logger.info(f"[DIARIZATION] Initialized pyannote pipeline on {device}")
        except Exception as e:
            logger.error(f"[DIARIZATION] Failed to load pyannote pipeline: {e}")
            logger.info("[DIARIZATION] Falling back to simple speaker assignment")
            self.diarization_pipeline = None
    
    def run(self, audio_path: str) -> List[Dict[str, Any]]:
        """
        Run speaker diarization on audio file
        Returns list of segments with speaker labels
        """
        if self.diarization_pipeline is None:
            logger.warning("[DIARIZATION] Pipeline not available, returning empty")
            return []
        
        try:
            # Run diarization
            logger.info(f"[DIARIZATION] Processing: {audio_path}")
            diarization = self.diarization_pipeline(audio_path)
            
            # Convert to segment format
            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append({
                    "start": turn.start,
                    "end": turn.end,
                    "speaker": speaker
                })
            
            logger.info(f"[DIARIZATION] Found {len(segments)} speaker segments")
            return segments
            
        except Exception as e:
            logger.error(f"[DIARIZATION] Error during processing: {e}")
            return []
    
    def assign_speakers_to_transcript(
        self, 
        transcript_segments: List[Dict[str, Any]], 
        speaker_segments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Assign speaker labels to transcript segments based on time overlap
        
        Args:
            transcript_segments: List of segments from Whisper with 'start', 'end', 'text'
            speaker_segments: List of speaker segments from diarization with 'start', 'end', 'speaker'
        
        Returns:
            Combined segments with speaker labels
        """
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
