"""Application service for atomic multi-audio upload and durable batch jobs."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.database.models.models import (
    AudioBatch,
    AudioBatchItem,
    AudioBatchSummaryJob,
    AudioFile,
    Language,
    Summary,
    Task,
)
from src.services.audio_batch_contracts import (
    AudioBatchAcceptedResponse,
    AudioBatchContractError,
    AudioBatchCreateRequest,
    AudioBatchFileDescriptor,
    AudioBatchItemBinding,
    AudioBatchResponse,
    AudioBatchSummaryJobResponse,
    AudioBatchSummaryManifestItem,
    AudioBatchSummaryRequest,
    AudioBatchTranscribeRequest,
    AudioBatchUploadOptions,
    BATCH_MAX_AGGREGATE_BYTES,
    BATCH_MAX_FILES,
    canonical_batch_request_fingerprint,
    canonical_summary_source_manifest_sha256,
    derive_audio_batch_aggregate,
    normalize_audio_batch_id,
)
from src.services.audio_batch_repository import (
    AudioBatchIdempotencyConflict,
    create_or_replay_audio_batch,
    find_idempotent_audio_batch,
)
from src.services.audio_storage import (
    StagedAudio,
    StoredAudio,
    cleanup_file,
    finalize_staged_upload,
    stage_upload,
)
from src.services.task_service import released_investigation_run_identity


class AudioBatchServiceError(RuntimeError):
    """Typed public-safe failure; no user content or provider detail is retained."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(message)

    def as_detail(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }


def _cleanup_uploads(
    staged: Sequence[StagedAudio], stored: Sequence[StoredAudio]
) -> None:
    for item in staged:
        cleanup_file(item.temp_path)
    for item in stored:
        cleanup_file(item.absolute_path)


def _contract_error(exc: Exception) -> AudioBatchServiceError:
    if isinstance(exc, AudioBatchIdempotencyConflict):
        return AudioBatchServiceError(exc.code, exc.message, status_code=409)
    if isinstance(exc, AudioBatchContractError):
        status_code = 413 if exc.code.endswith("SIZE_EXCEEDED") else 422
        return AudioBatchServiceError(exc.code, exc.message, status_code=status_code)
    return AudioBatchServiceError(
        "INVALID_AUDIO_BATCH_REQUEST",
        "The audio batch request is invalid.",
        status_code=422,
    )


def _upload_failure(exc: HTTPException) -> AudioBatchServiceError:
    if exc.status_code == 413:
        return AudioBatchServiceError(
            "BATCH_FILE_SIZE_EXCEEDED",
            "An audio file exceeds the 100 MB limit.",
            status_code=413,
        )
    if exc.status_code >= 500:
        return AudioBatchServiceError(
            "BATCH_AUDIO_VALIDATION_UNAVAILABLE",
            "Audio validation is unavailable.",
            status_code=503,
            retryable=True,
        )
    return AudioBatchServiceError(
        "BATCH_AUDIO_FILE_INVALID",
        "One or more uploaded files are invalid audio.",
        status_code=400,
    )


def _ensure_positive_scope(*, user_id: int, case_id: int) -> None:
    if type(user_id) is not int or user_id < 1:
        raise AudioBatchServiceError(
            "INVALID_BATCH_OWNER", "Batch owner is invalid.", status_code=422
        )
    if type(case_id) is not int or case_id < 1:
        raise AudioBatchServiceError(
            "INVALID_BATCH_CASE", "Batch case is invalid.", status_code=422
        )


def _language_id(db: Session, language_code: str) -> int:
    primary_code = language_code.split("-", 1)[0].lower()
    language = (
        db.query(Language).filter(Language.language_code == primary_code).first()
        or db.query(Language).order_by(Language.id.asc()).first()
    )
    if language is None:
        raise AudioBatchServiceError(
            "BATCH_LANGUAGE_UNAVAILABLE",
            "No supported audio language is configured.",
            status_code=503,
        )
    return language.id


def _build_create_request(
    *,
    case_id: int,
    idempotency_key: str,
    staged: Sequence[StagedAudio],
    upload_options: AudioBatchUploadOptions,
) -> AudioBatchCreateRequest:
    try:
        return AudioBatchCreateRequest(
            case_id=case_id,
            idempotency_key=idempotency_key,
            files=[
                AudioBatchFileDescriptor(
                    original_filename=item.original_filename,
                    size_bytes=item.size,
                    verified_audio_sha256=item.sha256,
                )
                for item in staged
            ],
            upload_options=upload_options,
        )
    except (ValidationError, AudioBatchContractError) as exc:
        raise _contract_error(exc) from exc


def create_audio_batch_from_uploads(
    db: Session,
    *,
    files: list[UploadFile],
    case_id: int,
    user_id: int,
    idempotency_key: str,
    upload_options: AudioBatchUploadOptions,
) -> tuple[AudioBatch, bool]:
    """Stage every source, replay before row creation, then commit all rows atomically."""

    _ensure_positive_scope(user_id=user_id, case_id=case_id)
    if not files:
        raise AudioBatchServiceError(
            "BATCH_FILES_REQUIRED",
            "At least one audio file is required.",
            status_code=422,
        )
    if len(files) > BATCH_MAX_FILES:
        raise AudioBatchServiceError(
            "BATCH_FILE_COUNT_EXCEEDED",
            "An audio batch cannot exceed 20 files.",
            status_code=413,
        )

    staged: list[StagedAudio] = []
    stored: list[StoredAudio] = []
    request: AudioBatchCreateRequest | None = None
    try:
        for upload in files:
            try:
                staged.append(stage_upload(upload))
            except HTTPException as exc:
                raise _upload_failure(exc) from exc
            if sum(item.size for item in staged) > BATCH_MAX_AGGREGATE_BYTES:
                raise AudioBatchServiceError(
                    "BATCH_AGGREGATE_SIZE_EXCEEDED",
                    "Batch audio bytes exceed the 1 GB aggregate limit.",
                    status_code=413,
                )

        request = _build_create_request(
            case_id=case_id,
            idempotency_key=idempotency_key,
            staged=staged,
            upload_options=upload_options,
        )
        fingerprint = canonical_batch_request_fingerprint(request)
        replay = find_idempotent_audio_batch(
            db,
            user_id=user_id,
            case_id=case_id,
            idempotency_key=request.idempotency_key,
        )
        if replay is not None:
            if replay.request_fingerprint_sha256 != fingerprint:
                raise AudioBatchIdempotencyConflict()
            _cleanup_uploads(staged, stored)
            return replay, False

        for item in staged:
            stored.append(finalize_staged_upload(item, case_id))

        language_id = _language_id(db, upload_options.language)
        bindings: list[AudioBatchItemBinding] = []
        for source in stored:
            task = Task(
                id=str(uuid4()),
                filename=source.original_filename,
                status="uploaded",
                case_id=case_id,
                user_id=user_id,
                result={},
            )
            db.add(task)
            db.flush()
            audio = AudioFile(
                filename=source.original_filename,
                case_id=case_id,
                task_id=task.id,
                file_path=source.relative_path,
                status="uploaded",
                language_id=language_id,
                uploaded_by=user_id,
                file_size=source.size,
                duration=None,
                audio_status_id=None,
                processed_at=None,
                error_message=None,
                is_archived=False,
                storage_type="local",
                storage_config={},
                extra_metadata={
                    "original_filename": source.original_filename,
                    "sha256": source.sha256,
                    "integrity_status": "verified_at_upload",
                    "evidence_source": "user_upload",
                },
            )
            db.add(audio)
            db.flush()
            task.result = {
                "audio_id": audio.id,
                "download_url": f"/api/v1/audio/{audio.id}/download",
                "filename": source.original_filename,
                "audio_sha256": source.sha256,
                "audio_integrity_status": "verified_at_upload",
            }
            bindings.append(AudioBatchItemBinding(task_id=task.id, audio_id=audio.id))

        created = create_or_replay_audio_batch(
            db, request=request, user_id=user_id, item_bindings=bindings
        )
        if not created.created:
            raise AudioBatchServiceError(
                "BATCH_REPLAY_RACE",
                "Audio batch replay could not be resolved safely.",
                status_code=409,
                retryable=True,
            )
        db.commit()
        # Keep the committed ORM identity. Response projection runs while this
        # request-scoped session is still open and reloads expired attributes.
        return created.batch, True
    except IntegrityError as exc:
        db.rollback()
        _cleanup_uploads(staged, stored)
        if request is None:
            raise AudioBatchServiceError(
                "BATCH_PERSISTENCE_FAILED",
                "Audio batch could not be persisted.",
                status_code=503,
                retryable=True,
            ) from exc
        replay = find_idempotent_audio_batch(
            db,
            user_id=user_id,
            case_id=case_id,
            idempotency_key=request.idempotency_key,
        )
        if replay is None:
            raise AudioBatchServiceError(
                "BATCH_PERSISTENCE_FAILED",
                "Audio batch could not be persisted.",
                status_code=503,
                retryable=True,
            ) from exc
        if replay.request_fingerprint_sha256 != canonical_batch_request_fingerprint(
            request
        ):
            raise AudioBatchIdempotencyConflict() from exc
        return replay, False
    except AudioBatchIdempotencyConflict as exc:
        db.rollback()
        _cleanup_uploads(staged, stored)
        raise _contract_error(exc) from exc
    except AudioBatchServiceError:
        db.rollback()
        _cleanup_uploads(staged, stored)
        raise
    except Exception as exc:
        db.rollback()
        _cleanup_uploads(staged, stored)
        raise AudioBatchServiceError(
            "BATCH_PERSISTENCE_FAILED",
            "Audio batch could not be persisted.",
            status_code=503,
            retryable=True,
        ) from exc


def audio_batch_response(batch: AudioBatch) -> AudioBatchResponse:
    items = sorted(batch.items, key=lambda item: item.position)
    return AudioBatchResponse.model_validate(
        {
            "id": batch.id,
            "case_id": batch.case_id,
            "status": batch.status,
            "requested_count": batch.requested_count,
            "completed_count": batch.completed_count,
            "failed_count": batch.failed_count,
            "cancelled_count": batch.cancelled_count,
            "total_size_bytes": batch.total_size_bytes,
            "error_code": batch.error_code,
            "created_at": batch.created_at,
            "updated_at": batch.updated_at or batch.created_at,
            "items": [
                {
                    "id": item.id,
                    "position": item.position,
                    "task_id": item.task_id,
                    "audio_id": item.audio_id,
                    "original_filename": item.original_filename,
                    "status": item.status,
                    "error_code": item.error_code,
                    "celery_task_id": item.celery_task_id,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at or item.created_at,
                }
                for item in items
            ],
        }
    )


def _locked_owned_batch(db: Session, *, batch_id: str, user_id: int) -> AudioBatch:
    normalized_id = normalize_audio_batch_id(batch_id)
    batch = (
        db.query(AudioBatch)
        .options(selectinload(AudioBatch.items), selectinload(AudioBatch.summary_jobs))
        .filter(AudioBatch.id == normalized_id, AudioBatch.user_id == user_id)
        .with_for_update()
        .one_or_none()
    )
    if batch is None:
        raise AudioBatchServiceError(
            "AUDIO_BATCH_NOT_FOUND", "Audio batch not found.", status_code=404
        )
    return batch


def _scoped_item_rows(
    db: Session, batch: AudioBatch
) -> tuple[dict[str, Task], dict[int, AudioFile]]:
    items = list(batch.items)
    tasks = {
        task.id: task
        for task in db.query(Task)
        .filter(Task.id.in_([item.task_id for item in items]))
        .all()
    }
    audios = {
        audio.id: audio
        for audio in db.query(AudioFile)
        .filter(AudioFile.id.in_([item.audio_id for item in items]))
        .all()
    }
    for item in items:
        task = tasks.get(item.task_id)
        audio = audios.get(item.audio_id)
        if (
            task is None
            or audio is None
            or task.case_id != batch.case_id
            or task.user_id != batch.user_id
            or audio.case_id != batch.case_id
            or audio.uploaded_by != batch.user_id
            or audio.task_id != task.id
        ):
            raise AudioBatchServiceError(
                "BATCH_ITEM_SCOPE_MISMATCH",
                "Batch item persistence is inconsistent.",
                status_code=409,
            )
    return tasks, audios


def queue_audio_batch_transcription(
    db: Session,
    *,
    batch_id: str,
    user_id: int,
    options: AudioBatchTranscribeRequest,
) -> AudioBatchAcceptedResponse:
    batch = _locked_owned_batch(db, batch_id=batch_id, user_id=user_id)
    tasks, audios = _scoped_item_rows(db, batch)
    if batch.status in {"queued", "processing", "cancel_requested"}:
        raise AudioBatchServiceError(
            "BATCH_TRANSCRIPTION_ALREADY_RUNNING",
            "Batch transcription is already active.",
            status_code=409,
        )
    if batch.status in {"succeeded", "cancelled"}:
        raise AudioBatchServiceError(
            "BATCH_TRANSCRIPTION_TERMINAL",
            "Batch transcription is already terminal.",
            status_code=409,
        )

    items_by_task = {item.task_id: item for item in batch.items}
    if any(task_id not in items_by_task for task_id in options.task_ids):
        raise AudioBatchServiceError(
            "BATCH_TRANSCRIPTION_SELECTION_INVALID",
            "Every selected task must belong to this batch.",
            status_code=422,
        )
    eligible = [items_by_task[task_id] for task_id in options.task_ids]
    if any(item.status not in {"uploaded", "failed"} for item in eligible):
        raise AudioBatchServiceError(
            "BATCH_TRANSCRIPTION_ITEM_NOT_ELIGIBLE",
            "Every selected batch item must be eligible for transcription.",
            status_code=409,
        )
    celery_task_id = str(uuid4())
    batch.upload_options = options.model_dump(mode="json", exclude={"task_ids"})
    batch.transcription_task_ids = list(options.task_ids)
    batch.status = "queued"
    batch.error_code = None
    for item in eligible:
        item.status = "queued"
        item.error_code = None
        item.celery_task_id = celery_task_id
        task = tasks[item.task_id]
        audio = audios[item.audio_id]
        task.status = "uploaded"
        task.error = None
        audio.status = "uploaded"
        audio.error_message = None
    db.commit()

    try:
        from src.worker.tasks.batch_task import transcribe_audio_batch_task

        transcribe_audio_batch_task.apply_async(
            kwargs={"batch_id": batch.id}, task_id=celery_task_id
        )
    except Exception as exc:
        failed = _locked_owned_batch(db, batch_id=batch.id, user_id=user_id)
        if failed.status == "queued":
            for item in failed.items:
                if item.status == "queued":
                    item.status = "failed"
                    item.error_code = "BATCH_ENQUEUE_FAILED"
            aggregate = derive_audio_batch_aggregate(
                [
                    item.status
                    for item in sorted(failed.items, key=lambda value: value.position)
                ]
            )
            failed.status = aggregate.status
            failed.completed_count = aggregate.completed_count
            failed.failed_count = aggregate.failed_count
            failed.cancelled_count = aggregate.cancelled_count
            failed.error_code = "BATCH_ENQUEUE_FAILED"
            db.commit()
        raise AudioBatchServiceError(
            "BATCH_ENQUEUE_FAILED",
            "Batch transcription could not be queued.",
            status_code=503,
            retryable=True,
        ) from exc
    return AudioBatchAcceptedResponse(batch_id=batch.id, status="queued")


def cancel_audio_batch(
    db: Session, *, batch_id: str, user_id: int
) -> AudioBatchAcceptedResponse:
    batch = _locked_owned_batch(db, batch_id=batch_id, user_id=user_id)
    _scoped_item_rows(db, batch)
    for job in batch.summary_jobs:
        if job.status == "queued":
            job.status = "cancelled"
            job.error_code = None
        elif job.status == "processing":
            job.status = "cancel_requested"
            job.error_code = None
    if batch.status in {"succeeded", "failed", "partially_succeeded", "cancelled"}:
        db.commit()
        return AudioBatchAcceptedResponse(batch_id=batch.id, status=batch.status)

    for item in batch.items:
        if item.status in {"uploaded", "queued", "failed"}:
            item.status = "cancelled"
            item.error_code = None
        elif item.status in {"transcribing", "cancel_requested"}:
            item.status = "cancel_requested"
            item.error_code = None
    aggregate = derive_audio_batch_aggregate(
        [item.status for item in sorted(batch.items, key=lambda value: value.position)]
    )
    batch.status = aggregate.status
    batch.completed_count = aggregate.completed_count
    batch.failed_count = aggregate.failed_count
    batch.cancelled_count = aggregate.cancelled_count
    batch.error_code = None
    db.commit()
    return AudioBatchAcceptedResponse(batch_id=batch.id, status=batch.status)


def _transcript_revision_id(result: dict[str, object], transcript_sha256: str) -> str:
    identity = released_investigation_run_identity(
        result.get("released_investigation_run")
    )
    if identity is not None and len(identity[1]) <= 255:
        return identity[1]
    return f"transcript-sha256:{transcript_sha256}"


def create_audio_batch_summary_job(
    db: Session,
    *,
    batch_id: str,
    user_id: int,
    request: AudioBatchSummaryRequest,
) -> AudioBatchSummaryJob:
    batch = _locked_owned_batch(db, batch_id=batch_id, user_id=user_id)
    tasks, _audios = _scoped_item_rows(db, batch)
    items_by_task = {item.task_id: item for item in batch.items}
    if any(task_id not in items_by_task for task_id in request.task_ids):
        raise AudioBatchServiceError(
            "BATCH_SUMMARY_SELECTION_INVALID",
            "Every selected task must belong to this batch.",
            status_code=422,
        )

    manifest: list[AudioBatchSummaryManifestItem] = []
    for position, task_id in enumerate(request.task_ids):
        item = items_by_task[task_id]
        task = tasks[task_id]
        result = task.result if isinstance(task.result, dict) else {}
        transcript = result.get("transcription")
        if (
            item.status != "transcribed"
            or task.status == "failed"
            or not isinstance(transcript, str)
            or not transcript.strip()
        ):
            raise AudioBatchServiceError(
                "BATCH_SUMMARY_SOURCE_NOT_READY",
                "Every selected source must have a usable transcript.",
                status_code=409,
            )
        transcript_sha256 = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
        manifest.append(
            AudioBatchSummaryManifestItem(
                position=position,
                batch_item_id=item.id,
                task_id=item.task_id,
                audio_id=item.audio_id,
                filename=item.original_filename,
                transcript_sha256=transcript_sha256,
                source_revision_id=_transcript_revision_id(result, transcript_sha256),
            )
        )

    summary_options = request.model_dump(
        mode="json", exclude={"task_ids", "user_prompt"}
    )
    celery_task_id = str(uuid4())
    job = AudioBatchSummaryJob(
        id=str(uuid4()),
        batch_id=batch.id,
        case_id=batch.case_id,
        user_id=batch.user_id,
        status="queued",
        selected_count=len(manifest),
        source_manifest=[item.model_dump(mode="json") for item in manifest],
        source_manifest_sha256=canonical_summary_source_manifest_sha256(manifest),
        summary_options=summary_options,
        # This means the worker actually applied the preference, not merely that
        # the API accepted one. The worker flips it only at the model boundary.
        user_prompt_applied=False,
        celery_task_id=celery_task_id,
        error_code=None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        from src.worker.tasks.summarize_task import summarize_audio_batch_job_task

        summarize_audio_batch_job_task.apply_async(
            kwargs={"summary_job_id": job.id, "user_prompt": request.user_prompt},
            task_id=celery_task_id,
        )
    except Exception as exc:
        failed = (
            db.query(AudioBatchSummaryJob)
            .filter(
                AudioBatchSummaryJob.id == job.id,
                AudioBatchSummaryJob.batch_id == batch.id,
                AudioBatchSummaryJob.user_id == user_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if failed is not None and failed.status == "queued":
            failed.status = "failed"
            failed.error_code = "SUMMARY_ENQUEUE_FAILED"
            db.commit()
        raise AudioBatchServiceError(
            "SUMMARY_ENQUEUE_FAILED",
            "Merged summary could not be queued.",
            status_code=503,
            retryable=True,
        ) from exc
    return job


def get_owned_audio_batch_summary_job(
    db: Session,
    *,
    batch_id: str,
    summary_job_id: str,
    user_id: int,
) -> AudioBatchSummaryJob | None:
    normalized_batch_id = normalize_audio_batch_id(batch_id)
    normalized_job_id = normalize_audio_batch_id(summary_job_id)
    return (
        db.query(AudioBatchSummaryJob)
        .options(selectinload(AudioBatchSummaryJob.summary))
        .filter(
            AudioBatchSummaryJob.id == normalized_job_id,
            AudioBatchSummaryJob.batch_id == normalized_batch_id,
            AudioBatchSummaryJob.user_id == user_id,
        )
        .one_or_none()
    )


def audio_batch_summary_job_response(
    job: AudioBatchSummaryJob,
) -> AudioBatchSummaryJobResponse:
    try:
        manifest = [
            AudioBatchSummaryManifestItem.model_validate(item)
            for item in (job.source_manifest or [])
        ]
    except (ValidationError, AudioBatchContractError) as exc:
        raise AudioBatchServiceError(
            "SUMMARY_MANIFEST_INVALID",
            "Merged summary provenance is invalid.",
            status_code=409,
        ) from exc
    if len(manifest) != job.selected_count or (
        canonical_summary_source_manifest_sha256(manifest) != job.source_manifest_sha256
    ):
        raise AudioBatchServiceError(
            "SUMMARY_MANIFEST_INVALID",
            "Merged summary provenance is invalid.",
            status_code=409,
        )

    summary_text: str | None = None
    if job.status == "succeeded":
        summary = job.summary
        if not isinstance(summary, Summary) or not isinstance(summary.content, str):
            raise AudioBatchServiceError(
                "SUMMARY_RESULT_INVALID",
                "Merged summary result is invalid.",
                status_code=409,
            )
        summary_text = summary.content
    error = None
    if job.error_code:
        error = {
            "code": job.error_code,
            "message": "Merged summary processing failed.",
            "retryable": job.error_code == "SUMMARY_ENQUEUE_FAILED",
        }
    return AudioBatchSummaryJobResponse.model_validate(
        {
            "batch_id": job.batch_id,
            "summary_job_id": job.id,
            "status": job.status,
            "summary": summary_text,
            "source_manifest": [
                {
                    "position": item.position,
                    "task_id": item.task_id,
                    "filename": item.filename,
                }
                for item in manifest
            ],
            "user_prompt_applied": bool(job.user_prompt_applied),
            "error": error,
        }
    )


__all__ = [
    "AudioBatchServiceError",
    "audio_batch_response",
    "audio_batch_summary_job_response",
    "cancel_audio_batch",
    "create_audio_batch_from_uploads",
    "create_audio_batch_summary_job",
    "get_owned_audio_batch_summary_job",
    "queue_audio_batch_transcription",
]
