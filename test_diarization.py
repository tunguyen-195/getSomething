"""Test Speaker Diarization"""
import sys, os, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, '.')

print("="*80)
print("TESTING SPEAKER DIARIZATION")
print("="*80)

from src.speech_to_text.transcriber import Transcriber
transcriber = Transcriber()
print(f"Model loaded: {transcriber.model_name}")

audio = r"storage\audio\Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3"
print(f"\nProcessing: {audio}")

start = time.time()
result = transcriber.transcribe_with_diarization(audio, fast_mode=True, enable_diarization=True)
elapsed = time.time() - start

print(f"Completed: {elapsed:.2f}s | Speed: {result['speed_factor']:.1f}x")
print(f"Speakers: {result['num_speakers']} | Segments: {len(result['segments'])}")

print("\nFirst 3 segments:")
for i, seg in enumerate(result['segments'][:3]):
    print(f"{i+1}. [{seg['speaker']}] {seg['text'][:80]}...")

output = audio.replace('.mp3', '_diarized.txt')
with open(output, 'w', encoding='utf-8') as f:
    f.write(result['formatted_transcript'])
print(f"\nSaved to: {output}")
