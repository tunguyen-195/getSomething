
import sys
import os
sys.path.append(os.getcwd())

import logging
logging.basicConfig(level=logging.INFO)

from src.audio_processing.vad.silero_adapter import SileroVADAdapter

def test_silero():
    print("Testing SileroVADAdapter...")
    try:
        vad = SileroVADAdapter()
        # Trigger model load
        vad._load_model()
        print("✅ Silero Model loaded successfully")
        
        # Check download paths
        if vad.model_path.exists():
            print(f"✅ Model found at {vad.model_path}")
        else:
            print(f"❌ Model missing at {vad.model_path}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_silero()
