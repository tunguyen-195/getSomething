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

def download_faster_whisper_model(model_size, dest_dir):
    repo_map = {
        'large-v2': 'guillaumekln/faster-whisper-large-v2',
        'large-v3': 'guillaumekln/faster-whisper-large-v3',
        'medium-v2': 'guillaumekln/faster-whisper-medium-v2',
        'small-v2': 'guillaumekln/faster-whisper-small-v2',
        'tiny-v2': 'guillaumekln/faster-whisper-tiny-v2',
    }
    repo = repo_map[model_size]
    # Kiểm tra nếu đã có đủ file model trong snapshot hash thì bỏ qua
    try:
        # Tìm thư mục hash trong dest_dir
        hash_dirs = [d for d in Path(dest_dir).iterdir() if d.is_dir() and len(d.name) == 40]
        if hash_dirs:
            hash_dir = hash_dirs[0]
            required_files = [
                hash_dir / 'model.bin',
                hash_dir / 'tokenizer.json',
                hash_dir / 'config.json',
                hash_dir / 'vocabulary.txt',
            ]
            if all(f.exists() for f in required_files):
                logger.info(f"Model {repo} already exists at {hash_dir}, skip download.")
                return True
    except Exception as e:
        logger.warning(f"Error checking existing model files for {repo}: {e}")
    # Nếu chưa đủ file thì tải về
    try:
        logger.info(f"Downloading {repo} to {dest_dir}")
        snapshot_path = snapshot_download(repo_id=repo, local_dir=dest_dir, local_dir_use_symlinks=False, resume_download=True)
        logger.info(f"Downloaded snapshot to: {snapshot_path}")
        files = glob.glob(str(Path(snapshot_path) / '**'), recursive=True)
        logger.info(f"Files in snapshot: {files}")
    except Exception as e:
        logger.warning(f"Failed to download {repo}: {e}")
        return False
    return True

def download_pyannote_models():
    try:
        from huggingface_hub import snapshot_download
        pyannote_models = [
            'pyannote/speaker-diarization',
            'pyannote/embedding',
            'pyannote/segmentation',
        ]
        for model in pyannote_models:
            cache_dir = Path("models/pyannote_cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            # Kiểm tra nếu đã có đủ file model trong hash thì skip
            hash_dirs = [d for d in cache_dir.iterdir() if d.is_dir() and len(d.name) == 40]
            found = False
            for hash_dir in hash_dirs:
                if any((hash_dir / f).exists() for f in ["pytorch_model.bin", "config.json", "preprocessor_config.json"]):
                    logger.info(f"pyannote model {model} already exists at {hash_dir}, skip download.")
                    found = True
                    break
            if found:
                continue
            logger.info(f"Downloading pyannote model: {model}")
            try:
                snapshot_download(model, cache_dir=str(cache_dir), local_dir_use_symlinks=False, resume_download=True)
            except Exception as e:
                logger.warning(f"pyannote.audio model download failed: {e}")
        logger.info("All pyannote.audio models checked.")
    except Exception as e:
        logger.warning(f"pyannote.audio model download failed: {e}")

def download_speechbrain_models():
    try:
        from huggingface_hub import snapshot_download
        sb_models = [
            'speechbrain/emotion-recognition-wav2vec2',
            'speechbrain/sentiment-analysis-wav2vec2',
            'speechbrain/stress-detection-wav2vec2',
        ]
        for model in sb_models:
            cache_dir = Path("models/speechbrain_cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            # Kiểm tra nếu đã có đủ file model trong hash thì skip
            hash_dirs = [d for d in cache_dir.iterdir() if d.is_dir() and len(d.name) == 40]
            found = False
            for hash_dir in hash_dirs:
                if any((hash_dir / f).exists() for f in ["model.ckpt", "hyperparams.yaml", "config.json"]):
                    logger.info(f"SpeechBrain model {model} already exists at {hash_dir}, skip download.")
                    found = True
                    break
            if found:
                continue
            logger.info(f"Downloading SpeechBrain model: {model}")
            try:
                snapshot_download(model, cache_dir=str(cache_dir), local_dir_use_symlinks=False, resume_download=True)
            except Exception as e:
                logger.warning(f"SpeechBrain model download failed: {e}")
        logger.info("All SpeechBrain models checked.")
    except Exception as e:
        logger.warning(f"SpeechBrain model download failed: {e}")

def main():
    ensure_packages()
    model_manager = ModelManager()
    whisper_sizes = ['large-v2', 'large-v3', 'medium-v2', 'small-v2', 'tiny-v2']
    for size in whisper_sizes:
        dest = model_manager.models_dir / f"models--guillaumekln--faster-whisper-{size}" / "snapshots"
        dest.mkdir(parents=True, exist_ok=True)
        ok = download_faster_whisper_model(size, str(dest))
        ct2_dir = dest / "ct2"
        if ok and not ct2_dir.exists():
            logger.info(f"Converting {size} to CTranslate2 format...")
            try:
                subprocess.run([
                    sys.executable, '-m', 'ctranslate2.converters.transformers',
                    '--model', str(dest),
                    '--output_dir', str(ct2_dir),
                    '--copy_files', 'tokenizer.json', 'preprocessor_config.json',
                    '--quantization', 'int8'
                ], check=True)
            except Exception as e:
                logger.warning(f"CTranslate2 conversion failed for {size}: {e}")
    # Luôn tải các model pipeline cho pyannote.audio và SpeechBrain
    download_pyannote_models()
    download_speechbrain_models()
    logger.info("All models checked, downloaded, and converted successfully!")

if __name__ == "__main__":
    main() 