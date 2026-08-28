"""Durable Celery orchestration for ordered multi-audio transcription."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.database.config.database import SessionLocal
from src.database.models.models import AudioBatch, AudioBatchItem, AudioFile, Task
from src.services.audio_batch_contracts import (
    AudioBatchContractError,
    AudioBatchUploadOptions,
    derive_audio_batch_aggregate,
    normalize_audio_batch_id,
)
from src.services.audio_storage import compute_sha256, resolve_audio_path
from src.worker.worker import celery_app


logger = logging.getLogger(__name__)


_TERMINAL_ITEM_STATUSES: Final[frozenset[str]] = frozenset(
    {"transcribed", "failed", "cancelled"}
)
_TERMINAL_BATCH_STATUSES: Final[frozenset[str]] = frozenset({"succeeded", "cancelled"})
_SAFE_BATCH_MESSAGES: Final[dict[str, str]] = {
    "BATCH_NOT_FOUND": "The audio batch is unavailable.",
    "BATCH_OPTIONS_INVALID": "The audio batch transcription options are invalid.",
    "BATCH_SELECTION_INVALID": "The audio batch transcription selection is invalid.",
    "BATCH_ITEM_COUNT_MISMATCH": "The audio batch item set is incomplete.",
    "BATCH_ITEM_SCOPE_MISMATCH": "An audio batch item failed its ownership check.",
    "BATCH_SOURCE_UNAVAILABLE": "An audio source is unavailable.",
    "BATCH_SOURCE_INTEGRITY_MISMATCH": "An audio source failed integrity verification.",
    "BATCH_TRANSCRIPTION_FAILED": "Audio transcription failed.",
    "BATCH_TRANSCRIPT_INVALID": "Audio transcription produced no verified transcript.",
    "BATCH_PERSISTENCE_FAILED": "The audio batch state could not be persisted.",
}


class SafeAudioBatchTaskError(RuntimeError):
    """A worker failure whose code and message are safe for durable state."""

    def __init__(self, code: str) -> None:
        self.code = (
            code if code in _SAFE_BATCH_MESSAGES else "BATCH_TRANSCRIPTION_FAILED"
        )
        super().__init__(_SAFE_BATCH_MESSAGES[self.code])


def _request_id(task: Any, batch_id: str) -> str:
    request = getattr(task, "request", None)
    value = getattr(request, "id", None)
    if isinstance(value, str) and value.strip():
        return value
    # Direct ``Task.run`` calls in the focused harness have no Celery request.
    return f"eager-audio-batch:{batch_id}"


def _locked_batch(db: Session, batch_id: str) -> AudioBatch | None:
    return (
        db.query(AudioBatch)
        .filter(AudioBatch.id == batch_id)
        .with_for_update()
        .one_or_none()
    )


def _locked_items(db: Session, batch_id: str) -> list[AudioBatchItem]:
    return (
        db.query(AudioBatchItem)
        .filter(AudioBatchItem.batch_id == batch_id)
        .order_by(AudioBatchItem.position.asc(), AudioBatchItem.id.asc())
        .with_for_update()
        .all()
    )


def _refresh_parent(
    db: Session,
    batch: AudioBatch,
    *,
    items: list[AudioBatchItem] | None = None,
) -> list[AudioBatchItem]:
    resolved_items = items if items is not None else _locked_items(db, batch.id)
    if len(resolved_items) != batch.requested_count:
        raise SafeAudioBatchTaskError("BATCH_ITEM_COUNT_MISMATCH")
    if [item.position for item in resolved_items] != list(range(batch.requested_count)):
        raise SafeAudioBatchTaskError("BATCH_ITEM_COUNT_MISMATCH")

    try:
        aggregate = derive_audio_batch_aggregate(
            [item.status for item in resolved_items]
        )
    except (AudioBatchContractError, ValidationError, ValueError) as exc:
        raise SafeAudioBatchTaskError("BATCH_ITEM_COUNT_MISMATCH") from exc

    batch.status = aggregate.status
    batch.completed_count = aggregate.completed_count
    batch.failed_count = aggregate.failed_count
    batch.cancelled_count = aggregate.cancelled_count
    if aggregate.failed_count and aggregate.status == "partially_succeeded":
        batch.error_code = "BATCH_TRANSCRIPTION_FAILED"
    elif aggregate.failed_count and aggregate.status == "failed":
        batch.error_code = "BATCH_TRANSCRIPTION_FAILED"
    elif not aggregate.failed_count:
        batch.error_code = None
    db.flush()
    return resolved_items


def _mark_nonterminal_items_failed(
    db: Session,
    batch: AudioBatch,
    code: str,
) -> None:
    items = _locked_items(db, batch.id)
    for item in items:
        if item.status not in _TERMINAL_ITEM_STATUSES:
            item.status = "failed"
            item.error_code = code
    _refresh_parent(db, batch, items=items)


def _prepare_batch(
    db: Session,
    *,
    batch_id: str,
    celery_task_id: str,
) -> tuple[str, list[int], AudioBatchUploadOptions | None]:
    batch = _locked_batch(db, batch_id)
    if batch is None:
        return "missing", [], None
    items = _locked_items(db, batch_id)
    if len(items) != batch.requested_count or [item.position for item in items] != list(
        range(batch.requested_count)
    ):
        _mark_nonterminal_items_failed(db, batch, "BATCH_ITEM_COUNT_MISMATCH")
        return "invalid", [], None

    selection = batch.transcription_task_ids
    items_by_task_id = {item.task_id: item for item in items}
    if (
        not isinstance(selection, list)
        or not selection
        or len(selection) > batch.requested_count
        or any(type(task_id) is not str or not task_id for task_id in selection)
        or len(selection) != len(set(selection))
        or any(task_id not in items_by_task_id for task_id in selection)
    ):
        selected_existing = (
            [
                items_by_task_id[task_id]
                for task_id in selection
                if type(task_id) is str and task_id in items_by_task_id
            ]
            if isinstance(selection, list)
            else []
        )
        for item in selected_existing:
            if item.status not in _TERMINAL_ITEM_STATUSES:
                item.status = "failed"
                item.error_code = "BATCH_SELECTION_INVALID"
        _refresh_parent(db, batch, items=items)
        batch.error_code = "BATCH_SELECTION_INVALID"
        return "invalid", [], None
    selected_items = [items_by_task_id[task_id] for task_id in selection]

    if batch.status in _TERMINAL_BATCH_STATUSES:
        _refresh_parent(db, batch, items=items)
        return "terminal", [], None

    if batch.status == "cancel_requested" or any(
        item.status == "cancel_requested" for item in items
    ):
        for item in items:
            if item.status not in _TERMINAL_ITEM_STATUSES:
                item.status = "cancelled"
                item.error_code = None
        _refresh_parent(db, batch, items=items)
        return "cancelled", [], None

    # Redelivery after a partial/failed run only refreshes durable state. A new
    # API dispatch resets retryable items to queued before publishing a task.
    if selected_items and all(
        item.status in _TERMINAL_ITEM_STATUSES for item in selected_items
    ):
        _refresh_parent(db, batch, items=items)
        return "terminal", [], None

    foreign_claim = next(
        (
            item.celery_task_id
            for item in selected_items
            if item.status not in _TERMINAL_ITEM_STATUSES
            and item.celery_task_id
            and item.celery_task_id != celery_task_id
        ),
        None,
    )
    if foreign_claim is not None:
        _refresh_parent(db, batch, items=items)
        return "already_dispatched", [], None

    try:
        options = AudioBatchUploadOptions.model_validate(batch.upload_options or {})
    except (AudioBatchContractError, ValidationError, TypeError, ValueError):
        for item in selected_items:
            if item.status not in _TERMINAL_ITEM_STATUSES:
                item.status = "failed"
                item.error_code = "BATCH_OPTIONS_INVALID"
        _refresh_parent(db, batch, items=items)
        return "invalid", [], None

    item_ids: list[int] = []
    for item in selected_items:
        if item.status in _TERMINAL_ITEM_STATUSES:
            continue
        if item.status not in {"queued", "transcribing"}:
            item.status = "failed"
            item.error_code = "BATCH_SELECTION_INVALID"
            continue
        item.celery_task_id = celery_task_id
        item.error_code = None
        item_ids.append(item.id)
    _refresh_parent(db, batch, items=items)
    if any(item.error_code == "BATCH_SELECTION_INVALID" for item in selected_items):
        batch.error_code = "BATCH_SELECTION_INVALID"
        return "invalid", [], None
    return "ready", item_ids, options


def _claim_item(
    db: Session,
    *,
    batch_id: str,
    item_id: int,
    celery_task_id: str,
) -> tuple[str, str | None]:
    batch = _locked_batch(db, batch_id)
    if batch is None:
        return "missing", None
    item = (
        db.query(AudioBatchItem)
        .filter(
            AudioBatchItem.id == item_id,
            AudioBatchItem.batch_id == batch_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if item is None:
        _mark_nonterminal_items_failed(db, batch, "BATCH_ITEM_COUNT_MISMATCH")
        return "invalid", None
    if item.status in _TERMINAL_ITEM_STATUSES:
        _refresh_parent(db, batch)
        return "terminal", item.task_id
    if batch.status == "cancel_requested" or item.status == "cancel_requested":
        item.status = "cancelled"
        item.error_code = None
        _refresh_parent(db, batch)
        return "cancelled", item.task_id
    if item.celery_task_id != celery_task_id:
        _refresh_parent(db, batch)
        return "already_dispatched", item.task_id

    task = db.query(Task).filter(Task.id == item.task_id).one_or_none()
    audio = db.query(AudioFile).filter(AudioFile.id == item.audio_id).one_or_none()
    if (
        task is None
        or audio is None
        or task.id != audio.task_id
        or task.case_id != batch.case_id
        or task.user_id != batch.user_id
        or audio.case_id != batch.case_id
        or audio.uploaded_by != batch.user_id
    ):
        item.status = "failed"
        item.error_code = "BATCH_ITEM_SCOPE_MISMATCH"
        _refresh_parent(db, batch)
        return "invalid", item.task_id

    stored_sha256 = (audio.extra_metadata or {}).get("sha256")
    if stored_sha256 != item.verified_audio_sha256:
        item.status = "failed"
        item.error_code = "BATCH_SOURCE_INTEGRITY_MISMATCH"
        _sync_scoped_source_failure(
            db,
            batch=batch,
            item=item,
            code="BATCH_SOURCE_INTEGRITY_MISMATCH",
        )
        _refresh_parent(db, batch)
        return "invalid", item.task_id

    # A worker may die after ASR durably published the transcript but before
    # the item finalizer ran. Reuse that verified result instead of invoking
    # the recognizer a second time.
    task_result = task.result if isinstance(task.result, dict) else {}
    if (
        task.status == "transcribed"
        and isinstance(task_result.get("transcription"), str)
        and bool(task_result.get("transcription", "").strip())
        and task_result.get("audio_sha256") == item.verified_audio_sha256
    ):
        item.status = "transcribing"
        item.error_code = None
        _refresh_parent(db, batch)
        return "recovered", item.task_id

    item.status = "transcribing"
    item.error_code = None
    _refresh_parent(db, batch)
    return "claimed", item.task_id


def _verify_audio_bytes(batch_id: str, item_id: int) -> str | None:
    with SessionLocal() as db:
        item = (
            db.query(AudioBatchItem)
            .filter(
                AudioBatchItem.id == item_id,
                AudioBatchItem.batch_id == batch_id,
            )
            .one_or_none()
        )
        if item is None:
            return "BATCH_ITEM_COUNT_MISMATCH"
        audio = db.query(AudioFile).filter(AudioFile.id == item.audio_id).one_or_none()
        if audio is None:
            return "BATCH_SOURCE_UNAVAILABLE"
        try:
            path: Path = resolve_audio_path(audio.file_path)
            if not path.is_file():
                return "BATCH_SOURCE_UNAVAILABLE"
            actual_sha256 = compute_sha256(path)
        except (HTTPException, OSError, TypeError, ValueError):
            return "BATCH_SOURCE_UNAVAILABLE"
        if actual_sha256 != item.verified_audio_sha256:
            return "BATCH_SOURCE_INTEGRITY_MISMATCH"
    return None


def _item_audio_sha256(batch_id: str, item_id: int) -> str | None:
    with SessionLocal() as db:
        item = (
            db.query(AudioBatchItem)
            .filter(
                AudioBatchItem.id == item_id,
                AudioBatchItem.batch_id == batch_id,
            )
            .one_or_none()
        )
        return item.verified_audio_sha256 if item is not None else None


def _safe_transcription_error(exc: Exception) -> str:
    if isinstance(exc, SafeAudioBatchTaskError):
        return exc.code
    if isinstance(exc, HTTPException) and exc.status_code == 404:
        return "BATCH_SOURCE_UNAVAILABLE"
    return "BATCH_TRANSCRIPTION_FAILED"


def _sync_scoped_source_failure(
    db: Session,
    *,
    batch: AudioBatch,
    item: AudioBatchItem,
    code: str,
) -> None:
    """Project a safe item failure only onto its still-valid task/audio binding."""

    task = db.query(Task).filter(Task.id == item.task_id).one_or_none()
    audio = db.query(AudioFile).filter(AudioFile.id == item.audio_id).one_or_none()
    if (
        task is None
        or audio is None
        or audio.task_id != task.id
        or task.case_id != batch.case_id
        or task.user_id != batch.user_id
        or audio.case_id != batch.case_id
        or audio.uploaded_by != batch.user_id
    ):
        return
    message = _SAFE_BATCH_MESSAGES.get(
        code, _SAFE_BATCH_MESSAGES["BATCH_TRANSCRIPTION_FAILED"]
    )
    task.status = "failed"
    task.error = message
    audio.status = "failed"
    audio.error_message = message


def _finish_item(
    *,
    batch_id: str,
    item_id: int,
    result: object = None,
    failure_code: str | None = None,
) -> None:
    with SessionLocal() as db:
        try:
            batch = _locked_batch(db, batch_id)
            if batch is None:
                raise SafeAudioBatchTaskError("BATCH_NOT_FOUND")
            item = (
                db.query(AudioBatchItem)
                .filter(
                    AudioBatchItem.id == item_id,
                    AudioBatchItem.batch_id == batch_id,
                )
                .with_for_update()
                .one_or_none()
            )
            if item is None:
                _mark_nonterminal_items_failed(db, batch, "BATCH_ITEM_COUNT_MISMATCH")
                db.commit()
                return

            if batch.status == "cancel_requested" or item.status == "cancel_requested":
                item.status = "cancelled"
                item.error_code = None
                _refresh_parent(db, batch)
                db.commit()
                return

            task = db.query(Task).filter(Task.id == item.task_id).one_or_none()
            if failure_code is None:
                task_result = (
                    task.result
                    if task is not None and isinstance(task.result, dict)
                    else {}
                )
                transcript = task_result.get("transcription")
                result_audio_sha256 = (
                    result.get("audio_sha256") if isinstance(result, dict) else None
                )
                if (
                    not isinstance(transcript, str)
                    or not transcript.strip()
                    or result_audio_sha256 != item.verified_audio_sha256
                    or task_result.get("audio_sha256") != item.verified_audio_sha256
                ):
                    failure_code = "BATCH_TRANSCRIPT_INVALID"

            if failure_code is None:
                item.status = "transcribed"
                item.error_code = None
            else:
                code = (
                    failure_code
                    if failure_code in _SAFE_BATCH_MESSAGES
                    else "BATCH_TRANSCRIPTION_FAILED"
                )
                item.status = "failed"
                item.error_code = code
                _sync_scoped_source_failure(
                    db,
                    batch=batch,
                    item=item,
                    code=code,
                )
            _refresh_parent(db, batch)
            db.commit()
        except Exception:
            db.rollback()
            raise


def _finalize_batch(batch_id: str) -> dict[str, object]:
    with SessionLocal() as db:
        try:
            batch = _locked_batch(db, batch_id)
            if batch is None:
                raise SafeAudioBatchTaskError("BATCH_NOT_FOUND")
            items = _refresh_parent(db, batch)
            payload = {
                "status": batch.status,
                "batch_id": batch.id,
                "requested_count": batch.requested_count,
                "completed_count": batch.completed_count,
                "failed_count": batch.failed_count,
                "cancelled_count": batch.cancelled_count,
                "items": [
                    {
                        "position": item.position,
                        "task_id": item.task_id,
                        "status": item.status,
                        "error_code": item.error_code,
                    }
                    for item in items
                ],
            }
            db.commit()
            return payload
        except Exception:
            db.rollback()
            raise


@celery_app.task(bind=True, name="tasks.transcribe_audio_batch")
def transcribe_audio_batch_task(self: Any, batch_id: str) -> dict[str, object]:
    """Transcribe one ordered batch sequentially with durable per-item recovery."""

    try:
        normalized_batch_id = normalize_audio_batch_id(batch_id)
    except AudioBatchContractError as exc:
        raise SafeAudioBatchTaskError("BATCH_NOT_FOUND") from exc
    celery_task_id = _request_id(self, normalized_batch_id)
    logger.info(
        "[CELERY_AUDIO_BATCH] Started | batch_id=%s | celery_id=%s",
        normalized_batch_id,
        celery_task_id,
    )

    with SessionLocal() as db:
        try:
            disposition, item_ids, options = _prepare_batch(
                db,
                batch_id=normalized_batch_id,
                celery_task_id=celery_task_id,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

    if disposition == "missing":
        raise SafeAudioBatchTaskError("BATCH_NOT_FOUND")
    if disposition != "ready" or options is None:
        return _finalize_batch(normalized_batch_id)

    from src.services.transcription.transcribe_service_v2 import transcribe_audio_v2

    for item_id in item_ids:
        with SessionLocal() as db:
            try:
                item_disposition, task_id = _claim_item(
                    db,
                    batch_id=normalized_batch_id,
                    item_id=item_id,
                    celery_task_id=celery_task_id,
                )
                db.commit()
            except Exception:
                db.rollback()
                raise

        if item_disposition == "already_dispatched":
            break
        if item_disposition == "recovered":
            integrity_error = _verify_audio_bytes(normalized_batch_id, item_id)
            _finish_item(
                batch_id=normalized_batch_id,
                item_id=item_id,
                result={"audio_sha256": None}
                if integrity_error is not None
                else {"audio_sha256": _item_audio_sha256(normalized_batch_id, item_id)},
                failure_code=integrity_error,
            )
            continue
        if item_disposition != "claimed" or task_id is None:
            continue

        integrity_error = _verify_audio_bytes(normalized_batch_id, item_id)
        if integrity_error is not None:
            _finish_item(
                batch_id=normalized_batch_id,
                item_id=item_id,
                failure_code=integrity_error,
            )
            continue

        try:
            with SessionLocal() as db:
                try:
                    result = transcribe_audio_v2(
                        task_id=task_id,
                        db=db,
                        enable_diarization=options.enable_diarization,
                        diarization_method=options.diarization_method,
                        language=options.language,
                        fast_mode=options.fast_mode,
                    )
                except Exception:
                    db.rollback()
                    raise
        except Exception as exc:
            logger.error(
                "[CELERY_AUDIO_BATCH] Item failed | batch_id=%s | item_id=%s | error_type=%s",
                normalized_batch_id,
                item_id,
                type(exc).__name__,
            )
            _finish_item(
                batch_id=normalized_batch_id,
                item_id=item_id,
                failure_code=_safe_transcription_error(exc),
            )
            continue

        _finish_item(
            batch_id=normalized_batch_id,
            item_id=item_id,
            result=result,
        )

    payload = _finalize_batch(normalized_batch_id)
    logger.info(
        "[CELERY_AUDIO_BATCH] Finished | batch_id=%s | status=%s | completed=%s | failed=%s | cancelled=%s",
        normalized_batch_id,
        payload["status"],
        payload["completed_count"],
        payload["failed_count"],
        payload["cancelled_count"],
    )
    return payload


__all__ = ["SafeAudioBatchTaskError", "transcribe_audio_batch_task"]
