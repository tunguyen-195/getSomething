from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

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
    Summary,
    Task,
    User,
)
from src.services.audio_batch_contracts import (
    AudioBatchSummaryManifestItem,
    canonical_summary_source_manifest_sha256,
)
from src.worker.tasks import batch_task, summarize_task


def _create_owner_case(db):
    user = User(
        username=f"batch-worker-{uuid4().hex}",
        email=f"batch-worker-{uuid4().hex}@example.test",
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
        title="Batch worker",
        status_id=status.id,
        priority_id=priority.id,
        created_by=user.id,
    )
    db.add(case)
    db.flush()
    return user, case, language


def _create_batch(tmp_path: Path, *, count: int = 2, status: str = "queued"):
    db = SessionLocal()
    try:
        user, case, language = _create_owner_case(db)
        batch = AudioBatch(
            id=str(uuid4()),
            case_id=case.id,
            user_id=user.id,
            status=status,
            requested_count=count,
            completed_count=0,
            failed_count=0,
            cancelled_count=0,
            total_size_bytes=count * 8,
            upload_options={
                "enable_diarization": False,
                "diarization_method": "none",
                "language": "vi",
                "fast_mode": True,
            },
            idempotency_key=f"worker-{uuid4()}",
            request_fingerprint_sha256="a" * 64,
        )
        db.add(batch)
        db.flush()
        paths: dict[str, Path] = {}
        task_ids: list[str] = []
        for position in range(count):
            task_id = str(uuid4())
            filename = f"source-{position}.wav"
            source_path = tmp_path / filename
            source_path.write_bytes(f"audio-{position}".encode("ascii"))
            digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
            task = Task(
                id=task_id,
                filename=filename,
                status="uploaded",
                result={},
                case_id=case.id,
                user_id=user.id,
            )
            db.add(task)
            db.flush()
            audio = AudioFile(
                filename=filename,
                file_path=filename,
                file_size=source_path.stat().st_size,
                status="uploaded",
                task_id=task_id,
                case_id=case.id,
                language_id=language.id,
                uploaded_by=user.id,
                extra_metadata={"sha256": digest},
            )
            db.add(audio)
            db.flush()
            db.add(
                AudioBatchItem(
                    batch_id=batch.id,
                    task_id=task_id,
                    audio_id=audio.id,
                    position=position,
                    original_filename=filename,
                    verified_audio_sha256=digest,
                    status="queued",
                    celery_task_id=f"eager-audio-batch:{batch.id}",
                )
            )
            paths[filename] = source_path
            task_ids.append(task_id)
        batch.transcription_task_ids = task_ids
        db.commit()
        return batch.id, paths
    finally:
        db.close()


def _persist_mock_transcript(db, task_id: str, text: str) -> dict[str, object]:
    task = db.query(Task).filter(Task.id == task_id).one()
    audio = db.query(AudioFile).filter(AudioFile.task_id == task_id).one()
    digest = (audio.extra_metadata or {})["sha256"]
    task.status = "transcribed"
    task.result = {
        "transcription": text,
        "audio_sha256": digest,
        "audio_integrity_status": "verified",
    }
    audio.status = "transcribed"
    db.commit()
    return {"transcript": text, "audio_sha256": digest}


def test_batch_worker_is_ordered_durable_and_idempotent(tmp_path, monkeypatch) -> None:
    batch_id, paths = _create_batch(tmp_path)
    db = SessionLocal()
    try:
        batch = db.query(AudioBatch).filter(AudioBatch.id == batch_id).one()
        selected_order = list(reversed(batch.transcription_task_ids))
        batch.transcription_task_ids = selected_order
        db.commit()
    finally:
        db.close()
    calls: list[str] = []
    monkeypatch.setattr(
        batch_task,
        "resolve_audio_path",
        lambda value: paths[str(value)],
    )

    def fake_transcribe(*, task_id, db, **_options):
        calls.append(task_id)
        return _persist_mock_transcript(db, task_id, f"Transcript {len(calls)}")

    monkeypatch.setattr(
        "src.services.transcription.transcribe_service_v2.transcribe_audio_v2",
        fake_transcribe,
    )
    first = batch_task.transcribe_audio_batch_task.run(batch_id)
    second = batch_task.transcribe_audio_batch_task.run(batch_id)

    assert first["status"] == second["status"] == "succeeded"
    assert first["completed_count"] == 2
    assert len(calls) == 2
    db = SessionLocal()
    try:
        items = (
            db.query(AudioBatchItem)
            .filter(AudioBatchItem.batch_id == batch_id)
            .order_by(AudioBatchItem.position)
            .all()
        )
        assert calls == selected_order
        assert {item.status for item in items} == {"transcribed"}
        assert len({item.celery_task_id for item in items}) == 1
    finally:
        db.close()


def test_batch_worker_continues_after_safe_per_item_failure(
    tmp_path, monkeypatch
) -> None:
    batch_id, paths = _create_batch(tmp_path)
    calls = 0
    monkeypatch.setattr(
        batch_task,
        "resolve_audio_path",
        lambda value: paths[str(value)],
    )

    def fake_transcribe(*, task_id, db, **_options):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("raw-provider-secret-must-not-persist")
        return _persist_mock_transcript(db, task_id, "Second transcript")

    monkeypatch.setattr(
        "src.services.transcription.transcribe_service_v2.transcribe_audio_v2",
        fake_transcribe,
    )
    result = batch_task.transcribe_audio_batch_task.run(batch_id)
    assert result["status"] == "partially_succeeded"
    assert result["completed_count"] == result["failed_count"] == 1
    assert calls == 2

    db = SessionLocal()
    try:
        items = (
            db.query(AudioBatchItem)
            .filter(AudioBatchItem.batch_id == batch_id)
            .order_by(AudioBatchItem.position)
            .all()
        )
        failed_task = db.query(Task).filter(Task.id == items[0].task_id).one()
        assert items[0].error_code == "BATCH_TRANSCRIPTION_FAILED"
        assert failed_task.error == "Audio transcription failed."
        assert "raw-provider-secret" not in failed_task.error
        assert items[1].status == "transcribed"
    finally:
        db.close()


def test_batch_worker_processes_only_ordered_selected_subset(
    tmp_path, monkeypatch
) -> None:
    batch_id, paths = _create_batch(tmp_path, count=3)
    db = SessionLocal()
    try:
        batch = db.query(AudioBatch).filter(AudioBatch.id == batch_id).one()
        upload_order = [item.task_id for item in batch.items]
        selected_order = [upload_order[2], upload_order[0]]
        batch.transcription_task_ids = selected_order
        unselected = batch.items[1]
        unselected.status = "uploaded"
        unselected.celery_task_id = None
        db.commit()
        unselected_task_id = unselected.task_id
    finally:
        db.close()

    calls: list[str] = []
    monkeypatch.setattr(
        batch_task,
        "resolve_audio_path",
        lambda value: paths[str(value)],
    )

    def fake_transcribe(*, task_id, db, **_options):
        calls.append(task_id)
        return _persist_mock_transcript(db, task_id, f"Transcript {len(calls)}")

    monkeypatch.setattr(
        "src.services.transcription.transcribe_service_v2.transcribe_audio_v2",
        fake_transcribe,
    )
    result = batch_task.transcribe_audio_batch_task.run(batch_id)
    assert calls == selected_order
    assert result["completed_count"] == 2

    db = SessionLocal()
    try:
        unselected = (
            db.query(AudioBatchItem)
            .filter(
                AudioBatchItem.batch_id == batch_id,
                AudioBatchItem.task_id == unselected_task_id,
            )
            .one()
        )
        unselected_task = db.query(Task).filter(Task.id == unselected_task_id).one()
        assert unselected.status == "uploaded"
        assert unselected.celery_task_id is None
        assert unselected_task.status == "uploaded"
        assert unselected_task.result == {}
    finally:
        db.close()


def test_batch_worker_recovers_published_transcript_without_repeating_asr(
    tmp_path, monkeypatch
) -> None:
    batch_id, paths = _create_batch(tmp_path, count=1)
    db = SessionLocal()
    try:
        batch = db.query(AudioBatch).filter(AudioBatch.id == batch_id).one()
        item = batch.items[0]
        task = db.query(Task).filter(Task.id == item.task_id).one()
        task.status = "transcribed"
        task.result = {
            "transcription": "Published before worker acknowledgement",
            "audio_sha256": item.verified_audio_sha256,
        }
        item.status = "transcribing"
        item.celery_task_id = f"eager-audio-batch:{batch_id}"
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        batch_task,
        "resolve_audio_path",
        lambda value: paths[str(value)],
    )
    calls = 0

    def forbidden_transcribe(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("published transcript should be recovered")

    monkeypatch.setattr(
        "src.services.transcription.transcribe_service_v2.transcribe_audio_v2",
        forbidden_transcribe,
    )
    result = batch_task.transcribe_audio_batch_task.run(batch_id)
    assert result["status"] == "succeeded"
    assert result["completed_count"] == 1
    assert calls == 0


def test_batch_worker_invalid_options_fail_only_selected_subset(
    tmp_path, monkeypatch
) -> None:
    batch_id, _paths = _create_batch(tmp_path, count=3)
    db = SessionLocal()
    try:
        batch = db.query(AudioBatch).filter(AudioBatch.id == batch_id).one()
        selected = batch.items[1]
        batch.transcription_task_ids = [selected.task_id]
        for item in batch.items:
            if item.id != selected.id:
                item.status = "uploaded"
                item.celery_task_id = None
        batch.upload_options = {"unexpected": "raw-secret-must-not-persist"}
        db.commit()
        selected_id = selected.id
        unselected_ids = [item.id for item in batch.items if item.id != selected.id]
    finally:
        db.close()

    calls = 0

    def forbidden_transcribe(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("ASR must not run with invalid durable options")

    monkeypatch.setattr(
        "src.services.transcription.transcribe_service_v2.transcribe_audio_v2",
        forbidden_transcribe,
    )
    result = batch_task.transcribe_audio_batch_task.run(batch_id)
    assert calls == 0
    assert result["failed_count"] == 1

    db = SessionLocal()
    try:
        selected = (
            db.query(AudioBatchItem).filter(AudioBatchItem.id == selected_id).one()
        )
        unselected = (
            db.query(AudioBatchItem).filter(AudioBatchItem.id.in_(unselected_ids)).all()
        )
        assert selected.status == "failed"
        assert selected.error_code == "BATCH_OPTIONS_INVALID"
        assert {item.status for item in unselected} == {"uploaded"}
        assert all(item.error_code is None for item in unselected)
    finally:
        db.close()


def test_batch_worker_honors_cancel_before_asr(tmp_path, monkeypatch) -> None:
    batch_id, _paths = _create_batch(tmp_path)
    db = SessionLocal()
    try:
        batch = db.query(AudioBatch).filter(AudioBatch.id == batch_id).one()
        batch.status = "cancel_requested"
        for item in batch.items:
            item.status = "cancel_requested"
        db.commit()
    finally:
        db.close()

    calls = 0

    def forbidden_transcribe(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("ASR must not run after cancellation")

    monkeypatch.setattr(
        "src.services.transcription.transcribe_service_v2.transcribe_audio_v2",
        forbidden_transcribe,
    )
    result = batch_task.transcribe_audio_batch_task.run(batch_id)
    assert result["status"] == "cancelled"
    assert result["cancelled_count"] == 2
    assert calls == 0


def _make_transcribed_summary_job(tmp_path: Path, *, tamper_hash: bool = False):
    batch_id, paths = _create_batch(tmp_path)
    db = SessionLocal()
    try:
        batch = db.query(AudioBatch).filter(AudioBatch.id == batch_id).one()
        manifest: list[AudioBatchSummaryManifestItem] = []
        for position, item in enumerate(batch.items):
            task = db.query(Task).filter(Task.id == item.task_id).one()
            transcript = f"Verified transcript {position}"
            digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
            task.status = "transcribed"
            task.result = {
                "transcription": transcript,
                "audio_sha256": item.verified_audio_sha256,
                "audio_integrity_status": "verified",
            }
            item.status = "transcribed"
            manifest.append(
                AudioBatchSummaryManifestItem(
                    position=position,
                    batch_item_id=item.id,
                    task_id=item.task_id,
                    audio_id=item.audio_id,
                    filename=item.original_filename,
                    transcript_sha256=digest,
                    source_revision_id=f"transcript-sha256:{digest}",
                )
            )
        batch.status = "succeeded"
        batch.completed_count = len(batch.items)
        job = AudioBatchSummaryJob(
            id=str(uuid4()),
            batch_id=batch.id,
            case_id=batch.case_id,
            user_id=batch.user_id,
            status="queued",
            selected_count=len(manifest),
            source_manifest=[item.model_dump(mode="json") for item in manifest],
            source_manifest_sha256=(
                "0" * 64
                if tamper_hash
                else canonical_summary_source_manifest_sha256(manifest)
            ),
            summary_options={
                "model_name": None,
                "summary_type": "detailed",
                "min_length": 10,
                "max_length": 200,
                "length_mode": "auto",
            },
            user_prompt_applied=False,
        )
        db.add(job)
        db.commit()
        return job.id, paths
    finally:
        db.close()


def test_summary_job_manifest_mismatch_fails_before_llm(tmp_path, monkeypatch) -> None:
    job_id, _paths = _make_transcribed_summary_job(tmp_path, tamper_hash=True)
    calls = 0

    def forbidden_summary(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("LLM must not run for a mismatched manifest")

    monkeypatch.setattr(
        "src.services.summarization.summary_service_v2.summarize_multi_transcripts_v2",
        forbidden_summary,
    )
    with pytest.raises(summarize_task.SafeAudioBatchSummaryJobError) as exc_info:
        summarize_task.summarize_audio_batch_job_task.run(
            job_id,
            user_prompt="private-summary-preference",
        )
    assert exc_info.value.code == "SUMMARY_MANIFEST_HASH_MISMATCH"
    assert calls == 0

    db = SessionLocal()
    try:
        job = (
            db.query(AudioBatchSummaryJob)
            .filter(AudioBatchSummaryJob.id == job_id)
            .one()
        )
        assert job.status == "failed"
        assert job.error_code == "SUMMARY_MANIFEST_HASH_MISMATCH"
        assert job.user_prompt_applied is False
        assert db.query(Summary).count() == 0
        durable = repr(
            (
                job.source_manifest,
                job.summary_options,
                job.error_code,
                job.user_prompt_applied,
            )
        )
        assert "private-summary-preference" not in durable
    finally:
        db.close()


@pytest.mark.parametrize(
    ("tamper", "expected_code"),
    [
        ("transcript", "SUMMARY_SOURCE_TRANSCRIPT_MISMATCH"),
        ("audio", "SUMMARY_SOURCE_AUDIO_MISMATCH"),
        ("scope", "SUMMARY_SOURCE_SCOPE_MISMATCH"),
    ],
)
def test_summary_job_source_mismatch_fails_before_llm(
    tmp_path, monkeypatch, tamper, expected_code
) -> None:
    job_id, paths = _make_transcribed_summary_job(tmp_path)
    db = SessionLocal()
    try:
        job = (
            db.query(AudioBatchSummaryJob)
            .filter(AudioBatchSummaryJob.id == job_id)
            .one()
        )
        first = AudioBatchSummaryManifestItem.model_validate(job.source_manifest[0])
        if tamper == "transcript":
            task = db.query(Task).filter(Task.id == first.task_id).one()
            result = dict(task.result)
            result["transcription"] = "Changed after manifest creation"
            task.result = result
        elif tamper == "scope":
            user, _case, _language = _create_owner_case(db)
            task = db.query(Task).filter(Task.id == first.task_id).one()
            task.user_id = user.id
        db.commit()
    finally:
        db.close()
    if tamper == "audio":
        paths[first.filename].write_bytes(b"tampered-audio-bytes")

    monkeypatch.setattr(
        summarize_task,
        "resolve_audio_path",
        lambda value: paths[str(value)],
    )
    calls = 0

    def forbidden_summary(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("LLM must not run for a mismatched source")

    monkeypatch.setattr(
        "src.services.summarization.summary_service_v2.summarize_multi_transcripts_v2",
        forbidden_summary,
    )
    with pytest.raises(summarize_task.SafeAudioBatchSummaryJobError) as exc_info:
        summarize_task.summarize_audio_batch_job_task.run(job_id)
    assert exc_info.value.code == expected_code
    assert calls == 0
    db = SessionLocal()
    try:
        job = (
            db.query(AudioBatchSummaryJob)
            .filter(AudioBatchSummaryJob.id == job_id)
            .one()
        )
        assert job.status == "failed"
        assert job.error_code == expected_code
        assert db.query(Summary).count() == 0
    finally:
        db.close()


def test_summary_job_revalidates_sources_after_llm_before_persistence(
    tmp_path, monkeypatch
) -> None:
    job_id, paths = _make_transcribed_summary_job(tmp_path)
    monkeypatch.setattr(
        summarize_task,
        "resolve_audio_path",
        lambda value: paths[str(value)],
    )

    @contextmanager
    def no_handoff(*_args, **_kwargs):
        yield

    monkeypatch.setattr(summarize_task, "_llama_server_handoff", no_handoff)
    calls = 0

    def fake_summary(**_kwargs):
        nonlocal calls
        calls += 1
        db = SessionLocal()
        try:
            job = (
                db.query(AudioBatchSummaryJob)
                .filter(AudioBatchSummaryJob.id == job_id)
                .one()
            )
            source = AudioBatchSummaryManifestItem.model_validate(
                job.source_manifest[0]
            )
            task = db.query(Task).filter(Task.id == source.task_id).one()
            result = dict(task.result)
            result["transcription"] = "Changed while model was running"
            task.result = result
            db.commit()
        finally:
            db.close()
        return {
            "available": True,
            "summary": "Must be discarded",
            "num_transcripts": 2,
            "runtime": {"user_prompt_applied": False, "llm_call_count": 1},
        }

    monkeypatch.setattr(
        "src.services.summarization.summary_service_v2.summarize_multi_transcripts_v2",
        fake_summary,
    )
    with pytest.raises(summarize_task.SafeAudioBatchSummaryJobError) as exc_info:
        summarize_task.summarize_audio_batch_job_task.run(job_id)
    assert exc_info.value.code == "SUMMARY_SOURCE_TRANSCRIPT_MISMATCH"
    assert calls == 1
    db = SessionLocal()
    try:
        job = (
            db.query(AudioBatchSummaryJob)
            .filter(AudioBatchSummaryJob.id == job_id)
            .one()
        )
        assert job.status == "failed"
        assert job.summary_id is None
        assert db.query(Summary).count() == 0
    finally:
        db.close()


def test_summary_job_marks_prompt_applied_only_after_model_boundary(
    tmp_path, monkeypatch
) -> None:
    job_id, paths = _make_transcribed_summary_job(tmp_path)
    monkeypatch.setattr(
        summarize_task,
        "resolve_audio_path",
        lambda value: paths[str(value)],
    )

    @contextmanager
    def no_handoff(*_args, **_kwargs):
        yield

    monkeypatch.setattr(summarize_task, "_llama_server_handoff", no_handoff)

    def failing_summary(**_kwargs):
        raise RuntimeError("provider-secret-not-persisted")

    monkeypatch.setattr(
        "src.services.summarization.summary_service_v2.summarize_multi_transcripts_v2",
        failing_summary,
    )
    with pytest.raises(summarize_task.SafeAudioBatchSummaryJobError) as exc_info:
        summarize_task.summarize_audio_batch_job_task.run(
            job_id,
            user_prompt="Focus on decisions",
        )
    assert exc_info.value.code == "SUMMARY_GENERATION_FAILED"
    db = SessionLocal()
    try:
        job = (
            db.query(AudioBatchSummaryJob)
            .filter(AudioBatchSummaryJob.id == job_id)
            .one()
        )
        assert job.status == "failed"
        assert job.user_prompt_applied is True
        assert "Focus on decisions" not in repr(
            (job.source_manifest, job.summary_options, job.error_code)
        )
    finally:
        db.close()


def test_summary_job_cancel_requested_during_llm_discards_result(
    tmp_path, monkeypatch
) -> None:
    job_id, paths = _make_transcribed_summary_job(tmp_path)
    monkeypatch.setattr(
        summarize_task,
        "resolve_audio_path",
        lambda value: paths[str(value)],
    )

    @contextmanager
    def no_handoff(*_args, **_kwargs):
        yield

    monkeypatch.setattr(summarize_task, "_llama_server_handoff", no_handoff)

    def summary_then_cancel(**_kwargs):
        db = SessionLocal()
        try:
            job = (
                db.query(AudioBatchSummaryJob)
                .filter(AudioBatchSummaryJob.id == job_id)
                .one()
            )
            job.status = "cancel_requested"
            db.commit()
        finally:
            db.close()
        return {
            "available": True,
            "summary": "Must be discarded after cancellation",
            "num_transcripts": 2,
            "runtime": {"user_prompt_applied": True, "llm_call_count": 1},
        }

    monkeypatch.setattr(
        "src.services.summarization.summary_service_v2.summarize_multi_transcripts_v2",
        summary_then_cancel,
    )
    result = summarize_task.summarize_audio_batch_job_task.run(
        job_id,
        user_prompt="Focus on decisions",
    )
    assert result["status"] == "cancelled"
    assert result["summary_id"] is None
    assert result["user_prompt_applied"] is False
    db = SessionLocal()
    try:
        assert db.query(Summary).count() == 0
    finally:
        db.close()


def test_summary_job_persists_ordered_provenance_and_is_idempotent(
    tmp_path, monkeypatch
) -> None:
    job_id, paths = _make_transcribed_summary_job(tmp_path)
    calls = 0
    monkeypatch.setattr(
        summarize_task,
        "resolve_audio_path",
        lambda value: paths[str(value)],
    )

    @contextmanager
    def no_handoff(*_args, **_kwargs):
        yield

    monkeypatch.setattr(summarize_task, "_llama_server_handoff", no_handoff)

    def fake_summary(**kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["transcripts"] == [
            "Verified transcript 0",
            "Verified transcript 1",
        ]
        assert kwargs["user_prompt"] == "Focus on decisions"
        return {
            "available": True,
            "summary": "Verified merged summary",
            "num_transcripts": 2,
            "model": "fixture-model",
            "summary_type": "detailed",
            "runtime": {"user_prompt_applied": True, "llm_call_count": 1},
        }

    monkeypatch.setattr(
        "src.services.summarization.summary_service_v2.summarize_multi_transcripts_v2",
        fake_summary,
    )
    first = summarize_task.summarize_audio_batch_job_task.run(
        job_id,
        user_prompt="Focus on decisions",
    )
    second = summarize_task.summarize_audio_batch_job_task.run(
        job_id,
        user_prompt="Focus on decisions",
    )
    assert first == second
    assert first["status"] == "succeeded"
    assert first["user_prompt_applied"] is True
    assert calls == 1

    db = SessionLocal()
    try:
        job = (
            db.query(AudioBatchSummaryJob)
            .filter(AudioBatchSummaryJob.id == job_id)
            .one()
        )
        summary = db.query(Summary).filter(Summary.id == job.summary_id).one()
        assert summary.content == "Verified merged summary"
        assert [source["position"] for source in summary.files] == [0, 1]
        assert all(source["transcript_sha256"] for source in summary.files)
        assert all(source["audio_sha256"] for source in summary.files)
        assert "Focus on decisions" not in repr(
            (job.source_manifest, job.summary_options, summary.files, summary.content)
        )
        assert db.query(Summary).count() == 1
    finally:
        db.close()
