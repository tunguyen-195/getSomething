import sys
sys.path.insert(0, ".")
from src.speech_to_text.transcriber import Transcriber

transcriber = Transcriber()
audio_path = "storage/audio/filetest.mp3"

print("Testing OLD transcribe() method\n")

result = transcriber.transcribe(audio_path, fast_mode=True)

print(f"Duration: {result['duration']:.1f}s")
print(f"Transcript length: {len(result['transcription'])} chars")
print("\nFirst 200 chars of transcript:")
sys.stdout.buffer.write(result['transcription'][:200].encode('utf-8'))
print("\n")
