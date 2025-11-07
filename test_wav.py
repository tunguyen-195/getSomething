from faster_whisper import WhisperModel
import sys

model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16", download_root="models/whisper")
audio = "storage/audio/Ghi am Thai Dung 27.8.2025.WAV"

print(f"Testing: {audio}")
segments, info = model.transcribe(audio, language="vi", vad_filter=False, beam_size=5)

seg_list = list(segments)
print(f"\nDuration: {info.duration:.1f}s")
print(f"Total segments: {len(seg_list)}")
print("\nFirst 5 segments:")

for i, seg in enumerate(seg_list[:5]):
    text_preview = seg.text[:80] if len(seg.text) > 80 else seg.text
    sys.stdout.buffer.write(f"{i+1}. [{seg.start:.1f}s-{seg.end:.1f}s] {text_preview}\n".encode('utf-8'))
