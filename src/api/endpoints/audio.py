from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Form, Body, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import List, Dict, Any
from src.services.audio_service import summarize_transcript, save_audio_and_create_task, process_task
from src.services.task_service import (
    effective_task_status,
    extract_visualization_payload,
    get_task,
    list_tasks,
    released_investigation_run_identity,
    update_task,
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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    DEFAULT_SUMMARY_TYPE,
    MultiSummaryRequest,
    SUMMARY_USER_PROMPT_MAX_LENGTH,
    SummaryMaximumExceeded,
    SummaryRequest,
    SummaryRequestContractError,
    SummaryRequestOptions,
    SummaryType,
    normalize_summary_user_prompt,
    validate_summary_request_options,
)
from src.services.summarization.investigation_preview import (
    coerce_public_preview_payload,
    sanitize_legacy_preview_text,
)
from src.services.summarization.public_projection import (
    public_context_analysis_payload,
    public_task_payload,
    public_task_result_payload,
)

router = APIRouter()


class TaskContextUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_context_prompt: str | None = Field(
        default=None,
        max_length=SUMMARY_USER_PROMPT_MAX_LENGTH,
    )

    @field_validator("user_context_prompt", mode="before")
    @classmethod
    def validate_legacy_user_prompt(cls, value: object) -> str | None:
        return normalize_summary_user_prompt(value)


class VisualizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visualization_type: str = "all"


class ResummarizeRequest(SummaryRequestOptions):
    # Preserve the legacy request schema/defaults while inheriting the shared
    # strict contract, including optional user_prompt validation.
    model_name: str | None = None
    summary_type: SummaryType = "investigation"
    min_length: int = 50
    max_length: int = 200
    length_mode: str = "auto"


def _summary_output_failure(result: Any) -> tuple[str, str] | None:
    if not isinstance(result, dict):
        return "SUMMARY_RESULT_INVALID", "Summarization service returned an invalid result."
    if result.get("available") is not True:
        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        return (
            str(error.get("code") or "SUMMARY_UNAVAILABLE"),
            str(
                error.get("message")
                or result.get("summary")
                or "Summarization service is unavailable."
            ),
        )
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return "SUMMARY_EMPTY", "Summarization service returned an empty summary."
    return None


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
    summary_state: object = None,
    summary_authority: object = None,
    summary_notice: object = None,
    summary_error: object = None,
    summary_preview: object = None,
) -> dict[str, Any]:
    """Build the only result fields owned by a summary endpoint."""

    patch = {
        "summary": summary,
        "summary_model": model_name,
        "summary_type": summary_type,
        "summary_state": summary_state,
        "summary_authority": summary_authority,
        "summary_notice": summary_notice,
        "summary_error": summary_error,
        "summary_preview": summary_preview,
        "summary_runtime": runtime if isinstance(runtime, dict) else {},
    }
    if isinstance(context_analysis, dict):
        patch["context_analysis"] = context_analysis
    return patch


def _process_task_in_worker(task_id: str, model_name: str):
    """Give each executor worker its own transaction and connection."""
    with SessionLocal() as worker_db:
        try:
            return process_task(task_id, model_name, worker_db)
        except Exception:
            worker_db.rollback()
            raise


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
            summary_state = None
            summary_authority = None
            summary_notice = None
            summary_preview = None
            summary_type = None
            summary_variants = {}
            diarization_scope = None
            file_provenance = None
            diarization = None
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
                        result_data = public_task_result_payload(result_data)

                        # Extract data from result JSON (check multiple locations for compatibility)
                        # Priority: result["transcription"] > result["transcript"] > result["text"]
                        transcript = result_data.get('transcription') or result_data.get('transcript') or result_data.get('text')
                        summary = sanitize_legacy_preview_text(result_data.get('summary')) or None
                        num_speakers = result_data.get('num_speakers')
                        has_diarization = result_data.get('has_diarization', False)
                        visualization_data = result_data.get("visualization_data")
                        has_visualization = bool(visualization_data)
                        formatted_transcript = result_data.get('formatted_transcript')
                        segments = result_data.get('segments', [])
                        context_analysis = result_data.get('context_analysis') or {}
                        summary_state = result_data.get("summary_state")
                        summary_authority = result_data.get("summary_authority")
                        summary_notice = result_data.get("summary_notice")
                        summary_type = result_data.get("summary_type")
                        summary_variants = result_data.get("summary_variants") or {}
                        diarization_scope = result_data.get("diarization_scope")
                        file_provenance = result_data.get("file_provenance")
                        diarization = result_data.get("diarization")
                        summary_preview = coerce_public_preview_payload(
                            result_data.get("summary_preview")
                        )
                        if not duration:
                            duration = result_data.get('duration')
                    except Exception as e:
                        logger.warning(f"[GET_AUDIO] Failed to parse task result for {af.id}: {e}")

            response_status = effective_task_status(task_status, af.status, result_data)
            if response_status == "visualized" and not has_visualization:
                response_status = (
                    "summarized"
                    if summary or summary_state
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
                "summary_state": summary_state,
                "summary_authority": summary_authority,
                "summary_notice": summary_notice,
                "summary_type": summary_type,
                "summary_variants": summary_variants,
                "summary_preview": summary_preview,
                "formatted_transcript": formatted_transcript,
                "segments": segments,
                "context_analysis": context_analysis,
                "diarization_scope": diarization_scope,
                "file_provenance": file_provenance,
                "diarization": diarization,
            })

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GET_AUDIO] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list audio files") from None

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

                    result_data = public_task_result_payload(result_data)

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
        raise HTTPException(status_code=500, detail="Failed to read transcript") from None

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
                return [public_task_payload(task) for task in filtered]
            except Exception:
                pass
        if case_id:
            all_tasks = [t for t in all_tasks if str(t.get("case_id")) == str(case_id)]
        return [public_task_payload(task) for task in all_tasks]
    except Exception as e:
        logger.error(f"[GET_TASKS] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list tasks") from None

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
        result_data = public_task_result_payload(task.get("result", {}))
        if isinstance(result_data, str):
            import json
            try:
                result_data = json.loads(result_data)
            except:
                result_data = {}

        if isinstance(result_data, dict):
            result_data = dict(result_data)
            released_visualization = result_data.get("visualization_data")
            result_data["visualization_data"] = released_visualization
            result_data["has_visualization"] = bool(released_visualization)
            result_data["context_analysis"] = public_context_analysis_payload(
                result_data.get("context_analysis")
            )
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
            "error": "Task processing failed." if task.get("error") else None,
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "case_id": task.get("case_id"),
        }

        # Extract transcript from result (check multiple locations for compatibility)
        if isinstance(result_data, dict):
            result_data["summary"] = (
                sanitize_legacy_preview_text(result_data.get("summary")) or None
            )
            result_data["summary_preview"] = coerce_public_preview_payload(
                result_data.get("summary_preview")
            )
            transcript = result_data.get("transcription") or result_data.get("transcript") or result_data.get("text")
            summary = result_data.get("summary")
            summary_state = result_data.get("summary_state")
            num_speakers = result_data.get("num_speakers")
            duration = result_data.get("duration")
            has_diarization = result_data.get("has_diarization", False)
            formatted_transcript = result_data.get("formatted_transcript")
            segments = result_data.get("segments", [])
            context_analysis = result_data.get("context_analysis") or {}
            requested_engine = result_data.get("requested_engine")
            engine_used = result_data.get("engine_used")
            fallback_reason = result_data.get("fallback_reason")

            # Add extracted fields to response
            if transcript:
                response["transcript"] = transcript
            if summary:
                response["summary"] = summary
            if summary_state:
                response["summary_state"] = summary_state
            for key in (
                "summary_authority",
                "summary_notice",
                "summary_preview",
                "summary_runtime",
            ):
                if result_data.get(key) is not None:
                    response[key] = result_data.get(key)
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
                response["summary"] = sanitize_legacy_preview_text(
                    task.get("summary")
                )
            response["result"] = result_data

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GET_TASK] Error getting task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to read task") from None

@router.post("/visualize/{task_id}")
async def create_visualization(
    task_id: str,
    request: VisualizationRequest,
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
    try:
        visualization_type = request.visualization_type
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
                expected_released_run=released_run,
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
            "result": {
                "visualization_data": payload,
                "has_visualization": True,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VISUALIZE_API] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Visualization failed") from None



@router.post("/summarize-multi")
async def summarize_multi(
    request: MultiSummaryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tóm tắt nhiều transcript thành một summary tổng hợp với model và context tuỳ chọn"""

    # Sử dụng model mặc định nếu không chỉ định
    model_name = request.model_name

    try:
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
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
            transcripts = all_transcripts
        else:
            transcripts = request.transcripts
        from src.services.summarization.summary_service_v2 import (
            summarize_multi_transcripts_v2,
        )

        result = summarize_multi_transcripts_v2(
            transcripts=transcripts,
            model_name=model_name,
            summary_type=request.summary_type,
            case_id=request.case_id,
            min_length=request.min_length,
            max_length=request.max_length,
            length_mode=request.length_mode,
            user_prompt=request.user_prompt,
        )
        failure = _summary_output_failure(result)
        if failure is not None:
            code, message = failure
            raise HTTPException(status_code=503, detail={"code": code, "message": message})
        return {"summary": result["summary"]}
    except SummaryRequestContractError as exc:
        raise HTTPException(status_code=422, detail=exc.as_error()) from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error summarizing multi transcripts: {str(e)}")
        raise HTTPException(status_code=500, detail="Summarization failed") from None

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
        for t in tasks:
            transcript = t.get("result", {}).get("transcription") or t.get("result", {}).get("text")
            if transcript:
                transcripts.append(transcript)
        from src.services.summarization.summary_service_v2 import (
            summarize_multi_transcripts_v2,
        )

        result = summarize_multi_transcripts_v2(
            transcripts=transcripts,
            model_name=request.model_name,
            summary_type=request.summary_type,
            case_id=request.case_id,
            min_length=request.min_length,
            max_length=request.max_length,
            length_mode=request.length_mode,
            user_prompt=request.user_prompt,
        )
        failure = _summary_output_failure(result)
        if failure is not None:
            code, message = failure
            raise HTTPException(status_code=503, detail={"code": code, "message": message})
        return {"summary": result["summary"]}
    except SummaryRequestContractError as exc:
        raise HTTPException(status_code=422, detail=exc.as_error()) from exc
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error summarizing case: {str(e)}")
        raise HTTPException(status_code=500, detail="Case summarization failed") from None

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
    request: TaskContextUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update only the user-authored prompt; Analysis is server-owned."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    assert_task_access(db, current_user, task_id, "write")
    if not update_task(
        task_id,
        {"result": {"user_context_prompt": request.user_context_prompt}},
    ):
        raise HTTPException(status_code=500, detail="Failed to update context prompt")
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
        logger.error(f"[OLLAMA_MODELS] Error: {e}", exc_info=True)
        return {"models": [], "error": "Model discovery failed"}

@router.post("/tasks/{task_id}/resummarize")
def resummarize_task(
    task_id: str,
    request: ResummarizeRequest = Body(default=ResummarizeRequest()),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tóm tắt lại file với user_context_prompt mới (nếu có), luôn ưu tiên model tốt nhất."""
    try:
        options = validate_summary_request_options(
            summary_type=request.summary_type,
            min_length=request.min_length,
            max_length=request.max_length,
            length_mode=request.length_mode,
            user_prompt=request.user_prompt,
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
    if "user_prompt" in request.model_fields_set:
        user_prompt = options.user_prompt
    else:
        try:
            user_prompt = normalize_summary_user_prompt(
                result.get("user_context_prompt")
            )
        except SummaryRequestContractError as exc:
            raise HTTPException(status_code=422, detail=exc.as_error()) from exc
    if not transcript:
        raise HTTPException(status_code=400, detail="No transcript found")
    from src.services.summarization.summary_service_v2 import summarize_transcript_v2

    summary_result = summarize_transcript_v2(
        transcript=transcript,
        model_name=request.model_name,
        summary_type=options.summary_type,
        include_context=False,
        user_prompt=user_prompt,
        min_length=options.min_length,
        max_length=options.max_length,
        length_mode=options.length_mode,
        transcript_segments=result.get("segments") or [],
        source_metadata={
            "task_id": task_id,
            "case_id": task.get("case_id") or result.get("case_id"),
            "file_name": task.get("filename") or result.get("filename"),
            "audio_id": result.get("audio_id"),
            "audio_sha256": result.get("audio_sha256"),
            "audio_integrity_status": result.get("audio_integrity_status"),
            "num_speakers": result.get("num_speakers"),
            "has_diarization": result.get("has_diarization"),
            "degraded": result.get("degraded"),
            "diarization_status": result.get("diarization_status"),
            "diarization_method_used": result.get("diarization_method_used"),
            "speaker_provenance": result.get("speaker_provenance"),
        },
        allow_evidence_preview=options.summary_type == "investigation",
    )
    failure = _summary_output_failure(summary_result)
    if failure is not None:
        error_code, error_message = failure
        update_task(task_id, {"status": "failed", "error": error_message})
        raise HTTPException(
            status_code=502,
            detail={"code": error_code, "message": error_message, "task_id": task_id},
        )
    summary = str(summary_result["summary"])
    summary_result_patch = _summary_context_patch(
        summary=summary,
        context_analysis=summary_result.get("context"),
        model_name=summary_result.get("model") or request.model_name,
        summary_type=options.summary_type,
        runtime=summary_result.get("runtime"),
        summary_state=summary_result.get("summary_state"),
        summary_authority=summary_result.get("summary_authority"),
        summary_notice=summary_result.get("summary_notice"),
        summary_error=summary_result.get("error"),
        summary_preview=summary_result.get("summary_preview"),
    )
    if not update_task(
        task_id,
        {
            "status": "summarized",
            "result": summary_result_patch,
            "summary": summary,
            "model_name": summary_result.get("model") or request.model_name,
            "error": None,
        },
    ):
        raise HTTPException(
            status_code=500,
            detail={
                "code": "SUMMARY_PERSISTENCE_FAILED",
                "message": "Failed to persist summarization result.",
                "task_id": task_id,
            },
        )
    public_result = public_task_result_payload(summary_result_patch)
    return {
        "summary": summary,
        "model": summary_result.get("model") or request.model_name,
        "summary_type": options.summary_type,
        "context_analysis": public_context_analysis_payload(
            result.get("context_analysis")
        ),
        "result": public_result,
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
        raise HTTPException(status_code=500, detail="Failed to delete audio") from None

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
    # Đẩy xử lý sang Celery để tránh giữ kết nối lâu gây ECONNRESET qua proxy dev
    process_task_async.delay(task_id, model_name, diarization_method)
    # Trả về ngay để frontend polling qua /tasks/{task_id}
    try:
        # Đánh dấu trạng thái task theo vocabulary canonical.
        task = get_task(task_id) or {}
        if task.get("status") not in ["transcribing", "transcribed", "summarizing", "summarized", "visualizing", "visualized", "failed"]:
            update_task(task_id, {"status": "transcribing"})
    except Exception:
        # Không chặn response nếu cập nhật trạng thái thất bại
        pass
    return {"task_id": task_id, "status": "transcribing"}

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
            future_to_task = {
                executor.submit(_process_task_in_worker, tid, model_name): tid
                for tid in batch
            }
            for future in as_completed(future_to_task):
                tid = future_to_task[future]
                try:
                    result = future.result()
                    results.append({"task_id": tid, "status": "success", "result": result})
                except Exception as e:
                    logger.error(f"[BATCH_PROCESS] Task {tid} failed: {e}", exc_info=True)
                    results.append(
                        {"task_id": tid, "status": "error", "message": "Task processing failed"}
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
            logger.error(f"[BATCH_UPLOAD] File upload failed: {e}", exc_info=True)
            results.append({"error": "Audio upload failed", "filename": file.filename})
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
    fast_mode: bool = Body(False, embed=True),
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
        task_result = task.get("result") if isinstance(task.get("result"), dict) else {}
        transcript = (
            task_result.get("transcription")
            or task_result.get("transcript")
            or task.get("transcript")
        )
        if not transcript:
            raise HTTPException(
                status_code=400,
                detail="Task must be transcribed first. Please run transcription before summarization."
            )

        # Summarize using V2
        from src.services.summarization.summary_service_v2 import summarize_transcript_v2

        # Call V2 service
        result_v2 = summarize_transcript_v2(
            transcript=transcript,
            model_name=model_name,
            summary_type=summary_type,
            include_context=include_context_analysis,
            user_prompt=request.user_prompt,
            min_length=request.min_length,
            max_length=request.max_length,
            length_mode=request.length_mode,
            transcript_segments=task_result.get("segments") or [],
            source_metadata={
                "task_id": task_id,
                "case_id": task.get("case_id") or task_result.get("case_id"),
                "file_name": task.get("filename") or task_result.get("filename"),
                "audio_id": task_result.get("audio_id"),
                "audio_sha256": task_result.get("audio_sha256"),
                "audio_integrity_status": task_result.get("audio_integrity_status"),
                "num_speakers": task_result.get("num_speakers"),
                "has_diarization": task_result.get("has_diarization"),
                "degraded": task_result.get("degraded"),
                "diarization_status": task_result.get("diarization_status"),
                "diarization_method_used": task_result.get(
                    "diarization_method_used"
                ),
                "diarization_fallback_reason": task_result.get(
                    "diarization_fallback_reason"
                ),
                "diarization_degraded_reasons": task_result.get(
                    "diarization_degraded_reasons"
                ),
                "speaker_provenance": task_result.get("speaker_provenance"),
            },
            grounded_context=(
                task_result.get("context_analysis")
                if isinstance(task_result.get("context_analysis"), dict)
                else None
            ),
            allow_evidence_preview=summary_type == "investigation",
            investigation_scenario=request.investigation_scenario,
        )

        failure = _summary_output_failure(result_v2)
        if failure is not None:
            error_code, error_message = failure
            if not update_task(task_id, {"status": "failed", "error": error_message}):
                raise HTTPException(
                    status_code=500,
                    detail={
                        "code": "SUMMARY_PERSISTENCE_FAILED",
                        "message": "Failed to persist summarization failure state.",
                        "task_id": task_id,
                    },
                )
            raise HTTPException(
                status_code=502,
                detail={
                    "code": error_code,
                    "message": error_message,
                    "task_id": task_id,
                },
            )

        summary_text = result_v2.get("summary", "")
        summary_result_patch = _summary_context_patch(
            summary=summary_text,
            context_analysis=result_v2.get("context"),
            model_name=result_v2.get("model") or model_name,
            summary_type=summary_type,
            runtime=result_v2.get("runtime"),
            summary_state=result_v2.get("summary_state"),
            summary_authority=result_v2.get("summary_authority"),
            summary_notice=result_v2.get("summary_notice"),
            summary_error=result_v2.get("error"),
            summary_preview=result_v2.get("summary_preview"),
        )

        # Task service merges this narrow patch against the latest stored result.
        if not update_task(task_id, {
            "status": "summarized",
            "summary": summary_text or None,
            "result": summary_result_patch,
            "model_name": summary_result_patch["summary_model"],
            "error": None,
        }):
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "SUMMARY_PERSISTENCE_FAILED",
                    "message": "Failed to persist summarization result.",
                    "task_id": task_id,
                },
            )

        response = {
            "task_id": task_id,
            "status": "summarized",
            "summary": summary_text,
            "model_name": summary_result_patch["summary_model"],
            "summary_type": summary_type,
            "runtime": result_v2.get("runtime") or {},
            "summary_state": result_v2.get("summary_state"),
            "summary_authority": result_v2.get("summary_authority"),
            "summary_notice": result_v2.get("summary_notice"),
            "summary_preview": result_v2.get("summary_preview"),
            "context_analysis": public_context_analysis_payload(
                summary_result_patch.get("context_analysis")
            ),
            "result": {
                **summary_result_patch,
                "context_analysis": public_context_analysis_payload(
                    summary_result_patch.get("context_analysis")
                ),
            },
        }

        logger.info(f"[API] Summary completed for task {task_id}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API] Error summarizing task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Summarization failed") from None


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
