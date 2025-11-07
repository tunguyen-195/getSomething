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


def transcribe_audio_v2(
    task_id: str,
    db,
    enable_diarization: bool = True,
    diarization_method: str = "pyannote",
    language: str = "vi",
    fast_mode: bool = True
) -> Dict:
    """
    Transcribe audio file with optional speaker diarization.
    Uses model managers for better performance and resource management.
    
    Args:
        task_id: Task ID
        db: Database session
        enable_diarization: Enable speaker diarization
        diarization_method: Method (pyannote, simple_vad, none)
        language: Language code (default: vi)
        fast_mode: Skip heavy post-processing
        
    Returns:
        dict with transcript, segments, speakers, duration, etc.
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
        
        audio_path = Path(audio_file.file_path)
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail=f"Audio file not found: {audio_path}")
        
        # Update status to transcribing
        update_task(task_id, {"status": "transcribing"})
        audio_file.status = "transcribing"
        db.commit()
        
        # Get Whisper manager (lazy loaded)
        whisper_mgr = get_whisper_manager()
        logger.info("[TRANSCRIBE_V2] Whisper manager ready")
        
        # Step 1: Transcribe with Whisper (Optimized for Vietnamese accuracy)
        logger.info(f"[TRANSCRIBE_V2] Transcribing audio: {audio_path.name}")
        segments_iter, info = whisper_mgr.transcribe(
            str(audio_path),
            language=language,
            beam_size=10,                     # Increased from 5 for better Vietnamese accuracy
            temperature=0.0,                  # Deterministic output (repeatable)
            best_of=5,                        # Generate 5 samples, pick best
            compression_ratio_threshold=2.4,  # Detect repetitions
            log_prob_threshold=-1.0,          # Filter low-confidence segments
            no_speech_threshold=0.6,          # Detect silence/non-speech
            initial_prompt="Đây là cuộc hội thoại bằng tiếng Việt.",  # Vietnamese context
            vad_filter=False,                 # Don't cut content
            word_timestamps=True              # Get word-level timing for better accuracy
        )
        
        # Collect segments
        segments = []
        full_text_parts = []
        
        for segment in segments_iter:
            seg_dict = {
                'start': segment.start,
                'end': segment.end,
                'text': segment.text.strip(),
                'speaker': None  # Will be filled by diarization
            }
            segments.append(seg_dict)
            full_text_parts.append(segment.text.strip())
        
        full_transcript = " ".join(full_text_parts)
        duration = info.duration
        
        logger.info(
            f"[TRANSCRIBE_V2] Whisper done | segments={len(segments)} | "
            f"duration={duration:.1f}s | language={info.language}"
        )
        
        # Step 2: Speaker Diarization (if enabled)
        num_speakers = 1
        diarization_time = 0
        
        if enable_diarization and diarization_method == "pyannote":
            pyannote_mgr = get_pyannote_manager()
            
            if pyannote_mgr.is_available():
                logger.info("[TRANSCRIBE_V2] Running Pyannote diarization...")
                diar_start = time.time()
                
                diarization = pyannote_mgr.diarize(str(audio_path))
                
                if diarization:
                    # Merge speaker labels with transcript segments
                    speakers_found = set()
                    
                    for seg in segments:
                        mid_time = (seg['start'] + seg['end']) / 2
                        
                        # Find speaker at this timestamp
                        for turn, _, speaker in diarization.itertracks(yield_label=True):
                            if turn.start <= mid_time <= turn.end:
                                seg['speaker'] = speaker
                                speakers_found.add(speaker)
                                break
                    
                    num_speakers = len(speakers_found)
                    diarization_time = time.time() - diar_start
                    
                    logger.info(
                        f"[TRANSCRIBE_V2] Diarization done | speakers={num_speakers} | "
                        f"time={diarization_time:.1f}s"
                    )
                else:
                    logger.warning("[TRANSCRIBE_V2] Diarization returned None")
            else:
                logger.warning("[TRANSCRIBE_V2] Pyannote not available, skipping diarization")
                enable_diarization = False
        
        # Step 3: Format output
        formatted_transcript = ""
        
        if enable_diarization and num_speakers > 1:
            # Format with speaker labels
            for seg in segments:
                speaker_label = seg.get('speaker', 'Unknown')
                time_start = f"{int(seg['start']//3600):02d}:{int((seg['start']%3600)//60):02d}:{seg['start']%60:06.3f}"
                time_end = f"{int(seg['end']//3600):02d}:{int((seg['end']%3600)//60):02d}:{seg['end']%60:06.3f}"
                formatted_transcript += f"{time_start} --> {time_end} [{speaker_label}]\n{seg['text']}\n\n"
        else:
            # Plain format
            for seg in segments:
                formatted_transcript += f"{seg['text']} "
            formatted_transcript = formatted_transcript.strip()
        
        # Save transcript to file
        transcript_file = str(audio_path).replace('.mp3', '_transcript.txt')
        transcript_file = transcript_file.replace('.wav', '_transcript.txt')
        transcript_file = transcript_file.replace('.m4a', '_transcript.txt')
        
        with open(transcript_file, 'w', encoding='utf-8') as f:
            f.write(formatted_transcript)
        
        logger.info(f"[TRANSCRIBE_V2] Saved transcript to {transcript_file}")
        
        # Calculate metrics
        total_time = time.time() - start_time
        speed_factor = duration / total_time if total_time > 0 else 0
        
        # Prepare response
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
            "language": info.language,
            "transcript_file": transcript_file,
            "fast_mode": fast_mode
        }
        
        # Update task with result
        update_task(task_id, {
            "status": "transcribed",
            "transcript": full_transcript,
            "has_diarization": enable_diarization and num_speakers > 1,
            "num_speakers": num_speakers,
            "duration": duration,
            "processing_time": total_time
        })
        
        # Update audio file
        audio_file.status = "transcribed"
        audio_file.duration = duration
        db.commit()
        
        logger.info(
            f"[TRANSCRIBE_V2] Complete | task_id={task_id} | "
            f"speakers={num_speakers} | total_time={total_time:.1f}s | "
            f"speed={speed_factor:.1f}x"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"[TRANSCRIBE_V2] Error: {e}", exc_info=True)
        
        # Update status to failed
        try:
            update_task(task_id, {"status": "failed", "error": str(e)})
            if audio_file:
                audio_file.status = "failed"
                db.commit()
        except:
            pass
        
        raise HTTPException(status_code=500, detail=str(e))
