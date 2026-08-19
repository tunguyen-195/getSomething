"""
Cherry Transcription Service
Integrates Cherry Core ASR and Diarization into SpeechToInformation.
"""
import logging
import time
from pathlib import Path
from typing import Dict, List
from src.cherry_core.domain.entities import Transcript, SpeakerSegment

logger = logging.getLogger(__name__)


class CherryTranscriberService:
    def __init__(self):
        from src.cherry_core.adapters.asr.hallucination_filter import HallucinationFilter  # noqa: F401
        from src.cherry_core.adapters.asr.phowhisper_adapter import PhoWhisperAdapter
        from src.cherry_core.adapters.asr.whisperv2_adapter import WhisperV2Adapter
        from src.cherry_core.adapters.diarization.pyannote_adapter import PyannoteAdapter

        # Initialize adapters
        # VAD disabled to preserve beginning of audio (was cutting initial speech)
        # See implementation_plan.md for rationale
        self.whisper_adapter = WhisperV2Adapter(use_vad=False)
        self.phowhisper_adapter = PhoWhisperAdapter()
        self.diarizer = PyannoteAdapter()

    def transcribe(
        self,
        audio_path: str,
        language: str = "vi",
        enable_diarization: bool = True,
        model_type: str = "whisper" # 'whisper' or 'phowhisper'
    ) -> Dict:
        """
        Transcribe audio using Cherry Core adapters.
        Returns a dictionary compatible with the existing system.
        """
        start_time = time.time()
        audio_path_obj = Path(audio_path)

        logger.info(f"[CHERRY_TRANSCRIBE] Starting {audio_path_obj.name} | lang={language} | dia={enable_diarization} | model={model_type}")

        # 1. ASR
        if model_type == "phowhisper" and language == "vi":
            logger.info("[CHERRY_TRANSCRIBE] Using PhoWhisper Adapter (SOTA Vietnamese)")
            transcript_entity = self.phowhisper_adapter.transcribe(str(audio_path))
        else:
            logger.info("[CHERRY_TRANSCRIBE] Using WhisperV2 Adapter")
            transcript_entity = self.whisper_adapter.transcribe(str(audio_path))

        logger.info(f"[CHERRY_TRANSCRIBE] ASR complete. Text length: {len(transcript_entity.text)}")

        # 2. Diarization
        num_speakers = None
        diarization_time = 0
        has_diarization = False
        diarization_status = "disabled"
        diarization_fallback_reason = None
        speaker_provenance = {
            "provider": "none",
            "assignment_method": "none",
        }

        if enable_diarization:
            diarization_status = "unavailable"
            dia_start = time.time()
            try:
                segments = self.diarizer.diarize(str(audio_path))

                # Merge logic
                # Enhance transcript segments with speaker based on overlap
                self._merge_speakers(transcript_entity, segments)

                speakers_found = {segment.speaker_id for segment in segments}
                diarization_time = time.time() - dia_start
                speaker_provenance = self.diarizer.provenance()
                if speakers_found:
                    num_speakers = len(speakers_found)
                    has_diarization = True
                    diarization_status = "success"
                    logger.info(
                        "[CHERRY_TRANSCRIBE] Diarization complete. Speakers: %s",
                        num_speakers,
                    )
                else:
                    diarization_status = "degraded"
                    diarization_fallback_reason = "pyannote_returned_no_speaker_turns"
                    logger.warning("[CHERRY_TRANSCRIBE] Pyannote returned no speaker turns")

            except Exception as e:
                logger.error(f"[CHERRY_TRANSCRIBE] Diarization failed: {e}")
                diarization_time = time.time() - dia_start
                diarization_fallback_reason = f"{type(e).__name__}: {e}"[:500]
                provenance = getattr(self.diarizer, "provenance", None)
                if callable(provenance):
                    speaker_provenance = provenance()
                speaker_provenance["load_error"] = diarization_fallback_reason
                if not isinstance(e, FileNotFoundError) and speaker_provenance.get(
                    "artifact_verified"
                ):
                    diarization_status = "failed"

        # 3. Format Output compatible with existing system
        # Existing system expects segments to be list of dicts: {'start', 'end', 'text', 'speaker', ...}
        # Transcript.segments from adapters is already List[Dict] usually, need to verify

        # Check adapters output.
        # WhisperV2Adapter returns segments as list of dicts.
        # PhoWhisperAdapter returns segments as list of dicts.

        result_segments = transcript_entity.segments

        # Hallucination filtering post-processing (optional, if not already done by adapter)
        # Note: WhisperV2Adapter already does some filtering.

        total_time = time.time() - start_time

        return {
            "transcript": transcript_entity.text,
            "segments": result_segments,
            "num_speakers": num_speakers,
            "language": language,
            "duration": self._estim_duration(result_segments), # Estimate if not provided
            "processing_time": total_time,
            "diarization_time": diarization_time,
            "model_used": model_type,
            "has_diarization": has_diarization,
            "diarization_status": diarization_status,
            "diarization_method_used": "pyannote" if has_diarization else None,
            "diarization_fallback_reason": diarization_fallback_reason,
            "degraded": enable_diarization and diarization_status != "success",
            "speaker_provenance": speaker_provenance,
        }

    def _merge_speakers(self, transcript: Transcript, diarization_segments: List[SpeakerSegment]):
        """
        Merge diarization segments into transcript segments.
        Overlap logic similar to existing usage.
        """
        for t_seg in transcript.segments:
            t_start = t_seg['start']
            t_end = t_seg['end']
            t_dur = t_end - t_start

            best_speaker = None
            best_overlap = 0.0

            for d_seg in diarization_segments:
                # Calc overlap
                overlap_start = max(t_start, d_seg.start_time)
                overlap_end = min(t_end, d_seg.end_time)

                if overlap_end > overlap_start:
                    overlap_dur = overlap_end - overlap_start
                    ratio = overlap_dur / t_dur if t_dur > 0 else 0

                    if ratio > best_overlap:
                        best_overlap = ratio
                        best_speaker = d_seg.speaker_id

            if best_speaker and best_overlap > 0.3:  # Threshold
                t_seg['speaker'] = best_speaker

    def _estim_duration(self, segments):
        if not segments:
            return 0.0
        return segments[-1]['end']

    def unload(self) -> None:
        """Release every optional Cherry model before another GPU stage."""

        for adapter in (
            self.whisper_adapter,
            self.phowhisper_adapter,
            self.diarizer,
        ):
            unload = getattr(adapter, "unload", None)
            if callable(unload):
                unload()


# Singleton access
_service = None


def get_cherry_transcriber():
    global _service
    if _service is None:
        _service = CherryTranscriberService()
    return _service


def unload_cherry_transcriber() -> None:
    """Unload an existing singleton without instantiating a new service."""

    global _service
    if _service is not None:
        _service.unload()
