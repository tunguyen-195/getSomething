"""
Cherry Core Configuration for SpeechToInformation
Adapted from E:\research\Cherry2\cherry_core\core\config.py
"""
import os
from pathlib import Path

# Base directory - adjusted for SpeechToInformation structure
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent

# Model directory. Keep this repo portable; developers can override with env.
MODELS_DIR = Path(os.getenv("CHERRY_MODELS_DIR", str(PROJECT_ROOT / "models")))

PHOWHISPER_PATH = MODELS_DIR / "phowhisper-large"
WHISPER_V3_PATH = MODELS_DIR / "whisper-large-v3"
WHISPER_V2_PATH = MODELS_DIR / "whisper-large-v2"
PROTONX_PATH = MODELS_DIR / "protonx"
SILERO_PATH = MODELS_DIR / "silero"
SPEECHBRAIN_PATH = MODELS_DIR / "speechbrain-ecapa-voxceleb"

# LLM Configuration
USE_VLLM = False  # Use LlamaCpp for Windows
LLM_MODEL_NAME = "vistral-7b-chat-Q4_K_M.gguf"
LLM_MODEL_TYPE = "vistral"  # or "qwen3"

# Audio
SAMPLE_RATE = 16000

# Settings
OFFLINE_MODE = True

# Prompts directory
PROMPTS_DIR = BASE_DIR / "prompts"
