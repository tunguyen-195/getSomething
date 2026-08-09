"""
Transcription Service v2 - Refactored with Model Managers
Uses WhisperManager and PyannoteManager for better performance
"""
import time
import logging
from pathlib import Path
from typing import Dict, Optional
from fastapi import HTTPException

from .models.whisper_manager import get_whisper_manager
from .models.pyannote_manager import get_pyannote_manager
from src.services.task_service import get_task, update_task
from src.database.models.models import AudioFile
from src.core.logging import logger
from src.services.audio_storage import resolve_audio_path


def transcribe_audio_v2(
    task_id: str,
    db,
    enable_diarization: bool = True,
    diarization_method: str = "pyannote",
    language: str = "vi",
    fast_mode: bool = True
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
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        audio_file = db.query(AudioFile).filter(AudioFile.task_id == task_id).first()
        if not audio_file:
            raise HTTPException(status_code=404, detail="Audio file not found")

        audio_path = resolve_audio_path(audio_file.file_path)
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path}")

        # Update status to transcribing
        update_task(task_id, {"status": "transcribing"})
        audio_file.status = "transcribing"
        db.commit()

        # CHERRY CORE INTEGRATION (Offline & Enhanced)
        # Use Cherry adapters if available
        USE_CHERRY_CORE = True # Enforced for this version

        segments = []
        full_text_parts = []
        num_speakers = 1
        diarization_time = 0
        duration = 0
        info = None

        if USE_CHERRY_CORE:
            try:
                from src.services.transcription.cherry_transcription_service import get_cherry_transcriber
                logger.info("[TRANSCRIBE_V2] Using Cherry Core Engine (Offline Mode)")
                cherry_svc = get_cherry_transcriber()

                # Force Whisper V2 for all languages as requested by user
                model_type_sel = "whisper"

                # Use Cherry Transcriber
                cherry_result = cherry_svc.transcribe(
                    audio_path=str(audio_path),
                    language=language,
                    enable_diarization=enable_diarization,
                    model_type=model_type_sel
                )

                # Adapt result to existing variables
                segments = cherry_result['segments']
                duration = cherry_result['duration']
                full_text_parts = [str(s.get('text', '')) for s in segments]

                num_speakers = cherry_result['num_speakers']
                diarization_time = cherry_result['diarization_time']

                # Set generic info object for logging compatibility
                class InfoStub:
                    def __init__(self, lang, dur):
                        self.language = lang
                        self.duration = dur
                info = InfoStub(language, duration)

            except ImportError as e:
                logger.error(f"[TRANSCRIBE_V2] Cherry Core import failed: {e}. Falling back to legacy.")
                USE_CHERRY_CORE = False
            except Exception as e:
                logger.error(f"[TRANSCRIBE_V2] Cherry Core execution failed: {e}. Falling back to legacy.")
                USE_CHERRY_CORE = False

        if not USE_CHERRY_CORE:
            # ORIGINAL LOGIC
            whisper_mgr = get_whisper_manager()
            logger.info("[TRANSCRIBE_V2] Legacy Whisper manager ready")

            # Step 1: Transcribe with Whisper
            whisper_params = {
                "language": language,
                "beam_size": 1,
                "temperature": 0.0,
                "compression_ratio_threshold": 2.4,
                "log_prob_threshold": -1.0,
                "no_speech_threshold": 0.5,
                "initial_prompt": "Tiếng Việt",
                "vad_filter": True,
                "vad_parameters": {
                    "threshold": 0.4,
                    "min_speech_duration_ms": 200,
                    "min_silence_duration_ms": 1500,
                    "speech_pad_ms": 800,
                },
                "word_timestamps": True,
                "condition_on_previous_text": False,
            }

            segments_iter, info = whisper_mgr.transcribe(str(audio_path), **whisper_params)

            # Filter logic (simplified for brevity, main anti-hallucination)
            prompt_texts = ["tiếng việt", "hãy chuyển đổi"]
            yt_patterns = ["subscribe", "đăng ký kênh", "thanks for watching"]

            for segment in segments_iter:
                text = segment.text.strip()
                text_lower = text.lower()
                is_valid = True

                # Filter prompts
                for p in prompt_texts:
                    if p in text_lower and len(text) < 50:
                        is_valid = False; break

                if is_valid:
                    # Filter YT
                    for yt in yt_patterns:
                        if yt in text_lower and len(text) < 100:
                             is_valid = False; break

                if is_valid:
                    seg_dict = {
                        'start': segment.start,
                        'end': segment.end,
                        'text': text,
                        'speaker': None,
                        'confidence': getattr(segment, 'avg_logprob', None)
                    }
                    segments.append(seg_dict)
                    full_text_parts.append(text)

            duration = info.duration

            # Step 2: Diarization (Legacy)
            if enable_diarization:
                pyannote_mgr = get_pyannote_manager()
                if pyannote_mgr.is_available():
                    diar_start = time.time()
                    diarization = pyannote_mgr.diarize(str(audio_path))
                    if diarization:
                        speakers_found = set()
                        for seg in segments:
                            # Merge logic (simplified)
                            start, end = seg['start'], seg['end']
                            best_overlap, best_spk = 0, None
                            for turn, _, speaker in diarization.itertracks(yield_label=True):
                                o_start = max(start, turn.start)
                                o_end = min(end, turn.end)
                                if o_end > o_start:
                                    ratio = (o_end - o_start) / (end - start)
                                    if ratio > best_overlap:
                                        best_overlap, best_spk = ratio, speaker
                            if best_spk and best_overlap > 0.3:
                                seg['speaker'] = best_spk
                                speakers_found.add(best_spk)
                        num_speakers = len(speakers_found)
                        diarization_time = time.time() - diar_start

        # Step 3: Format output (Common)
        formatted_transcript = ""
        full_transcript = " ".join(full_text_parts)

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
            "language": info.language if info else "vi",
            "transcript_file": transcript_file,
            "fast_mode": fast_mode
        }

        result_dict = response.copy()
        result_dict.update({
             "transcription": full_transcript,
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

        logger.info(f"[TRANSCRIBE_V2] Complete | task_id={task_id} | time={total_time:.1f}s")
        return response

    except Exception as e:
        logger.error(f"[TRANSCRIBE_V2] Error: {e}", exc_info=True)
        try:
            update_task(task_id, {"status": "failed", "error": str(e)})
            if 'audio_file' in locals() and audio_file:
                audio_file.status = "failed"
                db.commit()
        except:
            pass
        raise HTTPException(status_code=500, detail=str(e))
