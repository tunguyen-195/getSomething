import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

def check_modules():
    print("Checking Cherry Core Modules...")
    
    try:
        from src.cherry_core.config import MODELS_DIR, PHOWHISPER_PATH
        print(f"✅ Config loaded. Models Dir: {MODELS_DIR}")
        print(f"   PhoWhisper Path: {PHOWHISPER_PATH}")
    except ImportError as e:
        print(f"❌ Config import failed: {e}")
        return

    try:
        from src.cherry_core.adapters.asr import PhoWhisperAdapter
        print("✅ PhoWhisperAdapter imported")
    except ImportError as e:
        print(f"❌ PhoWhisperAdapter import failed: {e}")

    try:
        from src.cherry_core.adapters.llm import LlamaCppAdapter
        print("✅ LlamaCppAdapter imported")
    except ImportError as e:
        print(f"❌ LlamaCppAdapter import failed: {e}")

    try:
        from src.services.transcription.cherry_transcription_service import get_cherry_transcriber
        print("✅ CherryTranscriptionService imported")
    except ImportError as e:
        print(f"❌ CherryTranscriptionService import failed: {e}")

    try:
        from src.services.cherry_summarizer import check_cherry_core_available
        available = check_cherry_core_available()
        print(f"✅ Cherry Core Availability Check: {available}")
    except ImportError as e:
        print(f"❌ Cherry Summarizer import failed: {e}")

if __name__ == "__main__":
    check_modules()
