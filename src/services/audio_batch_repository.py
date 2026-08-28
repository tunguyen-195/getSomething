"""Transaction-scoped persistence helpers for durable multi-audio batches."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session, selectinload

from src.database.models.models import AudioBatch, AudioBatchItem, AudioFile, Task
from src.services.audio_batch_contracts import (
    AudioBatchContractError,
    AudioBatchCreateRequest,
    AudioBatchItemBinding,
    canonical_batch_request_fingerprint,
    derive_audio_batch_aggregate,
    normalize_audio_batch_id,
    normalize_batch_idempotency_key,
)


class AudioBatchIdempotencyConflict(AudioBatchContractError):
    def __init__(self) -> None:
        super().__init__(
            "BATCH_IDEMPOTENCY_CONFLICT",
            "The idempotency key is already bound to a different batch request.",
        )


@dataclass(frozen=True)
class AudioBatchCreateResult:
    batch: AudioBatch
    created: bool


def get_owned_audio_batch(
    db: Session,
    *,
    batch_id: str,
    user_id: int,
    case_id: int | None = None,
) -> AudioBatch | None:
    """Return only a creator-owned batch; callers expose foreign batches as 404.

    The API layer must additionally call ``assert_case_access`` for the resolved case.
    Batch ownership is intentionally narrower than general case membership in Phase 1.
    """

    normalized_id = normalize_audio_batch_id(batch_id)
    if type(user_id) is not int or user_id < 1:
        raise AudioBatchContractError(
            "INVALID_BATCH_OWNER", "user_id must be a positive integer."
        )
    query = (
        db.query(AudioBatch)
        .options(selectinload(AudioBatch.items))
        .filter(
            AudioBatch.id == normalized_id,
            AudioBatch.user_id == user_id,
        )
    )
    if case_id is not None:
        if type(case_id) is not int or case_id < 1:
            raise AudioBatchContractError(
                "INVALID_BATCH_CASE", "case_id must be a positive integer."
            )
        query = query.filter(AudioBatch.case_id == case_id)
    return query.one_or_none()


def find_idempotent_audio_batch(
    db: Session,
    *,
    user_id: int,
    case_id: int,
    idempotency_key: str,
) -> AudioBatch | None:
    """Resolve replay identity only inside the exact user and case scope."""

    if type(user_id) is not int or user_id < 1:
        raise AudioBatchContractError(
            "INVALID_BATCH_OWNER", "user_id must be a positive integer."
        )
    if type(case_id) is not int or case_id < 1:
        raise AudioBatchContractError(
            "INVALID_BATCH_CASE", "case_id must be a positive integer."
        )
    normalized_key = normalize_batch_idempotency_key(idempotency_key)
    return (
        db.query(AudioBatch)
        .options(selectinload(AudioBatch.items))
        .filter(
            AudioBatch.user_id == user_id,
            AudioBatch.case_id == case_id,
            AudioBatch.idempotency_key == normalized_key,
        )
        .one_or_none()
    )


def create_or_replay_audio_batch(
    db: Session,
    *,
    request: AudioBatchCreateRequest,
    user_id: int,
    item_bindings: list[AudioBatchItemBinding],
) -> AudioBatchCreateResult:
    """Create one parent/items set or return a byte-equivalent prior request.

    The caller owns commit/rollback and should translate a unique-constraint race by
    re-reading with ``find_idempotent_audio_batch`` in a new transaction.
    """

    fingerprint = canonical_batch_request_fingerprint(request)
    existing = find_idempotent_audio_batch(
        db,
        user_id=user_id,
        case_id=request.case_id,
        idempotency_key=request.idempotency_key,
    )
    if existing is not None:
        if existing.request_fingerprint_sha256 != fingerprint:
            raise AudioBatchIdempotencyConflict()
        return AudioBatchCreateResult(batch=existing, created=False)

    if len(item_bindings) != len(request.files):
        raise AudioBatchContractError(
            "BATCH_ITEM_BINDING_MISMATCH",
            "Every validated file requires exactly one task/audio binding.",
        )
    task_ids = [binding.task_id for binding in item_bindings]
    audio_ids = [binding.audio_id for binding in item_bindings]
    if len(task_ids) != len(set(task_ids)) or len(audio_ids) != len(set(audio_ids)):
        raise AudioBatchContractError(
            "DUPLICATE_BATCH_ITEM_BINDING",
            "Task and audio bindings must be unique within a batch.",
        )

    tasks_by_id = {
        task.id: task for task in db.query(Task).filter(Task.id.in_(task_ids)).all()
    }
    audio_by_id = {
        audio.id: audio
        for audio in db.query(AudioFile).filter(AudioFile.id.in_(audio_ids)).all()
    }
    for binding in item_bindings:
        task = tasks_by_id.get(binding.task_id)
        audio = audio_by_id.get(binding.audio_id)
        if (
            task is None
            or audio is None
            or task.case_id != request.case_id
            or task.user_id != user_id
            or audio.case_id != request.case_id
            or audio.uploaded_by != user_id
            or audio.task_id != binding.task_id
        ):
            raise AudioBatchContractError(
                "BATCH_ITEM_SCOPE_MISMATCH",
                "Every task/audio binding must belong to the batch owner and case.",
            )

    batch = AudioBatch(
        id=str(uuid4()),
        case_id=request.case_id,
        user_id=user_id,
        status="created",
        requested_count=len(request.files),
        completed_count=0,
        failed_count=0,
        cancelled_count=0,
        total_size_bytes=request.total_size_bytes,
        upload_options=request.upload_options.model_dump(mode="json"),
        transcription_task_ids=[],
        idempotency_key=request.idempotency_key,
        request_fingerprint_sha256=fingerprint,
    )
    batch.items = [
        AudioBatchItem(
            task_id=binding.task_id,
            audio_id=binding.audio_id,
            position=position,
            original_filename=file.original_filename,
            verified_audio_sha256=file.verified_audio_sha256,
            status="uploaded",
        )
        for position, (file, binding) in enumerate(
            zip(request.files, item_bindings, strict=True)
        )
    ]
    db.add(batch)
    db.flush()
    return AudioBatchCreateResult(batch=batch, created=True)


def refresh_audio_batch_aggregate(batch: AudioBatch) -> None:
    """Update persisted counters/status from all item rows deterministically."""

    if len(batch.items) != batch.requested_count:
        raise AudioBatchContractError(
            "BATCH_ITEM_COUNT_MISMATCH",
            "Persisted batch item count does not match requested_count.",
        )
    aggregate = derive_audio_batch_aggregate([item.status for item in batch.items])
    batch.status = aggregate.status
    batch.completed_count = aggregate.completed_count
    batch.failed_count = aggregate.failed_count
    batch.cancelled_count = aggregate.cancelled_count


__all__ = [
    "AudioBatchCreateResult",
    "AudioBatchIdempotencyConflict",
    "create_or_replay_audio_batch",
    "find_idempotent_audio_batch",
    "get_owned_audio_batch",
    "normalize_audio_batch_id",
    "refresh_audio_batch_aggregate",
]
