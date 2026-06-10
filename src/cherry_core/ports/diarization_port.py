from abc import ABC, abstractmethod
from typing import List
from core.domain.entities import SpeakerSegment


class ISpeakerDiarizer(ABC):
    """
    Port for Speaker Diarization.
    Segments audio by speaker identity.
    """

    @abstractmethod
    def diarize(self, audio_path: str) -> List[SpeakerSegment]:
        """
        Analyze audio and return segments with speaker labels.

        Args:
            audio_path: Path to audio file.

        Returns:
            List of SpeakerSegment with start_time, end_time, speaker_id.
        """
        pass
