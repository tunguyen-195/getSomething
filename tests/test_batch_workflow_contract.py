from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect

from src.database.config.database import SessionLocal
from src.database.models.models import (
    AudioBatch,
    AudioBatchItem,
    AudioBatchSummaryJob,
    AudioFile,
    Case,
    CasePriority,
    CaseStatus,
    Language,
    Task,
    User,
)
from src.services.audio_batch_contracts import (
    AudioBatchContractError,
    AudioBatchCreateRequest,
    AudioBatchFileDescriptor,
    AudioBatchItemBinding,
    AudioBatchResponse,
    AudioBatchSummaryManifestItem,
    AudioBatchSummaryRequest,
    AudioBatchTranscribeRequest,
    BATCH_MAX_AGGREGATE_BYTES,
    BATCH_MAX_FILE_BYTES,
    BATCH_MAX_FILES,
    canonical_batch_request_fingerprint,
    canonical_summary_source_manifest_sha256,
    derive_audio_batch_aggregate,
)
from src.services.audio_batch_repository import (
    AudioBatchIdempotencyConflict,
    create_or_replay_audio_batch,
    get_owned_audio_batch,
    normalize_audio_batch_id,
    refresh_audio_batch_aggregate,
)


SHA_A = "a" * 64


def _descriptor(
    position: int,
    *,
    size_bytes: int = 1,
    filename: str | None = None,
) -> dict[str, object]:
    return {
        "original_filename": filename or f"audio-{position}.wav",
        "size_bytes": size_bytes,
        "verified_audio_sha256": f"{position:064x}"[-64:],
    }


def test_batch_create_contract_enforces_count_file_and_aggregate_limits() -> None:
    accepted = AudioBatchCreateRequest(
        case_id=1,
        idempotency_key=" replay-key ",
        files=[_descriptor(index) for index in range(BATCH_MAX_FILES)],
    )
    assert accepted.idempotency_key == "replay-key"
    assert len(accepted.files) == BATCH_MAX_FILES

    with pytest.raises(ValidationError):
        AudioBatchCreateRequest(
            case_id=1,
            idempotency_key="too-many",
            files=[_descriptor(index) for index in range(BATCH_MAX_FILES + 1)],
        )
    with pytest.raises(ValidationError):
        AudioBatchFileDescriptor.model_validate(
            _descriptor(1, size_bytes=BATCH_MAX_FILE_BYTES + 1)
        )
    with pytest.raises(ValidationError, match="1 GB aggregate limit"):
        AudioBatchCreateRequest(
            case_id=1,
            idempotency_key="aggregate",
            files=[
                _descriptor(index, size_bytes=BATCH_MAX_FILE_BYTES)
                for index in range(
                    BATCH_MAX_AGGREGATE_BYTES // BATCH_MAX_FILE_BYTES + 1
                )
            ],
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("filename", "../audio.wav"),
        ("filename", "safe\u202eaudio.wav"),
        ("idempotency", "safe\u2066key"),
    ],
)
def test_batch_contract_rejects_paths_and_unicode_format_controls(
    field: str, value: str
) -> None:
    payload = {
        "case_id": 1,
        "idempotency_key": value if field == "idempotency" else "safe-key",
        "files": [
            _descriptor(1, filename=value if field == "filename" else "safe.wav")
        ],
    }
    with pytest.raises(ValidationError):
        AudioBatchCreateRequest.model_validate(payload)


def test_batch_contract_rejects_unicode_equivalent_duplicate_filenames() -> None:
    with pytest.raises(ValidationError, match="duplicate filenames"):
        AudioBatchCreateRequest(
            case_id=1,
            idempotency_key="duplicates",
            files=[
                _descriptor(1, filename="AUDIO.wav"),
                _descriptor(2, filename="ＡＵＤＩＯ.wav"),
            ],
        )


def test_batch_transcription_selection_is_explicit_ordered_and_unique() -> None:
    request = AudioBatchTranscribeRequest(
        task_ids=["task-2", "task-1"],
        enable_diarization=False,
        diarization_method="none",
    )
    assert request.task_ids == ["task-2", "task-1"]
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        AudioBatchTranscribeRequest(task_ids=["task-1", "task-1"])
    with pytest.raises(ValidationError):
        AudioBatchTranscribeRequest(task_ids=[])
    with pytest.raises(ValidationError):
        AudioBatchTranscribeRequest(task_ids=["task\u202e-1"])


def test_summary_selection_and_manifest_hash_are_strict_ordered_contracts() -> None:
    request = AudioBatchSummaryRequest(
        task_ids=["task-2", "task-1"],
        summary_type="detailed",
        min_length=100,
        max_length=400,
        user_prompt=" focus ",
    )
    assert request.user_prompt == "focus"
    with pytest.raises(ValidationError, match="must not contain duplicates"):
        AudioBatchSummaryRequest(task_ids=["task-1", "task-1"])

    manifest = [
        AudioBatchSummaryManifestItem(
            position=index,
            batch_item_id=index + 1,
            task_id=task_id,
            audio_id=index + 1,
            filename=f"{task_id}.wav",
            transcript_sha256=f"{index + 1:064x}",
            source_revision_id=f"transcript-sha256:{index + 1:064x}",
        )
        for index, task_id in enumerate(request.task_ids)
    ]
    first_hash = canonical_summary_source_manifest_sha256(manifest)
    assert len(first_hash) == 64
    reversed_payload = [
        item.model_copy(update={"position": index})
        for index, item in enumerate(reversed(manifest))
    ]
    assert canonical_summary_source_manifest_sha256(reversed_payload) != first_hash


def test_batch_fingerprint_is_stable_excludes_replay_key_and_preserves_order() -> None:
    base = AudioBatchCreateRequest(
        case_id=3,
        idempotency_key="first",
        files=[_descriptor(1), _descriptor(2)],
    )
    replay = base.model_copy(update={"idempotency_key": "second"})
    reordered = base.model_copy(update={"files": list(reversed(base.files))})

    assert canonical_batch_request_fingerprint(
        base
    ) == canonical_batch_request_fingerprint(replay)
    assert canonical_batch_request_fingerprint(
        base
    ) != canonical_batch_request_fingerprint(reordered)


def test_aggregate_accounts_for_success_failure_and_cancellation() -> None:
    succeeded = derive_audio_batch_aggregate(["transcribed", "transcribed"])
    assert succeeded.model_dump() == {
        "status": "succeeded",
        "requested_count": 2,
        "completed_count": 2,
        "failed_count": 0,
        "cancelled_count": 0,
    }
    mixed = derive_audio_batch_aggregate(["transcribed", "failed", "cancelled"])
    assert mixed.status == "partially_succeeded"
    assert mixed.completed_count == 1
    assert mixed.failed_count == 1
    assert mixed.cancelled_count == 1
    assert derive_audio_batch_aggregate(["cancelled"]).status == "cancelled"


def _response_payload(*, batch_id: str | None = None) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "id": batch_id or str(uuid4()),
        "case_id": 1,
        "status": "succeeded",
        "requested_count": 1,
        "completed_count": 1,
        "failed_count": 0,
        "cancelled_count": 0,
        "total_size_bytes": 1,
        "error_code": None,
        "created_at": now,
        "updated_at": now,
        "items": [
            {
                "id": 1,
                "position": 0,
                "task_id": "task-1",
                "audio_id": 1,
                "original_filename": "audio.wav",
                "status": "transcribed",
                "error_code": None,
                "celery_task_id": None,
                "created_at": now,
                "updated_at": now,
            }
        ],
    }


def test_batch_response_requires_uuid4_complete_items_and_exact_success_counts() -> (
    None
):
    AudioBatchResponse.model_validate(_response_payload())

    with pytest.raises(ValidationError, match="canonical UUID4"):
        AudioBatchResponse.model_validate(_response_payload(batch_id="x" * 36))
    missing_item = _response_payload()
    missing_item["items"] = []
    with pytest.raises(ValidationError, match="item count must equal"):
        AudioBatchResponse.model_validate(missing_item)
    false_success = _response_payload()
    false_success["completed_count"] = 0
    false_success["failed_count"] = 1
    with pytest.raises(ValidationError, match="succeeded requires every"):
        AudioBatchResponse.model_validate(false_success)


def test_batch_metadata_has_scoped_uniqueness_checks_indexes_and_restrict_fks() -> None:
    parent = inspect(AudioBatch)
    parent_constraints = {
        constraint.name for constraint in parent.local_table.constraints
    }
    parent_indexes = {index.name for index in parent.local_table.indexes}
    assert "uq_audio_batch_owner_case_idempotency" in parent_constraints
    assert "check_audio_batch_succeeded_counts" in parent_constraints
    assert {
        "idx_audio_batch_owner_created",
        "idx_audio_batch_case_created",
        "idx_audio_batch_status",
    } <= parent_indexes

    child = inspect(AudioBatchItem)
    child_constraints = {
        constraint.name for constraint in child.local_table.constraints
    }
    assert {
        "uq_audio_batch_item_position",
        "uq_audio_batch_item_task",
        "uq_audio_batch_item_audio",
    } <= child_constraints
    foreign_keys = {
        foreign_key.parent.name: foreign_key.ondelete
        for foreign_key in child.local_table.foreign_keys
    }
    assert foreign_keys == {
        "batch_id": "CASCADE",
        "task_id": "RESTRICT",
        "audio_id": "RESTRICT",
    }

    summary_job = inspect(AudioBatchSummaryJob)
    summary_job_constraints = {
        constraint.name for constraint in summary_job.local_table.constraints
    }
    summary_job_indexes = {index.name for index in summary_job.local_table.indexes}
    assert {
        "check_audio_batch_summary_job_status",
        "check_audio_batch_summary_job_selected_count",
        "check_audio_batch_summary_job_manifest_sha256",
        "check_audio_batch_summary_job_error_code",
    } <= summary_job_constraints
    assert {
        "idx_audio_batch_summary_job_batch_created",
        "idx_audio_batch_summary_job_owner_created",
        "idx_audio_batch_summary_job_status",
    } <= summary_job_indexes


def _persist_owner_case_task_audio(db):
    user = User(
        username=f"batch-user-{uuid4().hex}",
        email=f"batch-{uuid4().hex}@example.test",
        password_hash="not-used",
        is_active=True,
    )
    db.add(user)
    db.flush()
    status = db.query(CaseStatus).first()
    priority = db.query(CasePriority).first()
    language = db.query(Language).first()
    assert status is not None and priority is not None and language is not None
    case = Case(
        case_code=uuid4().hex,
        title="Batch contract",
        status_id=status.id,
        priority_id=priority.id,
        created_by=user.id,
    )
    db.add(case)
    db.flush()
    task = Task(
        id=str(uuid4()),
        filename="audio.wav",
        status="uploaded",
        result={},
        case_id=case.id,
        user_id=user.id,
    )
    db.add(task)
    db.flush()
    audio = AudioFile(
        filename="audio.wav",
        file_path="fixture.wav",
        file_size=1,
        status="uploaded",
        task_id=task.id,
        case_id=case.id,
        language_id=language.id,
        uploaded_by=user.id,
    )
    db.add(audio)
    db.flush()
    return user, case, task, audio


def test_repository_scopes_bindings_and_replays_only_identical_requests() -> None:
    db = SessionLocal()
    try:
        user, case, task, audio = _persist_owner_case_task_audio(db)
        request = AudioBatchCreateRequest(
            case_id=case.id,
            idempotency_key="same-request",
            files=[
                {
                    "original_filename": "audio.wav",
                    "size_bytes": 1,
                    "verified_audio_sha256": SHA_A,
                }
            ],
        )
        binding = AudioBatchItemBinding(task_id=task.id, audio_id=audio.id)
        created = create_or_replay_audio_batch(
            db, request=request, user_id=user.id, item_bindings=[binding]
        )
        assert created.created is True
        assert created.batch.items[0].position == 0

        replayed = create_or_replay_audio_batch(
            db, request=request, user_id=user.id, item_bindings=[binding]
        )
        assert replayed.created is False
        assert replayed.batch.id == created.batch.id
        assert (
            get_owned_audio_batch(
                db, batch_id=created.batch.id, user_id=user.id, case_id=case.id
            )
            is created.batch
        )
        assert (
            get_owned_audio_batch(
                db, batch_id=created.batch.id, user_id=user.id + 1, case_id=case.id
            )
            is None
        )

        changed = request.model_copy(
            update={
                "files": [
                    AudioBatchFileDescriptor(
                        original_filename="changed.wav",
                        size_bytes=1,
                        verified_audio_sha256=SHA_A,
                    )
                ]
            }
        )
        with pytest.raises(AudioBatchIdempotencyConflict):
            create_or_replay_audio_batch(
                db, request=changed, user_id=user.id, item_bindings=[binding]
            )

        created.batch.items.clear()
        with pytest.raises(AudioBatchContractError, match="item count"):
            refresh_audio_batch_aggregate(created.batch)
    finally:
        db.rollback()
        db.close()


def test_repository_rejects_cross_owner_task_audio_binding() -> None:
    db = SessionLocal()
    try:
        user, case, task, audio = _persist_owner_case_task_audio(db)
        request = AudioBatchCreateRequest(
            case_id=case.id,
            idempotency_key="foreign-owner",
            files=[_descriptor(1, filename="audio.wav")],
        )
        with pytest.raises(AudioBatchContractError, match="batch owner and case"):
            create_or_replay_audio_batch(
                db,
                request=request,
                user_id=user.id + 1,
                item_bindings=[
                    AudioBatchItemBinding(task_id=task.id, audio_id=audio.id)
                ],
            )
    finally:
        db.rollback()
        db.close()


@pytest.mark.parametrize(
    "value",
    [
        "not-a-uuid",
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        str(uuid4())[:-1],
    ],
)
def test_batch_id_normalizer_rejects_malformed_or_noncanonical_values(
    value: str,
) -> None:
    with pytest.raises(AudioBatchContractError):
        normalize_audio_batch_id(value)
