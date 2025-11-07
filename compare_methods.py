import sys
sys.path.insert(0, ".")
from src.speech_to_text.transcriber import Transcriber

transcriber = Transcriber()
audio = "storage/audio/filetest.mp3"

print("="*60)
print("METHOD 1: transcribe() [OLD - WORKING]")
print("="*60)
r1 = transcriber.transcribe(audio, fast_mode=True)
print(f"First 150 chars: {r1['transcription'][:150]}")

print("\n" + "="*60)
print("METHOD 2: transcribe_with_diarization() [NEW - BROKEN]")
print("="*60)
r2 = transcriber.transcribe_with_diarization(audio, fast_mode=True, enable_diarization=False)
print(f"First 150 chars: {r2.get('transcription', '')[:150]}")

print("\n" + "="*60)
print("COMPARISON")
print("="*60)
print(f"Method 1 starts with: {r1['transcription'][:30]}")
print(f"Method 2 starts with: {r2.get('transcription', '')[:30]}")
