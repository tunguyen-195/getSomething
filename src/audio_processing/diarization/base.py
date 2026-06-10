from abc import ABC, abstractmethod
from typing import List, Dict, Any

class SpeakerDiarizationPipeline(ABC):
    @abstractmethod
    def run(self, audio_path: str) -> List[Dict[str, Any]]:
        """
        Thực thi pipeline diarization, trả về list segment:
        [
            {"start": float, "end": float, "text": str, "speaker": str/int}
        ]
        """
        pass
