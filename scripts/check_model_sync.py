import ctranslate2
import faster_whisper
print("CTranslate2 version:", ctranslate2.__version__)
print("Faster-Whisper version:", faster_whisper.__version__)
from faster_whisper import WhisperModel
model_path = "models/faster-whisper-large-v2"
model = WhisperModel(model_path, device="cpu")
print("Model loaded successfully:", model_path) 