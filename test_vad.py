import sys
sys.path.insert(0, ".")
from src.speech_to_text.transcriber import Transcriber

# Test with VAD disabled
transcriber = Transcriber()

audio = r"storage\audio\Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3"

print("Testing với vad_filter=False...")
segments, info = transcriber.model.transcribe(
    audio,
    language="vi",
    beam_size=5,
    vad_filter=False,  # Disable VAD
    word_timestamps=False
)

print(f"Duration: {info.duration:.1f}s")
seg_list = list(segments)
print(f"Num segments: {len(seg_list)}")
print(f"\nFirst 3 segments:")
for i, seg in enumerate(seg_list[:3]):
    print(f"{i+1}. [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text[:80]}")
