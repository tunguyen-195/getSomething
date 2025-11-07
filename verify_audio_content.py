"""Verify audio content matches expected transcript"""
import sys
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, '.')
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Test all audio files to find the correct one
from faster_whisper import WhisperModel

print("Loading model...")
model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16", download_root="models/whisper")

audio_dir = "storage/audio"
audio_files = [
    "filetest.mp3",
    "Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3",
    "Ghi am Thai Dung 27.8.2025.WAV",
    "Cách Dùng Cursor AI Hiệu Quả CHO NGƯỜI MỚI BẮT ĐẦU.mp3"
]

for audio_file in audio_files:
    path = os.path.join(audio_dir, audio_file)
    if not os.path.exists(path):
        print(f"\n❌ NOT FOUND: {audio_file}")
        continue
    
    print(f"\n{'='*80}")
    print(f"Testing: {audio_file}")
    print(f"Size: {os.path.getsize(path) / (1024*1024):.2f} MB")
    
    try:
        segments, info = model.transcribe(path, language="vi", vad_filter=False)
        seg_list = list(segments)
        
        if not seg_list:
            print("  ⚠️ NO SEGMENTS FOUND")
            continue
        
        first_text = seg_list[0].text
        print(f"  Duration: {info.duration:.1f}s")
        print(f"  First segment: {first_text[:100]}")
        
        # Check if it matches hotel booking content
        hotel_keywords = ["khách sạn", "shilla", "prius", "đặt phòng", "lễ tân"]
        matches = [kw for kw in hotel_keywords if kw.lower() in first_text.lower()]
        
        if matches:
            print(f"  ✅ MATCHES HOTEL BOOKING (keywords: {matches})")
        else:
            print(f"  ❌ Does NOT match hotel booking")
            
    except Exception as e:
        print(f"  ❌ ERROR: {e}")

print("\n" + "="*80)