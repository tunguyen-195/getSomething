"""Test Integrated Model - Whisper Large-v3-Turbo"""
import sys
import os
import time
from pathlib import Path

os.environ['PYTHONIOENCODING'] = 'utf-8'
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, '.')

print("=" * 60)
print("TESTING INTEGRATED MODEL")
print("=" * 60)

# Test 1: Import system components
print("\n[1] Importing system components...")
try:
    from src.speech_to_text.transcriber import Transcriber
    from src.core.config import settings
    print("✓ System imports successful")
    print(f"  Model: {settings.WHISPER_MODEL}")
    print(f"  Local mode: {getattr(settings, 'WHISPER_USE_LOCAL', True)}")
except Exception as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Test 2: Initialize Transcriber
print("\n[2] Initializing Transcriber (this loads the model)...")
try:
    import torch
    if torch.cuda.is_available():
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
    
    start = time.time()
    transcriber = Transcriber()
    load_time = time.time() - start
    
    print(f"✓ Transcriber initialized in {load_time:.1f}s")
    print(f"  Model: {transcriber.model_name}")
    print(f"  Device: {transcriber.device}")
    print(f"  Batch size: {transcriber.batch_size}")
except Exception as e:
    print(f"✗ Initialization failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Transcribe audio
print("\n[3] Transcribing audio file...")
audio_file = r"storage\audio\Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3"

if os.path.exists(audio_file):
    try:
        start = time.time()
        result = transcriber.transcribe(audio_file, fast_mode=True)  # Enable fast mode
        transcribe_time = time.time() - start
        
        print(f"✓ Transcription completed in {transcribe_time:.2f}s")
        print(f"  Mode: FAST (no LLM post-processing)")
        
        # Display results
        duration = result.get('duration', 0)
        if duration > 0:
            print(f"  Duration: {duration:.1f}s")
            print(f"  Speed: {duration / transcribe_time:.1f}x real-time")
        
        print(f"  Language: {result.get('language', 'N/A')}")
        print(f"  Segments: {len(result.get('segments', []))}")
        
        # Show first 300 chars of transcript
        transcript = result.get('transcription', '')
        if transcript:
            print(f"\n  Transcript (first 300 chars):")
            print(f"  {transcript[:300]}...")
        
        # Show first 3 segments
        segments = result.get('segments', [])
        if segments:
            print(f"\n  First 3 segments:")
            for i, seg in enumerate(segments[:3], 1):
                print(f"    {i}. [{seg.get('start', 0):.1f}s] {seg.get('text', '')[:80]}")
        
    except Exception as e:
        print(f"✗ Transcription failed: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"! Audio file not found: {audio_file}")

print("\n" + "=" * 60)
print("INTEGRATION TEST COMPLETED")
print("=" * 60)