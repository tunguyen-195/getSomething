from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Query, Form, Body, Depends, Request
from typing import List, Dict, Any
import json
import os
from src.services.audio_service import save_audio_and_create_task, process_task, process_task_with_diarization
from src.services.task_service import (
    SummaryResultRejected,
    SummaryTransitionResult,
    begin_summary_attempt,
    build_summary_attempt_binding,
    build_summary_result_patch,
    canonical_summary_code,
    create_task,
    effective_task_status,
    extract_active_visualization_payload,
    extract_visualization_payload,
    fail_summary_attempt,
    get_task,
    list_tasks,
    released_investigation_run_identity,
    safe_summary_message,
    succeed_summary_attempt,
    update_task,
    validate_summary_service_result,
)
from src.services.transcribe_service import transcribe_audio
from src.services.visualization_service import generate_visualization
from src.core.logging import logger
from src.core.config import settings
import uuid
from datetime import datetime, timedelta
from src.database.models.models import Case, AudioFile, Task, User
from src.database.config.database import SessionLocal, get_db
from sqlalchemy.orm import Session, joinedload
import subprocess
from fastapi.responses import FileResponse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote
from src.services.audio_storage import media_type_for_filename, resolve_audio_path
from src.core.auth import (
    accessible_case_ids,
    assert_audio_access,
    assert_case_access,
    assert_task_access,
    check_rate_limit,
    get_current_user,
)
from src.services.audit_service import log_activity
from src.core.time import LEGACY_DATABASE_TIMEZONE, utc_isoformat
from src.services.summarization.contracts import (
    CaseSummaryRequest,
    DEFAULT_SUMMARY_MAX_WORDS,
    DEFAULT_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_TYPE,
    MultiSummaryRequest,
    SummaryMaximumExceeded,
    SummaryRequest,
    SummaryRequestContractError,
    SummaryType,
    validate_summary_request_options,
)

router = APIRouter()


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
) -> SummaryTransitionResult:
    return begin_summary_attempt(
        task_id,
        attempt_id,
        request_fingerprint=request_fingerprint,
        source_revision_id=source_revision_id,
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


def _validated_summary_or_http_error(
    result: object,
    *,
    multi: bool = False,
    expected_summary_type: SummaryType | None = None,
):
    try:
        return validate_summary_service_result(
            result,
            multi=multi,
            expected_summary_type=expected_summary_type,
        )
    except SummaryResultRejected as rejection:
        raise HTTPException(
            status_code=502,
            detail={
                "code": rejection.code,
                "message": safe_summary_message(rejection.code),
            },
        ) from None


def _summary_maximum_http_error(exc: SummaryMaximumExceeded) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={
            "code": "SUMMARY_MAX_LENGTH_EXCEEDED",
            "message": str(exc),
            "length_contract": exc.contract,
        },
    )


def _summary_context_patch(
    *,
    summary: str,
    context_analysis: object,
    model_name: str | None,
    summary_type: SummaryType,
    runtime: object = None,
) -> dict[str, Any]:
    """Build the only result fields owned by a summary endpoint."""

    return {
        "summary": summary,
        "context_analysis": (
            context_analysis if isinstance(context_analysis, dict) else None
        ),
        "summary_model": model_name,
        "summary_type": summary_type,
        "summary_runtime": runtime if isinstance(runtime, dict) else {},
    }


def _process_task_in_worker(task_id: str, model_name: str):
    """Give each executor worker its own transaction and connection."""
    with SessionLocal() as worker_db:
        try:
            return process_task(task_id, model_name, worker_db)
        except Exception:
            worker_db.rollback()
            raise


def _safe_batch_process_failure(
    code: object,
    *,
    status: str = "failed",
) -> dict[str, Any]:
    safe_code = canonical_summary_code(code, "SUMMARY_GENERATION_FAILED")
    return {
        "status": status if status in {"failed", "needs_review"} else "failed",
        "error": {
            "code": safe_code,
            "message": safe_summary_message(safe_code),
        },
    }


def _attach_audio_creation_metadata(result: Dict[str, Any], db: Session) -> Dict[str, Any]:
    audio_id = result.get("audio_id")
    if not audio_id:
        return result
    audio_file = db.query(AudioFile).filter(AudioFile.id == audio_id).first()
    if not audio_file:
        return result
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


def _attach_batch_audio_creation_metadata(
    results: List[Dict[str, Any]],
    db: Session,
) -> List[Dict[str, Any]]:
    audio_ids = {
        result.get("audio_id")
        for result in results
        if result.get("audio_id") is not None
    }
    if not audio_ids:
        return results

    audio_by_id = {
        audio_file.id: audio_file
        for audio_file in db.query(AudioFile).filter(AudioFile.id.in_(audio_ids)).all()
    }
    for result in results:
        audio_file = audio_by_id.get(result.get("audio_id"))
        if not audio_file:
            continue
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
    return results


@router.get("/")
def read_audio(
    case_id: int = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all audio files with transcript/summary from Task.result JSON"""
    try:
        query = db.query(AudioFile).options(joinedload(AudioFile.task))
        if case_id:
            assert_case_access(db, current_user, case_id, "read")
            query = query.filter(AudioFile.case_id == case_id)
        else:
            allowed_ids = accessible_case_ids(db, current_user)
            if allowed_ids is not None:
                query = query.filter(AudioFile.case_id.in_(allowed_ids or {-1}))
        query = query.filter(AudioFile.is_archived.is_(False))

        audio_files = query.order_by(
            AudioFile.created_at.desc(),
            AudioFile.id.desc(),
        ).all()

        result = []
        for af in audio_files:
            # Get transcript/summary/visualization from Task.result JSON
            transcript = None
            summary = None
            num_speakers = None
            has_diarization = False
            visualization_data = None
            has_visualization = False
            duration = getattr(af, 'duration', None)
            formatted_transcript = None
            segments = []
            context_analysis = {}
            result_data = {}

            task_status = None
            if af.task_id:
                task = af.task
                if task:
                    task_status = task.status
                if task and task.result:
                    try:
                        if isinstance(task.result, str):
                            import json
                            result_data = json.loads(task.result)
                        else:
                            result_data = task.result

                        # Extract data from result JSON (check multiple locations for compatibility)
                        # Priority: result["transcription"] > result["transcript"] > result["text"]
                        transcript = result_data.get('transcription') or result_data.get('transcript') or result_data.get('text')
                        summary = result_data.get('summary')
                        num_speakers = result_data.get('num_speakers')
                        has_diarization = result_data.get('has_diarization', False)
                        visualization_data = extract_active_visualization_payload(
                            result_data
                        )
                        has_visualization = bool(visualization_data)
                        formatted_transcript = result_data.get('formatted_transcript')
                        segments = result_data.get('segments', [])
                        context_analysis = result_data.get('context_analysis', {})
                        if not duration:
                            duration = result_data.get('duration')
                    except Exception as e:
                        logger.warning(f"[GET_AUDIO] Failed to parse task result for {af.id}: {e}")

            response_status = effective_task_status(task_status, af.status, result_data)
            if response_status == "visualized" and not has_visualization:
                response_status = (
                    "summarized"
                    if summary
                    else "transcribed"
                    if transcript
                    else "uploaded"
                )

            result.append({
                "id": af.id,
                "audio_id": af.id,
                "task_id": af.task_id,
                "filename": af.filename,
                "case_id": af.case_id,
                "status": response_status,
                "audio_status": af.status,
                "duration": duration,
                "num_speakers": num_speakers,
                "has_diarization": has_diarization,
                "has_visualization": has_visualization,
                "visualization_data": visualization_data,
                "download_url": f"/api/v1/audio/{af.id}/download",
                "created_at": utc_isoformat(
                    af.created_at,
                    naive_timezone=LEGACY_DATABASE_TIMEZONE,
                ),
                "uploaded_at": utc_isoformat(
                    af.uploaded_at,
                    naive_timezone=LEGACY_DATABASE_TIMEZONE,
                ),
                "transcript": transcript,
                "summary": summary,
                "formatted_transcript": formatted_transcript,
                "segments": segments,
                "context_analysis": context_analysis,
            })

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GET_AUDIO] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/files/{file_id}/transcript")
async def get_file_transcript(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get transcript for an audio file by file ID.
    Extracts transcript from Task.result JSON in database.
    """
    try:
        audio_file = db.query(AudioFile).filter(AudioFile.id == file_id).first()
        if not audio_file:
            raise HTTPException(status_code=404, detail="Audio file not found")
        assert_case_access(db, current_user, audio_file.case_id, "read")

        transcript = None
        summary = None
        result_data = {}

        if audio_file.task_id:
            task = db.query(Task).filter(Task.id == audio_file.task_id).first()
            if task and task.result:
                try:
                    if isinstance(task.result, str):
                        import json
                        result_data = json.loads(task.result)
                    else:
                        result_data = task.result

                    # Extract transcript (check multiple locations for compatibility)
                    transcript = result_data.get('transcription') or result_data.get('transcript') or result_data.get('text')
                    summary = result_data.get('summary')
                except Exception as e:
                    logger.warning(f"[GET_FILE_TRANSCRIPT] Failed to parse task result for file {file_id}: {e}")

        return {
            "file_id": file_id,
            "task_id": audio_file.task_id,
            "created_at": utc_isoformat(
                audio_file.created_at,
                naive_timezone=LEGACY_DATABASE_TIMEZONE,
            ),
            "uploaded_at": utc_isoformat(
                audio_file.uploaded_at,
                naive_timezone=LEGACY_DATABASE_TIMEZONE,
            ),
            "transcript": transcript,
            "summary": summary,
            "result": result_data  # Include full result for compatibility
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GET_FILE_TRANSCRIPT] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload")
async def upload_audio(
    file: UploadFile = File(...),
    case_id: str = Form(None),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Upload file, chỉ lưu file và tạo AudioFile/Task, không xử lý ngay"""
    try:
        logger.info(f"[UPLOAD] Bắt đầu upload audio | case_id={case_id}")
        if case_id:
            assert_case_access(db, current_user, int(case_id), "write")
        check_rate_limit(f"rl:upload:{current_user.id}", settings.UPLOAD_RATE_LIMIT_PER_HOUR, 3600)
        result = save_audio_and_create_task(file, db, case_id=int(case_id) if case_id else None, user_id=current_user.id)
        log_activity(
            db,
            "upload",
            current_user.id,
            request=request,
            case_id=int(case_id) if case_id else None,
            audio_id=result.get("audio_id"),
            task_id=result.get("task_id"),
            detail={"status": "pending", "file_size": result.get("file_size")},
        )
        db.commit()
        _attach_audio_creation_metadata(result, db)
        logger.info(f"[UPLOAD] Hoàn thành upload audio | task_id={result.get('task_id')} | audio_id={result.get('audio_id')}")
        return result
    except Exception as e:
        logger.error(f"[UPLOAD] Lỗi upload file: {e}", exc_info=True)
        raise

@router.get("/tasks")
async def get_tasks(
    date: str = Query(None),
    case_id: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Get all tasks, optionally filter by date (YYYY-MM-DD) and case_id"""
    try:
        all_tasks = list_tasks()
        allowed_ids = accessible_case_ids(db, current_user)
        if allowed_ids is not None:
            all_tasks = [t for t in all_tasks if t.get("case_id") in allowed_ids]
        if date:
            try:
                dt = datetime.strptime(date, "%Y-%m-%d")
                next_day = dt + timedelta(days=1)
                filtered = [t for t in all_tasks if t.get("created_at") and dt <= datetime.fromisoformat(t["created_at"]) < next_day]
                if case_id:
                    filtered = [t for t in filtered if str(t.get("case_id")) == str(case_id)]
                return filtered
            except Exception:
                pass
        if case_id:
            all_tasks = [t for t in all_tasks if str(t.get("case_id")) == str(case_id)]
        return all_tasks
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tasks/{task_id}")
async def get_task_by_id(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get task by ID (dùng cho polling trạng thái async). Trả về đầy đủ data từ task.result."""
    try:
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "read")

        # Extract data from task.result (matching v2 structure)
        result_data = task.get("result", {})
        if isinstance(result_data, str):
            import json
            try:
                result_data = json.loads(result_data)
            except:
                result_data = {}

        if isinstance(result_data, dict):
            result_data = dict(result_data)
            released_visualization = extract_active_visualization_payload(
                result_data
            )
            result_data["visualization_data"] = released_visualization
            result_data["has_visualization"] = bool(released_visualization)
        else:
            released_visualization = None
            result_data = {}

        response_status = task.get("status")
        if response_status == "visualized" and not released_visualization:
            response_status = (
                "summarized"
                if result_data.get("summary")
                else "transcribed"
                if result_data.get("transcription")
                else "uploaded"
            )

        # Build response with all available data
        response = {
            "task_id": task_id,
            "id": task.get("id"),
            "filename": task.get("filename"),
            "status": response_status,
            "error": task.get("error"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "case_id": task.get("case_id"),
        }

        # Extract transcript from result (check multiple locations for compatibility)
        if isinstance(result_data, dict):
            transcript = result_data.get("transcription") or result_data.get("transcript") or result_data.get("text")
            summary = result_data.get("summary")
            num_speakers = result_data.get("num_speakers")
            duration = result_data.get("duration")
            has_diarization = result_data.get("has_diarization", False)
            formatted_transcript = result_data.get("formatted_transcript")
            segments = result_data.get("segments", [])
            context_analysis = result_data.get("context_analysis", {})
            requested_engine = result_data.get("requested_engine")
            engine_used = result_data.get("engine_used")
            fallback_reason = result_data.get("fallback_reason")

            # Add extracted fields to response
            if transcript:
                response["transcript"] = transcript
            if summary:
                response["summary"] = summary
            if num_speakers is not None:
                response["num_speakers"] = num_speakers
            if duration is not None:
                response["duration"] = duration
            response["has_diarization"] = has_diarization
            if formatted_transcript:
                response["formatted_transcript"] = formatted_transcript
            if segments:
                response["segments"] = segments
            if context_analysis:
                response["context_analysis"] = context_analysis
            if requested_engine:
                response["requested_engine"] = requested_engine
            if engine_used:
                response["engine_used"] = engine_used
            if fallback_reason:
                response["fallback_reason"] = fallback_reason
            response["has_visualization"] = bool(released_visualization)
            response["visualization_data"] = released_visualization

            # Also include full result for backward compatibility
            response["result"] = result_data
        else:
            # Fallback: check direct fields (old format)
            if task.get("transcript"):
                response["transcript"] = task.get("transcript")
            if task.get("summary"):
                response["summary"] = task.get("summary")
            response["result"] = result_data

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GET_TASK] Error getting task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/visualize/{task_id}")
async def create_visualization(
    task_id: str,
    visualization_type: str = Body("all", embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate visualization from transcribed task.
    Creates timeline, entity graph, and relationship map.

    Args:
        task_id: Task ID (must have transcript)
        visualization_type: Type (timeline, entity_graph, relationship_map, all)

    Returns:
        Visualization data with nodes, edges, timeline, events
    """
    audio_file = None
    try:
        logger.info(f"[VISUALIZE_API] Starting visualization | task_id={task_id} | type={visualization_type}")
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)

        from src.services.visualization_service import VisualizationProjectionError

        task = get_task(task_id)
        task_result = task.get("result") if task and isinstance(task.get("result"), dict) else {}
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

        logger.info(f"[VISUALIZE_API] Completed | task_id={task_id}")
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
        logger.error(f"[VISUALIZE_API] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/summarize-multi")
async def summarize_multi(
    request: MultiSummaryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tóm tắt nhiều transcript thành một summary tổng hợp với model và context tuỳ chọn"""

    # Sử dụng model mặc định nếu không chỉ định
    model_name = request.model_name or settings.DEFAULT_AI_MODEL

    try:
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
        context_analysis = request.context_analysis
        if request.case_id:
            numeric_case_id = int(request.case_id)
            assert_case_access(db, current_user, numeric_case_id, "process")
            all_transcripts = []
            tasks = list_tasks()
            for task in tasks:
                if task.get("case_id") == numeric_case_id:
                    task_result = task.get("result") if isinstance(task.get("result"), dict) else {}
                    transcript = task_result.get("transcription") or task.get("transcript")
                    if transcript:
                        all_transcripts.append(transcript)
                    if context_analysis is None:
                        task_context = task_result.get("context_analysis")
                        if isinstance(task_context, dict) and task_context:
                            context_analysis = task_context
            transcripts = all_transcripts
        else:
            transcripts = request.transcripts
        if not transcripts:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "SUMMARY_RESULT_INVALID",
                    "message": safe_summary_message("SUMMARY_RESULT_INVALID"),
                },
            )
        from src.services.summarization.summary_service_v2 import (
            summarize_multi_transcripts_v2,
        )

        raw_result = summarize_multi_transcripts_v2(
            transcripts=transcripts,
            model_name=model_name,
            summary_type=request.summary_type,
            case_id=request.case_id,
            context_analysis=context_analysis,
            min_length=request.min_length,
            max_length=request.max_length,
        )
        validated = _validated_summary_or_http_error(
            raw_result,
            multi=True,
            expected_summary_type=request.summary_type,
        )
        return {"summary": validated.summary, "result": validated.safe_result}
    except SummaryMaximumExceeded as exc:
        raise _summary_maximum_http_error(exc) from exc
    except SummaryRequestContractError as exc:
        raise HTTPException(status_code=422, detail=exc.as_error()) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Error summarizing multi transcripts | error_type=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "SUMMARY_GENERATION_FAILED",
                "message": safe_summary_message("SUMMARY_GENERATION_FAILED"),
            },
        ) from None

@router.post("/summarize-case")
def summarize_case(
    request: CaseSummaryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tóm tắt toàn bộ các file thuộc một case"""
    try:
        assert_case_access(db, current_user, int(request.case_id), "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
        tasks = list_tasks(case_id=request.case_id)
        transcripts = []
        context_analysis = request.context_analysis
        for t in tasks:
            task_result = t.get("result") if isinstance(t.get("result"), dict) else {}
            transcript = task_result.get("transcription") or task_result.get("text")
            if transcript:
                transcripts.append(transcript)
            if context_analysis is None:
                task_context = task_result.get("context_analysis")
                if isinstance(task_context, dict) and task_context:
                    context_analysis = task_context
        if not transcripts:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "SUMMARY_RESULT_INVALID",
                    "message": safe_summary_message("SUMMARY_RESULT_INVALID"),
                },
            )
        from src.services.summarization.summary_service_v2 import (
            summarize_multi_transcripts_v2,
        )

        raw_result = summarize_multi_transcripts_v2(
            transcripts=transcripts,
            model_name=request.model_name or settings.DEFAULT_AI_MODEL,
            summary_type=request.summary_type,
            case_id=request.case_id,
            context_analysis=context_analysis,
            min_length=request.min_length,
            max_length=request.max_length,
        )
        validated = _validated_summary_or_http_error(
            raw_result,
            multi=True,
            expected_summary_type=request.summary_type,
        )
        return {"summary": validated.summary, "result": validated.safe_result}
    except SummaryMaximumExceeded as exc:
        raise _summary_maximum_http_error(exc) from exc
    except SummaryRequestContractError as exc:
        raise HTTPException(status_code=422, detail=exc.as_error()) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Error summarizing case | error_type=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "SUMMARY_GENERATION_FAILED",
                "message": safe_summary_message("SUMMARY_GENERATION_FAILED"),
            },
        ) from None

@router.get("/cases")
def get_cases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Case).filter(Case.is_archived.is_(False))
    allowed_ids = accessible_case_ids(db, current_user)
    if allowed_ids is not None:
        query = query.filter(Case.id.in_(allowed_ids or {-1}))
    return [
        {
            "id": case.id,
            "case_code": case.case_code,
            "title": case.title,
            "description": case.description,
            "status_id": case.status_id,
            "priority_id": case.priority_id,
            "created_by": case.created_by,
            "created_at": utc_isoformat(
                case.created_at,
                naive_timezone=LEGACY_DATABASE_TIMEZONE,
            ),
            "is_archived": case.is_archived,
        }
        for case in query.order_by(Case.created_at.desc(), Case.id.desc()).all()
    ]

@router.post("/cases")
def create_case(
    data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from src.database.models.models import CaseStatus, CasePriority
    status = db.query(CaseStatus).filter(CaseStatus.status_name == "active").first()
    priority = db.query(CasePriority).filter(CasePriority.priority_name == "high").first()
    if not status or not priority:
        raise HTTPException(status_code=500, detail="Missing default status or priority")
    case = Case(
        title=data["title"],
        case_code=str(uuid.uuid4()),
        description=data.get("description"),
        status_id=status.id,
        priority_id=priority.id,
        created_by=current_user.id,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return {
        "id": case.id,
        "case_code": case.case_code,
        "title": case.title,
        "description": case.description,
        "status_id": case.status_id,
        "priority_id": case.priority_id,
        "created_by": case.created_by,
        "created_at": utc_isoformat(
            case.created_at,
            naive_timezone=LEGACY_DATABASE_TIMEZONE,
        ),
        "is_archived": case.is_archived,
    }

@router.patch("/tasks/{task_id}/context")
def update_task_context(
    task_id: str,
    context_analysis: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cập nhật context_analysis hoặc user_context_prompt cho task"""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    assert_task_access(db, current_user, task_id, "write")
    result_patch: dict[str, Any] = {}
    if "user_context_prompt" in context_analysis:
        result_patch["user_context_prompt"] = context_analysis["user_context_prompt"]
    if "context_analysis" in context_analysis:
        ca = context_analysis["context_analysis"]
        if not isinstance(ca, dict):
            ca = {}
        result_patch["context_analysis"] = ca
    if not update_task(task_id, {"result": result_patch}):
        raise _summary_http_error(
            "SUMMARY_PERSISTENCE_FAILED",
            task_id=task_id,
            status_code=500,
        )
    return {"detail": "Context updated"}

@router.get("/ollama-models")
def get_ollama_models():
    """Trả về danh sách các model Ollama đang chạy trên hệ thống"""
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        models = []
        for line in result.stdout.splitlines():
            if line.strip() and not line.startswith("NAME"):
                parts = line.split()
                if parts:
                    models.append(parts[0])
        return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}

@router.post("/tasks/{task_id}/resummarize")
def resummarize_task(
    task_id: str,
    summary_type: SummaryType = Body(DEFAULT_SUMMARY_TYPE, embed=True),
    min_length: int = Body(DEFAULT_SUMMARY_MIN_WORDS, embed=True),
    max_length: int = Body(DEFAULT_SUMMARY_MAX_WORDS, embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tóm tắt lại file với user_context_prompt mới (nếu có), luôn ưu tiên model tốt nhất."""
    try:
        options = validate_summary_request_options(
            summary_type=summary_type,
            min_length=min_length,
            max_length=max_length,
        )
    except SummaryRequestContractError as exc:
        raise HTTPException(status_code=422, detail=exc.as_error()) from exc

    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    assert_task_access(db, current_user, task_id, "process")
    check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    result = task.get("result") or {}
    transcript = result.get("transcription") or result.get("text")
    context = result.get("context_analysis")
    user_context_prompt = result.get("user_context_prompt")
    if not transcript:
        raise HTTPException(status_code=400, detail="No transcript found")

    request_fingerprint, source_revision_id = build_summary_attempt_binding(
        transcript,
        model_name=None,
        summary_type=options.summary_type,
        include_context=True,
        min_length=options.min_length,
        max_length=options.max_length,
        user_prompt=user_context_prompt,
    )
    attempt_id = str(uuid.uuid4())
    begun = _begin_summary_transition(
        task_id,
        attempt_id,
        request_fingerprint=request_fingerprint,
        source_revision_id=source_revision_id,
    )
    if not begun.accepted:
        code = begun.code if begun.outcome == "conflict" else "SUMMARY_PERSISTENCE_FAILED"
        raise _summary_http_error(
            code,
            task_id=task_id,
            status_code=409 if begun.outcome == "conflict" else 500,
        )

    try:
        from src.services.summarization.summary_service_v2 import summarize_transcript_v2

        raw_result = summarize_transcript_v2(
            transcript=transcript,
            model_name=None,
            summary_type=options.summary_type,
            include_context=True,
            user_prompt=user_context_prompt,
            min_length=options.min_length,
            max_length=options.max_length,
            source_metadata={
                "summary_source_revision_id": source_revision_id,
                "request_fingerprint": request_fingerprint,
            },
        )
        validated = validate_summary_service_result(
            raw_result,
            expected_summary_type=options.summary_type,
            expected_source_revision_id=source_revision_id,
            expected_request_fingerprint=request_fingerprint,
        )
    except SummaryResultRejected as rejection:
        persisted = _persist_summary_failure(task_id, attempt_id, rejection)
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
            "[API] Resummarize provider failed | task_id=%s | error_type=%s",
            task_id,
            type(exc).__name__,
        )
        rejection = SummaryResultRejected(
            "SUMMARY_GENERATION_FAILED",
            stage="execution",
            retryable=True,
            needs_review=False,
        )
        persisted = _persist_summary_failure(task_id, attempt_id, rejection)
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

    summary_result_patch = build_summary_result_patch(
        validated,
        summary_type=options.summary_type,
    )
    persisted = _persist_summary_success(task_id, attempt_id, summary_result_patch)
    if not persisted.accepted:
        code = persisted.code if persisted.outcome == "conflict" else "SUMMARY_PERSISTENCE_FAILED"
        raise _summary_http_error(
            code,
            task_id=task_id,
            status_code=409 if persisted.outcome == "conflict" else 500,
        )
    return {
        "attempt_id": attempt_id,
        "summary": validated.summary,
        "model": validated.model,
        "summary_type": options.summary_type,
        "context_analysis": summary_result_patch["context_analysis"],
        "result": summary_result_patch,
    }

@router.get("/{audio_id}/download")
def download_audio(
    audio_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    audio = assert_audio_access(db, current_user, audio_id, "read")
    if not audio.file_path:
        raise HTTPException(status_code=404, detail="Audio file not found")
    audio_path = resolve_audio_path(audio.file_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(
        audio_path,
        filename=audio.filename,
        media_type=media_type_for_filename(audio.filename or str(audio_path)),
    )

@router.delete("/{audio_id}")
def delete_audio(
    audio_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete audio file from disk and database. Accepts both audio_id and task_id."""
    try:
        # Try to find by task_id first (since frontend uses task_id)
        audio = db.query(AudioFile).filter(AudioFile.task_id == audio_id).first()
        if not audio:
            # Fallback to audio id
            try:
                audio = db.query(AudioFile).filter(AudioFile.id == int(audio_id)).first()
            except ValueError:
                pass

        if not audio:
            raise HTTPException(status_code=404, detail="Audio file not found")
        assert_case_access(db, current_user, audio.case_id, "delete")

        # Delete file from disk
        if audio.file_path:
            try:
                audio_path = resolve_audio_path(audio.file_path)
                audio_path.unlink(missing_ok=True)
                logger.info(f"[DELETE_AUDIO] Deleted file for audio id={audio.id}")
            except Exception as e:
                logger.warning(f"[DELETE_AUDIO] Could not delete file from disk: {e}")

        # Delete associated task if exists
        if audio.task_id:
            task = db.query(Task).filter(Task.id == audio.task_id).first()
            if task:
                db.delete(task)

        # Delete from DB
        log_activity(
            db,
            "delete",
            current_user.id,
            request=request,
            case_id=audio.case_id,
            audio_id=audio.id,
            task_id=audio.task_id,
            detail={"resource": "audio"},
        )
        db.delete(audio)
        db.commit()

        logger.info(f"[DELETE_AUDIO] Deleted audio id={audio.id}, task_id={audio.task_id}")
        return {"detail": "Audio deleted", "id": str(audio.id)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[DELETE_AUDIO] Error: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# Import from old tasks.py file (backward compatibility with v1 API)
# The new modular tasks are in src.worker.tasks.* submodules
from src.worker.tasks import process_task_async

@router.post("/process-task/{task_id}")
async def process_uploaded_task(
    task_id: str,
    model_name: str = Body(None, embed=True),
    diarization_method: str = Body("none", embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Xử lý file đã upload: transcribe, summarize, speaker diarization nếu có. Gửi task cho Celery, trả về ngay, frontend polling trạng thái."""

    # Sử dụng model mặc định nếu không chỉ định
    if model_name is None:
        model_name = settings.DEFAULT_AI_MODEL

    logger.info(f"[PROCESS_TASK] [ASYNC] Nhận request xử lý task_id={task_id} với model={model_name}, diarization_method={diarization_method}")
    assert_task_access(db, current_user, task_id, "process")
    check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    if not update_task(task_id, {"status": "transcribing"}):
        raise _summary_http_error(
            "SUMMARY_PERSISTENCE_FAILED",
            task_id=task_id,
            status_code=500,
        )
    try:
        celery_task = process_task_async.delay(
            task_id,
            model_name,
            diarization_method,
        )
    except Exception as exc:
        logger.error(
            "[PROCESS_TASK] Enqueue failed | task_id=%s | error_type=%s",
            task_id,
            type(exc).__name__,
        )
        persisted = update_task(
            task_id,
            {
                "status": "failed",
                "error": safe_summary_message("SUMMARY_ENQUEUE_FAILED"),
            },
        )
        raise _summary_http_error(
            "SUMMARY_ENQUEUE_FAILED" if persisted else "SUMMARY_PERSISTENCE_FAILED",
            task_id=task_id,
            status_code=503 if persisted else 500,
        ) from None
    return {
        "task_id": task_id,
        "status": "transcribing",
        "celery_task_id": celery_task.id,
    }

@router.post("/process-tasks")
async def process_multiple_tasks(
    task_ids: List[str] = Body(..., embed=True),
    model_name: str = Body(None, embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Xử lý nhiều task (nhiều file/audio) theo batch, tận dụng batch_size và pipeline tối ưu."""

    # Sử dụng model mặc định nếu không chỉ định
    if model_name is None:
        model_name = settings.DEFAULT_AI_MODEL

    import time
    from src.speech_to_text.transcriber import Transcriber
    transcriber = Transcriber()
    batch_size = transcriber.batch_size
    results = []
    total_start = time.time()
    # Chia task_ids thành các batch nhỏ
    for task_id in task_ids:
        assert_task_access(db, current_user, task_id, "process")
    check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
    for i in range(0, len(task_ids), batch_size):
        batch = task_ids[i:i+batch_size]
        batch_start = time.time()
        with ThreadPoolExecutor(max_workers=min(batch_size, 8)) as executor:
            future_to_task = {}
            for tid in batch:
                if not update_task(tid, {"status": "transcribing"}):
                    results.append(
                        {
                            "task_id": tid,
                            **_safe_batch_process_failure(
                                "SUMMARY_PERSISTENCE_FAILED"
                            ),
                        }
                    )
                    continue
                future_to_task[
                    executor.submit(_process_task_in_worker, tid, model_name)
                ] = tid
            for future in as_completed(future_to_task):
                tid = future_to_task[future]
                try:
                    result = future.result()
                    if isinstance(result, dict) and result.get("status") in {
                        "failed",
                        "needs_review",
                    }:
                        raw_error = result.get("error")
                        raw_code = (
                            raw_error.get("code")
                            if isinstance(raw_error, dict)
                            else None
                        )
                        results.append(
                            {
                                "task_id": tid,
                                **_safe_batch_process_failure(
                                    raw_code,
                                    status=result["status"],
                                ),
                            }
                        )
                    else:
                        results.append(
                            {"task_id": tid, "status": "success", "result": result}
                        )
                except Exception as exc:
                    logger.error(
                        "[BATCH] Worker failed | task_id=%s | error_type=%s",
                        tid,
                        type(exc).__name__,
                    )
                    results.append(
                        {
                            "task_id": tid,
                            **_safe_batch_process_failure(
                                "SUMMARY_GENERATION_FAILED"
                            ),
                        }
                    )
        batch_end = time.time()
        logger.info(f"[BATCH] Xử lý batch {i//batch_size+1}: {len(batch)} task, thời gian: {batch_end-batch_start:.2f}s")
    total_end = time.time()
    logger.info(f"[BATCH] Tổng thời gian xử lý {len(task_ids)} task: {total_end-total_start:.2f}s")
    return {"results": results}

@router.post("/batch")
async def batch_upload_audio(
    files: List[UploadFile] = File(...),
    case_id: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Batch upload audio files, create AudioFile and Task for each."""
    task_ids = []
    results = []
    status = "success"
    assert_case_access(db, current_user, int(case_id), "write")
    check_rate_limit(f"rl:upload:{current_user.id}", settings.UPLOAD_RATE_LIMIT_PER_HOUR, 3600)
    for file in files:
        try:
            result = save_audio_and_create_task(file, db, case_id=int(case_id) if case_id else None, user_id=current_user.id)
            task_ids.append(result.get("task_id"))
            results.append(result)
        except Exception as e:
            status = "error"
            results.append({"error": str(e), "filename": file.filename})
    return {
        "task_ids": task_ids,
        "results": _attach_batch_audio_creation_metadata(results, db),
        "status": status,
    }

@router.get("/public/{filename}")
def get_audio_public(filename: str):
    raise HTTPException(status_code=410, detail="Use /api/v1/audio/{audio_id}/download")


# ============================================================================
# NEW ENDPOINTS - Separate Workflow Steps
# ============================================================================

@router.post("/transcribe/{task_id}")
async def transcribe_task(
    task_id: str,
    enable_diarization: bool = Body(True, embed=True),
    diarization_method: str = Body("pyannote", embed=True),
    fast_mode: bool = Body(True, embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Transcribe audio file (SEPARATE from summarization).

    Args:
        task_id: Task ID (file must be uploaded first)
        enable_diarization: Enable speaker diarization
        diarization_method: Method (pyannote, simple_vad, none)
        fast_mode: Skip heavy post-processing

    Returns:
        Transcription result with segments, speakers, etc.
    """
    logger.info(
        f"[API] POST /transcribe/{task_id} | "
        f"diarization={enable_diarization} | method={diarization_method} | fast={fast_mode}"
    )

    try:
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
        result = transcribe_audio(
            task_id=task_id,
            db=db,
            enable_diarization=enable_diarization,
            diarization_method=diarization_method if enable_diarization else "none",
            fast_mode=fast_mode
        )
        return result
    except Exception as e:
        logger.error(f"[API] Error transcribing task {task_id}: {e}", exc_info=True)
        raise


@router.post("/summarize-task/{task_id}")
async def summarize_task(
    task_id: str,
    request: SummaryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Summarize transcript (SEPARATE from transcription).
    Task must be transcribed first.

    Args:
        task_id: Task ID (must have transcript)
        model_name: AI model to use (gemma2:9b, deepseek-r1:7b, etc.)
        summary_type: Type of summary (brief, detailed, investigation)
        include_context_analysis: Include entity/action analysis

    Returns:
        Summary with context analysis
    """
    model_name = request.model_name or settings.DEFAULT_AI_MODEL
    summary_type = request.summary_type
    include_context_analysis = request.include_context

    logger.info(
        f"[API] POST /summarize-task/{task_id} | "
        f"model={model_name} | type={summary_type} | context={include_context_analysis}"
    )

    try:
        # Get task
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)

        # Check if transcript exists
        transcript = task.get('transcript')
        if not transcript:
            raise HTTPException(
                status_code=400,
                detail="Task must be transcribed first. Please run transcription before summarization."
            )

        # Summarize using V2
        from src.services.summarization.summary_service_v2 import summarize_transcript_v2

        request_fingerprint, source_revision_id = build_summary_attempt_binding(
            transcript,
            model_name=model_name,
            summary_type=summary_type,
            include_context=include_context_analysis,
            min_length=request.min_length,
            max_length=request.max_length,
            user_prompt=request.user_prompt,
        )
        attempt_id = str(uuid.uuid4())
        begun = _begin_summary_transition(
            task_id,
            attempt_id,
            request_fingerprint=request_fingerprint,
            source_revision_id=source_revision_id,
        )
        if not begun.accepted:
            code = begun.code if begun.outcome == "conflict" else "SUMMARY_PERSISTENCE_FAILED"
            raise _summary_http_error(
                code,
                task_id=task_id,
                status_code=409 if begun.outcome == "conflict" else 500,
            )

        try:
            result_v2 = summarize_transcript_v2(
                transcript=transcript,
                model_name=model_name,
                summary_type=summary_type,
                include_context=include_context_analysis,
                user_prompt=request.user_prompt,
                min_length=request.min_length,
                max_length=request.max_length,
                source_metadata={
                    "summary_source_revision_id": source_revision_id,
                    "request_fingerprint": request_fingerprint,
                },
            )
            validated = validate_summary_service_result(
                result_v2,
                expected_summary_type=summary_type,
                expected_source_revision_id=source_revision_id,
                expected_request_fingerprint=request_fingerprint,
            )
        except SummaryResultRejected as rejection:
            persisted = _persist_summary_failure(task_id, attempt_id, rejection)
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
                "[API] Summary provider failed | task_id=%s | error_type=%s",
                task_id,
                type(exc).__name__,
            )
            rejection = SummaryResultRejected(
                "SUMMARY_GENERATION_FAILED",
                stage="execution",
                retryable=True,
                needs_review=False,
            )
            persisted = _persist_summary_failure(task_id, attempt_id, rejection)
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

        summary_text = validated.summary
        summary_result_patch = build_summary_result_patch(
            validated,
            summary_type=summary_type,
        )
        persisted = _persist_summary_success(
            task_id,
            attempt_id,
            summary_result_patch,
        )
        if not persisted.accepted:
            code = persisted.code if persisted.outcome == "conflict" else "SUMMARY_PERSISTENCE_FAILED"
            raise _summary_http_error(
                code,
                task_id=task_id,
                status_code=409 if persisted.outcome == "conflict" else 500,
            )

        response = {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "status": "summarized",
            "summary": summary_text,
            "model_name": summary_result_patch["summary_model"],
            "summary_type": summary_type,
            "runtime": result_v2.get("runtime") or {},
            "context_analysis": summary_result_patch["context_analysis"],
            "result": summary_result_patch,
        }

        logger.info(f"[API] Summary completed for task {task_id}")
        return response

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[API] Summary request failed | task_id=%s | error_type=%s",
            task_id,
            type(exc).__name__,
        )
        raise _summary_http_error(
            "SUMMARY_GENERATION_FAILED",
            task_id=task_id,
            status_code=500,
        ) from None


# DEPRECATED: Duplicate endpoint - using create_visualization (line 255) instead
# @router.post("/visualize/{task_id}")
# async def visualize_task(
#     task_id: str,
#     visualization_type: str = Body("all", embed=True)
# ):
#     """
#     Generate visualization data from transcript.
#     Task must be transcribed first.
#
#     Args:
#         task_id: Task ID (must have transcript)
#         visualization_type: Type (timeline, entity_graph, relationship_map, all)
#
#     Returns:
#         Visualization data (nodes, edges, timeline, events)
#     """
#     logger.info(
#         f"[API] POST /visualize/{task_id} | type={visualization_type}"
#     )
#
#     try:
#         result = generate_visualization(
#             task_id=task_id,
#             visualization_type=visualization_type
#         )
#         return result
#     except Exception as e:
#         logger.error(f"[API] Error generating visualization for task {task_id}: {e}", exc_info=True)
#         raise
