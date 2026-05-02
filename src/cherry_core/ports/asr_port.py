from abc import ABC, abstractmethod
from ..domain.entities import Transcript

class ITranscriber(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str) -> Transcript:
        """
        Transcribe audio file to Domain Transcript.
        """
        pass
