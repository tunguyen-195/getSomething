"""
Transcription Service - Separate from summarization
Handles audio transcription with optional speaker diarization
"""
from src.core.logging import logger
from src.speech_to_text.transcriber import Transcriber
from src.services.task_service import get_task, update_task
from src.database.models.models import AudioFile
from fastapi import HTTPException
from src.services.audio_storage import resolve_audio_path


def transcribe_audio(
    task_id: str,
    db,
    enable_diarization: bool = True,
    diarization_method: str = "pyannote",
    fast_mode: bool = True
) -> dict:
    """
    Transcribe audio file with optional speaker diarization.
    This is a SEPARATE step from summarization.

    Args:
        task_id: Task ID
        db: Database session
        enable_diarization: Enable speaker diarization
        diarization_method: Method for diarization (pyannote, simple_vad, none)
        fast_mode: Skip heavy post-processing for faster results

    Returns:
        dict with transcript, segments, speakers, duration, etc.
    """
    logger.info(
        f"[TRANSCRIBE_SERVICE] Starting transcription | "
        f"task_id={task_id} | diarization={enable_diarization} | "
        f"method={diarization_method} | fast_mode={fast_mode}"
    )

    try:
        # Get task and audio file
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        audio_file = db.query(AudioFile).filter(AudioFile.task_id == task_id).first()
        if not audio_file:
            raise HTTPException(status_code=404, detail="Audio file not found")

        # Check if file exists
        audio_path = resolve_audio_path(audio_file.file_path)
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path}")

        # Update status to transcribing
        update_task(task_id, {"status": "transcribing"})
        audio_file.status = "transcribing"
        db.commit()

        # Initialize transcriber
        transcriber = Transcriber()

        # Transcribe with or without diarization
        if enable_diarization and diarization_method != "none":
            logger.info(f"[TRANSCRIBE_SERVICE] Using diarization method: {diarization_method}")
            result = transcriber.transcribe_with_diarization(
                str(audio_path),
                fast_mode=fast_mode,
                enable_diarization=True
            )

            transcript_file = None

        else:
            logger.info("[TRANSCRIBE_SERVICE] Transcribing without diarization")
            result = transcriber.transcribe(str(audio_path), fast_mode=fast_mode)

            transcript_file = None

        # Extract results
        transcript = result.get('transcription', '') or result.get('transcript', '')
        segments = result.get('segments', [])
        num_speakers = result.get('num_speakers', 1 if not enable_diarization else len(set(seg.get('speaker') for seg in segments if seg.get('speaker'))))
        duration = result.get('duration', 0)
        processing_time = result.get('processing_time', 0)
        speed_factor = result.get('speed_factor', 0)

        # Prepare response
        response = {
            "task_id": task_id,
            "status": "transcribed",
            "transcript": transcript,
            "segments": segments if enable_diarization else [],
            "has_diarization": enable_diarization,
            "num_speakers": num_speakers,
            "duration": duration,
            "processing_time": processing_time,
            "speed_factor": speed_factor,
            "diarization_method": diarization_method if enable_diarization else "none",
            "fast_mode": fast_mode,
            "transcript_file": transcript_file
        }

        # Update task with transcription result
        update_task(task_id, {
            "status": "transcribed",
            "transcript": transcript,
            "has_diarization": enable_diarization,
            "num_speakers": num_speakers,
            "duration": duration,
            "processing_time": processing_time
        })

        # Update audio file
        audio_file.status = "transcribed"
        audio_file.duration = duration
        db.commit()

        logger.info(
            f"[TRANSCRIBE_SERVICE] Completed | task_id={task_id} | "
            f"speakers={num_speakers} | duration={duration:.1f}s | "
            f"processing_time={processing_time:.1f}s"
        )

        return response

    except Exception as e:
        logger.error(f"[TRANSCRIBE_SERVICE] Error: {e}", exc_info=True)

        # Update status to failed
        try:
            update_task(task_id, {"status": "failed", "error": str(e)})
            audio_file = db.query(AudioFile).filter(AudioFile.task_id == task_id).first()
            if audio_file:
                audio_file.status = "failed"
                db.commit()
        except:
            pass

        raise HTTPException(status_code=500, detail=str(e))
