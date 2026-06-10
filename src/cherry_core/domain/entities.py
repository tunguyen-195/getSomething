from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str

@dataclass
class SpeakerSegment:
    """Represents a segment of speech attributed to a specific speaker."""
    start_time: float
    end_time: float
    speaker_id: str  # e.g., "SPEAKER_1", "SPEAKER_2"
    text: str = ""   # Filled after ASR alignment
    words: List[Dict] = field(default_factory=list) # Word-level timestamps

@dataclass
class Transcript:
    """
    Represents the raw result of an ASR process.
    Core business entity.
    """
    text: str
    segments: List[TranscriptSegment] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class StrategicReport:
    """
    Represents the final Strategic Intelligence Dossier.
    """
    strategic_assessment: Dict[str, Any]
    tactical_intelligence: Dict[str, Any]
    behavioral_profiling: Dict[str, Any]
    operational_recommendations: List[str]
