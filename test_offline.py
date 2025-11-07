import os
import sys

print("="*80)
print("TEST PYANNOTE OFFLINE MODE")
print("="*80)

# Test 1: Check cached models
cache_dir = r"C:\Users\Admin\.cache\huggingface\hub"
print(f"\n[1] Checking cache directory: {cache_dir}")
import glob
models = glob.glob(os.path.join(cache_dir, "models--pyannote*"))
print(f"Found {len(models)} pyannote models:")
for m in models:
    print(f"  - {os.path.basename(m)}")

# Test 2: Try load without token
print("\n[2] Testing load without HF_TOKEN...")
os.environ.pop('HF_TOKEN', None)  # Remove token

try:
    from pyannote.audio import Pipeline
    print("Attempting to load pipeline...")
    
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=None
    )
    print("SUCCESS! Pipeline loaded without token")
    print("Offline mode: CONFIRMED")
except Exception as e:
    print(f"FAILED: {e}")
    print("\nTrying local path...")
    
    # Test 3: Load from exact cache path
    try:
        model_dirs = glob.glob(os.path.join(cache_dir, "models--pyannote--speaker-diarization-3.1"))
        if model_dirs:
            local_path = model_dirs[0]
            print(f"Local path: {local_path}")
            pipeline = Pipeline.from_pretrained(local_path)
            print("SUCCESS with local path!")
        else:
            print("No local model found")
    except Exception as e2:
        print(f"Also failed: {e2}")

print("\n" + "="*80)
