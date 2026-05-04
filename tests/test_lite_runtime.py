import pytest
from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.core.config import settings
from src.database.models.models import AudioFile, RuntimeJobLease, Task
from src.services import lite_runtime
from src.services.lite_runtime import lite_runner_enabled
from src.services.task_service import update_task
from src.services.transcription.asr_providers import resolve_asr_runtime, transcribe_with_provider


def _lite_test_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Task.__table__.create(engine, checkfirst=True)
    AudioFile.__table__.create(engine, checkfirst=True)
    RuntimeJobLease.__table__.create(engine, checkfirst=True)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _wait_for(predicate, timeout: float = 2.0):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    return predicate()


def test_full_mode_keeps_configured_runner_and_asr_provider(monkeypatch):
    monkeypatch.setattr(settings, "PROCESSING_RUNNER", "celery")
    monkeypatch.setattr(settings, "ASR_PROVIDER", "cherry_whisper_v2")
    monkeypatch.setattr(settings, "ASR_PROFILE", "full")
    monkeypatch.setattr(settings, "WHISPER_MODEL", "large-v3-turbo")
    monkeypatch.setattr(settings, "WHISPER_DEVICE", "cuda")
    monkeypatch.setattr(settings, "WHISPER_COMPUTE_TYPE", "float16")

    runtime = resolve_asr_runtime(None)

    assert lite_runner_enabled() is False
    assert runtime["profile"] == "full"
    assert runtime["provider"] == "cherry_whisper_v2"
    assert runtime["model"] == "large-v3-turbo"
    assert runtime["compute_type"] == "float16"


def test_rtx2050_safe_profile_uses_int8_batch_safe_provider(monkeypatch):
    monkeypatch.setattr(settings, "ASR_PROVIDER", "cherry_whisper_v2")
    monkeypatch.setattr(settings, "ASR_PROFILE", "full")

    runtime = resolve_asr_runtime("rtx2050_safe")

    assert runtime["provider"] == "faster_whisper_ct2"
    assert runtime["model"] == "small"
    assert runtime["device"] == "cuda"
    assert runtime["compute_type"] == "int8"
    assert runtime["beam_size"] == 5
    assert runtime["enable_diarization"] is False


def test_phowhisper_cpp_candidate_is_blocked_until_validated(monkeypatch):
    monkeypatch.setattr("src.services.transcription.asr_providers.provider_health", lambda: {
        "phowhisper_cpp_candidate_valid": False,
    })

    with pytest.raises(RuntimeError, match="PhoWhisper.cpp candidate is not valid"):
        transcribe_with_provider(
            audio_path="missing.wav",
            language="vi",
            profile="phowhisper_cpp_candidate",
            enable_diarization=False,
            diarization_method="none",
            task_id="test-task",
        )


def test_lite_db_lease_rejects_second_active_job(monkeypatch):
    Session = _lite_test_session()
    db = Session()
    monkeypatch.setattr(lite_runtime, "SessionLocal", Session)
    monkeypatch.setattr(settings, "LITE_JOB_LEASE_TTL_SECONDS", 900)

    db.add(Task(id="task-a", filename="a.wav", status="uploaded", result={}))
    db.add(Task(id="task-b", filename="b.wav", status="uploaded", result={}))
    db.commit()

    lite_runtime.acquire_lease(db, task_id="task-a", operation="transcribe")
    db.commit()

    with pytest.raises(Exception) as exc:
        lite_runtime.acquire_lease(db, task_id="task-b", operation="summarize")
    assert getattr(exc.value, "status_code", None) == 409

    db.close()


def test_lite_background_job_sets_initial_status_before_thread_and_preserves_terminal_status(monkeypatch):
    Session = _lite_test_session()
    monkeypatch.setattr(lite_runtime, "SessionLocal", Session)
    monkeypatch.setattr(settings, "LITE_JOB_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(settings, "LITE_JOB_LEASE_TTL_SECONDS", 900)

    request_db = Session()
    request_db.add(Task(id="task-race", filename="race.wav", status="uploaded", result={}))
    request_db.commit()

    def quick_success(task_id: str, *, db):
        update_task(task_id, {"status": "transcribed", "result": {"transcription": "ok"}}, db=db)
        db.commit()

    lite_runtime.start_lite_job(
        db=request_db,
        task_id="task-race",
        operation="transcribe",
        target=quick_success,
        args=("task-race",),
        queued_status="transcribing",
    )

    def terminal_status():
        db = Session()
        try:
            task = db.query(Task).filter(Task.id == "task-race").first()
            return task.status == "transcribed"
        finally:
            db.close()

    assert _wait_for(terminal_status)
    request_db.close()


def test_lite_background_job_persists_failed_status(monkeypatch):
    Session = _lite_test_session()
    monkeypatch.setattr(lite_runtime, "SessionLocal", Session)
    monkeypatch.setattr(settings, "LITE_JOB_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(settings, "LITE_JOB_LEASE_TTL_SECONDS", 900)

    request_db = Session()
    request_db.add(Task(id="task-fail", filename="fail.wav", status="uploaded", result={}))
    request_db.commit()

    def fail_fast(task_id: str, *, db):
        raise RuntimeError("boom")

    lite_runtime.start_lite_job(
        db=request_db,
        task_id="task-fail",
        operation="transcribe",
        target=fail_fast,
        args=("task-fail",),
        queued_status="transcribing",
    )

    def failed_status():
        db = Session()
        try:
            task = db.query(Task).filter(Task.id == "task-fail").first()
            return task.status == "failed" and task.error == "boom"
        finally:
            db.close()

    assert _wait_for(failed_status)
    request_db.close()


def test_lite_background_job_rolls_back_broken_session_before_marking_failed(monkeypatch):
    Session = _lite_test_session()
    monkeypatch.setattr(lite_runtime, "SessionLocal", Session)
    monkeypatch.setattr(settings, "LITE_JOB_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(settings, "LITE_JOB_LEASE_TTL_SECONDS", 900)

    request_db = Session()
    request_db.add(Task(id="task-sql-fail", filename="fail.wav", status="uploaded", result={}))
    request_db.commit()

    def fail_with_db_error(task_id: str, *, db):
        db.add(Task(id=task_id, filename="duplicate.wav", status="uploaded", result={}))
        db.flush()

    lite_runtime.start_lite_job(
        db=request_db,
        task_id="task-sql-fail",
        operation="transcribe",
        target=fail_with_db_error,
        args=("task-sql-fail",),
        queued_status="transcribing",
    )

    def failed_status():
        db = Session()
        try:
            task = db.query(Task).filter(Task.id == "task-sql-fail").first()
            return bool(task and task.status == "failed" and task.error)
        finally:
            db.close()

    assert _wait_for(failed_status)
    request_db.close()


def test_v2_status_polling_does_not_return_transcript_or_full_result(monkeypatch):
    import asyncio
    from src.api.endpoints import audio_v2
    from src.services import task_service

    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda task_id: {
            "status": "transcribed",
            "result": {
                "transcription": "sensitive transcript",
                "formatted_transcript": "sensitive formatted transcript",
                "segments": [{"text": "sensitive segment"}],
                "summary": "summary",
                "visualization_data": {"nodes": []},
                "duration": 12.3,
            },
            "filename": "audio.wav",
        },
    )
    monkeypatch.setattr(audio_v2, "assert_task_access", lambda *args, **kwargs: True)

    response = asyncio.run(audio_v2.get_status_v2("task-privacy", db=None, current_user=object()))

    assert response["status"] == "transcribed"
    assert response["transcript_available"] is True
    assert "transcript" not in response
    assert "formatted_transcript" not in response
    assert "segments" not in response
    assert "visualization_data" not in response
    assert "result" not in response


def test_v2_transcription_detail_is_transcript_only_and_no_store(monkeypatch):
    import asyncio
    from src.api.endpoints import audio_v2
    from src.services import task_service

    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda task_id: {
            "status": "transcribed",
            "result": {
                "transcription": "selected transcript",
                "raw_transcription": "raw transcript",
                "review_transcription": "review transcript",
                "segments": [{"text": "selected transcript"}],
                "summary": "must not leak",
                "visualization_data": {"nodes": ["must not leak"]},
            },
            "filename": "audio.wav",
        },
    )
    monkeypatch.setattr(audio_v2, "assert_task_access", lambda *args, **kwargs: True)
    response_obj = Response()

    response = asyncio.run(
        audio_v2.get_transcription_detail_v2(
            "task-detail",
            response=response_obj,
            db=None,
            current_user=object(),
        )
    )

    assert response["transcription"] == "selected transcript"
    assert response["raw_transcription"] == "raw transcript"
    assert response_obj.headers["Cache-Control"] == "no-store"
    assert response_obj.headers["Pragma"] == "no-cache"
    assert "summary" not in response
    assert "visualization_data" not in response


def test_v2_summary_detail_is_summary_only_and_no_store(monkeypatch):
    import asyncio
    from src.api.endpoints import audio_v2
    from src.services import task_service

    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda task_id: {
            "status": "summarized",
            "result": {
                "transcription": "must not leak",
                "segments": [{"text": "must not leak"}],
                "summary": "safe summary detail",
                "summary_model": "test-model",
                "visualization_data": {"nodes": ["must not leak"]},
            },
            "summary": "fallback summary",
            "filename": "audio.wav",
        },
    )
    monkeypatch.setattr(audio_v2, "assert_task_access", lambda *args, **kwargs: True)
    response_obj = Response()

    response = asyncio.run(
        audio_v2.get_summary_detail_v2(
            "task-summary",
            response=response_obj,
            db=None,
            current_user=object(),
        )
    )

    assert response["summary"] == "safe summary detail"
    assert response["summary_model"] == "test-model"
    assert response_obj.headers["Cache-Control"] == "no-store"
    assert response_obj.headers["Pragma"] == "no-cache"
    assert "transcription" not in response
    assert "segments" not in response
    assert "visualization_data" not in response


def test_v2_analysis_detail_is_graph_only_and_no_store(monkeypatch):
    import asyncio
    from src.api.endpoints import audio_v2
    from src.services import task_service

    graph = {
        "schema_version": "analysis_intelligence.v2",
        "analysis_mode": "general",
        "nodes": [],
        "warnings": ["deterministic"],
    }
    monkeypatch.setattr(
        task_service,
        "get_task",
        lambda task_id: {
            "status": "visualized",
            "result": {
                "transcription": "must not leak",
                "segments": [{"text": "must not leak"}],
                "summary": "must not leak",
                "has_visualization": True,
                "visualization_data": graph,
            },
            "filename": "audio.wav",
        },
    )
    monkeypatch.setattr(audio_v2, "assert_task_access", lambda *args, **kwargs: True)
    response_obj = Response()

    response = asyncio.run(
        audio_v2.get_analysis_detail_v2(
            "task-analysis",
            response=response_obj,
            db=None,
            current_user=object(),
        )
    )

    assert response["visualization_data"] == graph
    assert response["schema_version"] == "analysis_intelligence.v2"
    assert response_obj.headers["Cache-Control"] == "no-store"
    assert response_obj.headers["Pragma"] == "no-cache"
    assert "transcription" not in response
    assert "segments" not in response
    assert "summary" not in response


def test_lite_audio_list_returns_metadata_not_transcript_payload(monkeypatch):
    from src.api.endpoints import audio

    Session = _lite_test_session()
    db = Session()
    monkeypatch.setattr(settings, "APP_EDITION", "lite")
    monkeypatch.setattr(settings, "PROCESSING_RUNNER", "single_job_db_lease")
    monkeypatch.setattr(audio, "accessible_case_ids", lambda *args, **kwargs: None)

    db.add(Task(
        id="task-list",
        filename="list.wav",
        status="transcribed",
        result={
            "transcription": "sensitive transcript",
            "formatted_transcript": "sensitive formatted",
            "segments": [{"text": "sensitive segment"}],
            "summary": "summary",
            "visualization_data": {"nodes": ["sensitive"]},
            "context_analysis": {"topic": "sensitive"},
        },
    ))
    db.add(AudioFile(
        id=10,
        filename="list.wav",
        file_path="list.wav",
        status="transcribed",
        task_id="task-list",
        case_id=1,
        language_id=1,
        uploaded_by=1,
        is_archived=False,
    ))
    db.commit()

    response = audio.read_audio(case_id=None, db=db, current_user=object())

    assert len(response) == 1
    item = response[0]
    assert item["transcript_available"] is True
    assert item["segments_available"] is True
    assert item["analysis_available"] is True
    assert "transcript" not in item
    assert "formatted_transcript" not in item
    assert "segments" not in item
    assert "visualization_data" not in item
    assert "context_analysis" not in item
    db.close()


def test_llm_provider_error_does_not_include_response_body(monkeypatch):
    import requests
    from src.services.summarization.models.llm_manager import LLMManager

    sensitive = "transcript 0978 711 253 should not appear"

    class FakeResponse:
        status_code = 500
        reason = "Internal Server Error"
        text = sensitive

        def json(self):
            return {}

    monkeypatch.setattr(settings, "ANALYSIS_LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "ANALYSIS_LLM_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setattr(settings, "ANALYSIS_LLM_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ANALYSIS_LLM_MODEL", "test-model")
    monkeypatch.setattr(settings, "ANALYSIS_LLM_MAX_INPUT_CHARS", 24000)
    monkeypatch.setattr(settings, "ANALYSIS_LLM_MAX_OUTPUT_TOKENS", 2000)
    monkeypatch.setattr(settings, "ANALYSIS_LLM_TIMEOUT_SECONDS", 60)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: type("ModelResponse", (), {
        "status_code": 200,
        "json": lambda self: {"data": [{"id": "test-model"}]},
    })())
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: FakeResponse())

    monkeypatch.setattr(LLMManager, "_instance", None)
    monkeypatch.setattr(LLMManager, "_initialized", False)
    manager = LLMManager()
    with pytest.raises(Exception) as exc:
        manager.generate("hello", model="test-model")

    message = str(exc.value)
    assert "status=500" in message
    assert sensitive not in message
