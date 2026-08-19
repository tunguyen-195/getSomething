import logging
import os
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from src.cherry_core.ports.correction_port import ITextCorrector

logger = logging.getLogger(__name__)

import torch

from src.cherry_core.config import PROTONX_PATH

class ProtonXAdapter(ITextCorrector):
    """
    Adapter for ProtonX Vietnamese Spell Correction.
    Uses 'protonx-models/protonx-legal-tc' via transformers.
    Optimized for GPU usage and Long Text handling.
    """
    MODEL_ID = "protonx-models/protonx-legal-tc"
    LOCAL_DIR = PROTONX_PATH

    def __init__(self):
        self.tokenizer = None
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
    def _ensure_model(self):
        if not self.model:
            logger.info(f"Initializing ProtonX Corrector (Target: {self.LOCAL_DIR}) on {self.device.upper()}...")
            
            # Check if local model exists (simple check)
            if os.path.exists(self.LOCAL_DIR) and len(os.listdir(self.LOCAL_DIR)) > 0:
                logger.info("Loading model from local storage (Offline Mode)...")
                try:
                    self.tokenizer = AutoTokenizer.from_pretrained(self.LOCAL_DIR, local_files_only=True, trust_remote_code=True)
                    self.model = AutoModelForSeq2SeqLM.from_pretrained(self.LOCAL_DIR, local_files_only=True, trust_remote_code=True)
                    self.model.to(self.device)
                    logger.info("ProtonX Corrector loaded successfully.")
                except Exception as e:
                    logger.error(f"Failed to load local model: {e}")
                    raise RuntimeError("Local model text corrupted. Please run setup_models.py")
            else:
                raise RuntimeError(
                    f"Model not found in {self.LOCAL_DIR}. "
                    "Rule: No runtime downloads. Please run 'python scripts/setup_models.py' first."
                )

    def correct(self, text: str) -> str:
        """
        Corrects the input text using the Seq2Seq model.
        Handles long text by splitting into segments.
        """
        self._ensure_model()
        if not text or len(text.strip()) == 0:
            return ""

        try:
            # Simple chunking by approximate length (or newlines) to avoid 512 limits
            # ASR output often lacks punctuation, so we use a sliding window approach if needed.
            # For simplicity and speed, we split by 100 words chunks which is safe for 512 tokens.
            words = text.split()
            chunk_size = 100
            chunks = [' '.join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
            
            corrected_chunks = []
            for chunk in chunks:
                if not chunk.strip():
                    continue
                    
                # Tokenize
                inputs = self.tokenizer(chunk, return_tensors="pt", max_length=512, truncation=True)
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                
                # Generate (Batch inference possible but simple loop is safer for now)
                with torch.no_grad():
                    outputs = self.model.generate(
                        inputs["input_ids"],
                        max_length=512,
                        num_beams=3, # Reduced from 5 for speed, 3 is sufficient
                        early_stopping=True
                    )
                
                # Decode
                corrected_chunk = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
                corrected_chunks.append(corrected_chunk)
            
            # Join back
            return " ".join(corrected_chunks)
            
        except Exception as e:
            logger.error(f"Correction failed: {e}")
            return text # Fallback to original
