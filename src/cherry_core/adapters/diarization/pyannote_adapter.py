"""Pyannote speaker diarization adapter with verified local artifacts."""
import logging
import os
from typing import List, Optional

from src.cherry_core.ports.diarization_port import ISpeakerDiarizer
from src.cherry_core.domain.entities import SpeakerSegment
from src.core.config import settings
from src.services.transcription.models.pyannote_manager import (
    PYANNOTE_MODEL_ROOT,
    compatible_model_spec,
    required_artifact_files,
    resolve_compatible_local_snapshot,
    unwrap_diarization_annotation,
)

logger = logging.getLogger(__name__)


class PyannoteAdapter(ISpeakerDiarizer):
    """
    Speaker Diarization using Pyannote Community-1 (4.0) End-to-End Neural Pipeline.

    Upgraded from 3.1 for:
    - Better speaker assignment (reduced confusion)
    - Improved speaker counting accuracy
    - 16ms frame resolution (vs 1.2s windows)
    - Native overlap handling
    - ~17% DER on AMI benchmark (vs 18.8% in 3.1)
    """

    def __init__(self,
                 hf_token: Optional[str] = None,
                 num_speakers: Optional[int] = None,
                 min_speakers: Optional[int] = None,
                 max_speakers: Optional[int] = None,
                 device: str = "cpu"):
        """
        Args:
            hf_token: HuggingFace token for model download (required first time)
            num_speakers: Exact number of speakers (if known)
            min_speakers: Minimum expected speakers
            max_speakers: Maximum expected speakers
            device: "cpu" or "cuda"
        """
        self.hf_token = hf_token or os.getenv("HF_TOKEN")
        self.num_speakers = num_speakers
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers
        self.device = device
        self._pipeline = None
        self._load_attempted = False
        self._load_error: Optional[str] = None
        self._model_id: Optional[str] = None
        self._model_revision: Optional[str] = None
        self._artifact_verified = False

    def _ensure_pipeline(self):
        """Lazy load Pyannote pipeline."""
        if self._pipeline is None and self._load_attempted:
            raise RuntimeError(self._load_error or "Pyannote pipeline unavailable")
        if self._pipeline is None and not self._load_attempted:
            self._load_attempted = True
            logger.info("🔊 Loading Pyannote Speaker Diarization Pipeline...")

            try:
                from pyannote.audio import Pipeline
                import torch

                local_snapshot = resolve_compatible_local_snapshot()
                model_id, model_revision, _required_files = compatible_model_spec()
                if local_snapshot is not None:
                    local_source, model_id, model_revision = local_snapshot
                    self._pipeline = Pipeline.from_pretrained(
                        local_source / "config.yaml",
                        use_auth_token=False,
                        cache_dir=str(PYANNOTE_MODEL_ROOT),
                    )
                    self._artifact_verified = True
                    logger.info("Using local Pyannote snapshot: %s", local_source)
                elif settings.OFFLINE_STRICT:
                    raise FileNotFoundError(
                        "No complete local Pyannote snapshot is declared for offline use"
                    )
                else:
                    self._pipeline = Pipeline.from_pretrained(
                        model_id,
                        use_auth_token=self.hf_token
                    )
                    logger.info("Using provider Pyannote model: %s", model_id)

                if self._pipeline is None:
                    raise ValueError("Failed to load any Pyannote model")
                self._model_id = model_id
                self._model_revision = model_revision

                # Move to device
                if self.device == "cuda" and torch.cuda.is_available():
                    self._pipeline.to(torch.device("cuda"))
                    logger.info("✅ Pyannote loaded on CUDA.")
                else:
                    logger.info("✅ Pyannote loaded on CPU.")

            except Exception as e:
                self._load_error = f"pipeline_load_failed: {type(e).__name__}: {e}"[:500]
                logger.error(f"❌ Failed to load Pyannote: {e}")
                raise

    def diarize(self, audio_path: str) -> List[SpeakerSegment]:
        """
        Perform speaker diarization using Pyannote 3.1.

        Args:
            audio_path: Path to audio file

        Returns:
            List of SpeakerSegment with start_time, end_time, speaker_id
        """
        self._ensure_pipeline()

        logger.info(f"🎤 Pyannote Diarization: {audio_path}")

        # Build pipeline parameters
        params = {}
        if self.num_speakers is not None:
            params["num_speakers"] = self.num_speakers
        if self.min_speakers is not None:
            params["min_speakers"] = self.min_speakers
        if self.max_speakers is not None:
            params["max_speakers"] = self.max_speakers

        # Run diarization
        diarization = unwrap_diarization_annotation(self._pipeline(audio_path, **params))

        # Convert to SpeakerSegment format
        segments = []
        speaker_map = {}  # Map pyannote speaker labels to SPEAKER_X format
        speaker_counter = 1

        for turn, _, speaker in diarization.itertracks(yield_label=True):
            # Normalize speaker labels
            if speaker not in speaker_map:
                speaker_map[speaker] = f"SPEAKER_{speaker_counter}"
                speaker_counter += 1

            segments.append(SpeakerSegment(
                start_time=turn.start,
                end_time=turn.end,
                speaker_id=speaker_map[speaker]
            ))

        logger.info(f"✅ Pyannote Diarization complete: {len(segments)} segments ({len(speaker_map)} speakers)")

        return segments

    def provenance(self) -> dict:
        model_id, expected_revision, _required_files = compatible_model_spec()
        return {
            "provider": "pyannote",
            "model_id": self._model_id or model_id,
            "model_revision": self._model_revision or expected_revision,
            "artifact_root": str(PYANNOTE_MODEL_ROOT),
            "artifact_verified": self._artifact_verified,
            "required_files": required_artifact_files(),
            "load_error": self._load_error,
            "assignment_method": "segment_max_overlap",
        }

    def unload(self) -> None:
        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
        self._load_attempted = False
        self._load_error = None
        self._model_id = None
        self._model_revision = None
        self._artifact_verified = False
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
