"""
Simple VAD-based Speaker Diarization (100% Offline Fallback)

This is a lightweight, guaranteed-offline diarization solution that doesn't 
depend on any external services or authentication.

Approach:
1. Use Whisper's built-in VAD to detect speech segments
2. Extract basic audio features (MFCCs or energy-based)
3. Apply clustering (Spectral or KMeans) to group by speakers
4. Assign speaker labels to transcript segments

Advantages:
- 100% offline, no external dependencies
- No HuggingFace, no auth tokens needed
- Simple and maintainable
- Fast processing

Disadvantages:
- Lower accuracy than SOTA models
- May struggle with similar voices
- No handling of overlapping speech
"""

import logging
import numpy as np
from typing import List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

class SimpleVADDiarizer:
    """
    Simple VAD-based diarization using clustering
    100% offline, no external dependencies
    """
    
    def __init__(self, num_speakers=2, method='spectral'):
        """
        Args:
            num_speakers: Expected number of speakers (default: 2)
            method: Clustering method ('spectral' or 'kmeans')
        """
        self.num_speakers = num_speakers
        self.method = method
        logger.info(f"[SIMPLE_DIARIZER] Initialized with {num_speakers} speakers, method={method}")
    
    def extract_features(self, audio: np.ndarray, sr: int = 16000) -> np.ndarray:
        """
        Extract simple audio features for clustering
        Uses energy-based features (RMS, ZCR, spectral centroid)
        """
        try:
            import librosa
            
            # Extract features
            # 1. RMS Energy
            rms = librosa.feature.rms(y=audio)[0]
            
            # 2. Zero Crossing Rate
            zcr = librosa.feature.zero_crossing_rate(audio)[0]
            
            # 3. Spectral Centroid
            spec_cent = librosa.feature.spectral_centroid(y=audio, sr=sr)[0]
            
            # 4. MFCCs (first 13 coefficients)
            mfccs = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=13)
            
            # Combine features
            features = np.vstack([
                rms,
                zcr,
                spec_cent,
                mfccs
            ])
            
            # Transpose to (time, features)
            features = features.T
            
            logger.debug(f"[FEATURES] Extracted shape: {features.shape}")
            return features
            
        except Exception as e:
            logger.error(f"[FEATURES] Error extracting features: {e}")
            # Fallback: simple energy-based
            frame_length = int(sr * 0.025)  # 25ms frames
            hop_length = int(sr * 0.010)    # 10ms hop
            
            frames = librosa.util.frame(audio, frame_length=frame_length, hop_length=hop_length)
            energy = np.sqrt(np.mean(frames**2, axis=0))
            return energy.reshape(-1, 1)
    
    def cluster_segments(self, features: np.ndarray) -> np.ndarray:
        """
        Cluster audio segments by speaker using features
        """
        try:
            from sklearn.cluster import SpectralClustering, KMeans
            from sklearn.preprocessing import StandardScaler
            
            # Normalize features
            scaler = StandardScaler()
            features_scaled = scaler.fit_transform(features)
            
            # Apply clustering
            if self.method == 'spectral':
                clustering = SpectralClustering(
                    n_clusters=self.num_speakers,
                    affinity='rbf',
                    random_state=42
                )
            else:  # kmeans
                clustering = KMeans(
                    n_clusters=self.num_speakers,
                    random_state=42,
                    n_init=10
                )
            
            labels = clustering.fit_predict(features_scaled)
            logger.info(f"[CLUSTERING] Assigned {len(set(labels))} unique speakers")
            
            return labels
            
        except Exception as e:
            logger.error(f"[CLUSTERING] Error: {e}")
            # Fallback: assign all to speaker 0
            return np.zeros(len(features), dtype=int)
    
    def assign_speakers_to_segments(
        self, 
        transcript_segments: List[Dict[str, Any]],
        audio_path: str
    ) -> List[Dict[str, Any]]:
        """
        Assign speaker labels to transcript segments
        
        Args:
            transcript_segments: List of segments from Whisper with 'start', 'end', 'text'
            audio_path: Path to audio file
            
        Returns:
            Segments with 'speaker' field added
        """
        try:
            import librosa
            import soundfile as sf
            
            logger.info(f"[DIARIZATION] Processing {len(transcript_segments)} segments")
            
            # Load audio
            audio, sr = librosa.load(audio_path, sr=16000)
            
            # Extract segment-level features
            segment_features = []
            segment_times = []
            
            for seg in transcript_segments:
                start_sample = int(seg['start'] * sr)
                end_sample = int(seg['end'] * sr)
                
                # Extract segment audio
                seg_audio = audio[start_sample:end_sample]
                
                if len(seg_audio) < sr * 0.5:  # Skip very short segments
                    continue
                
                # Extract features for this segment
                features = self.extract_features(seg_audio, sr)
                
                # Use mean of features as segment representation
                seg_feature = np.mean(features, axis=0)
                segment_features.append(seg_feature)
                segment_times.append((seg['start'], seg['end']))
            
            if len(segment_features) == 0:
                logger.warning("[DIARIZATION] No valid segments found")
                # Assign all to speaker 0
                for seg in transcript_segments:
                    seg['speaker'] = 'SPEAKER_00'
                return transcript_segments
            
            # Stack features
            features_matrix = np.vstack(segment_features)
            
            # Cluster
            labels = self.cluster_segments(features_matrix)
            
            # Assign labels to transcript segments
            label_idx = 0
            for seg in transcript_segments:
                if label_idx < len(labels):
                    speaker_id = int(labels[label_idx])
                    seg['speaker'] = f'SPEAKER_{speaker_id:02d}'
                    label_idx += 1
                else:
                    seg['speaker'] = 'SPEAKER_00'
            
            logger.info(f"[DIARIZATION] Completed with {self.num_speakers} speakers")
            return transcript_segments
            
        except Exception as e:
            logger.error(f"[DIARIZATION] Error: {e}", exc_info=True)
            # Fallback: assign all to speaker 0
            for seg in transcript_segments:
                seg['speaker'] = 'SPEAKER_00'
            return transcript_segments


def get_simple_diarizer(num_speakers=2) -> SimpleVADDiarizer:
    """Factory function to get simple diarizer instance"""
    return SimpleVADDiarizer(num_speakers=num_speakers, method='spectral')
