import logging
from typing import List
import numpy as np

from src.cherry_core.ports.diarization_port import ISpeakerDiarizer
from src.cherry_core.domain.entities import SpeakerSegment

logger = logging.getLogger(__name__)

# Optional imports with fallback
try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    from sklearn.cluster import SpectralClustering
    RESEMBLYZER_AVAILABLE = True
except ImportError:
    RESEMBLYZER_AVAILABLE = False
    logger.warning("Resemblyzer not installed. Diarization will use fallback heuristics.")


class ResemblyzerAdapter(ISpeakerDiarizer):
    """
    Speaker Diarization using Resemblyzer embeddings + Spectral Clustering.
    Offline-capable after initial model download.
    """
    
    def __init__(self, n_speakers: int = 2):
        """
        Args:
            n_speakers: Expected number of speakers (for clustering).
        """
        self.n_speakers = n_speakers
        self._encoder = None
        
    def _ensure_encoder(self):
        if not RESEMBLYZER_AVAILABLE:
            raise ImportError("Install resemblyzer: pip install resemblyzer scikit-learn")
        if self._encoder is None:
            logger.info("Loading Resemblyzer VoiceEncoder...")
            self._encoder = VoiceEncoder()
            logger.info("✅ VoiceEncoder loaded.")
    
    def diarize(self, audio_path: str) -> List[SpeakerSegment]:
        """
        Perform speaker diarization on audio file.
        
        Pipeline:
        1. Load and preprocess audio.
        2. Split into fixed-length segments (e.g., 1 second).
        3. Compute d-vector embeddings for each segment.
        4. Cluster embeddings using Spectral Clustering.
        5. Return labeled segments.
        """
        self._ensure_encoder()
        
        logger.info(f"🎤 Diarizing: {audio_path}")
        
        # 1. Load audio
        wav = preprocess_wav(audio_path)
        
        # 2. Segment audio into chunks (1 second each, 16kHz sample rate)
        segment_duration = 1.0  # seconds
        sample_rate = 16000
        segment_samples = int(segment_duration * sample_rate)
        
        segments = []
        embeddings = []
        
        for i in range(0, len(wav), segment_samples):
            segment_wav = wav[i:i + segment_samples]
            if len(segment_wav) < segment_samples // 2:
                continue  # Skip very short final segments
            
            # Pad if needed
            if len(segment_wav) < segment_samples:
                segment_wav = np.pad(segment_wav, (0, segment_samples - len(segment_wav)))
            
            start_time = i / sample_rate
            end_time = min((i + segment_samples) / sample_rate, len(wav) / sample_rate)
            
            # Compute embedding
            embedding = self._encoder.embed_utterance(segment_wav)
            embeddings.append(embedding)
            segments.append((start_time, end_time))
        
        if len(embeddings) < self.n_speakers:
            logger.warning("Not enough segments for clustering. Assigning all to SPEAKER_1.")
            return [
                SpeakerSegment(start_time=s[0], end_time=s[1], speaker_id="SPEAKER_1")
                for s in segments
            ]
        
        # 3. Cluster embeddings
        embeddings_matrix = np.array(embeddings)
        clustering = SpectralClustering(
            n_clusters=self.n_speakers,
            affinity='nearest_neighbors',
            n_neighbors=min(10, len(embeddings)),
            random_state=42
        ).fit(embeddings_matrix)
        
        labels = clustering.labels_
        
        # 4. Create labeled segments
        result = []
        for idx, (start, end) in enumerate(segments):
            speaker_id = f"SPEAKER_{labels[idx] + 1}"
            result.append(SpeakerSegment(
                start_time=start,
                end_time=end,
                speaker_id=speaker_id
            ))
        
        logger.info(f"✅ Diarization complete: {len(result)} segments, {self.n_speakers} speakers.")
        return result
