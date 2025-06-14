import os
import whisper
import torch
from tqdm import tqdm
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def download_whisper_model():
    try:
        logger.info("Starting Whisper model download...")
        
        # Set device
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {device}")
        
        # Download with retry mechanism
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Download attempt {attempt + 1}/{max_retries}")
                model = whisper.load_model("large-v3", device=device)
                logger.info("Whisper model downloaded successfully!")
                return True
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    logger.info("Retrying...")
                    # Clear CUDA cache if using GPU
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                else:
                    logger.error("All download attempts failed")
                    return False
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return False

if __name__ == "__main__":
    download_whisper_model() 