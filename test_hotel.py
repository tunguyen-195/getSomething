import sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, '.')
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
from src.speech_to_text.transcriber import Transcriber
transcriber = Transcriber()
audio = 'storage/audio/Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3'
print(f'Testing HOTEL BOOKING file: {audio}')
print('='*60)
r1 = transcriber.transcribe(audio, fast_mode=True)
text1 = r1['transcription']
print(f'Length: {len(text1)}')
print(f'First 150: {text1[:150]}')
print()
print('Expected: Khách sạn Shilla Prius Hotel...')
if 'khách sạn' in text1.lower() or 'shilla' in text1.lower():
    print('✅ CORRECT - Hotel booking content')
else:
    print('❌ WRONG - Not hotel booking')
