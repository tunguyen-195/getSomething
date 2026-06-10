"""
Transcription Service v2 - Refactored with Model Managers
Uses WhisperManager and PyannoteManager for better performance
"""
import time
import logging
from pathlib import Path
from typing import Dict, Optional
from fastapi import HTTPException

from src.services.task_service import get_task, update_task
from src.database.models.models import AudioFile
from src.core.logging import logger
from src.services.audio_storage import resolve_audio_path
from src.core.config import settings
from src.services.transcription.asr_providers import transcribe_with_provider


def _speaker_set(segments: list[dict]) -> set[str]:
    return {
        str(seg.get("speaker"))
        for seg in segments
        if isinstance(seg, dict) and seg.get("speaker")
    }


def _assign_default_speakers(segments: list[dict]) -> set[str]:
    for seg in segments:
        if isinstance(seg, dict) and not seg.get("speaker"):
            seg["speaker"] = "SPEAKER_00"
    return _speaker_set(segments)


def _assign_speakers_from_diarization_segments(
    transcript_segments: list[dict],
    diarization_segments: list[dict],
    *,
    min_overlap_ratio: float = 0.3,
) -> set[str]:
    speakers_found: set[str] = set()
    for seg in transcript_segments:
        try:
            start = float(seg["start"])
            end = float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue

        best_overlap, best_spk = 0.0, None
        for dia_seg in diarization_segments:
            try:
                dia_start = float(dia_seg["start"])
                dia_end = float(dia_seg["end"])
            except (KeyError, TypeError, ValueError):
                continue
            o_start = max(start, dia_start)
            o_end = min(end, dia_end)
            if o_end <= o_start:
                continue
            ratio = (o_end - o_start) / (end - start) if end > start else 0.0
            if ratio > best_overlap:
                best_overlap = ratio
                best_spk = dia_seg.get("speaker")

        if best_spk and best_overlap > min_overlap_ratio:
            seg["speaker"] = str(best_spk)
            speakers_found.add(str(best_spk))
        elif seg.get("speaker"):
            speakers_found.add(str(seg["speaker"]))
    return speakers_found


def _run_simple_vad_diarization(
    transcript_segments: list[dict],
    audio_path: Path,
    *,
    num_speakers: int = 2,
) -> tuple[list[dict], set[str]]:
    from src.audio_processing.diarization.simple_vad import get_simple_diarizer

    diarizer = get_simple_diarizer(num_speakers=num_speakers)
    assigned = diarizer.assign_speakers_to_segments(transcript_segments, str(audio_path))
    return assigned, _speaker_set(assigned)


def _run_requested_diarization(
    *,
    segments: list[dict],
    audio_path: Path,
    requested_method: str,
    warnings: list[str],
) -> tuple[list[dict], bool, int, str, float]:
    method = (requested_method or "pyannote").strip().lower()
    if method not in {"pyannote", "simple_vad"}:
        warnings.append(f"diarization_method_unsupported:{method}")
        method = "pyannote"

    if not segments:
        warnings.append("diarization_no_transcript_segments")
        return segments, False, 1, "unavailable", 0.0

    elapsed = 0.0
    if method == "simple_vad":
        start = time.time()
        try:
            assigned, speakers = _run_simple_vad_diarization(segments, audio_path)
            elapsed += time.time() - start
            return assigned, bool(speakers), len(speakers) if speakers else 1, "simple_vad", elapsed
        except Exception as exc:
            elapsed += time.time() - start
            logger.warning("[DIARIZATION] SimpleVAD failed: %s", exc, exc_info=True)
            warnings.append(f"diarization_simple_vad_failed:{exc.__class__.__name__}")
            return segments, False, 1, "unavailable", elapsed

    start = time.time()
    try:
        from .models.pyannote_manager import get_pyannote_manager

        pyannote_mgr = get_pyannote_manager()
        if pyannote_mgr.is_available():
            diarization_segments = pyannote_mgr.diarize(str(audio_path))
            if diarization_segments:
                speakers = _assign_speakers_from_diarization_segments(segments, diarization_segments)
                elapsed += time.time() - start
                if speakers:
                    return segments, True, len(speakers), "pyannote", elapsed
                warnings.append("diarization_pyannote_no_overlap")
            else:
                warnings.append("diarization_pyannote_no_segments")
        else:
            warnings.append("diarization_pyannote_unavailable")
    except Exception as exc:
        logger.warning("[DIARIZATION] Pyannote failed: %s", exc, exc_info=True)
        warnings.append(f"diarization_pyannote_failed:{exc.__class__.__name__}")
    elapsed += time.time() - start

    fallback_start = time.time()
    try:
        assigned, speakers = _run_simple_vad_diarization(segments, audio_path)
        elapsed += time.time() - fallback_start
        if speakers:
            warnings.append("diarization_fallback_simple_vad")
            return assigned, True, len(speakers), "simple_vad_fallback", elapsed
    except Exception as exc:
        logger.warning("[DIARIZATION] SimpleVAD fallback failed: %s", exc, exc_info=True)
        warnings.append(f"diarization_fallback_failed:{exc.__class__.__name__}")
        elapsed += time.time() - fallback_start

    return segments, False, 1, "unavailable", elapsed


def _asr_reliability_report(
    segments: list[dict],
    *,
    warnings: list[str],
    model_info: dict,
) -> dict:
    avg_logprobs = []
    no_speech_probs = []
    for segment in segments:
        for key, target in (("avg_logprob", avg_logprobs), ("confidence", avg_logprobs)):
            value = segment.get(key)
            if value is None:
                continue
            try:
                target.append(float(value))
                break
            except (TypeError, ValueError):
                continue
        value = segment.get("no_speech_prob")
        if value is not None:
            try:
                no_speech_probs.append(float(value))
            except (TypeError, ValueError):
                pass

    mean_logprob = sum(avg_logprobs) / len(avg_logprobs) if avg_logprobs else None
    max_no_speech = max(no_speech_probs) if no_speech_probs else None
    guard = model_info.get("guard") if isinstance(model_info, dict) else {}
    removed_segments = int((guard or {}).get("removed_segments") or 0)
    review_required = bool(
        removed_segments
        or any(str(warning).startswith(("detected_language_unexpected", "asr_guard_removed_segments")) for warning in warnings)
        or (mean_logprob is not None and mean_logprob <= settings.ASR_GUARD_MIN_AVG_LOGPROB)
        or (max_no_speech is not None and max_no_speech >= settings.ASR_GUARD_MAX_NO_SPEECH_PROB)
    )
    return {
        "review_required": review_required,
        "mean_avg_logprob": mean_logprob,
        "max_no_speech_prob": max_no_speech,
        "removed_segments": removed_segments,
        "segment_count": len(segments),
        "reason": "asr_guard_or_low_confidence" if review_required else "ok",
    }


def transcribe_audio_v2(
    task_id: str,
    db,
    enable_diarization: bool = True,
    diarization_method: str = "pyannote",
    language: str = "vi",
    fast_mode: bool = True,
    asr_profile: str | None = None,
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

    try:
        # Get task and audio file
        task = get_task(task_id, db=db)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        audio_file = db.query(AudioFile).filter(AudioFile.task_id == task_id).first()
        if not audio_file:
            raise HTTPException(status_code=404, detail="Audio file not found")

        audio_path = resolve_audio_path(audio_file.file_path)
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path}")

        # Update status to transcribing
        update_task(task_id, {"status": "transcribing"}, db=db)
        audio_file.status = "transcribing"
        db.commit()

        segments = []
        diarization_time = 0
        asr_result = transcribe_with_provider(
            audio_path=str(audio_path),
            language=language,
            profile=asr_profile or settings.ASR_PROFILE,
            enable_diarization=enable_diarization,
            diarization_method=diarization_method,
            task_id=task_id,
        )
        segments = asr_result.get("segments", [])
        duration = float(asr_result.get("duration") or 0.0)
        language = asr_result.get("language") or language
        warnings = asr_result.get("warnings", [])
        model_info = asr_result.get("model_info", {})
        raw_segments = asr_result.get("raw_segments")
        if not isinstance(raw_segments, list) or not raw_segments:
            raw_segments = segments
        raw_transcript = str(
            asr_result.get("raw_text")
            or asr_result.get("raw_transcription")
            or ""
        ).strip()
        filtered_transcript = str(
            asr_result.get("filtered_text")
            or asr_result.get("filtered_transcription")
            or asr_result.get("text")
            or ""
        ).strip()
        hallucination_report = (
            asr_result.get("hallucination_report")
            or asr_result.get("phoguard")
            or (model_info.get("guard") if isinstance(model_info, dict) else {})
            or {}
        )
        if not raw_transcript:
            raw_transcript = " ".join(
                str(seg.get("text", "")).strip()
                for seg in raw_segments
                if str(seg.get("text", "")).strip()
            ).strip()
        if not filtered_transcript:
            filtered_transcript = " ".join(
                str(seg.get("text", "")).strip()
                for seg in segments
                if str(seg.get("text", "")).strip()
            ).strip()
        asr_reliability = _asr_reliability_report(
            segments,
            warnings=warnings,
            model_info=model_info,
        )
        speakers_found = _speaker_set(segments)
        diarization_used = bool(enable_diarization and speakers_found)
        effective_diarization_method = diarization_method if enable_diarization else "none"
        num_speakers = len(speakers_found) if speakers_found else 1

        if enable_diarization and diarization_method != "none" and not diarization_used:
            (
                segments,
                diarization_used,
                num_speakers,
                effective_diarization_method,
                extra_diarization_time,
            ) = _run_requested_diarization(
                segments=segments,
                audio_path=audio_path,
                requested_method=diarization_method,
                warnings=warnings,
            )
            diarization_time += extra_diarization_time

        if enable_diarization and diarization_used and not _speaker_set(segments):
            speakers_found = _assign_default_speakers(segments)
            num_speakers = len(speakers_found) if speakers_found else 1
        elif diarization_used:
            speakers_found = _speaker_set(segments)
            num_speakers = len(speakers_found) if speakers_found else 1

        # Step 3: Format output (Common)
        formatted_transcript = ""
        full_transcript = filtered_transcript or asr_result.get("text") or " ".join(
            str(seg.get("text", "")).strip() for seg in segments if str(seg.get("text", "")).strip()
        )

        if diarization_used:
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

        response = {
            "task_id": task_id,
            "status": "transcribed",
            "transcript": full_transcript,
            "formatted_transcript": formatted_transcript,
            "segments": segments,
            "raw_segments": raw_segments,
            "has_diarization": bool(enable_diarization and diarization_used),
            "num_speakers": num_speakers,
            "duration": duration,
            "processing_time": total_time,
            "transcription_time": total_time - diarization_time,
            "diarization_time": diarization_time,
            "speed_factor": speed_factor,
            "diarization_method": effective_diarization_method if enable_diarization else "none",
            "language": language,
            "transcript_file": transcript_file,
            "fast_mode": fast_mode,
            "asr_provider": asr_result.get("provider"),
            "asr_profile": asr_profile or settings.ASR_PROFILE,
            "model_info": model_info,
            "warnings": warnings,
            "phoguard": hallucination_report,
            "hallucination_report": hallucination_report,
            "asr_reliability": asr_reliability,
            "raw_transcription": raw_transcript,
            "review_transcription": raw_transcript,
            "filtered_transcription": full_transcript,
        }

        result_dict = response.copy()
        result_dict.update({
             "transcription": full_transcript,
             "summary": "",
             "context_analysis": {},
             "confidence": 0.5 if asr_reliability["review_required"] else 1.0,
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
        }, db=db)

        audio_file.status = "transcribed"
        audio_file.duration = duration
        db.commit()

        logger.info(f"[TRANSCRIBE_V2] Complete | task_id={task_id} | time={total_time:.1f}s")
        return response

    except Exception as e:
        logger.error(f"[TRANSCRIBE_V2] Error: {e}", exc_info=True)
        try:
            update_task(task_id, {"status": "failed", "error": str(e)}, db=db)
            if 'audio_file' in locals() and audio_file:
                audio_file.status = "failed"
                db.commit()
        except:
            pass
        raise HTTPException(status_code=500, detail=str(e))
