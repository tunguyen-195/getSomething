import logging
from faster_whisper import WhisperModel
import torch
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join("models", "faster-whisper-large-v2")

def ensure_model_local():
    if os.path.exists(MODEL_PATH) and any(os.scandir(MODEL_PATH)):
        logger.info(f"Model already exists at {MODEL_PATH}, using offline mode.")
        return MODEL_PATH
    raise RuntimeError(f"Model path {MODEL_PATH} does not exist. Please download the model manually for offline use.")

def load_faster_whisper_large_v2():
    try:
        model_dir = ensure_model_local()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        model = WhisperModel(model_dir, device=device, compute_type=compute_type)
        logger.info("faster-whisper large-v2 model loaded from local cache and ready!")
        return True
    except Exception as e:
        logger.error(f"Error loading faster-whisper large-v2: {str(e)}")
        return False

if __name__ == "__main__":
    load_faster_whisper_large_v2() 