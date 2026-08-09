"""Audio API v2 - Modular"""
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Depends, Form, Query
from typing import Any, Dict
from src.core.logging import logger
from src.database.config.database import get_db
from sqlalchemy.orm import Session
from src.services.audio_service import save_audio_and_create_task
from src.core.auth import assert_case_access, assert_task_access, check_rate_limit, get_current_user
from src.core.config import settings
from src.database.models.models import AudioFile, User
from src.core.time import LEGACY_DATABASE_TIMEZONE, utc_isoformat
from src.services.task_service import (
    SummaryResultRejected,
    SummaryTransitionResult,
    begin_summary_attempt,
    build_summary_attempt_binding,
    build_summary_result_patch,
    effective_task_status,
    extract_active_visualization_payload,
    extract_visualization_payload,
    fail_summary_attempt,
    released_investigation_run_identity,
    safe_summary_message,
    succeed_summary_attempt,
    validate_summary_service_result,
)
from src.services.summarization.contracts import (
    DEFAULT_SUMMARY_MAX_WORDS,
    DEFAULT_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_TYPE,
    SummaryRequestContractError,
    SummaryType,
    validate_summary_request_options,
)

router = APIRouter()

_SUMMARY_RESPONSE_FIELDS = frozenset(
    {
        "available",
        "summary",
        "context",
        "model",
        "requested_model",
        "summary_type",
        "release",
        "runtime",
        "error",
        "num_transcripts",
        "case_id",
    }
)


def _summary_response_result(result: dict[str, Any]) -> dict[str, Any]:
    """Expose summary-owned fields without replaying visualization projections."""

    return {
        key: value
        for key, value in result.items()
        if key in _SUMMARY_RESPONSE_FIELDS
    }


def _summary_http_error(code: str, *, task_id: str, status_code: int = 502) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": safe_summary_message(code),
            "task_id": task_id,
        },
    )


def _begin_summary_transition(
    task_id: str,
    attempt_id: str,
    *,
    request_fingerprint: str,
    source_revision_id: str,
    stage: str,
) -> SummaryTransitionResult:
    return begin_summary_attempt(
        task_id,
        attempt_id,
        request_fingerprint=request_fingerprint,
        source_revision_id=source_revision_id,
        stage=stage,
    )


def _persist_summary_success(
    task_id: str,
    attempt_id: str,
    result_patch: dict[str, Any],
) -> SummaryTransitionResult:
    return succeed_summary_attempt(task_id, attempt_id, result_patch)


def _persist_summary_failure(
    task_id: str,
    attempt_id: str,
    rejection: SummaryResultRejected,
) -> SummaryTransitionResult:
    return fail_summary_attempt(
        task_id,
        attempt_id,
        code=rejection.code,
        stage=rejection.stage,
        retryable=rejection.retryable,
        needs_review=rejection.needs_review,
    )


def _summary_failure_response(
    outcome: SummaryTransitionResult,
    rejection: SummaryResultRejected,
    *,
    accepted_status: int,
) -> tuple[str, int]:
    if outcome.accepted:
        return rejection.code, accepted_status
    if outcome.outcome == "conflict":
        return outcome.code, 409
    return "SUMMARY_PERSISTENCE_FAILED", 500

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
async def summarize_v2(
    task_id: str,
    model_name: str = Body(None),
    summary_type: SummaryType = Body(DEFAULT_SUMMARY_TYPE),
    include_context: bool = Body(True),
    async_mode: bool = Body(True),
    min_length: int = Body(DEFAULT_SUMMARY_MIN_WORDS),
    max_length: int = Body(DEFAULT_SUMMARY_MAX_WORDS),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        try:
            options = validate_summary_request_options(
                summary_type=summary_type,
                min_length=min_length,
                max_length=max_length,
            )
        except SummaryRequestContractError as exc:
            raise HTTPException(status_code=422, detail=exc.as_error()) from exc

        summary_type = options.summary_type
        min_length = options.min_length
        max_length = options.max_length

        from src.services.task_service import get_task
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

        request_fingerprint, source_revision_id = build_summary_attempt_binding(
            transcript,
            model_name=model_name,
            summary_type=summary_type,
            include_context=include_context,
            min_length=min_length,
            max_length=max_length,
            user_prompt=None,
        )
        attempt_id = str(uuid.uuid4())
        if async_mode:
            from src.worker.tasks.summarize_task import summarize_transcript_task
            begun = _begin_summary_transition(
                task_id,
                attempt_id,
                request_fingerprint=request_fingerprint,
                source_revision_id=source_revision_id,
                stage="enqueue",
            )
            if not begun.accepted:
                code = begun.code if begun.outcome == "conflict" else "SUMMARY_PERSISTENCE_FAILED"
                raise _summary_http_error(
                    code,
                    task_id=task_id,
                    status_code=409 if begun.outcome == "conflict" else 500,
                )
            try:
                celery_task = summarize_transcript_task.apply_async(
                    kwargs={
                        "task_id": task_id,
                        "model_name": model_name,
                        "summary_type": summary_type,
                        "include_context": include_context,
                        "user_prompt": None,
                        "min_length": min_length,
                        "max_length": max_length,
                    },
                    task_id=attempt_id,
                )
            except Exception as exc:
                logger.error(
                    "[API_V2] Summary enqueue failed | task_id=%s | error_type=%s",
                    task_id,
                    type(exc).__name__,
                )
                rejection = SummaryResultRejected(
                    "SUMMARY_ENQUEUE_FAILED",
                    stage="enqueue",
                    retryable=True,
                    needs_review=False,
                )
                persisted = _persist_summary_failure(
                    task_id,
                    attempt_id,
                    rejection,
                )
                code, status_code = _summary_failure_response(
                    persisted,
                    rejection,
                    accepted_status=503,
                )
                raise _summary_http_error(
                    code,
                    task_id=task_id,
                    status_code=status_code,
                ) from None
            return {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "status": "summarizing",
                "celery_task_id": celery_task.id,
            }
        else:
            from src.services.summarization.summary_service_v2 import summarize_transcript_v2
            begun = _begin_summary_transition(
                task_id,
                attempt_id,
                request_fingerprint=request_fingerprint,
                source_revision_id=source_revision_id,
                stage="execution",
            )
            if not begun.accepted:
                code = begun.code if begun.outcome == "conflict" else "SUMMARY_PERSISTENCE_FAILED"
                raise _summary_http_error(
                    code,
                    task_id=task_id,
                    status_code=409 if begun.outcome == "conflict" else 500,
                )
            try:
                raw_result = summarize_transcript_v2(
                    transcript,
                    model_name,
                    summary_type,
                    include_context,
                    min_length=min_length,
                    max_length=max_length,
                    source_metadata={
                        "summary_source_revision_id": source_revision_id,
                        "request_fingerprint": request_fingerprint,
                    },
                )
                validated = validate_summary_service_result(
                    raw_result,
                    expected_summary_type=summary_type,
                    expected_source_revision_id=source_revision_id,
                    expected_request_fingerprint=request_fingerprint,
                )
            except SummaryResultRejected as rejection:
                persisted = _persist_summary_failure(
                    task_id,
                    attempt_id,
                    rejection,
                )
                code, status_code = _summary_failure_response(
                    persisted,
                    rejection,
                    accepted_status=502,
                )
                raise _summary_http_error(
                    code,
                    task_id=task_id,
                    status_code=status_code,
                ) from None
            except Exception as exc:
                logger.error(
                    "[API_V2] Summary provider failed | task_id=%s | error_type=%s",
                    task_id,
                    type(exc).__name__,
                )
                rejection = SummaryResultRejected(
                    "SUMMARY_GENERATION_FAILED",
                    stage="execution",
                    retryable=True,
                    needs_review=False,
                )
                persisted = _persist_summary_failure(
                    task_id,
                    attempt_id,
                    rejection,
                )
                code, status_code = _summary_failure_response(
                    persisted,
                    rejection,
                    accepted_status=502,
                )
                raise _summary_http_error(
                    code,
                    task_id=task_id,
                    status_code=status_code,
                ) from None
            result_patch = build_summary_result_patch(
                validated,
                summary_type=summary_type,
            )
            persisted = _persist_summary_success(
                task_id,
                attempt_id,
                result_patch,
            )
            if not persisted.accepted:
                code = persisted.code if persisted.outcome == "conflict" else "SUMMARY_PERSISTENCE_FAILED"
                raise _summary_http_error(
                    code,
                    task_id=task_id,
                    status_code=409 if persisted.outcome == "conflict" else 500,
                )
            return {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "status": "summarized",
                "result": _summary_response_result(validated.safe_result),
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[API_V2] Summarize request failed | task_id=%s | error_type=%s",
            task_id,
            type(exc).__name__,
        )
        raise _summary_http_error(
            "SUMMARY_GENERATION_FAILED",
            task_id=task_id,
            status_code=500,
        ) from None

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
