from __future__ import annotations

import json
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import dataclass
from enum import Enum
from functools import partial

import pytest

from src.core.config import settings
from src.services.summarization import bulletin_writer
from src.services.summarization import summary_service_v2
from src.services.summarization.models import llm_manager as llm_manager_module
from src.worker.runtime_contract import (
    RuntimeContractUnsupportedState,
    SUMMARY_IMPLEMENTATION_CONTRACT_VERSION,
    WORKER_RUNTIME_CONTRACT_VERSION,
    _module_implementation_digest,
    build_worker_runtime_contract,
    compare_worker_runtime_contracts,
    task_request_schema,
)
from src.worker.tasks import summarize_task
from src.worker.tasks.runtime_contract_task import worker_runtime_contract_task


def _task(task_id: str) -> dict:
    return {
        "id": task_id,
        "filename": "sample.wav",
        "status": "transcribed",
        "result": {
            "transcription": "Lan hẹn Minh tại bến xe lúc 09:00.",
            "segments": [],
        },
    }


def test_live_contract_task_matches_loaded_summary_signature() -> None:
    expected = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )
    observed = worker_runtime_contract_task.run()

    assert compare_worker_runtime_contracts(expected, observed) == []
    assert observed["fingerprint"] == expected["fingerprint"]
    assert observed["schema_version"] == WORKER_RUNTIME_CONTRACT_VERSION
    assert (
        observed["summary_implementation"]["schema_version"]
        == SUMMARY_IMPLEMENTATION_CONTRACT_VERSION
    )
    assert set(observed["summary_implementation"]["components"]) == {
        "summary_task_callable",
        "summary_runtime_settings",
        "src.core.config",
        "src.worker.tasks.summarize_task",
        "src.services.task_service",
        "src.services.model_runtime.gpu_lease",
        "src.services.investigation.claim_semantics",
        "src.services.investigation.contracts",
        "src.services.investigation.evidence_selector",
        "src.services.investigation.exact_detectors",
        "src.services.investigation.narrative_attestation",
        "src.services.investigation.run_contracts",
        "src.services.investigation.source_revision",
        "src.services.investigation.verification_contracts",
        "src.services.summarization.contracts",
        "src.services.summarization.summary_service_v2",
        "src.services.summarization.context_service",
        "src.services.summarization.deterministic_analysis",
        "src.services.summarization.investigation_preview",
        "src.services.summarization.legacy_context_adapter",
        "src.services.summarization.bulletin_writer",
        "src.services.summarization.models.context_analysis",
        "src.services.summarization.models.investigation_knowledge",
        "src.services.summarization.models.llm_manager",
        "src.services.summarization.models.openai_compatible_client",
        "src.services.summarization.investigation_scenarios",
        "src.services.summarization.public_projection",
    }


def test_contract_fingerprint_changes_when_wire_signature_changes() -> None:
    def old_task(task_id: str, model_name: str | None = None):
        return task_id, model_name

    def new_task(
        task_id: str,
        model_name: str | None = None,
        investigation_scenario: str = "auto",
    ):
        return task_id, model_name, investigation_scenario

    old_contract = build_worker_runtime_contract(old_task)
    new_contract = build_worker_runtime_contract(new_task)

    assert old_contract["fingerprint"] != new_contract["fingerprint"]
    assert compare_worker_runtime_contracts(new_contract, old_contract)


def test_contract_detects_same_signature_implementation_change() -> None:
    def old_task(task_id: str, model_name: str | None = None):
        return task_id, model_name

    def new_task(task_id: str, model_name: str | None = None):
        return {"task_id": task_id, "model_name": model_name}

    assert task_request_schema(old_task) == task_request_schema(new_task)

    old_contract = build_worker_runtime_contract(old_task)
    new_contract = build_worker_runtime_contract(new_task)

    assert old_contract["summary_task"] == new_contract["summary_task"]
    assert (
        old_contract["summary_implementation"]["fingerprint"]
        != new_contract["summary_implementation"]["fingerprint"]
    )
    assert "summary implementation fingerprint mismatch" in (
        compare_worker_runtime_contracts(new_contract, old_contract)
    )


def test_contract_detects_closure_and_annotation_changes() -> None:
    def make_task(marker: str):
        def task(task_id: str, model_name: str | None = None):
            return marker, task_id, model_name

        return task

    old_closure = build_worker_runtime_contract(make_task("old"))
    new_closure = build_worker_runtime_contract(make_task("new"))
    assert old_closure["summary_task"] == new_closure["summary_task"]
    assert old_closure["fingerprint"] != new_closure["fingerprint"]

    def old_annotation(task_id: "old_task_id"):  # noqa: F821
        return task_id

    def new_annotation(task_id: "new_task_id"):  # noqa: F821
        return task_id

    old_typed = build_worker_runtime_contract(old_annotation)
    new_typed = build_worker_runtime_contract(new_annotation)
    assert old_typed["summary_task"] == new_typed["summary_task"]
    assert old_typed["fingerprint"] != new_typed["fingerprint"]

    def old_generic_annotation(task_id: list[str]):
        return task_id

    def new_generic_annotation(task_id: list[int]):
        return task_id

    old_generic = build_worker_runtime_contract(old_generic_annotation)
    new_generic = build_worker_runtime_contract(new_generic_annotation)
    assert old_generic["summary_task"] == new_generic["summary_task"]
    assert old_generic["fingerprint"] != new_generic["fingerprint"]

    @dataclass(frozen=True)
    class ClosureState:
        marker: str

    def make_stateful_task(marker: str):
        state = ClosureState(marker)

        def task(task_id: str):
            return state.marker, task_id

        return task

    old_state = build_worker_runtime_contract(make_stateful_task("old"))
    new_state = build_worker_runtime_contract(make_stateful_task("new"))
    assert old_state["summary_task"] == new_state["summary_task"]
    assert old_state["fingerprint"] != new_state["fingerprint"]


def test_contract_ignores_code_filename_when_semantics_match() -> None:
    source = "def task(task_id: str):\n    return task_id\n"
    old_namespace: dict[str, object] = {}
    new_namespace: dict[str, object] = {}
    exec(compile(source, "old_workspace.py", "exec"), old_namespace)
    exec(compile(source, "new_workspace.py", "exec"), new_namespace)

    old_contract = build_worker_runtime_contract(old_namespace["task"])
    new_contract = build_worker_runtime_contract(new_namespace["task"])

    assert old_contract["summary_implementation"] == (
        new_contract["summary_implementation"]
    )
    assert old_contract["fingerprint"] == new_contract["fingerprint"]


def test_module_digest_ignores_absolute_import_origin(monkeypatch) -> None:
    monkeypatch.setattr(
        bulletin_writer,
        "__file__",
        "C:/deploy-a/src/services/summarization/bulletin_writer.py",
    )
    old_digest = _module_implementation_digest(bulletin_writer.__name__)
    monkeypatch.setattr(
        bulletin_writer,
        "__file__",
        "E:/deploy-b/src/services/summarization/bulletin_writer.py",
    )
    new_digest = _module_implementation_digest(bulletin_writer.__name__)

    assert old_digest == new_digest


def test_module_digest_ignores_llm_singleton_runtime_state(monkeypatch) -> None:
    monkeypatch.setattr(llm_manager_module.LLMManager, "_instance", None)
    monkeypatch.setattr(llm_manager_module.LLMManager, "_initialized", False)
    before_initialization = _module_implementation_digest(
        llm_manager_module.__name__
    )

    manager = llm_manager_module.LLMManager()
    assert manager._initialized is True
    after_initialization = _module_implementation_digest(
        llm_manager_module.__name__
    )

    assert after_initialization == before_initialization


def test_contract_detects_module_class_and_enum_constants(monkeypatch) -> None:
    monkeypatch.setattr(
        bulletin_writer,
        "runtime_prompt_marker",
        "old-prompt",
        raising=False,
    )
    old_prompt = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )
    monkeypatch.setattr(bulletin_writer, "runtime_prompt_marker", "new-prompt")
    new_prompt = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    monkeypatch.setattr(
        bulletin_writer,
        "runtime_container_marker",
        ["value"],
        raising=False,
    )
    old_container = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )
    monkeypatch.setattr(
        bulletin_writer,
        "runtime_container_marker",
        ("value",),
    )
    new_container = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    class OldPolicy:
        mode = "old"

    class NewPolicy:
        mode = "new"

    OldPolicy.__module__ = bulletin_writer.__name__
    NewPolicy.__module__ = bulletin_writer.__name__
    monkeypatch.setattr(
        bulletin_writer,
        "RuntimeContractPolicy",
        OldPolicy,
        raising=False,
    )
    old_class = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )
    monkeypatch.setattr(bulletin_writer, "RuntimeContractPolicy", NewPolicy)
    new_class = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    class OldMode(Enum):
        VALUE = "old"

    class NewMode(Enum):
        VALUE = "new"

    OldMode.__module__ = bulletin_writer.__name__
    NewMode.__module__ = bulletin_writer.__name__
    monkeypatch.setattr(
        bulletin_writer,
        "RuntimeContractMode",
        OldMode,
        raising=False,
    )
    old_enum = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )
    monkeypatch.setattr(bulletin_writer, "RuntimeContractMode", NewMode)
    new_enum = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    component = "src.services.summarization.bulletin_writer"
    assert (
        old_prompt["summary_implementation"]["components"][component]
        != new_prompt["summary_implementation"]["components"][component]
    )
    assert (
        old_class["summary_implementation"]["components"][component]
        != new_class["summary_implementation"]["components"][component]
    )
    assert (
        old_container["summary_implementation"]["components"][component]
        != new_container["summary_implementation"]["components"][component]
    )
    assert (
        old_enum["summary_implementation"]["components"][component]
        != new_enum["summary_implementation"]["components"][component]
    )


def test_contract_detects_descriptors_and_callable_closure_state(monkeypatch) -> None:
    class OldDescriptor:
        @property
        def value(self):
            return "old"

    class NewDescriptor:
        @property
        def value(self):
            return "new"

    OldDescriptor.__module__ = bulletin_writer.__name__
    NewDescriptor.__module__ = bulletin_writer.__name__
    monkeypatch.setattr(
        bulletin_writer,
        "RuntimeContractDescriptor",
        OldDescriptor,
        raising=False,
    )
    old_descriptor = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )
    monkeypatch.setattr(
        bulletin_writer,
        "RuntimeContractDescriptor",
        NewDescriptor,
    )
    new_descriptor = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    def old_helper(value: str):
        return value

    def new_helper(value: str):
        return {"value": value}

    class MutableState:
        def __init__(self) -> None:
            self.helper = old_helper

    state = MutableState()

    def task(task_id: str):
        return state.helper(task_id)

    initial_state = build_worker_runtime_contract(task)
    state.helper = new_helper
    changed_helper = build_worker_runtime_contract(task)

    component = "src.services.summarization.bulletin_writer"
    assert (
        old_descriptor["summary_implementation"]["components"][component]
        != new_descriptor["summary_implementation"]["components"][component]
    )
    assert initial_state["fingerprint"] != changed_helper["fingerprint"]


def test_mutable_closure_containers_fail_closed() -> None:
    state = {"counter": 1, "history": ["started"], "flags": {"ready"}}

    def task(task_id: str):
        return state, task_id

    with pytest.raises(RuntimeContractUnsupportedState):
        build_worker_runtime_contract(task)


def test_mutable_dataclass_callable_and_non_code_callables_are_detected() -> None:
    def old_helper(prefix: str, value: str):
        return f"{prefix}:{value}"

    def new_helper(prefix: str, value: str):
        return {"prefix": prefix, "value": value}

    @dataclass
    class MutableState:
        helper: object

    state = MutableState(helper=old_helper)

    def state_task(task_id: str):
        return state.helper("state", task_id)

    initial_state = build_worker_runtime_contract(state_task)
    state.helper = new_helper
    changed_helper = build_worker_runtime_contract(state_task)

    def make_partial_task(prefix: str):
        bound = partial(old_helper, prefix)

        def task(task_id: str):
            return bound(task_id)

        return task

    old_partial = build_worker_runtime_contract(make_partial_task("old"))
    new_partial = build_worker_runtime_contract(make_partial_task("new"))

    class OldCallable:
        def __call__(self, value: str):
            return value

    class NewCallable:
        def __call__(self, value: str):
            return {"value": value}

    def make_callable_task(helper):
        def task(task_id: str):
            return helper(task_id)

        return task

    old_callable = build_worker_runtime_contract(
        make_callable_task(OldCallable())
    )
    new_callable = build_worker_runtime_contract(
        make_callable_task(NewCallable())
    )

    class SlotState:
        __slots__ = "helper"

        def __init__(self, helper) -> None:
            self.helper = helper

    slot_state = SlotState(old_helper)

    def slot_task(task_id: str):
        return slot_state.helper("slot", task_id)

    old_slot = build_worker_runtime_contract(slot_task)
    slot_state.helper = new_helper
    new_slot = build_worker_runtime_contract(slot_task)

    assert initial_state["fingerprint"] != changed_helper["fingerprint"]
    assert old_partial["fingerprint"] != new_partial["fingerprint"]
    assert old_callable["fingerprint"] != new_callable["fingerprint"]
    assert old_slot["fingerprint"] != new_slot["fingerprint"]


def test_mutable_semantic_configuration_fails_closed() -> None:
    @dataclass
    class MutableConfig:
        mode: str

    def make_dataclass_task(mode: str):
        config = MutableConfig(mode=mode)

        def task(task_id: str):
            return config.mode, task_id

        return task

    class CallableConfig:
        def __init__(self, prefix: str) -> None:
            self.prefix = prefix

        def __call__(self, value: str):
            return f"{self.prefix}:{value}"

    def make_callable_task(prefix: str):
        helper = CallableConfig(prefix)

        def task(task_id: str):
            return helper(task_id)

        return task

    def helper(config: dict[str, str], value: str):
        return config["mode"], value

    def make_partial_task(mode: str):
        bound = partial(helper, {"mode": mode})

        def task(task_id: str):
            return bound(task_id)

        return task

    for task in (
        make_dataclass_task("old"),
        make_callable_task("old"),
        make_partial_task("old"),
    ):
        with pytest.raises(RuntimeContractUnsupportedState):
            build_worker_runtime_contract(task)


def test_contract_comparison_rejects_missing_or_tampered_structure() -> None:
    assert compare_worker_runtime_contracts({}, {})

    expected = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )
    missing_component = json.loads(json.dumps(expected))
    del missing_component["summary_implementation"]["components"][
        "src.services.summarization.bulletin_writer"
    ]
    errors = compare_worker_runtime_contracts(expected, missing_component)
    assert "observed summary implementation contract is invalid" in errors

    tampered_fingerprint = json.loads(json.dumps(expected))
    tampered_fingerprint["fingerprint"] = "0" * 64
    errors = compare_worker_runtime_contracts(expected, tampered_fingerprint)
    assert "observed runtime contract fingerprint is invalid" in errors


def test_contract_detects_loaded_writer_dependency_change(monkeypatch) -> None:
    baseline = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    def replacement_prompt(
        context_analysis,
        *,
        scenario_profile,
        max_words,
    ):
        return f"replacement:{scenario_profile}:{max_words}:{bool(context_analysis)}"

    replacement_prompt.__module__ = bulletin_writer.__name__
    monkeypatch.setattr(
        bulletin_writer,
        "build_bulletin_writer_prompt",
        replacement_prompt,
    )
    changed = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    component = "src.services.summarization.bulletin_writer"
    assert (
        baseline["summary_implementation"]["components"][component]
        != changed["summary_implementation"]["components"][component]
    )
    assert baseline["fingerprint"] != changed["fingerprint"]


def test_contract_detects_worker_failure_propagation_change(monkeypatch) -> None:
    baseline = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    def replacement_failure_update(error):
        return {"status": "failed", "error": error.code}

    replacement_failure_update.__module__ = summarize_task.__name__
    monkeypatch.setattr(
        summarize_task,
        "_safe_failure_update",
        replacement_failure_update,
    )
    changed = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    component = "src.worker.tasks.summarize_task"
    assert (
        baseline["summary_implementation"]["components"][component]
        != changed["summary_implementation"]["components"][component]
    )
    assert baseline["fingerprint"] != changed["fingerprint"]


def test_contract_detects_imported_repo_helper_change(monkeypatch) -> None:
    def old_helper(value):
        return value

    def new_helper(value):
        return {"value": value}

    old_helper.__module__ = "src.runtime_contract_test_helper"
    new_helper.__module__ = "src.runtime_contract_test_helper"
    monkeypatch.setattr(
        bulletin_writer,
        "_runtime_contract_test_helper",
        old_helper,
        raising=False,
    )
    old_contract = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )
    monkeypatch.setattr(
        bulletin_writer,
        "_runtime_contract_test_helper",
        new_helper,
    )
    new_contract = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    component = "src.services.summarization.bulletin_writer"
    assert (
        old_contract["summary_implementation"]["components"][component]
        != new_contract["summary_implementation"]["components"][component]
    )


def test_contract_detects_non_secret_runtime_setting_change(monkeypatch) -> None:
    baseline = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )
    monkeypatch.setattr(settings, "LLM_SEED", settings.LLM_SEED + 1)
    changed = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    component = "summary_runtime_settings"
    assert (
        baseline["summary_implementation"]["components"][component]
        != changed["summary_implementation"]["components"][component]
    )


def test_contract_detects_llama_context_setting_change(monkeypatch) -> None:
    baseline = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )
    monkeypatch.setattr(
        settings,
        "LLAMA_SERVER_CONTEXT_SIZE",
        settings.LLAMA_SERVER_CONTEXT_SIZE + 1024,
    )
    changed = build_worker_runtime_contract(
        summarize_task.summarize_transcript_task.run
    )

    component = "summary_runtime_settings"
    assert (
        baseline["summary_implementation"]["components"][component]
        != changed["summary_implementation"]["components"][component]
    )


def test_contract_fingerprint_is_stable_across_python_processes() -> None:
    command = [
        sys.executable,
        "-c",
        (
            "import json; "
            "from src.worker.runtime_contract import build_worker_runtime_contract; "
            "from src.worker.tasks.summarize_task import summarize_transcript_task; "
            "print(json.dumps(build_worker_runtime_contract("
            "summarize_transcript_task.run)))"
        ),
    ]
    fingerprints = []
    for _ in range(2):
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        payload = json.loads(result.stdout.splitlines()[-1])
        fingerprints.append(payload["fingerprint"])

    assert len(set(fingerprints)) == 1


def test_future_request_field_fails_typed_instead_of_argument_binding(
    monkeypatch,
) -> None:
    updates: list[dict] = []
    monkeypatch.setattr(summarize_task, "get_task", lambda task_id: _task(task_id))
    monkeypatch.setattr(
        summarize_task,
        "update_task",
        lambda task_id, data: updates.append(data) is None or True,
    )

    with pytest.raises(summarize_task.SafeSummaryTaskError) as exc_info:
        summarize_task.summarize_transcript_task.run(
            "task-contract-mismatch",
            future_request_field="unsupported",
        )

    assert exc_info.value.code == "SUMMARY_REQUEST_CONTRACT_MISMATCH"
    assert updates[-1]["status"] == "failed"
    assert "incompatible" in updates[-1]["error"]


def test_preview_only_result_never_persists_summarized(monkeypatch) -> None:
    updates: list[dict] = []
    monkeypatch.setattr(summarize_task, "get_task", lambda task_id: _task(task_id))
    monkeypatch.setattr(
        summarize_task,
        "update_task",
        lambda task_id, data: updates.append(data) is None or True,
    )
    monkeypatch.setattr(
        summarize_task,
        "_llama_server_handoff",
        lambda *args, **kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **kwargs: {
            "available": True,
            "summary": "",
            "summary_state": "grounded_transcript_only",
            "summary_preview": {
                "text": "Lan hẹn Minh tại bến xe lúc 09:00.",
                "world_facts_released": False,
            },
        },
    )

    with pytest.raises(summarize_task.SafeSummaryTaskError) as exc_info:
        summarize_task.summarize_transcript_task.run("task-preview-only")

    assert exc_info.value.code == "SUMMARY_PREVIEW_ONLY"
    assert updates[-1]["status"] == "failed"
    assert updates[-1]["result"]["summary"] is None
    assert updates[-1]["result"]["summary_state"] == "unavailable"
    assert updates[-1]["result"]["summary_preview"] is None
    assert updates[-1]["result"]["summary_error"]["code"] == "SUMMARY_PREVIEW_ONLY"
    assert all(update.get("status") != "summarized" for update in updates)


def test_third_attempt_writer_rejection_preserves_typed_runtime(
    monkeypatch,
) -> None:
    updates: list[dict] = []
    provider_detail = "unsupported source sentence fragment"
    runtime = {
        "writer_status": "rejected",
        "llm_call_count": 3,
        "writer_prompt_version": "investigative-bulletin-prompt-v5-repair-contract",
        "writer_sentence_delta_repair_applied": False,
        "token_budgets": [
            {"prompt_kind": "initial", "completion_tokens": 1024},
            {"prompt_kind": "repair", "completion_tokens": 768},
            {"prompt_kind": "delta_repair", "completion_tokens": 256},
        ],
    }
    monkeypatch.setattr(summarize_task, "get_task", lambda task_id: _task(task_id))
    monkeypatch.setattr(
        summarize_task,
        "update_task",
        lambda task_id, data: updates.append(data) is None or True,
    )
    monkeypatch.setattr(
        summarize_task,
        "_llama_server_handoff",
        lambda *args, **kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        summary_service_v2,
        "summarize_transcript_v2",
        lambda **kwargs: {
            "available": False,
            "summary": "",
            "summary_state": "unavailable",
            "error": {
                "code": "INVESTIGATION_WRITER_REJECTED",
                "message": provider_detail,
            },
            "runtime": runtime,
        },
    )

    with pytest.raises(summarize_task.SafeSummaryTaskError) as exc_info:
        summarize_task.summarize_transcript_task.run(
            "task-third-attempt-rejected",
            summary_type="investigation",
            min_length=120,
            max_length=400,
        )

    assert exc_info.value.code == "INVESTIGATION_WRITER_REJECTED"
    assert [update["status"] for update in updates] == ["summarizing", "failed"]
    failure = updates[-1]
    assert failure["error"] == (
        "The investigation summary failed its grounded-content quality gate."
    )
    assert failure["result"]["summary"] is None
    assert failure["result"]["summary_state"] == "unavailable"
    assert failure["result"]["summary_error"]["code"] == (
        "INVESTIGATION_WRITER_REJECTED"
    )
    assert failure["result"]["summary_notice"]["code"] == (
        "INVESTIGATION_WRITER_REJECTED"
    )
    assert failure["result"]["summary_runtime"] == runtime
    assert failure["result"]["summary_runtime"]["llm_call_count"] == 3
    assert [
        budget["prompt_kind"]
        for budget in failure["result"]["summary_runtime"]["token_budgets"]
    ] == ["initial", "repair", "delta_repair"]
    assert provider_detail not in repr(failure)
    assert "SUMMARY_GENERATION_FAILED" not in repr(failure)


def test_celery_prefers_current_top_level_diarized_segments(monkeypatch) -> None:
    updates: list[dict] = []
    captured: dict = {}
    current_segments = [
        {"speaker": "SPEAKER_00", "text": "Chị tên là Quyên."},
        {"speaker": "SPEAKER_01", "text": "Bên em vẫn còn phòng."},
    ]
    stale_nested_segments = [
        {"speaker": None, "text": "Chị tên là Quyên."},
        {"speaker": None, "text": "Bên em vẫn còn phòng."},
    ]
    monkeypatch.setattr(
        summarize_task,
        "get_task",
        lambda _task_id: {
            "result": {
                "transcription": "Chị tên là Quyên. Bên em vẫn còn phòng.",
                "segments": current_segments,
                "transcription_result": {"segments": stale_nested_segments},
            }
        },
    )
    monkeypatch.setattr(
        summarize_task,
        "update_task",
        lambda _task_id, data: updates.append(data) or True,
    )
    monkeypatch.setattr(
        summarize_task,
        "_llama_server_handoff",
        lambda *args, **kwargs: nullcontext(),
    )

    def summarize(**kwargs):
        captured.update(kwargs)
        return {
            "available": True,
            "summary": "Quyên trao đổi với người tham gia thứ hai.",
            "summary_state": "source_grounded_narrative",
            "context": {},
            "runtime": {},
        }

    monkeypatch.setattr(summary_service_v2, "summarize_transcript_v2", summarize)

    result = summarize_task.summarize_transcript_task.run(
        "task-current-segments",
        summary_type="investigation",
        min_length=120,
        max_length=400,
    )

    assert captured["transcript_segments"] == current_segments
    assert captured["source_metadata"]["current_transcript_segments"] == (
        current_segments
    )
    assert result["status"] == "success"
    assert [update["status"] for update in updates] == ["summarizing", "summarized"]


def test_celery_uses_nested_segments_only_for_legacy_results(monkeypatch) -> None:
    captured: dict = {}
    legacy_segments = [{"speaker": "SPEAKER_00", "text": "Nội dung."}]
    monkeypatch.setattr(
        summarize_task,
        "get_task",
        lambda _task_id: {
            "result": {
                "transcription": "Nội dung.",
                "transcription_result": {"segments": legacy_segments},
            }
        },
    )
    monkeypatch.setattr(summarize_task, "update_task", lambda *_args: True)
    monkeypatch.setattr(
        summarize_task,
        "_llama_server_handoff",
        lambda *args, **kwargs: nullcontext(),
    )

    def summarize(**kwargs):
        captured.update(kwargs)
        return {
            "available": True,
            "summary": "Một người tham gia cung cấp nội dung.",
            "summary_state": "source_grounded_narrative",
            "context": {},
            "runtime": {},
        }

    monkeypatch.setattr(summary_service_v2, "summarize_transcript_v2", summarize)

    summarize_task.summarize_transcript_task.run(
        "task-legacy-segments",
        summary_type="investigation",
        min_length=120,
        max_length=400,
    )

    assert captured["transcript_segments"] == legacy_segments


def test_typed_failure_discards_malformed_runtime_diagnostics() -> None:
    error = summarize_task.SafeSummaryTaskError(
        "INVESTIGATION_WRITER_REJECTED",
        result={"runtime": ["not", "an", "object"]},
    )

    update = summarize_task._safe_failure_update(error)

    assert update["result"]["summary_error"]["code"] == (
        "INVESTIGATION_WRITER_REJECTED"
    )
    assert update["result"]["summary_runtime"] == {}
