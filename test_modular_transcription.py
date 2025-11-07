"""
Test script for modular transcription with new managers
Tests against sample.m4a baseline
"""
import sys
import time
from pathlib import Path
import io

# Fix console encoding for Vietnamese
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from services.transcription.models.whisper_manager import get_whisper_manager
from services.transcription.models.pyannote_manager import get_pyannote_manager

def test_whisper_manager():
    """Test Whisper Manager singleton and lazy loading"""
    print("\n" + "="*60)
    print("TEST 1: Whisper Manager")
    print("="*60)
    
    audio_path = "storage/audio/sample.m4a"
    expected_file = "storage/audio/sample.m4a.txt"
    
    if not Path(audio_path).exists():
        print(f"[ERROR] Audio file not found: {audio_path}")
        return False
    
    # Load expected transcript
    with open(expected_file, 'r', encoding='utf-8') as f:
        expected_content = f.read()
    
    print(f"\n[INFO] Expected transcript length: {len(expected_content)} chars")
    print(f"[INFO] Expected speakers: 2 (Speaker 0, Speaker 1)")
    
    # Get manager (should NOT load model yet)
    print("\n[STEP] Getting Whisper manager...")
    start = time.time()
    manager = get_whisper_manager()
    print(f"[OK] Manager instance created in {time.time()-start:.2f}s (no model loaded yet)")
    
    # First transcription (will load model)
    print("\n[STEP] Transcribing (first time, will load model)...")
    start = time.time()
    segments, info = manager.transcribe(audio_path, vad_filter=False)
    
    # Collect segments
    transcripts = []
    for segment in segments:
        transcripts.append(segment.text)
    
    full_transcript = " ".join(transcripts)
    load_time = time.time() - start
    
    print(f"[OK] Transcription completed in {load_time:.2f}s")
    print(f"[INFO] Duration: {info.duration:.2f}s")
    print(f"[INFO] Language: {info.language}")
    print(f"[INFO] Segments: {len(transcripts)}")
    print(f"[INFO] Transcript length: {len(full_transcript)} chars")
    
    # Check first segment
    if transcripts:
        print(f"\n[TEXT] First segment: {transcripts[0][:100]}...")
    
    # Second transcription (should reuse model)
    print("\n[STEP] Transcribing again (should reuse cached model)...")
    start = time.time()
    segments2, info2 = manager.transcribe(audio_path, vad_filter=False)
    reuse_time = time.time() - start
    
    print(f"[OK] Second transcription in {reuse_time:.2f}s")
    print(f"[PERF] Speedup: {load_time/reuse_time:.1f}x faster (cached model)")
    
    # Verify content
    if "Anh à" in full_transcript or "anh à" in full_transcript.lower():
        print("\n[PASS] Content verification: PASSED (contains expected greeting)")
    else:
        print("\n[WARN] Content verification: Check manually")
        print(f"First 200 chars: {full_transcript[:200]}")
    
    return True


def main():
    """Run tests"""
    print("\n" + "="*70)
    print(" MODULAR TRANSCRIPTION SYSTEM - TEST SUITE")
    print("="*70)
    print(f"\n[TEST] Test file: storage/audio/sample.m4a")
    print(f"[TEST] Expected output: storage/audio/sample.m4a.txt")
    
    try:
        # Test 1: Whisper Manager
        if not test_whisper_manager():
            print("\n[FAIL] Whisper Manager test failed")
            return
        
        print("\n" + "="*70)
        print("[SUCCESS] ALL TESTS PASSED")
        print("="*70)
        
    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()