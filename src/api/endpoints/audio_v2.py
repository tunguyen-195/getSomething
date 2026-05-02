"""Audio API v2 - Modular"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Body, Depends, Form, Request
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
async def get_status_v2(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Get task status with full data from task.result.
    Used for polling after async operations (transcribe, summarize).
    """
    try:
        from src.services.task_service import get_task
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        assert_task_access(db, current_user, task_id, "read")

        # Extract result data (handle both dict and string JSON)
        result_data = task.get("result", {})
        if isinstance(result_data, str):
            import json
            try:
                result_data = json.loads(result_data)
            except:
                result_data = {}

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

        if isinstance(result_data, dict):
            num_speakers = result_data.get("num_speakers")
            duration = result_data.get("duration")
            has_diarization = result_data.get("has_diarization", False)
            formatted_transcript = result_data.get("formatted_transcript")
            segments = result_data.get("segments", [])
            context_analysis = result_data.get("context_analysis", {})
            visualization_data = result_data.get("visualization_data")
            has_visualization = result_data.get("has_visualization", False)
            audio_id = result_data.get("audio_id")
            download_url = result_data.get("download_url")

        # Build comprehensive response
        response = {
            "task_id": task_id,
            "audio_id": audio_id,
            "download_url": download_url,
            "status": task.get("status"),
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

        update_task(resolved_task_id, {"status": "visualizing"}, db=db)
        db.commit()

        result = generate_visualization(resolved_task_id, visualization_type)
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
        logger.error(f"[API_V2] Visualize error: {e}", exc_info=True)
        try:
            from src.services.task_service import update_task
            update_task(resolved_task_id or task_id, {"status": "failed", "error": str(e)}, db=db)
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/visualize/{task_id}/items/{item_id}/review")
async def review_visualization_item(
    task_id: str,
    item_id: str,
    patch: ReviewPatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
        logger.error(f"[API_V2] Review item error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update analysis review status")


@router.patch("/visualize/{task_id}/entities/{entity_id}")
async def update_visualization_entity(
    task_id: str,
    entity_id: str,
    patch: EntityPatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
        logger.error(f"[API_V2] Update entity error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update analysis entity")


@router.post("/visualize/{task_id}/entities/merge")
async def merge_visualization_entities(
    task_id: str,
    payload: EntityMergeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
        logger.error(f"[API_V2] Merge entities error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to merge analysis entities")


@router.post("/visualize/{task_id}/entities/{entity_id}/split")
async def split_visualization_entity(
    task_id: str,
    entity_id: str,
    payload: EntitySplitRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
        logger.error(f"[API_V2] Split entity error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to split analysis entity")
