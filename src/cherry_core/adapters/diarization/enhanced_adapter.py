"""
VAD-Enhanced Speaker Diarization Adapter.

Integrates Silero VAD preprocessing with speaker diarization to:
1. Filter out silence before embedding (reduces hallucination)
2. Create more accurate speech segments
3. Improve clustering quality

Pipeline: Audio → VAD → Speech Segments → Embeddings → Clustering → Labels
"""
import logging
from typing import List, Optional
import numpy as np

from src.cherry_core.ports.diarization_port import ISpeakerDiarizer
from src.cherry_core.domain.entities import SpeakerSegment

logger = logging.getLogger(__name__)

# Optional imports
try:
    from resemblyzer import VoiceEncoder, preprocess_wav
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score
    RESEMBLYZER_AVAILABLE = True
except ImportError:
    RESEMBLYZER_AVAILABLE = False

try:
    from src.cherry_core.adapters.vad.silero_adapter import SileroVADAdapter
    VAD_AVAILABLE = True
except ImportError:
    VAD_AVAILABLE = False


class EnhancedDiarizer(ISpeakerDiarizer):
    """
    Enhanced Speaker Diarization with VAD preprocessing and auto speaker count.
    
    Improvements over ResemblyzerAdapter:
    1. VAD preprocessing (filters silence)
    2. Auto speaker count estimation (silhouette score)
    3. Adaptive segment duration
    4. Multiple clustering options
    """
    
    def __init__(self, 
                 n_speakers: Optional[int] = None,  # None = auto-detect
                 segment_duration: float = 0.5,      # Shorter segments for precision
                 use_vad: bool = True,
                 max_speakers: int = 6):
        """
        Args:
            n_speakers: Number of speakers (None = auto-detect)
            segment_duration: Duration of each segment in seconds
            use_vad: Whether to use VAD preprocessing
            max_speakers: Maximum speakers for auto-detection
        """
        self.n_speakers = n_speakers
        self.segment_duration = segment_duration
        self.use_vad = use_vad and VAD_AVAILABLE
        self.max_speakers = max_speakers
        
        self._encoder = None
        self._vad = None
    
    def _ensure_encoder(self):
        """Lazy load embeddings encoder."""
        if not RESEMBLYZER_AVAILABLE:
            raise ImportError("Install resemblyzer: pip install resemblyzer scikit-learn")
        if self._encoder is None:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            logger.info("🔊 Loading VoiceEncoder for enhanced diarization...")
            self._encoder = VoiceEncoder()
            logger.info("✅ VoiceEncoder ready.")
    
    def _ensure_vad(self):
        """Lazy load VAD preprocessor."""
        if self.use_vad and self._vad is None:
            self._vad = SileroVADAdapter()
    
    def _estimate_speaker_count(self, embeddings: np.ndarray) -> int:
        """
        Estimate optimal number of speakers using silhouette score.
        
        Returns:
            Estimated number of speakers
        """
        if len(embeddings) < 3:
            return min(2, len(embeddings))
        
        best_k = 2
        best_score = -1
        
        for k in range(2, min(self.max_speakers + 1, len(embeddings))):
            try:
                clustering = AgglomerativeClustering(n_clusters=k).fit(embeddings)
                score = silhouette_score(embeddings, clustering.labels_)
                if score > best_score:
                    best_score = score
                    best_k = k
            except Exception:
                continue
        
        logger.info(f"📊 Auto-detected {best_k} speakers (silhouette: {best_score:.3f})")
        return best_k
    
    def diarize(self, audio_path: str) -> List[SpeakerSegment]:
        """
        Perform enhanced speaker diarization.
        
        Pipeline:
        1. (Optional) VAD preprocessing - get speech regions
        2. Load audio and segment based on speech regions
        3. Compute embeddings for each segment
        4. (Optional) Estimate speaker count
        5. Cluster embeddings
        6. Return labeled segments
        """
        self._ensure_encoder()
        
        logger.info(f"🎤 Enhanced diarization: {audio_path}")
        
        # Step 1: Get speech timestamps from VAD
        speech_regions = None
        if self.use_vad:
            self._ensure_vad()
            speech_regions = self._vad.get_speech_timestamps(audio_path)
            logger.info(f"VAD detected {len(speech_regions)} speech regions")
        
        # Step 2: Load and preprocess audio
        wav = preprocess_wav(audio_path)
        sample_rate = 16000
        segment_samples = int(self.segment_duration * sample_rate)
        
        # Step 3: Create segments (VAD-aware or fixed)
        segments = []
        embeddings = []
        
        if speech_regions:
            # VAD-aware segmentation
            for region in speech_regions:
                start_sample = int(region['start'] * sample_rate)
                end_sample = int(region['end'] * sample_rate)
                
                # Split long regions into sub-segments
                for i in range(start_sample, end_sample, segment_samples):
                    seg_end = min(i + segment_samples, end_sample)
                    segment_wav = wav[i:seg_end]
                    
                    if len(segment_wav) < segment_samples // 4:
                        continue
                    
                    # Pad if needed
                    if len(segment_wav) < segment_samples:
                        segment_wav = np.pad(segment_wav, (0, segment_samples - len(segment_wav)))
                    
                    start_time = i / sample_rate
                    end_time = seg_end / sample_rate
                    
                    embedding = self._encoder.embed_utterance(segment_wav)
                    embeddings.append(embedding)
                    segments.append((start_time, end_time))
        else:
            # Fixed segmentation (fallback)
            for i in range(0, len(wav), segment_samples):
                segment_wav = wav[i:i + segment_samples]
                if len(segment_wav) < segment_samples // 2:
                    continue
                
                if len(segment_wav) < segment_samples:
                    segment_wav = np.pad(segment_wav, (0, segment_samples - len(segment_wav)))
                
                start_time = i / sample_rate
                end_time = min((i + segment_samples) / sample_rate, len(wav) / sample_rate)
                
                embedding = self._encoder.embed_utterance(segment_wav)
                embeddings.append(embedding)
                segments.append((start_time, end_time))
        
        if len(embeddings) < 2:
            logger.warning("Not enough segments. Returning all as SPEAKER_1.")
            return [SpeakerSegment(start_time=s[0], end_time=s[1], speaker_id="SPEAKER_1") 
                    for s in segments]
        
        embeddings_matrix = np.array(embeddings)
        
        # Step 4: Determine speaker count
        n_speakers = self.n_speakers
        if n_speakers is None:
            n_speakers = self._estimate_speaker_count(embeddings_matrix)
        
        # Step 5: Cluster embeddings
        if n_speakers > len(embeddings):
            n_speakers = len(embeddings)
        
        clustering = AgglomerativeClustering(n_clusters=n_speakers).fit(embeddings_matrix)
        labels = clustering.labels_
        
        # Step 6: Create labeled segments
        result = []
        for idx, (start, end) in enumerate(segments):
            speaker_id = f"SPEAKER_{labels[idx] + 1}"
            result.append(SpeakerSegment(
                start_time=start,
                end_time=end,
                speaker_id=speaker_id
            ))
        
        # Merge consecutive segments with same speaker
        result = self._merge_consecutive(result)
        
        logger.info(f"✅ Enhanced diarization: {len(result)} segments, {n_speakers} speakers")
        return result
    
    def _merge_consecutive(self, segments: List[SpeakerSegment]) -> List[SpeakerSegment]:
        """Merge consecutive segments with the same speaker."""
        if not segments:
            return segments
        
        merged = [segments[0]]
        for seg in segments[1:]:
            if seg.speaker_id == merged[-1].speaker_id:
                # Extend previous segment
                merged[-1] = SpeakerSegment(
                    start_time=merged[-1].start_time,
                    end_time=seg.end_time,
                    speaker_id=seg.speaker_id
                )
            else:
                merged.append(seg)
        
        return merged
