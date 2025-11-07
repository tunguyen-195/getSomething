import sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, '.')
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
from src.speech_to_text.transcriber import Transcriber
transcriber = Transcriber()
audio = 'storage/audio/Cách Dùng Cursor AI Hiệu Quả CHO NGƯỜI MỚI BẮT ĐẦU.mp3'
print(f'Testing: {audio}')
print('='*60)
print('METHOD 1: transcribe()')
print('='*60)
r1 = transcriber.transcribe(audio, fast_mode=True)
text1 = r1['transcription']
print(f'Length: {len(text1)}')
print(f'First 100: {text1[:100]}')
print()
print('='*60)
print('METHOD 2: transcribe_with_diarization()')
print('='*60)
r2 = transcriber.transcribe_with_diarization(audio, fast_mode=True, enable_diarization=True)
text2 = r2.get('transcription', '')
print(f'Length: {len(text2)}')
print(f'First 100: {text2[:100]}')
print()
print('='*60)
if text1[:50] == text2[:50]:
    print('SAME content')
else:
    print('DIFFERENT content!')
