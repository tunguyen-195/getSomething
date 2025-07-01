import os
import sys
from pathlib import Path
import logging
import requests
from tqdm import tqdm
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from faster_whisper import WhisperModel
import ctranslate2
import hashlib
import json
import time
import shutil
import subprocess
from huggingface_hub import snapshot_download
import glob

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('download_models.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

REQUIRED_PACKAGES = [
    'faster-whisper', 'ctranslate2', 'transformers', 'huggingface_hub', 'tqdm', 'requests', 'torch',
    'pyannote.audio', 'speechbrain'
]

def ensure_packages():
    import importlib
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg.split('.')[0])
        except ImportError:
            logger.info(f"Installing missing package: {pkg}")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])

ensure_packages()

class ModelManager:
    def __init__(self):
        self.models_dir = Path("models")
        self.models_dir.mkdir(exist_ok=True)
        self.model_info_file = self.models_dir / "model_info.json"
        self.model_info = self._load_model_info()
        
    def _load_model_info(self):
        """Load model information from JSON file"""
        if self.model_info_file.exists():
            try:
                with open(self.model_info_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading model info: {e}")
                return {}
        return {}
    
    def _save_model_info(self):
        """Save model information to JSON file"""
        try:
            with open(self.model_info_file, 'w', encoding='utf-8') as f:
                json.dump(self.model_info, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving model info: {e}")
    
    def _calculate_hash(self, file_path):
        """Calculate SHA256 hash of a file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def check_model_exists(self, model_name, model_type):
        model_path = self.models_dir / model_name
        if not model_path.exists():
            raise RuntimeError(f"Model {model_name} ({model_type}) not found at {model_path}. Please download manually for offline use.")
        return True

def main():
    model_manager = ModelManager()
    # Kiểm tra các model cần thiết
    whisper_models = ["faster-whisper-large-v2", "faster-whisper-medium-v2"]
    for m in whisper_models:
        model_manager.check_model_exists(m, "whisper")
    t5_models = ["t5-base"]
    for m in t5_models:
        model_manager.check_model_exists(m, "t5")
    vosk_models = ["vosk-model-vn-0.4"]
    for m in vosk_models:
        model_manager.check_model_exists(m, "vosk")
    logger.info("All required models are present locally. Offline mode ready!")

if __name__ == "__main__":
    main() 