"""Audio API v2 - Modular"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Depends, Form, Request, Response
from pydantic import BaseModel, Field
from typing import Dict, Any, Literal
from src.core.logging import logger
from src.database.config.database import get_db
from sqlalchemy.orm import Session
from src.services.audio_service import save_audio_and_create_task
from src.core.auth import assert_case_access, assert_task_access, check_rate_limit, get_current_user
from src.core.config import settings
from src.database.models.models import User
from src.services.audit_service import log_activity
from src.services.task_service import extract_visualization_payload
from src.services.lite_runtime import lite_runner_enabled, start_lite_job

router = APIRouter()


ReviewStatusPatch = Literal["machine_suggested", "needs_review", "confirmed", "rejected"]


class ReviewPatch(BaseModel):
    review_status: ReviewStatusPatch
    expected_revision: int = Field(ge=1)
    review_note: str | None = Field(default=None, max_length=2000)


class EntityPatch(BaseModel):
    expected_revision: int = Field(ge=1)
    label: str | None = Field(default=None, max_length=500)
    type: str | None = Field(default=None, max_length=100)
    aliases: list[str] | None = None
    review_note: str | None = Field(default=None, max_length=2000)


class EntityMergeRequest(BaseModel):
    source_entity_ids: list[str] = Field(min_length=2)
    expected_revision: int = Field(ge=1)
    target_label: str | None = Field(default=None, max_length=500)
    target_type: str | None = Field(default=None, max_length=100)


class EntitySplitRequest(BaseModel):
    replacement_entities: list[dict[str, Any]] = Field(min_length=1)
    expected_revision: int = Field(ge=1)


def _task_result_dict(task: dict[str, Any]) -> dict[str, Any]:
    result_data = task.get("result", {})
    if isinstance(result_data, str):
        import json
        try:
            result_data = json.loads(result_data)
        except Exception:
            result_data = {}
    if not isinstance(result_data, dict):
        return {}
    return result_data


def _set_private_response_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _private_error_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _task_audio_id(task) -> int | None:
    return task.audio_files[0].id if getattr(task, "audio_files", None) else None


def _log_graph_update(
    db: Session,
    request: Request,
    current_user: User,
    *,
    task,
    action: str,
    item_id: str | None = None,
    item_count: int | None = None,
    graph_revision: int | None = None,
) -> None:
    detail: dict[str, Any] = {
        "resource": "analysis_graph_v2",
        "action": action,
    }
    if item_id:
        detail["item_id"] = item_id
    if item_count is not None:
        detail["item_count"] = item_count
    if graph_revision is not None:
        detail["graph_revision"] = graph_revision
    log_activity(
        db,
        "update",
        current_user.id,
        request=request,
        case_id=task.case_id,
        audio_id=_task_audio_id(task),
        task_id=task.id,
        detail=detail,
    )


def _log_graph_write_error(action: str, task_id: str, error: Exception) -> None:
    logger.error(
        "[API_V2] Analysis graph write failed | action=%s | task_id=%s | error_class=%s",
        action,
        task_id,
        error.__class__.__name__,
    )


def _log_sensitive_endpoint_error(action: str, task_id: str, error: Exception) -> None:
    logger.error(
        "[API_V2] Sensitive endpoint failed | action=%s | task_id=%s | error_class=%s",
        action,
        task_id,
        error.__class__.__name__,
    )


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
        return save_audio_and_create_task(file, db, case_id=int(case_id) if case_id else None, user_id=current_user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_V2] Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/transcribe/{task_id}")
async def transcribe_v2(
    task_id: str,
    enable_diarization: bool | None = Body(None),
    diarization_method: str = Body("pyannote"),
    language: str = Body("vi"),
    fast_mode: bool = Body(True),
    async_mode: bool = Body(True),
    asr_profile: str | None = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        from src.services.task_service import get_task, update_task
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)
        if enable_diarization is None:
            enable_diarization = settings.ENABLE_DIARIZATION_DEFAULT
        if lite_runner_enabled():
            from src.services.transcription.transcribe_service_v2 import transcribe_audio_v2

            job = start_lite_job(
                db=db,
                task_id=task_id,
                operation="transcribe",
                target=transcribe_audio_v2,
                args=(task_id,),
                kwargs={
                    "enable_diarization": enable_diarization,
                    "diarization_method": diarization_method,
                    "language": language,
                    "fast_mode": fast_mode,
                    "asr_profile": asr_profile,
                },
                queued_status="transcribing",
            )
            return {
                "task_id": task_id,
                "runner_job_id": job.runner_job_id,
                "status": "transcribing",
                "processing_runner": settings.PROCESSING_RUNNER,
            }
        if async_mode:
            from src.worker.tasks.transcribe_task import transcribe_audio_task
            celery_task = transcribe_audio_task.delay(task_id, enable_diarization, diarization_method, language, fast_mode)
            update_task(task_id, {"status": "transcribing"})
            return {"task_id": task_id, "celery_task_id": celery_task.id, "status": "transcribing"}
        else:
            from src.services.transcription.transcribe_service_v2 import transcribe_audio_v2
            return transcribe_audio_v2(task_id, db, enable_diarization, diarization_method, language, fast_mode, asr_profile)
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

        from src.services.summarization.models.llm_manager import llm_provider_configured
        if not llm_provider_configured():
            raise HTTPException(status_code=503, detail="llm_not_configured")

        logger.info(f"[API_V2] Summarize | task_id={task_id} | transcript_length={len(transcript)} | model={model_name}")

        if lite_runner_enabled():
            job = start_lite_job(
                db=db,
                task_id=task_id,
                operation="summarize",
                target=_run_summarize_lite,
                args=(task_id,),
                kwargs={
                    "model_name": model_name,
                    "summary_type": summary_type,
                    "include_context": include_context,
                },
                queued_status="summarizing",
            )
            return {
                "task_id": task_id,
                "status": "summarizing",
                "runner_job_id": job.runner_job_id,
                "processing_runner": settings.PROCESSING_RUNNER,
            }

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
async def get_status_v2(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Get task status for polling.

    Privacy boundary: this endpoint intentionally returns metadata only. It must
    not include raw transcript text, segments, visualization graph data, or the
    full Task.result payload.
    """
    try:
        from src.services.task_service import get_task
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "read")

        result_data = _task_result_dict(task)

        return {
            "task_id": task_id,
            "audio_id": result_data.get("audio_id"),
            "download_url": result_data.get("download_url"),
            "status": task.get("status"),
            "num_speakers": result_data.get("num_speakers"),
            "duration": result_data.get("duration"),
            "has_diarization": bool(result_data.get("has_diarization", False)),
            "has_visualization": bool(result_data.get("has_visualization", False)),
            "transcript_available": bool(
                result_data.get("transcription")
                or result_data.get("transcript")
                or task.get("transcript")
            ),
            "formatted_transcript_available": bool(result_data.get("formatted_transcript")),
            "segments_available": bool(result_data.get("segments")),
            "summary_available": bool(result_data.get("summary") or task.get("summary")),
            "analysis_available": bool(result_data.get("visualization_data") or result_data.get("context_analysis")),
            "result_available": bool(result_data),
            "processing_runner": settings.PROCESSING_RUNNER,
            "error": task.get("error"),
            "filename": task.get("filename"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[API_V2] Get status error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/transcriptions/{task_id}")
async def get_transcription_detail_v2(
    task_id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return transcript-only detail for an authorized task.

    This endpoint is the explicit boundary for transcript text. It does not
    return full Task.result, visualization data, summaries, or analysis graphs.
    """
    try:
        from src.services.task_service import get_task

        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "read")
        _set_private_response_headers(response)

        result_data = _task_result_dict(task)

        transcript = result_data.get("transcription") or result_data.get("transcript") or task.get("transcript")
        return {
            "task_id": task_id,
            "transcription": transcript,
            "raw_transcription": result_data.get("raw_transcription"),
            "review_transcription": result_data.get("review_transcription"),
            "filtered_transcription": result_data.get("filtered_transcription") or transcript,
            "formatted_transcript": result_data.get("formatted_transcript"),
            "segments": result_data.get("segments") or [],
            "raw_segments": result_data.get("raw_segments") or [],
            "language": result_data.get("language"),
            "duration": result_data.get("duration"),
            "num_speakers": result_data.get("num_speakers"),
            "has_diarization": bool(result_data.get("has_diarization", False)),
            "asr_provider": result_data.get("asr_provider"),
            "asr_profile": result_data.get("asr_profile"),
            "model_info": result_data.get("model_info") or {},
            "phoguard": result_data.get("phoguard"),
            "hallucination_report": result_data.get("hallucination_report") or result_data.get("phoguard"),
            "asr_reliability": result_data.get("asr_reliability"),
            "warnings": result_data.get("warnings") or [],
        }
    except HTTPException:
        raise
    except Exception as e:
        _log_sensitive_endpoint_error("get_transcription_detail", task_id, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to load transcription detail",
            headers=_private_error_headers(),
        )


@router.get("/summaries/{task_id}")
async def get_summary_detail_v2(
    task_id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return summary-only detail for an authorized task.

    This is the explicit boundary for generated summary text. It does not return
    transcripts, segments, full Task.result, visualization data, or analysis graphs.
    """
    try:
        from src.services.task_service import get_task

        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "read")
        _set_private_response_headers(response)

        result_data = _task_result_dict(task)
        return {
            "task_id": task_id,
            "summary": result_data.get("summary") or task.get("summary"),
            "summary_model": result_data.get("summary_model"),
            "summary_type": result_data.get("summary_type"),
            "warnings": result_data.get("warnings") or [],
        }
    except HTTPException:
        raise
    except Exception as e:
        _log_sensitive_endpoint_error("get_summary_detail", task_id, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to load summary detail",
            headers=_private_error_headers(),
        )


@router.get("/analyses/{task_id}")
async def get_analysis_detail_v2(
    task_id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return analysis graph detail for an authorized task.

    This is a sensitive detail endpoint: visualization_data may include
    analysis graph segments.text and evidence spans. It is not used for
    list/status/dashboard polling and must keep private no-store headers.
    """
    try:
        from src.services.task_service import get_task

        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "read")
        _set_private_response_headers(response)

        result_data = _task_result_dict(task)
        analysis = result_data.get("visualization_data")
        return {
            "task_id": task_id,
            "has_visualization": bool(result_data.get("has_visualization") or analysis),
            "visualization_data": analysis,
            "schema_version": analysis.get("schema_version") if isinstance(analysis, dict) else None,
            "analysis_mode": analysis.get("analysis_mode") if isinstance(analysis, dict) else None,
            "warnings": analysis.get("warnings") if isinstance(analysis, dict) else [],
        }
    except HTTPException:
        raise
    except Exception as e:
        _log_sensitive_endpoint_error("get_analysis_detail", task_id, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to load analysis detail",
            headers=_private_error_headers(),
        )


def _run_summarize_lite(
    task_id: str,
    *,
    model_name: str | None,
    summary_type: str,
    include_context: bool,
    db: Session,
) -> None:
    from src.services.task_service import get_task, update_task
    from src.services.summarization.summary_service_v2 import summarize_transcript_v2

    task = get_task(task_id, db=db)
    if not task:
        raise ValueError(f"Task {task_id} not found")
    result_data = task.get("result", {}) if isinstance(task.get("result"), dict) else {}
    transcript = result_data.get("transcription") or task.get("transcript")
    if not transcript or not transcript.strip():
        raise ValueError(f"Task {task_id} has no transcription")

    update_task(task_id, {"status": "summarizing"}, db=db)
    result = summarize_transcript_v2(transcript, model_name, summary_type, include_context)
    if not result.get("available"):
        raise ValueError(result.get("summary", "LLM not available for summarization"))
    update_task(
        task_id,
        {
            "status": "summarized",
            "result": {
                "summary": result.get("summary", ""),
                "context_analysis": result.get("context") or {},
                "summary_model": result.get("model"),
                "summary_type": result.get("summary_type", summary_type),
            },
        },
        db=db,
    )
    db.commit()


@router.post("/visualize/{task_id}")
async def visualize_v2(
    task_id: str,
    response: Response,
    visualization_type: str = Body("all", embed=True),
    analysis_mode: Literal["general", "selected"] = Body("general"),
    domain_template_ids: list[int] | None = Body(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _set_private_response_headers(response)
    resolved_task_id: str | None = None
    try:
        from src.services.task_service import get_task, resolve_task_id, update_task
        from src.services.visualization_service import generate_visualization

        resolved_task_id = resolve_task_id(task_id, db=db)
        if not resolved_task_id:
            raise HTTPException(status_code=404, detail="Task not found")

        task = get_task(resolved_task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, resolved_task_id, "process")
        check_rate_limit(f"rl:process:{current_user.id}", settings.PROCESS_RATE_LIMIT_PER_HOUR, 3600)

        requested_template_ids = domain_template_ids or []
        if analysis_mode == "general":
            requested_template_ids = []

        template_version_refs = []
        analysis_templates = []
        if analysis_mode == "selected" and requested_template_ids:
            from src.services.analysis_intelligence.domain_templates import (
                resolve_published_template_refs,
                resolve_published_templates_for_analysis,
            )

            template_version_refs = resolve_published_template_refs(db, current_user, requested_template_ids)
            analysis_templates = resolve_published_templates_for_analysis(db, current_user, requested_template_ids)

        if lite_runner_enabled():
            job = start_lite_job(
                db=db,
                task_id=resolved_task_id,
                operation="visualize",
                target=_run_visualize_lite,
                args=(resolved_task_id,),
                kwargs={
                    "visualization_type": visualization_type,
                    "analysis_mode": analysis_mode,
                    "requested_template_ids": requested_template_ids,
                    "template_version_refs": template_version_refs,
                    "analysis_templates": analysis_templates,
                },
                queued_status="visualizing",
            )
            return {
                "task_id": resolved_task_id,
                "status": "visualizing",
                "runner_job_id": job.runner_job_id,
                "processing_runner": settings.PROCESSING_RUNNER,
            }

        update_task(resolved_task_id, {"status": "visualizing"}, db=db)
        db.commit()

        result = generate_visualization(
            resolved_task_id,
            visualization_type,
            analysis_mode=analysis_mode,
            domain_template_ids=requested_template_ids,
            template_version_refs=template_version_refs,
            analysis_templates=analysis_templates,
        )
        payload = extract_visualization_payload(result)
        update_task(
            resolved_task_id,
            {"status": "visualized", "visualization_data": payload, "has_visualization": True},
            db=db,
        )
        db.commit()

        return {
            "task_id": resolved_task_id,
            "status": "visualized",
            "visualization_data": payload,
            "has_visualization": True,
            "result": result,
        }
    except HTTPException:
        raise
    except Exception as e:
        _log_sensitive_endpoint_error("visualize", resolved_task_id or task_id, e)
        try:
            from src.services.task_service import update_task
            update_task(resolved_task_id or task_id, {"status": "failed", "error": "analysis_generation_failed"}, db=db)
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=500,
            detail="analysis_generation_failed",
            headers=_private_error_headers(),
        )


def _run_visualize_lite(
    task_id: str,
    *,
    visualization_type: str,
    analysis_mode: str,
    requested_template_ids: list[int],
    template_version_refs: list[dict[str, Any]],
    analysis_templates: list[dict[str, Any]],
    db: Session,
) -> None:
    from src.services.task_service import update_task
    from src.services.visualization_service import generate_visualization

    update_task(task_id, {"status": "visualizing"}, db=db)
    db.commit()
    result = generate_visualization(
        task_id,
        visualization_type,
        analysis_mode=analysis_mode,
        domain_template_ids=requested_template_ids,
        template_version_refs=template_version_refs,
        analysis_templates=analysis_templates,
    )
    payload = extract_visualization_payload(result)
    update_task(
        task_id,
        {"status": "visualized", "visualization_data": payload, "has_visualization": True},
        db=db,
    )
    db.commit()


@router.patch("/visualize/{task_id}/items/{item_id}/review")
async def review_visualization_item(
    task_id: str,
    item_id: str,
    patch: ReviewPatch,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _set_private_response_headers(response)
    try:
        from src.services.analysis_intelligence.storage import review_item

        task = assert_task_access(db, current_user, task_id, "write")
        updated = review_item(
            db,
            task_id=task_id,
            item_id=item_id,
            review_status=patch.review_status,
            user_id=current_user.id,
            expected_revision=patch.expected_revision,
            review_note=patch.review_note,
        )
        _log_graph_update(
            db,
            request,
            current_user,
            task=task,
            action="review_item",
            item_id=item_id,
            graph_revision=updated.graph_revision,
        )
        db.commit()
        return {"task_id": task_id, "visualization_data": updated.to_storage_dict()}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        _log_graph_write_error("review_item", task_id, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to update analysis review status",
            headers=_private_error_headers(),
        )


@router.patch("/visualize/{task_id}/entities/{entity_id}")
async def update_visualization_entity(
    task_id: str,
    entity_id: str,
    patch: EntityPatch,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _set_private_response_headers(response)
    try:
        from src.services.analysis_intelligence.storage import update_entity

        task = assert_task_access(db, current_user, task_id, "write")
        patch_data = patch.model_dump(exclude_unset=True)
        expected_revision = patch_data.pop("expected_revision")
        updated = update_entity(
            db,
            task_id=task_id,
            entity_id=entity_id,
            patch=patch_data,
            user_id=current_user.id,
            expected_revision=expected_revision,
        )
        _log_graph_update(
            db,
            request,
            current_user,
            task=task,
            action="update_entity",
            item_id=entity_id,
            graph_revision=updated.graph_revision,
        )
        db.commit()
        return {"task_id": task_id, "visualization_data": updated.to_storage_dict()}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        _log_graph_write_error("update_entity", task_id, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to update analysis entity",
            headers=_private_error_headers(),
        )


@router.post("/visualize/{task_id}/entities/merge")
async def merge_visualization_entities(
    task_id: str,
    payload: EntityMergeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _set_private_response_headers(response)
    try:
        from src.services.analysis_intelligence.storage import merge_entities

        task = assert_task_access(db, current_user, task_id, "write")
        updated = merge_entities(
            db,
            task_id=task_id,
            source_entity_ids=payload.source_entity_ids,
            user_id=current_user.id,
            expected_revision=payload.expected_revision,
            target_label=payload.target_label,
            target_type=payload.target_type,
        )
        _log_graph_update(
            db,
            request,
            current_user,
            task=task,
            action="merge_entities",
            item_count=len(payload.source_entity_ids),
            graph_revision=updated.graph_revision,
        )
        db.commit()
        return {"task_id": task_id, "visualization_data": updated.to_storage_dict()}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        _log_graph_write_error("merge_entities", task_id, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to merge analysis entities",
            headers=_private_error_headers(),
        )


@router.post("/visualize/{task_id}/entities/{entity_id}/split")
async def split_visualization_entity(
    task_id: str,
    entity_id: str,
    payload: EntitySplitRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _set_private_response_headers(response)
    try:
        from src.services.analysis_intelligence.storage import split_entity

        task = assert_task_access(db, current_user, task_id, "write")
        updated = split_entity(
            db,
            task_id=task_id,
            entity_id=entity_id,
            replacement_entities=payload.replacement_entities,
            user_id=current_user.id,
            expected_revision=payload.expected_revision,
        )
        _log_graph_update(
            db,
            request,
            current_user,
            task=task,
            action="split_entity",
            item_id=entity_id,
            item_count=len(payload.replacement_entities),
            graph_revision=updated.graph_revision,
        )
        db.commit()
        return {"task_id": task_id, "visualization_data": updated.to_storage_dict()}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        _log_graph_write_error("split_entity", task_id, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to split analysis entity",
            headers=_private_error_headers(),
        )
