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
        asr_reliability = _asr_reliability_report(
            segments,
            warnings=warnings,
            model_info=model_info,
        )
        num_speakers = 1

        speakers_found = {seg.get("speaker") for seg in segments if seg.get("speaker")}
        if speakers_found:
            num_speakers = len(speakers_found)

        if enable_diarization and num_speakers <= 1 and diarization_method != "none":
            from .models.pyannote_manager import get_pyannote_manager

            pyannote_mgr = get_pyannote_manager()
            if pyannote_mgr.is_available():
                diar_start = time.time()
                diarization_segments = pyannote_mgr.diarize(str(audio_path))
                if diarization_segments:
                    speakers_found = set()
                    for seg in segments:
                        start, end = seg['start'], seg['end']
                        best_overlap, best_spk = 0, None
                        for dia_seg in diarization_segments:
                            o_start = max(start, dia_seg["start"])
                            o_end = min(end, dia_seg["end"])
                            if o_end > o_start:
                                ratio = (o_end - o_start) / (end - start) if end > start else 0
                                if ratio > best_overlap:
                                    best_overlap, best_spk = ratio, dia_seg["speaker"]
                        if best_spk and best_overlap > 0.3:
                            seg['speaker'] = best_spk
                            speakers_found.add(best_spk)
                    num_speakers = len(speakers_found) if speakers_found else 1
                    diarization_time = time.time() - diar_start

        # Step 3: Format output (Common)
        formatted_transcript = ""
        full_transcript = asr_result.get("text") or " ".join(
            str(seg.get("text", "")).strip() for seg in segments if str(seg.get("text", "")).strip()
        )

        if enable_diarization and num_speakers > 1:
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
            "has_diarization": enable_diarization and num_speakers > 1,
            "num_speakers": num_speakers,
            "duration": duration,
            "processing_time": total_time,
            "transcription_time": total_time - diarization_time,
            "diarization_time": diarization_time,
            "speed_factor": speed_factor,
            "diarization_method": diarization_method if enable_diarization else "none",
            "language": language,
            "transcript_file": transcript_file,
            "fast_mode": fast_mode,
            "asr_provider": asr_result.get("provider"),
            "asr_profile": asr_profile or settings.ASR_PROFILE,
            "model_info": model_info,
            "warnings": warnings,
            "phoguard": model_info.get("guard") if isinstance(model_info, dict) else {},
            "asr_reliability": asr_reliability,
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
