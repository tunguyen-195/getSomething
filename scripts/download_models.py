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
    
    def _check_model_exists(self, model_name, model_type):
        """Check if model exists and is valid"""
        model_path = self.models_dir / model_name
        if not model_path.exists():
            return False
            
        # Check model info
        model_key = f"{model_type}_{model_name}"
        if model_key not in self.model_info:
            return False
            
        # Verify model files
        if model_type == "whisper":
            return (model_path / "model.bin").exists()
        elif model_type == "t5":
            return all((model_path / f).exists() for f in ["config.json", "pytorch_model.bin"])
        elif model_type == "vosk":
            return all((model_path / f).exists() for f in ["conf", "am", "graph"])
            
        return False
    
    def download_file(self, url: str, filename: str):
        """Download file with progress bar and resume support"""
        if os.path.exists(filename):
            # Check if download is complete
            response = requests.head(url)
            total_size = int(response.headers.get('content-length', 0))
            if os.path.getsize(filename) == total_size:
                logger.info(f"File {filename} already exists and is complete")
                return True
                
            # Resume download
            first_byte = os.path.getsize(filename)
            headers = {'Range': f'bytes={first_byte}-'}
            response = requests.get(url, headers=headers, stream=True)
        else:
            response = requests.get(url, stream=True)
            
        total_size = int(response.headers.get('content-length', 0))
        
        with open(filename, 'ab' if os.path.exists(filename) else 'wb') as f, tqdm(
            desc=filename,
            total=total_size,
            unit='iB',
            unit_scale=True
        ) as pbar:
            for data in response.iter_content(chunk_size=1024):
                size = f.write(data)
                pbar.update(size)
                
        return True
    
    def download_whisper_model(self, model_name: str = "large"):
        try:
            model_dir = self.models_dir / f"whisper-{model_name}"
            if self._check_model_exists(f"whisper-{model_name}", "whisper"):
                logger.info(f"Whisper model {model_name} already exists")
                return True

            logger.info(f"Downloading Whisper model: {model_name}")
            # Tải model về đúng thư mục
            WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
                download_root=str(self.models_dir)
            )

            logger.info(f"Model downloaded successfully to: {model_dir}")
            return True

        except Exception as e:
            logger.error(f"Error downloading Whisper model: {str(e)}")
            return False
    
    def download_t5_model(self):
        """Download and save T5 model"""
        try:
            model_dir = self.models_dir / "t5-base"
            
            # Check if model exists
            if self._check_model_exists("t5-base", "t5"):
                logger.info("T5 model already exists")
                return True
                
            logger.info("Downloading T5 model...")
            model_dir.mkdir(parents=True, exist_ok=True)
            
            # Download tokenizer
            tokenizer = AutoTokenizer.from_pretrained("t5-base")
            tokenizer.save_pretrained(model_dir)
            
            # Download model with quantization
            model = AutoModelForSeq2SeqLM.from_pretrained(
                "t5-base",
                torch_dtype=torch.float16,
                low_cpu_mem_usage=True
            )
            model.save_pretrained(model_dir)
            
            # Update model info
            model_files = list(model_dir.glob("**/*"))
            total_size = sum(f.stat().st_size for f in model_files if f.is_file())
            self.model_info["t5_t5-base"] = {
                "version": "t5-base",
                "size": total_size,
                "files": [str(f.relative_to(model_dir)) for f in model_files if f.is_file()],
                "last_updated": time.time()
            }
            self._save_model_info()
            
            logger.info(f"T5 model downloaded and saved to: {model_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Error downloading T5 model: {str(e)}")
            return False
    
    def download_vosk_model(self):
        """Download and save Vosk model"""
        try:
            model_dir = self.models_dir / "vosk-model-vn-0.4"
            
            # Check if model exists
            if self._check_model_exists("vosk-model-vn-0.4", "vosk"):
                logger.info("Vosk model already exists")
                return True
                
            logger.info("Downloading Vosk model...")
            vosk_url = "https://alphacephei.com/vosk/models/vosk-model-vn-0.4.zip"
            vosk_zip = self.models_dir / "vosk-model-vn.zip"
            
            # Download model
            if not self.download_file(vosk_url, str(vosk_zip)):
                return False
                
            # Extract model
            import zipfile
            with zipfile.ZipFile(vosk_zip, 'r') as zip_ref:
                zip_ref.extractall(str(self.models_dir))
                
            # Update model info
            model_files = list(model_dir.glob("**/*"))
            total_size = sum(f.stat().st_size for f in model_files if f.is_file())
            self.model_info["vosk_vosk-model-vn-0.4"] = {
                "version": "0.4",
                "size": total_size,
                "files": [str(f.relative_to(model_dir)) for f in model_files if f.is_file()],
                "last_updated": time.time()
            }
            self._save_model_info()
            
            # Clean up zip file
            os.remove(vosk_zip)
            
            logger.info(f"Vosk model downloaded and saved to: {model_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Error downloading Vosk model: {str(e)}")
            return False

def main():
    model_manager = ModelManager()
    
    # Download models
    print("Checking and downloading models...")
    
    # Download Whisper model
    print("Checking Whisper model (large)...")
    model_manager.download_whisper_model("large")
    
    # Download Vosk model
    print("Checking Vosk model for Vietnamese...")
    model_manager.download_vosk_model()
    
    # Download T5 model (comment lại nếu chỉ cần Whisper)
    # print("Checking T5 model for summarization...")
    # model_manager.download_t5_model()
    
    print("All models checked and downloaded successfully!")

if __name__ == "__main__":
    main() 