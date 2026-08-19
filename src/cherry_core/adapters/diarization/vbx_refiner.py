import numpy as np
from typing import List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)

class VBxRefiner:
    """
    Implements a Viterbi-based Resegmentation (simplified VBx) to smooth speaker diarization.
    
    It treats the initial clustering as "noisy labels" and uses a Hidden Markov Model (HMM)
    to find the most likely sequence of speakers, penalizing rapid switching and 
    optimizing frame assignments based on embedding proximity to speaker centroids.
    """

    def __init__(self, loop_prob: float = 0.9):
        """
        Args:
            loop_prob (float): Probability of staying in the same state (speaker).
                               Higher = smoother (less switching).
        """
        self.loop_prob = loop_prob

    def refine(self, embeddings: np.ndarray, labels: List[int], timestamps: List[Tuple[float, float]]) -> List[int]:
        """
        Refine speaker labels using Viterbi decoding.

        Args:
            embeddings (np.ndarray): Shape (N_segments, embedding_dim)
            labels (List[int]): Initial speaker labels (0, 1, ...).
            timestamps (List[Tuple[float, float]]): Start/End times for segments (used for duration weighting if needed).

        Returns:
            List[int]: Refined speaker labels.
        """
        if len(labels) < 2:
            return labels

        unique_speakers = sorted(list(set(labels)))
        n_speakers = len(unique_speakers)
        n_segments = len(labels)
        
        if n_speakers < 2:
            return labels # No need to refine if 1 speaker

        logger.info(f"🔄 Running VBx Resegmentation on {n_segments} segments ({n_speakers} speakers)...")

        # 1. Calculate Speaker Centroids (GMM Means)
        # We assume spherical covariance for simplicity in this "careful" initial implementation
        centroids = {}
        for spk in unique_speakers:
            spk_indices = [i for i, label in enumerate(labels) if label == spk]
            spk_embeddings = embeddings[spk_indices]
            centroids[spk] = np.mean(spk_embeddings, axis=0)
            # Normalize centroid (cosine similarity space)
            centroids[spk] = centroids[spk] / np.linalg.norm(centroids[spk])

        # 2. Compute Emission Probabilities (Cosine Similarity -> Probability)
        # P(observation | state) ~ exp(similarity * scale)
        emission_matrix = np.zeros((n_segments, n_speakers))
        
        # Normalize all embeddings first
        norm_embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        
        for t in range(n_segments):
            for i, spk in enumerate(unique_speakers):
                # Cosine similarity
                sim = np.dot(norm_embeddings[t], centroids[spk])
                # Convert to "probability-like" score (Temperature scaling)
                # Being closer to centroid = higher score
                emission_matrix[t, i] = sim 

        # 3. Viterbi Decoding
        # Initialization
        # transitions: log probabilities
        # loop = log(p), switch = log((1-p)/(N-1))
        
        log_loop = np.log(self.loop_prob)
        if n_speakers > 1:
            log_switch = np.log((1 - self.loop_prob) / (n_speakers - 1))
        else:
            log_switch = -np.inf

        # dp[t, state] = max log_prob up to time t ending in state
        dp = np.zeros((n_segments, n_speakers))
        backpointer = np.zeros((n_segments, n_speakers), dtype=int)

        # Init first frame based on emission only (uniform prior)
        dp[0] = emission_matrix[0] * 10.0 # Scale up emission impact

        for t in range(1, n_segments):
            for s_curr in range(n_speakers):
                # Find best previous state
                probs = []
                for s_prev in range(n_speakers):
                    trans_prob = log_loop if s_prev == s_curr else log_switch
                    probs.append(dp[t-1, s_prev] + trans_prob)
                
                best_prev = np.argmax(probs)
                backpointer[t, s_curr] = best_prev
                dp[t, s_curr] = probs[best_prev] + (emission_matrix[t, s_curr] * 10.0)

        # Backtracking
        best_last_state = np.argmax(dp[n_segments-1])
        refined_indices = [0] * n_segments
        refined_indices[-1] = best_last_state
        
        for t in range(n_segments - 2, -1, -1):
            refined_indices[t] = backpointer[t+1, refined_indices[t+1]]

        # Map indices back to original speaker labels
        refined_labels = [unique_speakers[idx] for idx in refined_indices]
        
        # Check how many changed
        changes = sum(1 for i in range(n_segments) if labels[i] != refined_labels[i])
        logger.info(f"✅ VBx Refiner: Updated {changes}/{n_segments} segment labels.")

        return refined_labels
