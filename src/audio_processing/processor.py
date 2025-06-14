import librosa
import soundfile as sf
from pydub import AudioSegment
import numpy as np
from pathlib import Path
from typing import Union, Optional

class AudioProcessor:
    def __init__(self, sample_rate: int = 16000):
        """
        Initialize audio processor
        
        Args:
            sample_rate: Target sample rate for audio processing
        """
        self.sample_rate = sample_rate
    
    def load_audio(self, file_path: Union[str, Path]) -> tuple[np.ndarray, int]:
        """
        Load audio file and convert to mono
        
        Args:
            file_path: Path to audio file
            
        Returns:
            tuple: (audio_data, sample_rate)
        """
        audio, sr = librosa.load(file_path, sr=self.sample_rate, mono=True)
        return audio, sr
    
    def save_audio(self, audio: np.ndarray, file_path: Union[str, Path], sample_rate: Optional[int] = None):
        """
        Save audio data to file
        
        Args:
            audio: Audio data as numpy array
            file_path: Path to save audio file
            sample_rate: Sample rate of audio data
        """
        if sample_rate is None:
            sample_rate = self.sample_rate
        sf.write(file_path, audio, sample_rate)
    
    def convert_format(self, input_path: Union[str, Path], output_path: Union[str, Path], 
                      target_format: str = "wav"):
        """
        Convert audio file to target format
        
        Args:
            input_path: Path to input audio file
            output_path: Path to save converted audio
            target_format: Target audio format (e.g., 'wav', 'mp3')
        """
        audio = AudioSegment.from_file(input_path)
        audio.export(output_path, format=target_format)
    
    def normalize_audio(self, audio: np.ndarray) -> np.ndarray:
        """
        Normalize audio data to [-1, 1] range
        
        Args:
            audio: Audio data as numpy array
            
        Returns:
            Normalized audio data
        """
        return librosa.util.normalize(audio)
    
    def remove_silence(self, audio: np.ndarray, top_db: int = 20) -> np.ndarray:
        """
        Remove silence from audio
        
        Args:
            audio: Audio data as numpy array
            top_db: Threshold in dB for silence removal
            
        Returns:
            Audio data with silence removed
        """
        return librosa.effects.trim(audio, top_db=top_db)[0]
    
    def segment_audio(self, audio: np.ndarray, segment_length: int = 30) -> list[np.ndarray]:
        """
        Split audio into segments of specified length
        
        Args:
            audio: Audio data as numpy array
            segment_length: Length of each segment in seconds
            
        Returns:
            List of audio segments
        """
        samples_per_segment = segment_length * self.sample_rate
        segments = []
        
        for i in range(0, len(audio), samples_per_segment):
            segment = audio[i:i + samples_per_segment]
            if len(segment) == samples_per_segment:  # Only add complete segments
                segments.append(segment)
        
        return segments 