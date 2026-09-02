from __future__ import annotations

import copy
import hashlib
import importlib
import json
import logging
from pathlib import Path

import pytest

from src.services.model_runtime import gpu_lease as gpu_lease_context
from src.services.model_runtime.gpu_lease import (
    GpuLease,
    GpuLeaseQuarantined,
    GpuLeaseTimeout,
    arm_gpu_quarantine,
    get_gpu_quarantine,
    verify_and_clear_gpu_quarantine,
)
from src.services.summarization import summary_service_v2
from src.services.summarization.failure_contract import SafeSummaryTaskError
from src.services.summarization.models.llm_manager import LLMManager
from src.services.summarization.projections import project_visualization

gpu_lease_module = importlib.import_module("src.services.model_runtime.gpu_lease")


def _knowledge_context() -> dict:
    return {
        "analysis_status": "success",
        "summary": "Tong quan Nguyen Van A hen gap tai Ben xe B luc 20 gio.",
        "investigation_knowledge": {
            "evidence_spans": [
                {"evidence_id": "ev-1"},
                {"evidence_id": "ev-2"},
                {"evidence_id": "ev-3"},
            ],
            "quality": {"grounded_items": 4},
            "entities": [
                {
                    "entity_id": "entity-person-a",
                    "entity_type": "person",
                    "value": "Nguyen Van A",
                    "role": "nguoi goi",
                    "evidence_ids": ["ev-1"],
                },
                {
                    "entity_id": "entity-place-b",
                    "entity_type": "location",
                    "value": "Ben xe B",
                    "role": None,
                    "evidence_ids": ["ev-2"],
                },
            ],
            "relationships": [
                {
                    "source": "Nguyen Van A",
                    "target": "Ben xe B",
                    "label": "hen gap tai",
                    "evidence_ids": ["ev-3"],
                }
            ],
            "events": [
                {
                    "description": "Hen gap luc 20 gio",
                    "evidence_ids": ["ev-3"],
                }
            ],
            "timeline": [
                {
                    "event_id": "event-1",
                    "time": "20:00",
                    "description": "Hen gap",
                    "evidence_ids": ["ev-3"],
                }
            ],
        },
    }


def test_gpu_lease_writes_and_removes_owner_metadata(tmp_path):
    lock_path = tmp_path / "gpu.lock"

    with GpuLease("summary", "test-owner", path=lock_path, enabled=True) as snapshot:
        owner_path = lock_path.with_suffix(".lock.owner.json")
        assert snapshot is not None
        assert owner_path.exists()
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        assert owner["lease_id"] == snapshot.lease_id
        assert owner["stage"] == "summary"

    assert not owner_path.exists()


def test_gpu_lease_times_out_without_running_work(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu_lease_module, "_try_lock", lambda _handle: False)

    with pytest.raises(GpuLeaseTimeout):
        with GpuLease(
            "analysis",
            "blocked-owner",
            path=tmp_path / "gpu.lock",
            enabled=True,
            timeout_seconds=0.01,
            poll_seconds=0.01,
        ):
            pytest.fail("lease body must not run")


def test_gpu_lease_is_reentrant_in_the_same_thread(tmp_path):
    lock_path = tmp_path / "gpu.lock"

    with GpuLease("summary", "outer", path=lock_path, enabled=True) as outer:
        with GpuLease(
            "forensic",
            "nested",
            path=lock_path,
            enabled=True,
            timeout_seconds=0.01,
        ) as nested:
            assert nested == outer
            assert lock_path.with_suffix(".lock.owner.json").exists()

    assert not lock_path.with_suffix(".lock.owner.json").exists()


def test_disabled_gpu_lease_is_a_noop(monkeypatch):
    monkeypatch.setattr(gpu_lease_module.settings, "GPU_LEASE_ENABLED", False)
    with gpu_lease_context("summary", "disabled") as snapshot:
        assert snapshot is None


def test_failed_sleep_verification_blocks_audio_reacquire_until_recovery(tmp_path):
    lock_path = tmp_path / "gpu.lock"
    quarantine = arm_gpu_quarantine(
        "summary",
        "task:same-owner",
        "llama-server sleep verification pending",
        allowed_stages=("summary",),
        path=lock_path,
    )

    persisted = get_gpu_quarantine(path=lock_path)
    assert persisted is not None
    assert persisted.quarantine_id == quarantine.quarantine_id
    assert persisted.owner == "task:same-owner"
    assert persisted.reason == "llama-server sleep verification pending"

    assert verify_and_clear_gpu_quarantine(
        lambda: False,
        verified_by="test-failed-check",
        expected_quarantine_id=quarantine.quarantine_id,
        path=lock_path,
    ) is False

    failed = get_gpu_quarantine(path=lock_path)
    assert failed is not None
    assert failed.last_verification_error == "verifier returned false"
    with pytest.raises(GpuLeaseQuarantined) as blocked:
        with GpuLease(
            "transcription",
            "task:same-owner",
            path=lock_path,
            enabled=True,
            timeout_seconds=0.01,
        ):
            pytest.fail("audio work must remain blocked while llama-server holds VRAM")
    assert blocked.value.snapshot.owner == "task:same-owner"

    assert verify_and_clear_gpu_quarantine(
        lambda: True,
        verified_by="test-live-sleep-check",
        expected_quarantine_id=quarantine.quarantine_id,
        path=lock_path,
    ) is True
    assert get_gpu_quarantine(path=lock_path) is None

    with GpuLease(
        "transcription",
        "task:same-owner",
        path=lock_path,
        enabled=True,
        timeout_seconds=0.01,
    ) as lease:
        assert lease is not None


def test_summarize_task_fails_closed_when_llama_sleep_is_not_verified(
    tmp_path,
    monkeypatch,
):
    from src.worker.tasks import summarize_task

    lock_path = tmp_path / "gpu.lock"
    updates = []
    monkeypatch.setattr(summarize_task.settings, "LOCAL_LLM_PROVIDER", "llama_cpp_server")
    monkeypatch.setattr(summarize_task.settings, "GPU_LEASE_ENABLED", True)
    monkeypatch.setattr(summarize_task.settings, "GPU_LEASE_PATH", str(lock_path))
    monkeypatch.setattr(
        summarize_task,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung hop le."}},
    )
    monkeypatch.setattr(
        summarize_task,
        "update_task",
        lambda task_id, payload: updates.append((task_id, payload)) or True,
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **_kwargs: {"available": True, "summary": "Tom tat hop le."},
    )
    monkeypatch.setattr(
        summarize_task,
        "_verify_llama_server_sleeping",
        lambda: False,
    )

    with pytest.raises(summarize_task.SafeSummaryTaskError) as exc_info:
        summarize_task.summarize_transcript_task.run("task-unsafe-handoff")

    assert exc_info.value.code == "SUMMARY_UNSAFE_HANDOFF"
    assert any(payload.get("status") == "failed" for _, payload in updates)
    assert not any(payload.get("status") == "summarized" for _, payload in updates)
    quarantine = get_gpu_quarantine(path=lock_path)
    assert quarantine is not None
    assert quarantine.owner == "task:task-unsafe-handoff"
    with pytest.raises(GpuLeaseQuarantined):
        with GpuLease(
            "transcription",
            "task:task-unsafe-handoff",
            path=lock_path,
            enabled=True,
        ):
            pytest.fail("audio stage must not reacquire the quarantined GPU")


def test_multi_summary_task_rejects_unavailable_result(monkeypatch):
    from src.worker.tasks import summarize_task

    monkeypatch.setattr(summarize_task.settings, "LOCAL_LLM_PROVIDER", "ollama")
    monkeypatch.setattr(
        summarize_task,
        "get_task",
        lambda _task_id: {"result": {"transcription": "Noi dung hop le."}},
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_multi_transcripts_v2",
        lambda **_kwargs: {
            "available": False,
            "summary": "LLM not available",
        },
    )

    with pytest.raises(SafeSummaryTaskError) as exc_info:
        summarize_task.summarize_multi_task.run(["task-1"])
    assert exc_info.value.code == "SUMMARY_UNAVAILABLE"


def test_qwen35_uses_explicit_non_thinking_and_can_unload(monkeypatch):
    manager = LLMManager()
    payloads = []

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "qwen3.5:9b",
                "response": "{}",
                "done": True,
                "eval_count": 2,
                "eval_duration": 1_000_000_000,
            }

    def fake_post(_url, json, **_kwargs):
        payloads.append(json)
        return FakeResponse()

    monkeypatch.setattr(manager, "_provider_name", lambda: "ollama")
    monkeypatch.setattr(manager, "check_availability", lambda: True)
    monkeypatch.setattr(manager._session, "post", fake_post)

    manager.generate("PROMPT", model="qwen3.5:9b", json_mode=True)
    assert payloads[0]["think"] is False
    assert payloads[0]["prompt"] == "PROMPT"
    assert payloads[0]["keep_alive"]
    assert manager.unload_last_model() is True
    assert payloads[1] == {
        "model": "qwen3.5:9b",
        "stream": False,
        "keep_alive": 0,
    }


def test_streaming_generation_records_ttft_and_token_rates(monkeypatch):
    manager = LLMManager()
    generation_start = manager.get_generation_count()

    class FakeResponse:
        status_code = 200

        @staticmethod
        def iter_lines():
            yield json.dumps({"response": "OK", "done": False}).encode()
            yield json.dumps(
                {
                    "model": "qwen3.5:9b",
                    "response": "",
                    "done": True,
                    "prompt_eval_count": 10,
                    "prompt_eval_duration": 500_000_000,
                    "eval_count": 2,
                    "eval_duration": 100_000_000,
                }
            ).encode()

    monkeypatch.setattr(manager, "_provider_name", lambda: "ollama")
    monkeypatch.setattr(manager, "check_availability", lambda: True)
    monkeypatch.setattr(manager._session, "post", lambda *_args, **_kwargs: FakeResponse())

    assert manager.generate("PROMPT", model="qwen3.5:9b", stream=True) == "OK"
    metadata = manager.get_last_generation_metadata()

    assert manager.get_generation_count() == generation_start + 1
    assert metadata["time_to_first_token_seconds"] is not None
    assert metadata["prompt_tokens_per_second"] == 20.0
    assert metadata["decode_tokens_per_second"] == 20.0


def test_visualization_is_projected_from_grounded_knowledge():
    with pytest.raises(ValueError, match="InvestigationRun"):
        project_visualization(_knowledge_context())


def test_investigation_summary_renders_only_attested_projection_without_llm(
    monkeypatch,
):
    forbidden_calls = []
    released = object()
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: forbidden_calls.append("manager"),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "analyze_conversation_context",
        lambda *_args, **_kwargs: forbidden_calls.append("context"),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "render_released_narrative_text",
        lambda value: (
            "Tong quan Nguyen Van A hen gap tai Ben xe B luc 20 gio."
            if value is released
            else ""
        ),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "released_narrative_metadata",
        lambda value: {
            "run_id": "run-1",
            "source_revision_id": "source-rev-1",
            "sentence_ids": ["sentence-1"],
            "content_sha256": "a" * 64,
        }
        if value is released
        else {},
    )

    result = summary_service_v2.summarize_transcript_v2(
        "Nguyen Van A hen gap tai Ben xe B luc 20 gio.",
        model_name="qwen3.5:9b",
        summary_type="investigation",
        include_context=True,
        min_length=5,
        max_length=20,
        source_metadata={"source_revision_id": "source-rev-1"},
        released_narrative=released,
    )

    assert result["available"] is True
    assert result["runtime"]["llm_call_count"] == 0
    assert result["runtime"]["summary_generation"] == (
        "attested_deterministic_projection"
    )
    assert forbidden_calls == []
    assert result["summary"].startswith("Tong quan Nguyen Van A")


def test_legacy_forensic_provider_is_never_called(monkeypatch):
    legacy_calls = []

    monkeypatch.setattr(summary_service_v2.settings, "UNLOAD_MODELS_AFTER_TASK", False)
    monkeypatch.setattr(
        "src.services.cherry_summarizer.check_cherry_core_available",
        lambda: legacy_calls.append("availability"),
    )
    monkeypatch.setattr(
        "src.services.cherry_summarizer.summarize_forensic",
        lambda *_args, **_kwargs: legacy_calls.append("summarize"),
    )

    result = summary_service_v2.summarize_transcript_v2(
        "Noi dung can dieu tra.",
        summary_type="forensic",
        include_context=False,
    )

    assert result["available"] is False
    assert result["summary"] == ""
    assert result["error"]["code"] == "FORENSIC_LEGACY_PROVIDER_DISABLED"
    assert legacy_calls == []


def test_forensic_model_alias_fails_closed_without_generic_generation(monkeypatch):
    generic_manager_requested = []

    monkeypatch.setattr(summary_service_v2.settings, "UNLOAD_MODELS_AFTER_TASK", False)
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: generic_manager_requested.append(True),
    )
    result = summary_service_v2.summarize_transcript_v2(
        "Noi dung can dieu tra.",
        model_name="forensic",
        summary_type="detailed",
        include_context=False,
    )

    assert result["available"] is False
    assert result["summary"] == ""
    assert result["summary_type"] == "forensic"
    assert result["error"]["code"] == "FORENSIC_LEGACY_PROVIDER_DISABLED"
    assert generic_manager_requested == []


def test_investigation_summary_uses_model_without_attestation(monkeypatch):
    calls = []

    class FakeManager:
        def get_generation_count(self):
            return len(calls)

        def generate(self, prompt, **_kwargs):
            calls.append(prompt)
            return "Tom tat truc tiep tu transcript."

        def get_last_generation_metadata(self):
            return {"model": "qwen3.5:9b"}

    monkeypatch.setattr(summary_service_v2.settings, "UNLOAD_MODELS_AFTER_TASK", False)
    monkeypatch.setattr(summary_service_v2, "get_llm_manager", FakeManager)
    monkeypatch.setattr(
        summary_service_v2,
        "analyze_conversation_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("simple investigation summary must not analyze context")
        ),
    )

    result = summary_service_v2.summarize_transcript_v2(
        "Noi dung can tom tat.",
        model_name="qwen3.5:9b",
        summary_type="investigation",
        include_context=True,
    )

    assert result["available"] is True
    assert result["summary"] == "Tom tat truc tiep tu transcript."
    assert result["summary_state"] == "generated"
    assert result["runtime"]["llm_call_count"] == 1
    assert len(calls) == 1


def test_investigation_summary_rejects_shape_valid_mapping_spoof(monkeypatch):
    forbidden_calls = []
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: forbidden_calls.append("manager"),
    )

    result = summary_service_v2.summarize_transcript_v2(
        "Noi dung khong co evidence da resolve.",
        model_name="qwen3.5:9b",
        summary_type="investigation",
        include_context=True,
        min_length=2,
        max_length=20,
        released_narrative={
            "text": "Minh da thu nhan hanh vi va chuyen 50 trieu dong.",
            "source_revision_id": "forged",
        },
    )

    assert result["available"] is False
    assert result["summary"] == ""
    assert result["error"]["code"] == "INVESTIGATION_NARRATIVE_ATTESTATION_INVALID"
    assert forbidden_calls == []


def test_attested_projection_fails_closed_when_summary_violates_bounds(monkeypatch):
    released = object()
    forbidden_calls = []
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: forbidden_calls.append("manager"),
    )
    overlong_summary = (
        "Nguyen Van A hen Tran Thi B tai Ben xe Mien Dong luc 20 gio de ban giao "
        "ho so va thong nhat lien lac sau cuoc gap."
    )
    monkeypatch.setattr(
        summary_service_v2,
        "render_released_narrative_text",
        lambda value: overlong_summary if value is released else "",
    )
    monkeypatch.setattr(
        summary_service_v2,
        "released_narrative_metadata",
        lambda _value: {
            "run_id": "run-1",
            "source_revision_id": "source-rev-1",
            "sentence_ids": ["sentence-1"],
            "content_sha256": "a" * 64,
        },
    )

    result = summary_service_v2.summarize_transcript_v2(
        overlong_summary,
        model_name="qwen3.5:9b",
        summary_type="investigation",
        include_context=True,
        min_length=4,
        max_length=20,
        released_narrative=released,
    )

    assert result["available"] is False
    assert result["summary"] == ""
    assert result["error"]["code"] == "SUMMARY_MAX_LENGTH_EXCEEDED"
    assert result["runtime"]["length_contract"]["satisfied"] is False
    assert forbidden_calls == []


def test_generated_summary_outside_caller_bounds_fails_closed(monkeypatch):
    class FakeManager:
        def check_availability(self):
            return True

        def get_generation_count(self):
            return 0

        def generate(self, _prompt, **_kwargs):
            return "Tom tat nay vuot qua gioi han nam tu"

        def get_last_generation_metadata(self):
            return None

        def unload_last_model(self):
            return True

    monkeypatch.setattr(summary_service_v2, "get_llm_manager", lambda: FakeManager())

    result = summary_service_v2.summarize_transcript_v2(
        "Noi dung hoi thoai.",
        model_name="qwen3.5:9b",
        summary_type="brief",
        include_context=False,
        min_length=2,
        max_length=5,
        length_mode="manual",
    )

    assert result["available"] is False
    assert result["summary"] == ""
    assert result["error"]["code"] == "SUMMARY_MAX_LENGTH_EXCEEDED"
    assert result["runtime"]["length_contract"]["satisfied"] is False


def test_ollama_error_body_is_never_logged_or_raised(monkeypatch, caplog):
    secret = "SENSITIVE_TRANSCRIPT_FRAGMENT_0912345678"
    manager = LLMManager()

    class ErrorResponse:
        status_code = 500
        text = secret

    monkeypatch.setattr(manager, "_provider_name", lambda: "ollama")
    monkeypatch.setattr(manager, "check_availability", lambda: True)
    monkeypatch.setattr(
        manager._session,
        "post",
        lambda *_args, **_kwargs: ErrorResponse(),
    )

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError) as exc_info:
        manager.generate("PROMPT", model="qwen3.5:9b")

    assert secret not in str(exc_info.value)
    assert secret not in caplog.text


def test_generic_and_multi_summary_failures_never_return_provider_details(
    monkeypatch,
    caplog,
):
    secret = "SENSITIVE_PROVIDER_BODY_0912345678"

    class FailingManager:
        def check_availability(self):
            return True

        def get_generation_count(self):
            return 0

        def select_best_model(self):
            return "test-model"

        def generate(self, *_args, **_kwargs):
            raise RuntimeError(secret)

        def unload_last_model(self):
            return True

    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: FailingManager(),
    )
    monkeypatch.setattr(summary_service_v2.settings, "UNLOAD_MODELS_AFTER_TASK", False)

    with caplog.at_level(logging.ERROR):
        single = summary_service_v2.summarize_transcript_v2(
            "Noi dung hoi thoai.",
            summary_type="brief",
            include_context=False,
            min_length=2,
            max_length=20,
        )
        multi = summary_service_v2.summarize_multi_transcripts_v2(
            ["Noi dung thu nhat.", "Noi dung thu hai."],
            summary_type="brief",
            min_length=2,
            max_length=20,
        )

    for result in (single, multi):
        assert result["available"] is False
        assert result["summary"] == ""
        assert result["summary_state"] == "unavailable"
        assert result["error"]["code"] == "SUMMARY_GENERATION_FAILED"
        assert secret not in repr(result)
    assert secret not in caplog.text


def test_multi_summary_uses_explicit_gpu_owner(monkeypatch):
    leases = []

    class Lease:
        def __enter__(self):
            return None

        def __exit__(self, _exc_type, _exc, _traceback):
            return None

    def capture_lease(stage, owner):
        leases.append((stage, owner))
        return Lease()

    monkeypatch.setattr(summary_service_v2, "gpu_lease", capture_lease)
    monkeypatch.setattr(summary_service_v2.settings, "UNLOAD_MODELS_AFTER_TASK", False)
    monkeypatch.setattr(
        summary_service_v2,
        "_summarize_multi_transcripts_v2_unlocked",
        lambda **_kwargs: {"available": True, "summary": "Tom tat hop le."},
    )

    result = summary_service_v2.summarize_multi_transcripts_v2(
        ["Noi dung thu nhat.", "Noi dung thu hai."],
        summary_type="brief",
        min_length=2,
        max_length=20,
        gpu_owner="summary_job:test-job-id",
    )

    assert result["available"] is True
    assert leases == [("multi_summary", "summary_job:test-job-id")]


def test_invalid_caller_length_bounds_fail_before_generation(monkeypatch):
    generic_manager_requested = []

    monkeypatch.setattr(summary_service_v2.settings, "UNLOAD_MODELS_AFTER_TASK", False)
    monkeypatch.setattr(
        summary_service_v2,
        "get_llm_manager",
        lambda: generic_manager_requested.append(True),
    )

    with pytest.raises(Exception) as exc_info:
        summary_service_v2.summarize_transcript_v2(
            "Noi dung hoi thoai.",
            model_name="qwen3.5:9b",
            summary_type="brief",
            include_context=False,
            min_length=10,
            max_length=5,
        )

    assert getattr(exc_info.value, "code", None) == "INVALID_LENGTH_BOUNDS"
    assert generic_manager_requested == []


def test_cleanup_failure_does_not_mask_summary_success(monkeypatch):
    class FakeManager:
        def check_availability(self):
            return True

        def get_generation_count(self):
            return 0

        def generate(self, _prompt, **_kwargs):
            return "Tom tat hop le."

        def get_last_generation_metadata(self):
            return None

        def unload_last_model(self):
            raise RuntimeError("cleanup failed")

    monkeypatch.setattr(summary_service_v2, "get_llm_manager", lambda: FakeManager())

    result = summary_service_v2.summarize_transcript_v2(
        "Noi dung hoi thoai.",
        model_name="qwen3.5:9b",
        summary_type="brief",
        include_context=False,
        min_length=2,
        max_length=10,
    )

    assert result["available"] is True
    assert result["summary"] == "Tom tat hop le."


def test_cached_analysis_requires_matching_full_source_revision():
    from src.api.endpoints.summary import (
        _build_context_analysis_attestation,
        _cached_context_analysis,
    )
    from src.services.summarization.context_service import (
        build_transcript_grounded_fallback,
    )

    transcript = "Noi dung da niem phong"
    segments = [
        {
            "start": 0.0,
            "end": 1.0,
            "speaker": "SPEAKER_00",
            "text": transcript,
        }
    ]
    result_data = {
        "transcription": transcript,
        "segments": segments,
        "audio_integrity_status": "verified",
        "diarization_status": "unavailable",
        "diarization_degraded_reasons": ["fixture unavailable"],
    }
    source_metadata = {
        "task_id": "cache-task",
        "audio_integrity_status": "verified",
        "diarization_status": "unavailable",
        "diarization_degraded_reasons": ["fixture unavailable"],
    }
    cached = build_transcript_grounded_fallback(
        transcript,
        segments,
        source_metadata,
    )
    result_data["context_analysis"] = cached
    result_data["context_analysis_attestation"] = (
        _build_context_analysis_attestation(
            cached,
            task_id="cache-task",
            transcript=transcript,
            segments=segments,
        )
    )

    # Legacy grounded payloads are no longer cacheable; only the simple current
    # Analysis schema can receive the server attestation contract.
    assert _cached_context_analysis(result_data, transcript, "cache-task") is None
    assert _cached_context_analysis(result_data, "noi dung khac", "cache-task") is None

    speaker_mutation = copy.deepcopy(result_data)
    speaker_mutation["segments"][0]["speaker"] = "SPEAKER_01"
    assert _cached_context_analysis(speaker_mutation, transcript, "cache-task") is None

    timestamp_mutation = copy.deepcopy(result_data)
    timestamp_mutation["segments"][0]["end"] = 2.0
    assert _cached_context_analysis(timestamp_mutation, transcript, "cache-task") is None

    metadata_mutation = copy.deepcopy(result_data)
    metadata_mutation["diarization_status"] = "success"
    assert _cached_context_analysis(metadata_mutation, transcript, "cache-task") is None


def test_cached_simple_analysis_requires_current_prompt_and_transcript_hash():
    from src.api.endpoints.summary import (
        _build_context_analysis_attestation,
        _cached_context_analysis,
        _exact_transcript_sha256,
    )
    from src.services.summarization.models.context_analysis import (
        ANALYSIS_SCHEMA_VERSION,
        CONTEXT_PROMPT_VERSION,
    )

    transcript = "Noi dung phan tich hien tai"
    cached = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "analysis_status": "partial",
        "analysis_generation": "single_prompt_llm",
        "prompt_version": CONTEXT_PROMPT_VERSION,
        "analysis_text": "Phan tich co ich du chua co JSON day du.",
        "metrics": {
            "transcript_sha256": _exact_transcript_sha256(transcript),
        },
    }
    result_data = {
        "context_analysis": cached,
        "context_analysis_attestation": _build_context_analysis_attestation(
            cached,
            task_id="cache-task",
            transcript=transcript,
            segments=[],
        ),
    }

    assert _cached_context_analysis(result_data, transcript, "cache-task") is cached
    assert (
        _cached_context_analysis(
            result_data,
            "Noi  dung phan tich hien tai",
            "cache-task",
        )
        is None
    )
    assert _cached_context_analysis(result_data, "noi dung da doi", "cache-task") is None

    stale_prompt = copy.deepcopy(result_data)
    stale_prompt["context_analysis"]["prompt_version"] = "stale-prompt"
    assert _cached_context_analysis(stale_prompt, transcript, "cache-task") is None

    missing_attestation = copy.deepcopy(result_data)
    missing_attestation.pop("context_analysis_attestation")
    assert (
        _cached_context_analysis(missing_attestation, transcript, "cache-task")
        is None
    )


def test_analysis_attestation_binds_exact_transcript_and_generation_metadata():
    from src.api.endpoints.summary import (
        _analysis_source_metadata,
        _build_context_analysis_attestation,
        _cached_context_analysis,
    )
    from src.services.summarization.models.context_analysis import (
        ANALYSIS_SCHEMA_VERSION,
        CONTEXT_PROMPT_VERSION,
    )

    transcript = "Lan hen Minh\nluc 09:00"
    segments = [
        {
            "start": 0.0,
            "end": 2.0,
            "speaker": "SPEAKER_00",
            "text": transcript,
        }
    ]
    cached = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "analysis_status": "success",
        "analysis_generation": "single_prompt_llm",
        "prompt_version": CONTEXT_PROMPT_VERSION,
        "analysis_text": "Phan tich da ky.",
    }
    result_data = {
        "transcription": transcript,
        "segments": segments,
        "num_speakers": 1,
        "has_diarization": True,
        "diarization_status": "success",
        "context_analysis": cached,
    }
    source_metadata = _analysis_source_metadata(result_data, "cache-task")
    result_data["context_analysis_attestation"] = (
        _build_context_analysis_attestation(
            cached,
            task_id="cache-task",
            transcript=transcript,
            segments=segments,
            source_metadata=source_metadata,
        )
    )

    assert _cached_context_analysis(result_data, transcript, "cache-task") is cached
    assert (
        _cached_context_analysis(
            result_data,
            "Lan hen Minh luc 09:00",
            "cache-task",
        )
        is None
    )

    metadata_mutation = copy.deepcopy(result_data)
    metadata_mutation["num_speakers"] = 99
    assert (
        _cached_context_analysis(metadata_mutation, transcript, "cache-task")
        is None
    )

    extended_attestation = copy.deepcopy(result_data)
    extended_attestation["context_analysis_attestation"]["ignored"] = "ambiguous"
    assert (
        _cached_context_analysis(extended_attestation, transcript, "cache-task")
        is None
    )


def test_analysis_attestation_rejects_non_json_and_non_finite_inputs():
    from src.api.endpoints.summary import (
        _build_context_analysis_attestation,
        _cached_context_analysis,
    )
    from src.services.summarization.models.context_analysis import (
        ANALYSIS_SCHEMA_VERSION,
        CONTEXT_PROMPT_VERSION,
    )

    transcript = "Noi dung nguon."
    cached = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "analysis_status": "success",
        "prompt_version": CONTEXT_PROMPT_VERSION,
        "analysis_text": "Phan tich.",
    }
    valid_result = {
        "transcription": transcript,
        "segments": [],
        "context_analysis": cached,
        "context_analysis_attestation": _build_context_analysis_attestation(
            cached,
            task_id="cache-task",
            transcript=transcript,
            segments=[],
        ),
    }

    non_finite = copy.deepcopy(valid_result)
    non_finite["segments"] = [{"start": 0.0, "end": float("nan")}]
    assert _cached_context_analysis(non_finite, transcript, "cache-task") is None

    unserializable = copy.deepcopy(valid_result)
    unserializable["speaker_provenance"] = object()
    assert _cached_context_analysis(unserializable, transcript, "cache-task") is None

    with pytest.raises(ValueError, match="Non-finite"):
        _build_context_analysis_attestation(
            cached,
            task_id="cache-task",
            transcript=transcript,
            segments=[{"end": float("inf")}],
        )
    with pytest.raises(TypeError, match="Non-JSON"):
        _build_context_analysis_attestation(
            {**cached, "runtime": object()},
            task_id="cache-task",
            transcript=transcript,
            segments=[],
        )


def test_llama_startup_enforces_offline_single_gpu_idle_sleep():
    script = Path("scripts/start_llama_server.ps1").read_text(encoding="utf-8")

    assert "LLAMA_SERVER_CONTEXT_SIZE" in script
    assert "-DefaultValue 12288" in script
    assert "LLAMA_SERVER_MINIMUM_FREE_VRAM_MIB" in script
    assert "-DefaultValue 7000" in script
    assert "'--host', '127.0.0.1'" in script
    assert "'--parallel', '1'" in script
    assert "'--offline'" in script
    assert "'--sleep-idle-seconds', $SleepIdleSeconds" in script
    assert "SleepIdleSeconds must be at least 1" in script
