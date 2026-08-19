"""
Transcription Service v2 - Refactored with Model Managers
Uses WhisperManager and PyannoteManager for better performance
"""
import time
from typing import Dict
from fastapi import HTTPException
from faster_whisper.audio import decode_audio
from faster_whisper.vad import VadOptions, get_speech_timestamps

from .models.whisper_manager import get_whisper_manager
from .models.pyannote_manager import get_pyannote_manager
from src.services.task_service import get_task, update_task
from src.database.models.models import AudioFile
from src.core.config import settings
from src.core.logging import logger
from src.services.audio_storage import compute_sha256, resolve_audio_path
from src.services.model_runtime import gpu_lease


SUPPORTED_DIARIZATION_METHODS = {"none", "pyannote"}
LEADING_GAP_RESCUE_MIN_SECONDS = 2.0
LEADING_GAP_RESCUE_MAX_SECONDS = 30.0
RESCUE_MIN_AVG_LOGPROB = -0.6
RESCUE_MAX_NO_SPEECH_PROBABILITY = 0.5
RESCUE_MAX_COMPRESSION_RATIO = 2.4
RESCUE_MIN_VAD_SPEECH_OVERLAP_RATIO = 0.5
WHISPER_SAMPLE_RATE = 16000
PRIMARY_VAD_PARAMETERS = {
    "threshold": 0.4,
    "min_speech_duration_ms": 200,
    "min_silence_duration_ms": 1500,
    "speech_pad_ms": 800,
}
RESCUE_VALIDATION_VAD_PARAMETERS = {
    **PRIMARY_VAD_PARAMETERS,
    "speech_pad_ms": 0,
}


def _normalize_diarization_method(enabled: bool, method: str) -> str:
    if not enabled:
        return "none"
    normalized = (method or "pyannote").strip().lower()
    if normalized not in SUPPORTED_DIARIZATION_METHODS:
        raise ValueError(f"Unsupported diarization method: {method}")
    return normalized


def _engine_failure_reason(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:500]


def _whisper_decode_profile(fast_mode: bool) -> tuple[str, dict]:
    common = {
        "compression_ratio_threshold": 2.4,
        "log_prob_threshold": -1.0,
        "vad_filter": True,
        "vad_parameters": dict(PRIMARY_VAD_PARAMETERS),
        "word_timestamps": True,
        "condition_on_previous_text": False,
    }
    if fast_mode:
        return "fast-v1", {
            **common,
            "beam_size": 1,
            "temperature": 0.0,
            "no_speech_threshold": 0.5,
        }
    return "investigation-accuracy-v1", {
        **common,
        "beam_size": min(5, max(1, int(settings.WHISPER_BEAM_SIZE))),
        "temperature": 0.0,
        "no_speech_threshold": 0.6,
        "hallucination_silence_threshold": 1.5,
    }


def _normalized_words(text: str) -> set[str]:
    return {token.casefold() for token in text.split() if token.strip()}


def _detect_speech_intervals(audio_path) -> list[tuple[float, float]]:
    audio = decode_audio(str(audio_path), sampling_rate=WHISPER_SAMPLE_RATE)
    chunks = get_speech_timestamps(
        audio,
        vad_options=VadOptions(**RESCUE_VALIDATION_VAD_PARAMETERS),
        sampling_rate=WHISPER_SAMPLE_RATE,
    )
    return [
        (
            float(chunk["start"]) / WHISPER_SAMPLE_RATE,
            float(chunk["end"]) / WHISPER_SAMPLE_RATE,
        )
        for chunk in chunks
    ]


def _speech_overlap_ratio(
    start: float,
    end: float,
    speech_intervals: list[tuple[float, float]],
) -> float:
    duration = max(0.0, end - start)
    if duration <= 0.0:
        return 0.0
    overlap = sum(
        max(0.0, min(end, speech_end) - max(start, speech_start))
        for speech_start, speech_end in speech_intervals
    )
    return min(1.0, overlap / duration)


def _recover_leading_gap(
    whisper_mgr,
    audio_path,
    language: str,
    primary_segments: list[dict],
) -> tuple[list[dict], dict]:
    if not primary_segments:
        return [], {"status": "skipped", "reason": "no_primary_anchor"}

    first_primary = min(primary_segments, key=lambda item: float(item["start"]))
    first_start = float(first_primary["start"])
    if first_start < LEADING_GAP_RESCUE_MIN_SECONDS:
        return [], {"status": "skipped", "reason": "no_material_leading_gap"}

    window_end = min(first_start, LEADING_GAP_RESCUE_MAX_SECONDS)
    try:
        speech_intervals = _detect_speech_intervals(audio_path)
    except Exception as error:
        logger.warning(
            "[TRANSCRIBE_V2] Leading-gap rescue withheld: speech validation failed | error=%s",
            type(error).__name__,
        )
        return [], {
            "status": "withheld",
            "reason": "speech_activity_validation_failed",
            "error_type": type(error).__name__,
        }
    rescue_iterator, _rescue_info = whisper_mgr.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        temperature=0.0,
        no_speech_threshold=0.5,
        compression_ratio_threshold=RESCUE_MAX_COMPRESSION_RATIO,
        log_prob_threshold=-1.0,
        vad_filter=False,
        word_timestamps=True,
        condition_on_previous_text=False,
        hallucination_silence_threshold=1.0,
        clip_timestamps=f"0,{window_end:.3f}",
    )

    accepted: list[dict] = []
    rejected: list[dict] = []
    primary_words = _normalized_words(str(first_primary.get("text") or ""))
    for segment in rescue_iterator:
        text = str(segment.text or "").strip()
        avg_logprob = float(getattr(segment, "avg_logprob", -99.0))
        no_speech_probability = float(getattr(segment, "no_speech_prob", 1.0))
        compression_ratio = float(getattr(segment, "compression_ratio", 99.0))
        candidate_start = max(0.0, float(segment.start))
        candidate_end = min(float(segment.end), first_start)
        vad_speech_overlap_ratio = _speech_overlap_ratio(
            candidate_start,
            candidate_end,
            speech_intervals,
        )
        reasons = []
        if not text:
            reasons.append("empty_text")
        if float(segment.start) >= first_start or float(segment.end) > first_start + 0.25:
            reasons.append("outside_leading_gap")
        if avg_logprob < RESCUE_MIN_AVG_LOGPROB:
            reasons.append("low_log_probability")
        if no_speech_probability > RESCUE_MAX_NO_SPEECH_PROBABILITY:
            reasons.append("high_no_speech_probability")
        if compression_ratio > RESCUE_MAX_COMPRESSION_RATIO:
            reasons.append("high_compression_ratio")
        if vad_speech_overlap_ratio < RESCUE_MIN_VAD_SPEECH_OVERLAP_RATIO:
            reasons.append("insufficient_vad_speech_overlap")
        rescue_words = _normalized_words(text)
        if rescue_words and primary_words and rescue_words <= primary_words:
            reasons.append("duplicates_primary_segment")
        if reasons:
            rejected.append(
                {
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "vad_speech_overlap_ratio": vad_speech_overlap_ratio,
                    "reasons": reasons,
                }
            )
            continue
        accepted.append(
            {
                "start": float(segment.start),
                "end": min(float(segment.end), first_start),
                "text": text,
                "speaker": None,
                "confidence": avg_logprob,
                "no_speech_probability": no_speech_probability,
                "compression_ratio": compression_ratio,
                "vad_speech_overlap_ratio": vad_speech_overlap_ratio,
                "transcription_source": "leading_gap_rescue",
            }
        )

    return accepted, {
        "status": "applied" if accepted else "rejected",
        "profile": "leading-gap-rescue-v1",
        "window_start": 0.0,
        "window_end": window_end,
        "first_primary_start": first_start,
        "accepted_segments": len(accepted),
        "rejected_segments": rejected,
    }


def _safe_unload_transcription_models() -> None:
    cleanup_steps = (
        ("pyannote", lambda: get_pyannote_manager().unload()),
        ("whisper", lambda: get_whisper_manager().unload()),
    )
    for model_name, cleanup in cleanup_steps:
        try:
            cleanup()
        except Exception:
            logger.warning(
                "[TRANSCRIBE_V2] %s model cleanup failed",
                model_name,
                exc_info=True,
            )
    try:
        from .cherry_transcription_service import unload_cherry_transcriber

        unload_cherry_transcriber()
    except Exception:
        logger.warning(
            "[TRANSCRIBE_V2] Cherry model cleanup failed",
            exc_info=True,
        )


def transcribe_audio_v2(
    task_id: str,
    db,
    enable_diarization: bool = True,
    diarization_method: str = "pyannote",
    language: str = "vi",
    fast_mode: bool = False,
) -> Dict:
    """Run every transcription caller under the host-wide GPU lease."""

    with gpu_lease("transcription", f"task:{task_id}"):
        try:
            return _transcribe_audio_v2_unlocked(
                task_id=task_id,
                db=db,
                enable_diarization=enable_diarization,
                diarization_method=diarization_method,
                language=language,
                fast_mode=fast_mode,
            )
        finally:
            if settings.UNLOAD_MODELS_AFTER_TASK:
                _safe_unload_transcription_models()


def _transcribe_audio_v2_unlocked(
    task_id: str,
    db,
    enable_diarization: bool = True,
    diarization_method: str = "pyannote",
    language: str = "vi",
    fast_mode: bool = False
) -> Dict:
    """
    Transcribe audio file using configured engine.
    Supports:
    - Cherry Core (Offline, Enhanced with PhoWhisper + Pyannote 4.0)
    - Original Stack (Faster-Whisper + Pyannote 3.1)
    """
    logger.info(
        f"[TRANSCRIBE_V2] Starting | task_id={task_id} | "
        f"diarization={enable_diarization} | method={diarization_method} | fast={fast_mode}"
    )

    start_time = time.time()
    diarization_method = _normalize_diarization_method(
        enable_diarization,
        diarization_method,
    )
    diarization_enabled = diarization_method == "pyannote"

    try:
        # Get task and audio file
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        audio_file = db.query(AudioFile).filter(AudioFile.task_id == task_id).first()
        if not audio_file:
            raise HTTPException(status_code=404, detail="Audio file not found")

        audio_path = resolve_audio_path(audio_file.file_path)
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path}")

        source_metadata = getattr(audio_file, "extra_metadata", None) or {}
        expected_sha256 = source_metadata.get("sha256")
        audio_sha256 = compute_sha256(audio_path)
        if expected_sha256 and audio_sha256 != expected_sha256:
            raise RuntimeError("Audio integrity verification failed")
        audio_integrity_status = "verified" if expected_sha256 else "unverified_legacy"

        # Update status to transcribing
        update_task(task_id, {"status": "transcribing"})
        audio_file.status = "transcribing"
        db.commit()

        requested_engine = settings.TRANSCRIPTION_ENGINE
        engine_used = None
        fallback_reason = None

        segments = []
        full_text_parts = []
        num_speakers = None
        diarization_time = 0
        has_diarization = False
        diarization_status = "unavailable" if diarization_enabled else "disabled"
        diarization_method_used = None
        diarization_fallback_reason = None
        speaker_provenance = {
            "provider": "pyannote" if diarization_enabled else "none",
            "method_requested": diarization_method,
            "method_used": None,
            "assignment_method": "none",
        }
        duration = 0
        info = None
        coverage_rescue = {"status": "not_applicable"}

        if requested_engine in {"cherry", "auto"}:
            try:
                from src.services.transcription.cherry_transcription_service import get_cherry_transcriber
                logger.info(
                    "[TRANSCRIBE_V2] Trying Cherry Core | requested_engine=%s",
                    requested_engine,
                )
                cherry_svc = get_cherry_transcriber()

                # Force Whisper V2 for all languages as requested by user
                model_type_sel = "whisper"

                # Use Cherry Transcriber
                cherry_result = cherry_svc.transcribe(
                    audio_path=str(audio_path),
                    language=language,
                    enable_diarization=diarization_enabled,
                    model_type=model_type_sel
                )

                # Adapt result to existing variables
                segments = cherry_result['segments']
                duration = cherry_result['duration']
                full_text_parts = [str(s.get('text', '')) for s in segments]

                num_speakers = cherry_result.get('num_speakers')
                diarization_time = cherry_result.get('diarization_time', 0.0)
                has_diarization = cherry_result.get('has_diarization', False)
                diarization_status = cherry_result.get(
                    'diarization_status',
                    "success" if has_diarization else diarization_status,
                )
                diarization_method_used = cherry_result.get('diarization_method_used')
                diarization_fallback_reason = cherry_result.get(
                    'diarization_fallback_reason'
                )
                speaker_provenance = cherry_result.get(
                    'speaker_provenance',
                    speaker_provenance,
                )

                # Set generic info object for logging compatibility
                class InfoStub:
                    def __init__(self, lang, dur):
                        self.language = lang
                        self.duration = dur
                info = InfoStub(language, duration)
                engine_used = "cherry"

            except Exception as error:
                if requested_engine == "cherry":
                    logger.error(
                        "[TRANSCRIBE_V2] Cherry mode failed; fallback is disabled",
                        exc_info=True,
                    )
                    raise RuntimeError("Cherry transcription engine failed") from error
                fallback_reason = _engine_failure_reason(error)
                logger.warning(
                    "[TRANSCRIBE_V2] Auto mode falling back to legacy | reason=%s",
                    fallback_reason,
                )

        if engine_used is None:
            # ORIGINAL LOGIC
            whisper_mgr = get_whisper_manager()
            logger.info(
                "[TRANSCRIBE_V2] Legacy Whisper manager ready | requested_engine=%s",
                requested_engine,
            )

            # Step 1: Transcribe with Whisper
            asr_profile, whisper_params = _whisper_decode_profile(fast_mode)
            whisper_params = {"language": language, **whisper_params}

            segments_iter, info = whisper_mgr.transcribe(str(audio_path), **whisper_params)
            provenance = getattr(whisper_mgr, "provenance", None)
            asr_provenance = provenance() if callable(provenance) else {
                "provider": "faster-whisper",
                "artifact_verified": False,
            }

            for segment in segments_iter:
                text = segment.text.strip()
                if not text:
                    continue
                seg_dict = {
                    'start': segment.start,
                    'end': segment.end,
                    'text': text,
                    'speaker': None,
                    'confidence': getattr(segment, 'avg_logprob', None),
                    'no_speech_probability': getattr(segment, 'no_speech_prob', None),
                    'compression_ratio': getattr(segment, 'compression_ratio', None),
                    'transcription_source': 'primary_vad',
                }
                segments.append(seg_dict)
                full_text_parts.append(text)

            rescue_segments, coverage_rescue = _recover_leading_gap(
                whisper_mgr,
                audio_path,
                language,
                segments,
            )
            if rescue_segments:
                segments = sorted(
                    [*rescue_segments, *segments],
                    key=lambda item: (float(item['start']), float(item['end'])),
                )
                full_text_parts = [str(item.get('text') or '') for item in segments]

            duration = info.duration

            # Step 2: Diarization (Legacy)
            if diarization_enabled:
                pyannote_mgr = get_pyannote_manager()
                if pyannote_mgr.is_available():
                    diar_start = time.time()
                    diarization = pyannote_mgr.diarize(str(audio_path))
                    diarization_time = time.time() - diar_start
                    speaker_provenance = pyannote_mgr.provenance()
                    if diarization is not None:
                        speaker_turns = list(diarization.itertracks(yield_label=True))
                        speakers_found = {speaker for _turn, _track, speaker in speaker_turns}
                        for seg in segments:
                            # Merge logic (simplified)
                            start, end = seg['start'], seg['end']
                            best_overlap, best_spk = 0, None
                            for turn, _, speaker in speaker_turns:
                                o_start = max(start, turn.start)
                                o_end = min(end, turn.end)
                                if o_end > o_start:
                                    duration_seconds = end - start
                                    ratio = (
                                        (o_end - o_start) / duration_seconds
                                        if duration_seconds > 0
                                        else 0
                                    )
                                    if ratio > best_overlap:
                                        best_overlap, best_spk = ratio, speaker
                            if best_spk and best_overlap > 0.3:
                                seg['speaker'] = best_spk
                        if speakers_found:
                            num_speakers = len(speakers_found)
                            has_diarization = True
                            diarization_status = "success"
                            diarization_method_used = "pyannote"
                        else:
                            diarization_status = "degraded"
                            diarization_fallback_reason = (
                                "pyannote_returned_no_speaker_turns"
                            )
                    else:
                        diarization_status = "failed"
                        diarization_fallback_reason = (
                            pyannote_mgr.provenance().get("load_error")
                            or "pyannote_diarization_failed"
                        )
                else:
                    speaker_provenance = pyannote_mgr.provenance()
                    diarization_status = "unavailable"
                    diarization_fallback_reason = (
                        speaker_provenance.get("load_error")
                        or "pyannote_pipeline_unavailable"
                    )
            engine_used = "legacy"

        # Step 3: Format output (Common)
        formatted_transcript = ""
        full_transcript = " ".join(full_text_parts)

        if has_diarization and num_speakers is not None and num_speakers > 1:
            for seg in segments:
                speaker_label = seg.get('speaker', 'Unknown')
                # Format time HH:MM:SS.mmm
                start_s = seg['start']
                end_s = seg['end']
                t_start = f"{int(start_s//3600):02d}:{int((start_s%3600)//60):02d}:{start_s%60:06.3f}"
                t_end = f"{int(end_s//3600):02d}:{int((end_s%3600)//60):02d}:{end_s%60:06.3f}"
                formatted_transcript += f"{t_start} --> {t_end} [{speaker_label}]\n{seg.get('text', '')}\n\n"
        else:
            formatted_transcript = full_transcript

        transcript_file = None

        # Calculate result
        total_time = time.time() - start_time
        speed_factor = duration / total_time if total_time > 0 else 0

        speaker_provenance = {
            **speaker_provenance,
            "status": diarization_status,
            "method_requested": diarization_method,
            "method_used": diarization_method_used,
            "speaker_count": num_speakers,
        }
        combined_fallback_reason = fallback_reason or diarization_fallback_reason
        diarization_degraded_reasons = (
            [diarization_fallback_reason]
            if diarization_fallback_reason is not None
            else []
        )

        response = {
            "task_id": task_id,
            "status": "transcribed",
            "transcript": full_transcript,
            "formatted_transcript": formatted_transcript,
            "segments": segments,
            "has_diarization": has_diarization,
            "num_speakers": num_speakers,
            "duration": duration,
            "processing_time": total_time,
            "transcription_time": total_time - diarization_time,
            "diarization_time": diarization_time,
            "speed_factor": speed_factor,
            "diarization_method": diarization_method,
            "diarization_method_used": diarization_method_used,
            "diarization_status": diarization_status,
            "diarization_fallback_reason": diarization_fallback_reason,
            "diarization_degraded_reasons": diarization_degraded_reasons,
            "speaker_provenance": speaker_provenance,
            "degraded": diarization_enabled and diarization_status != "success",
            "language": info.language if info else "vi",
            "transcript_file": transcript_file,
            "fast_mode": fast_mode,
            "requested_engine": requested_engine,
            "engine_requested": requested_engine,
            "engine_used": engine_used,
            "fallback_reason": combined_fallback_reason,
            "transcription_fallback_reason": fallback_reason,
            "audio_sha256": audio_sha256,
            "audio_integrity_status": audio_integrity_status,
            "asr_profile": asr_profile if engine_used == "legacy" else "cherry",
            "asr_parameters": whisper_params if engine_used == "legacy" else {},
            "asr_provenance": (
                asr_provenance if engine_used == "legacy" else {
                    "provider": "cherry",
                    "model_id": cherry_result.get("model_used") if "cherry_result" in locals() else None,
                }
            ),
            "coverage_rescue": coverage_rescue,
        }

        result_dict = response.copy()
        result_dict.update({
             "transcription": full_transcript,
             "summary": "",
             "context_analysis": {},
             "confidence": 1.0,
             "filename": audio_path.name
        })

        update_task(task_id, {
            "status": "transcribed",
            "result": result_dict,
            "transcript": full_transcript,
            "has_diarization": response["has_diarization"],
            "num_speakers": num_speakers,
            "duration": duration,
            "processing_time": total_time
        })

        audio_file.status = "transcribed"
        audio_file.duration = duration
        db.commit()

        logger.info(
            "[TRANSCRIBE_V2] Complete | task_id=%s | time=%.1fs | requested_engine=%s | engine_used=%s",
            task_id,
            total_time,
            requested_engine,
            engine_used,
        )
        return response

    except Exception as e:
        logger.error(f"[TRANSCRIBE_V2] Error: {e}", exc_info=True)
        try:
            failure_result = {}
            if "requested_engine" in locals():
                failure_result = {
                    "requested_engine": requested_engine,
                    "engine_requested": requested_engine,
                    "engine_used": engine_used,
                    "fallback_reason": fallback_reason,
                }
            update_task(
                task_id,
                {"status": "failed", "error": str(e), "result": failure_result},
            )
            if 'audio_file' in locals() and audio_file:
                audio_file.status = "failed"
                db.commit()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))
