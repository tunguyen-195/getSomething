from .whisperx import WhisperXPipeline
from .nemo import NeMoPipeline
from .base import SpeakerDiarizationPipeline

PIPELINE_MAP = {
    "whisperx": WhisperXPipeline,
    "nemo": NeMoPipeline,
    "none": None
}

def get_pipeline(method: str) -> SpeakerDiarizationPipeline:
    if method == "none" or not method:
        return None
    cls = PIPELINE_MAP.get(method.lower())
    if cls is None:
        raise ValueError(f"Unknown diarization method: {method}")
    return cls()
