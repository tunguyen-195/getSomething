"""
Model Managers for Transcription
Singleton pattern with lazy loading
"""
from .whisper_manager import WhisperManager
from .pyannote_manager import PyannoteManager

__all__ = ['WhisperManager', 'PyannoteManager']
