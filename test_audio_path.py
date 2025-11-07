import sys
sys.path.insert(0, ".")
import os

audio_path = "storage/audio/filetest.mp3"
print(f"Testing file: {audio_path}")
print(f"File exists: {os.path.exists(audio_path)}")
print(f"Absolute path: {os.path.abspath(audio_path)}")

# Test direct model call
from faster_whisper import WhisperModel
model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16", download_root="models/whisper")

print("\n1. Testing with relative path (like diarization method):")
segments, info = model.transcribe(audio_path, language="vi", vad_filter=False)
seg_list = list(segments)
first_text = seg_list[0].text if seg_list else "EMPTY"
sys.stdout.buffer.write(f"   First segment: {first_text[:80]}\n".encode('utf-8'))

print("\n2. Testing with absolute path:")
abs_path = os.path.abspath(audio_path)
segments2, info2 = model.transcribe(abs_path, language="vi", vad_filter=False)
seg_list2 = list(segments2)
first_text2 = seg_list2[0].text if seg_list2 else "EMPTY"
sys.stdout.buffer.write(f"   First segment: {first_text2[:80]}\n".encode('utf-8'))
