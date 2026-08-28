"""Audio API v2 - Modular"""
from fastapi import (
    APIRouter,
    UploadFile,
    File,
    HTTPException,
    Body,
    Depends,
    Form,
    Query,
    status,
)
from pydantic import BaseModel, ConfigDict
from typing import Any
from src.core.logging import logger
from src.database.config.database import get_db
from sqlalchemy.orm import Session
from src.services.audio_service import save_audio_and_create_task
from src.core.auth import (
    assert_case_access,
    assert_task_access,
    check_rate_limit,
    get_current_user,
)
from src.core.config import settings
from src.database.models.models import AudioFile, User
from src.core.time import LEGACY_DATABASE_TIMEZONE, utc_isoformat
from src.services.task_service import (
    effective_task_status,
    extract_visualization_payload,
    released_investigation_run_identity,
)
from src.services.summarization.contracts import (
    DEFAULT_SUMMARY_MAX_WORDS,
    DEFAULT_SUMMARY_MIN_WORDS,
    DEFAULT_SUMMARY_TYPE,
    SummaryRequest,
    SummaryRequestContractError,
    SummaryType,
    validate_summary_request_options,
)
from src.services.summarization.investigation_preview import (
    coerce_public_preview_payload,
    sanitize_legacy_preview_text,
)
from src.services.summarization.failure_contract import (
    SafeSummaryTaskError,
    build_safe_summary_failure_update,
)
from src.services.summarization.investigation_scenarios import (
    DEFAULT_INVESTIGATION_SCENARIO,
    InvestigationScenario,
    require_investigation_scenario,
)
from src.services.summarization.public_projection import (
    public_context_analysis_payload,
    public_task_result_payload,
)
from src.services.audio_batch_contracts import (
    AudioBatchAcceptedResponse,
    AudioBatchContractError,
    AudioBatchResponse,
    AudioBatchSummaryJobResponse,
    AudioBatchSummaryRequest,
    AudioBatchTranscribeRequest,
    AudioBatchUploadOptions,
)
from src.services.audio_batch_repository import get_owned_audio_batch
from src.services.audio_batch_service import (
    AudioBatchServiceError,
    audio_batch_response,
    audio_batch_summary_job_response,
    cancel_audio_batch,
    create_audio_batch_from_uploads,
    create_audio_batch_summary_job,
    get_owned_audio_batch_summary_job,
    queue_audio_batch_transcription,
)

router = APIRouter()


class SummaryV2Request(SummaryRequest):
    """V2 keeps context enabled by default while sharing the canonical contract."""

    # Keep the explicit V2 schema visible to static contract/audit tooling while
    # inheriting validation (including the optional user_prompt) from the shared model.
    model_name: str | None = None
    summary_type: SummaryType = DEFAULT_SUMMARY_TYPE
    include_context: bool = True
    async_mode: bool = True
    min_length: int = DEFAULT_SUMMARY_MIN_WORDS
    max_length: int = DEFAULT_SUMMARY_MAX_WORDS
    length_mode: str = "auto"
    investigation_scenario: InvestigationScenario = DEFAULT_INVESTIGATION_SCENARIO


class VisualizationV2Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visualization_type: str = "all"


_SUMMARY_RESPONSE_FIELDS = frozenset(
    {
        "available",
        "summary",
        "context",
        "model",
        "requested_model",
        "summary_type",
        "summary_state",
        "summary_authority",
        "summary_notice",
        "summary_preview",
        "release",
        "runtime",
        "error",
        "num_transcripts",
        "case_id",
    }
)


def _summary_response_result(result: dict[str, Any]) -> dict[str, Any]:
    """Expose summary-owned fields without replaying visualization projections."""

    response = {
        key: value for key, value in result.items() if key in _SUMMARY_RESPONSE_FIELDS
    }
    response["summary"] = sanitize_legacy_preview_text(response.get("summary"))
    response["summary_preview"] = coerce_public_preview_payload(
        response.get("summary_preview")
    )
    response["context"] = public_context_analysis_payload(response.get("context"))
    return response


def _summary_contract_failure(result: Any) -> tuple[str, str] | None:
    if not isinstance(result, dict):
        return (
            "SUMMARY_RESULT_INVALID",
            "Summarization service returned an invalid result.",
        )
    if result.get("available") is not True:
        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        code = str(error.get("code") or "SUMMARY_UNAVAILABLE")
        message = str(
            error.get("message")
            or result.get("summary")
            or "Summarization service is unavailable."
        )
        return code, message
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return "SUMMARY_EMPTY", "Summarization service returned an empty summary."
    return None


def _batch_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AudioBatchServiceError):
        return HTTPException(status_code=exc.status_code, detail=exc.as_detail())
    if isinstance(exc, AudioBatchContractError):
        return HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.message, "retryable": False},
        )
    return HTTPException(
        status_code=500,
        detail={
            "code": "AUDIO_BATCH_INTERNAL_ERROR",
            "message": "Audio batch processing failed.",
            "retryable": True,
        },
    )


def _owned_batch_or_404(db: Session, *, batch_id: str, current_user: User, action: str):
    try:
        batch = get_owned_audio_batch(db, batch_id=batch_id, user_id=current_user.id)
    except AudioBatchContractError as exc:
        raise _batch_http_error(exc) from exc
    if batch is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "AUDIO_BATCH_NOT_FOUND",
                "message": "Audio batch not found.",
                "retryable": False,
            },
        )
    assert_case_access(db, current_user, batch.case_id, action)
    return batch


@router.post(
    "/batches",
    response_model=AudioBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_audio_batch_v2(
    files: list[UploadFile] = File(..., alias="files[]"),
    case_id: int = Form(...),
    idempotency_key: str = Form(...),
    enable_diarization: bool = Form(True),
    diarization_method: str = Form("pyannote"),
    language: str = Form("vi"),
    fast_mode: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atomically persist one ordered upload batch after validating every file."""

    try:
        assert_case_access(db, current_user, case_id, "write")
        check_rate_limit(
            f"rl:upload:{current_user.id}",
            settings.UPLOAD_RATE_LIMIT_PER_HOUR,
            3600,
        )
        options = AudioBatchUploadOptions.model_validate(
            {
                "enable_diarization": enable_diarization,
                "diarization_method": diarization_method,
                "language": language,
                "fast_mode": fast_mode,
            }
        )
        batch, _created = create_audio_batch_from_uploads(
            db,
            files=files,
            case_id=case_id,
            user_id=current_user.id,
            idempotency_key=idempotency_key,
            upload_options=options,
        )
        return audio_batch_response(batch)
    except HTTPException:
        raise
    except Exception as exc:
        if not isinstance(exc, (AudioBatchServiceError, AudioBatchContractError)):
            logger.error(
                "[API_V2_BATCH] Upload failed | error_type=%s", type(exc).__name__
            )
        raise _batch_http_error(exc) from exc


@router.get("/batches/{batch_id}", response_model=AudioBatchResponse)
async def get_audio_batch_v2(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        batch = _owned_batch_or_404(
            db, batch_id=batch_id, current_user=current_user, action="read"
        )
        return audio_batch_response(batch)
    except HTTPException:
        raise
    except Exception as exc:
        raise _batch_http_error(exc) from exc


@router.post(
    "/batches/{batch_id}/transcribe",
    response_model=AudioBatchAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def transcribe_audio_batch_v2(
    batch_id: str,
    request: AudioBatchTranscribeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        _owned_batch_or_404(
            db, batch_id=batch_id, current_user=current_user, action="process"
        )
        check_rate_limit(
            f"rl:process:{current_user.id}",
            settings.PROCESS_RATE_LIMIT_PER_HOUR,
            3600,
        )
        return queue_audio_batch_transcription(
            db,
            batch_id=batch_id,
            user_id=current_user.id,
            options=request,
        )
    except HTTPException:
        raise
    except Exception as exc:
        if not isinstance(exc, (AudioBatchServiceError, AudioBatchContractError)):
            logger.error(
                "[API_V2_BATCH] Transcription queue failed | error_type=%s",
                type(exc).__name__,
            )
        raise _batch_http_error(exc) from exc


@router.post(
    "/batches/{batch_id}/cancel",
    response_model=AudioBatchAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_audio_batch_v2(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        _owned_batch_or_404(
            db, batch_id=batch_id, current_user=current_user, action="process"
        )
        return cancel_audio_batch(db, batch_id=batch_id, user_id=current_user.id)
    except HTTPException:
        raise
    except Exception as exc:
        raise _batch_http_error(exc) from exc


@router.post(
    "/batches/{batch_id}/summary",
    response_model=AudioBatchSummaryJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def summarize_audio_batch_v2(
    batch_id: str,
    request: AudioBatchSummaryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        _owned_batch_or_404(
            db, batch_id=batch_id, current_user=current_user, action="process"
        )
        check_rate_limit(
            f"rl:process:{current_user.id}",
            settings.PROCESS_RATE_LIMIT_PER_HOUR,
            3600,
        )
        job = create_audio_batch_summary_job(
            db,
            batch_id=batch_id,
            user_id=current_user.id,
            request=request,
        )
        return audio_batch_summary_job_response(job)
    except HTTPException:
        raise
    except Exception as exc:
        if not isinstance(exc, (AudioBatchServiceError, AudioBatchContractError)):
            logger.error(
                "[API_V2_BATCH] Summary queue failed | error_type=%s",
                type(exc).__name__,
            )
        raise _batch_http_error(exc) from exc


@router.get(
    "/batches/{batch_id}/summary/{summary_job_id}",
    response_model=AudioBatchSummaryJobResponse,
)
async def get_audio_batch_summary_v2(
    batch_id: str,
    summary_job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        _owned_batch_or_404(
            db, batch_id=batch_id, current_user=current_user, action="read"
        )
        job = get_owned_audio_batch_summary_job(
            db,
            batch_id=batch_id,
            summary_job_id=summary_job_id,
            user_id=current_user.id,
        )
        if job is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "BATCH_SUMMARY_JOB_NOT_FOUND",
                    "message": "Merged summary job not found.",
                    "retryable": False,
                },
            )
        assert_case_access(db, current_user, job.case_id, "read")
        return audio_batch_summary_job_response(job)
    except HTTPException:
        raise
    except Exception as exc:
        raise _batch_http_error(exc) from exc


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
        check_rate_limit(
            f"rl:upload:{current_user.id}", settings.UPLOAD_RATE_LIMIT_PER_HOUR, 3600
        )
        result = save_audio_and_create_task(
            file,
            db,
            case_id=int(case_id) if case_id else None,
            user_id=current_user.id,
        )
        audio_file = (
            db.query(AudioFile).filter(AudioFile.id == result.get("audio_id")).first()
        )
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
        logger.error(f"[API_V2] Upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Audio upload failed") from None


@router.post("/transcribe/{task_id}")
async def transcribe_v2(
    task_id: str,
    enable_diarization: bool = Body(True),
    diarization_method: str = Body("pyannote"),
    language: str = Body("vi"),
    fast_mode: bool = Body(False),
    async_mode: bool = Body(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        from src.services.task_service import get_task, update_task

        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(
            f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600
        )
        if async_mode:
            from src.worker.tasks.transcribe_task import transcribe_audio_task

            celery_task = transcribe_audio_task.delay(
                task_id, enable_diarization, diarization_method, language, fast_mode
            )
            update_task(task_id, {"status": "transcribing"})
            return {
                "task_id": task_id,
                "celery_task_id": celery_task.id,
                "status": "transcribing",
            }
        else:
            from src.services.transcription.transcribe_service_v2 import (
                transcribe_audio_v2,
            )

            return transcribe_audio_v2(
                task_id, db, enable_diarization, diarization_method, language, fast_mode
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_V2] Transcribe error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Transcription failed") from None


@router.post("/summarize/{task_id}")
async def summarize_v2(
    task_id: str,
    request: SummaryV2Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model_name = request.model_name
    summary_type = request.summary_type
    include_context = request.include_context
    async_mode = request.async_mode
    min_length = request.min_length
    max_length = request.max_length
    length_mode = request.length_mode
    investigation_scenario = request.investigation_scenario
    try:
        try:
            options = validate_summary_request_options(
                summary_type=summary_type,
                min_length=min_length,
                max_length=max_length,
                length_mode=length_mode,
            )
        except SummaryRequestContractError as exc:
            raise HTTPException(status_code=422, detail=exc.as_error()) from exc

        summary_type = options.summary_type
        min_length = options.min_length
        max_length = options.max_length
        length_mode = options.length_mode
        investigation_scenario = require_investigation_scenario(investigation_scenario)

        from src.services.task_service import get_task, update_task

        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(
            f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600
        )

        # Get transcript from task result (standardized to "transcription")
        transcript = None
        transcript_segments = []
        grounded_context = None
        source_metadata = {"task_id": task_id}
        if task.get("result") and isinstance(task["result"], dict):
            # Transcript is stored in result["transcription"] (TaskResult schema)
            task_result = task["result"]
            transcript = task_result.get("transcription")
            transcript_segments = task_result.get("segments") or []
            grounded_context = task_result.get("context_analysis")
            source_metadata.update(
                audio_id=task_result.get("audio_id"),
                audio_sha256=task_result.get("audio_sha256"),
                audio_integrity_status=task_result.get("audio_integrity_status"),
                case_id=task.get("case_id") or task_result.get("case_id"),
                file_name=task.get("filename") or task_result.get("filename"),
                num_speakers=task_result.get("num_speakers"),
                has_diarization=task_result.get("has_diarization"),
                degraded=task_result.get("degraded"),
                diarization_status=task_result.get("diarization_status"),
                diarization_method_used=task_result.get("diarization_method_used"),
                diarization_fallback_reason=task_result.get(
                    "diarization_fallback_reason"
                ),
                diarization_degraded_reasons=task_result.get(
                    "diarization_degraded_reasons"
                ),
                speaker_provenance=task_result.get("speaker_provenance"),
            )

        if not transcript or not transcript.strip():
            logger.warning(
                f"[API_V2] No transcription found for task {task_id}. Task result keys: {list(task.get('result', {}).keys()) if task.get('result') else 'No result'}"
            )
            raise HTTPException(
                status_code=400,
                detail="No transcription found. Please transcribe the audio first.",
            )

        logger.info(
            f"[API_V2] Summarize | task_id={task_id} | transcript_length={len(transcript)} | model={model_name}"
        )

        if async_mode:
            from src.worker.tasks.summarize_task import summarize_transcript_task

            if not update_task(task_id, {"status": "summarizing"}):
                raise HTTPException(
                    status_code=500,
                    detail={
                        "code": "SUMMARY_PERSISTENCE_FAILED",
                        "message": "Failed to persist summarization state.",
                        "task_id": task_id,
                    },
                )
            try:
                celery_task = summarize_transcript_task.delay(
                    task_id=task_id,
                    model_name=model_name,
                    summary_type=summary_type,
                    include_context=include_context,
                    user_prompt=request.user_prompt,
                    min_length=min_length,
                    max_length=max_length,
                    length_mode=length_mode,
                    investigation_scenario=investigation_scenario,
                )
            except Exception:
                update_task(
                    task_id,
                    {"status": "failed", "error": "Summary job could not be queued."},
                )
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "SUMMARY_ENQUEUE_FAILED",
                        "message": "Summary job could not be queued.",
                        "task_id": task_id,
                    },
                ) from None
            return {
                "task_id": task_id,
                "status": "summarizing",
                "celery_task_id": celery_task.id,
            }
        else:
            from src.services.summarization.summary_service_v2 import (
                summarize_transcript_v2,
            )

            result = summarize_transcript_v2(
                transcript,
                model_name,
                summary_type,
                include_context,
                user_prompt=request.user_prompt,
                max_length=max_length,
                min_length=min_length,
                transcript_segments=transcript_segments,
                source_metadata=source_metadata,
                grounded_context=(
                    grounded_context if isinstance(grounded_context, dict) else None
                ),
                allow_evidence_preview=summary_type == "investigation",
                investigation_scenario=investigation_scenario,
                length_mode=length_mode,
            )
            failure = _summary_contract_failure(result)
            if failure is not None:
                error_code, _error_message = failure
                safe_error = SafeSummaryTaskError(error_code, result=result)
                persisted = update_task(
                    task_id,
                    build_safe_summary_failure_update(safe_error),
                )
                if not persisted:
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
                        "code": safe_error.code,
                        "message": str(safe_error),
                        "task_id": task_id,
                    },
                )

            summary_text = result.get("summary")
            if not isinstance(summary_text, str):
                summary_text = ""
            summary_result_patch = {
                "summary": summary_text or None,
                "summary_model": result.get("model"),
                "summary_type": summary_type,
                "summary_state": result.get("summary_state"),
                "summary_authority": result.get("summary_authority"),
                "summary_notice": result.get("summary_notice"),
                "summary_error": result.get("error"),
                "summary_preview": result.get("summary_preview"),
                "summary_runtime": result.get("runtime") or {},
            }
            generated_context = result.get("context")
            if isinstance(generated_context, dict):
                summary_result_patch["context_analysis"] = generated_context
            persisted = update_task(
                task_id,
                {
                    "status": "summarized",
                    "summary": summary_text or None,
                    "result": summary_result_patch,
                    "model_name": result.get("model"),
                    "error": None,
                },
            )
            if not persisted:
                raise HTTPException(
                    status_code=500,
                    detail={
                        "code": "SUMMARY_PERSISTENCE_FAILED",
                        "message": "Failed to persist summarization result.",
                        "task_id": task_id,
                    },
                )
            return {
                "task_id": task_id,
                "status": "summarized",
                "result": _summary_response_result(result),
            }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[API_V2] Summarize failed | error_type=%s",
            type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail="Summarization failed") from None


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
            lightweight_result = authorized_task.result
            if isinstance(lightweight_result, str):
                import json

                try:
                    lightweight_result = json.loads(lightweight_result)
                except Exception:
                    lightweight_result = {}
            if not isinstance(lightweight_result, dict):
                lightweight_result = {}
            lightweight_result = public_task_result_payload(lightweight_result)
            return {
                "task_id": task_id,
                "audio_id": audio_id,
                "download_url": f"/api/v1/audio/{audio_id}/download"
                if audio_id
                else None,
                "status": effective_task_status(
                    authorized_task.status,
                    audio.status if audio else None,
                ),
                "error": "Task processing failed." if authorized_task.error else None,
                "summary_state": lightweight_result.get("summary_state"),
                "summary_notice": lightweight_result.get("summary_notice"),
                "summary_error": lightweight_result.get("summary_error"),
                "filename": authorized_task.filename,
                "created_at": authorized_task.created_at,
                "updated_at": authorized_task.updated_at,
                "uploaded_at": utc_isoformat(
                    audio.uploaded_at,
                    naive_timezone=LEGACY_DATABASE_TIMEZONE,
                )
                if audio
                else None,
            }

        task = get_task(task_id, db=db)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # Extract result data (handle both dict and string JSON)
        result_data = public_task_result_payload(task.get("result", {}))
        if isinstance(result_data, str):
            import json

            try:
                result_data = json.loads(result_data)
            except:
                result_data = {}

        if isinstance(result_data, dict):
            result_data = dict(result_data)

        # Get transcript from task result (standardized to "transcription")
        transcript = None
        if isinstance(result_data, dict):
            transcript = result_data.get("transcription")

        # Get summary from task result or direct field
        summary = None
        if isinstance(result_data, dict):
            summary = result_data.get("summary")
        if not summary:
            summary = sanitize_legacy_preview_text(task.get("summary")) or None

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
            context_analysis = result_data.get("context_analysis") or {}
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
                "summarized" if summary else "transcribed" if transcript else "uploaded"
            )

        # Build comprehensive response
        response = {
            "task_id": task_id,
            "audio_id": audio_id,
            "download_url": download_url,
            "status": response_status,
            "transcript": transcript,
            "summary": summary,
            "summary_state": result_data.get("summary_state"),
            "summary_authority": result_data.get("summary_authority"),
            "summary_notice": result_data.get("summary_notice"),
            "summary_preview": result_data.get("summary_preview"),
            "num_speakers": num_speakers,
            "duration": duration,
            "has_diarization": has_diarization,
            "has_visualization": has_visualization,
            "visualization_data": visualization_data,
            "error": "Task processing failed." if task.get("error") else None,
            "filename": task.get("filename"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "uploaded_at": utc_isoformat(
                audio.uploaded_at,
                naive_timezone=LEGACY_DATABASE_TIMEZONE,
            )
            if audio
            else None,
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
        raise HTTPException(
            status_code=500, detail="Failed to read task status"
        ) from None


@router.post("/visualize/{task_id}")
async def visualize_v2(
    task_id: str,
    request: VisualizationV2Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        visualization_type = request.visualization_type
        from src.services.task_service import get_task
        from src.services.visualization_service import (
            VisualizationProjectionError,
            generate_visualization,
        )

        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(
            f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600
        )

        task_result = task.get("result") if isinstance(task.get("result"), dict) else {}
        released_run = task_result.get("released_investigation_run")
        active_identity = released_investigation_run_identity(released_run)
        try:
            result = generate_visualization(released_run, visualization_type)
        except VisualizationProjectionError as exc:
            status_code = (
                409 if exc.code == "VISUALIZATION_RELEASED_RUN_REQUIRED" else 412
            )
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
        logger.error(f"[API_V2] Visualize error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Visualization failed") from None
