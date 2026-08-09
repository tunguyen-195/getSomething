"""Audio API v2 - Modular"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Depends, Form, Query
from typing import Dict, Any
from src.core.logging import logger
from src.database.config.database import get_db
from sqlalchemy.orm import Session
from src.services.audio_service import save_audio_and_create_task
from src.core.auth import assert_case_access, assert_task_access, check_rate_limit, get_current_user
from src.core.config import settings
from src.database.models.models import AudioFile, User
from src.core.time import LEGACY_DATABASE_TIMEZONE, utc_isoformat
from src.services.task_service import (
    effective_task_status,
    extract_active_visualization_payload,
    extract_visualization_payload,
    released_investigation_run_identity,
)

router = APIRouter()

@router.post("/upload")
async def upload_audio_v2(
    file: UploadFile = File(...),
    case_id: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        logger.info("[API_V2] Upload audio")
        if case_id:
            assert_case_access(db, current_user, int(case_id), "write")
        check_rate_limit(f"rl:upload:{current_user.id}", settings.UPLOAD_RATE_LIMIT_PER_HOUR, 3600)
        result = save_audio_and_create_task(
            file,
            db,
            case_id=int(case_id) if case_id else None,
            user_id=current_user.id,
        )
        audio_file = db.query(AudioFile).filter(AudioFile.id == result.get("audio_id")).first()
        if audio_file:
            result.update(
                created_at=utc_isoformat(
                    audio_file.created_at,
                    naive_timezone=LEGACY_DATABASE_TIMEZONE,
                ),
                uploaded_at=utc_isoformat(
                    audio_file.uploaded_at,
                    naive_timezone=LEGACY_DATABASE_TIMEZONE,
                ),
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_V2] Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/transcribe/{task_id}")
async def transcribe_v2(task_id: str, enable_diarization: bool = Body(True), diarization_method: str = Body("pyannote"), language: str = Body("vi"), fast_mode: bool = Body(True), async_mode: bool = Body(True), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        from src.services.task_service import get_task, update_task
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
        if async_mode:
            from src.worker.tasks.transcribe_task import transcribe_audio_task
            celery_task = transcribe_audio_task.delay(task_id, enable_diarization, diarization_method, language, fast_mode)
            update_task(task_id, {"status": "transcribing"})
            return {"task_id": task_id, "celery_task_id": celery_task.id, "status": "transcribing"}
        else:
            from src.services.transcription.transcribe_service_v2 import transcribe_audio_v2
            return transcribe_audio_v2(task_id, db, enable_diarization, diarization_method, language, fast_mode)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_V2] Transcribe error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/summarize/{task_id}")
async def summarize_v2(task_id: str, model_name: str = Body(None), summary_type: str = Body("detailed"), include_context: bool = Body(True), async_mode: bool = Body(True), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        from src.services.task_service import get_task, update_task
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)

        # Get transcript from task result (standardized to "transcription")
        transcript = None
        if task.get("result") and isinstance(task["result"], dict):
            # Transcript is stored in result["transcription"] (TaskResult schema)
            transcript = task["result"].get("transcription")

        if not transcript or not transcript.strip():
            logger.warning(f"[API_V2] No transcription found for task {task_id}. Task result keys: {list(task.get('result', {}).keys()) if task.get('result') else 'No result'}")
            raise HTTPException(status_code=400, detail="No transcription found. Please transcribe the audio first.")

        logger.info(f"[API_V2] Summarize | task_id={task_id} | transcript_length={len(transcript)} | model={model_name}")

        if async_mode:
            from src.worker.tasks.summarize_task import summarize_transcript_task
            celery_task = summarize_transcript_task.delay(task_id, model_name, summary_type, include_context, None)
            update_task(task_id, {"status": "summarizing"})
            return {"task_id": task_id, "status": "summarizing", "celery_task_id": celery_task.id}
        else:
            from src.services.summarization.summary_service_v2 import summarize_transcript_v2
            result = summarize_transcript_v2(transcript, model_name, summary_type, include_context)
            update_task(task_id, {"status": "summarized", "summary": result["summary"]})
            return {"task_id": task_id, "status": "summarized", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_V2] Summarize error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tasks/{task_id}/status")
async def get_status_v2(
    task_id: str,
    include_result: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get task status with full data from task.result.
    Used for polling after async operations (transcribe, summarize).
    """
    try:
        from src.services.task_service import get_task

        authorized_task = assert_task_access(db, current_user, task_id, "read")
        audio = (
            db.query(AudioFile)
            .filter(AudioFile.task_id == task_id)
            .order_by(AudioFile.id.asc())
            .first()
        )
        if not include_result:
            audio_id = audio.id if audio else None
            return {
                "task_id": task_id,
                "audio_id": audio_id,
                "download_url": f"/api/v1/audio/{audio_id}/download" if audio_id else None,
                "status": effective_task_status(
                    authorized_task.status,
                    audio.status if audio else None,
                ),
                "error": authorized_task.error,
                "filename": authorized_task.filename,
                "created_at": authorized_task.created_at,
                "updated_at": authorized_task.updated_at,
                "uploaded_at": utc_isoformat(
                    audio.uploaded_at,
                    naive_timezone=LEGACY_DATABASE_TIMEZONE,
                ) if audio else None,
            }

        task = get_task(task_id, db=db)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # Extract result data (handle both dict and string JSON)
        result_data = task.get("result", {})
        if isinstance(result_data, str):
            import json
            try:
                result_data = json.loads(result_data)
            except:
                result_data = {}

        if isinstance(result_data, dict):
            result_data = dict(result_data)
            visualization_data = extract_active_visualization_payload(result_data)
            result_data["visualization_data"] = visualization_data
            result_data["has_visualization"] = bool(visualization_data)

        # Get transcript from task result (standardized to "transcription")
        transcript = None
        if isinstance(result_data, dict):
            transcript = result_data.get("transcription")

        # Get summary from task result or direct field
        summary = None
        if isinstance(result_data, dict):
            summary = result_data.get("summary")
        if not summary:
            summary = task.get("summary")

        # Get other fields from result
        num_speakers = None
        duration = None
        has_diarization = False
        formatted_transcript = None
        segments = []
        context_analysis = {}
        visualization_data = None
        has_visualization = False
        audio_id = None
        download_url = None
        requested_engine = None
        engine_used = None
        fallback_reason = None

        if isinstance(result_data, dict):
            num_speakers = result_data.get("num_speakers")
            duration = result_data.get("duration")
            has_diarization = result_data.get("has_diarization", False)
            formatted_transcript = result_data.get("formatted_transcript")
            segments = result_data.get("segments", [])
            context_analysis = result_data.get("context_analysis", {})
            visualization_data = result_data.get("visualization_data")
            has_visualization = bool(visualization_data)
            audio_id = result_data.get("audio_id") or (audio.id if audio else None)
            download_url = result_data.get("download_url")
            requested_engine = result_data.get("requested_engine")
            engine_used = result_data.get("engine_used")
            fallback_reason = result_data.get("fallback_reason")

        response_status = task.get("status")
        if response_status == "visualized" and not has_visualization:
            response_status = (
                "summarized"
                if summary
                else "transcribed"
                if transcript
                else "uploaded"
            )

        # Build comprehensive response
        response = {
            "task_id": task_id,
            "audio_id": audio_id,
            "download_url": download_url,
            "status": response_status,
            "transcript": transcript,
            "summary": summary,
            "num_speakers": num_speakers,
            "duration": duration,
            "has_diarization": has_diarization,
            "has_visualization": has_visualization,
            "visualization_data": visualization_data,
            "error": task.get("error"),
            "filename": task.get("filename"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "uploaded_at": utc_isoformat(
                audio.uploaded_at,
                naive_timezone=LEGACY_DATABASE_TIMEZONE,
            ) if audio else None,
            "requested_engine": requested_engine,
            "engine_used": engine_used,
            "fallback_reason": fallback_reason,
        }

        # Add optional fields if available
        if formatted_transcript:
            response["formatted_transcript"] = formatted_transcript
        if segments:
            response["segments"] = segments
        if context_analysis:
            response["context_analysis"] = context_analysis

        # Include full result for backward compatibility
        response["result"] = result_data

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_V2] Get status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/visualize/{task_id}")
async def visualize_v2(
    task_id: str,
    visualization_type: str = Body("all", embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        from src.services.task_service import get_task
        from src.services.visualization_service import (
            VisualizationProjectionError,
            generate_visualization,
        )

        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)

        task_result = task.get("result") if isinstance(task.get("result"), dict) else {}
        released_run = task_result.get("released_investigation_run")
        active_identity = released_investigation_run_identity(released_run)
        try:
            result = generate_visualization(released_run, visualization_type)
        except VisualizationProjectionError as exc:
            status_code = 409 if exc.code == "VISUALIZATION_RELEASED_RUN_REQUIRED" else 412
            raise HTTPException(
                status_code=status_code,
                detail={"code": exc.code, "message": str(exc), "task_id": task_id},
            ) from exc
        payload = (
            extract_visualization_payload(
                result,
                expected_run_id=active_identity[0],
                expected_source_revision_id=active_identity[1],
                expected_release_subject_sha256=active_identity[2],
            )
            if active_identity is not None
            else None
        )
        if payload is None:
            raise HTTPException(
                status_code=412,
                detail={
                    "code": "VISUALIZATION_ACTIVE_RUN_MISMATCH",
                    "message": "Visualization does not match the active released run.",
                    "task_id": task_id,
                },
            )

        return {
            "task_id": task_id,
            "status": "visualization_ready",
            "visualization_data": payload,
            "has_visualization": True,
            "result": result,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_V2] Visualize error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
