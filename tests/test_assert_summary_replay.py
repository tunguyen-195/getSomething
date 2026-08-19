import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.assert_summary_replay as replay_verifier
from scripts.assert_summary_replay import capture_task_state, verify_task_state
from src.services.investigation.chunk_planner import estimate_tokens
from src.core.config import settings
from src.services.summarization.summary_service_v2 import (
    SUMMARY_COMPLETION_FIXED_HEADROOM_TOKENS,
    SUMMARY_COMPLETION_TOKENS_PER_WORD,
    SUMMARY_CONTEXT_SAFETY_RESERVE_TOKENS,
    SUMMARY_MAX_COMPLETION_TOKENS,
    SUMMARY_MIN_COMPLETION_TOKENS,
    SIMPLE_INVESTIGATION_PROMPT_VERSION,
    build_simple_investigation_prompt,
    context_window_tokens_for_provider,
)


ROOT = Path(__file__).resolve().parents[1]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task(*, status: str, result: dict, error: str | None = None):
    return SimpleNamespace(id="task-1", status=status, result=result, error=error)


def _source_result(
    *,
    context: dict | None = None,
    context_attestation: dict | None = None,
) -> dict:
    result = {
        "transcription": "Noi dung goc",
        "segments": [{"start": 0.0, "end": 1.0, "text": "Noi dung goc"}],
    }
    if context is not None:
        result["context_analysis"] = context
    if context_attestation is not None:
        result["context_analysis_attestation"] = context_attestation
    return result


def _generated_result(*, context: dict | None = None) -> dict:
    summary = "Tom tat do mot lan goi LLM tra ve."
    source = _source_result(context=context)
    transcription = source["transcription"]
    segments = source["segments"]
    source_word_count = 3
    actual_words = len(summary.split())
    preferred_words = 20
    desired_completion_tokens = min(
        SUMMARY_MAX_COMPLETION_TOKENS,
        max(
            SUMMARY_MIN_COMPLETION_TOKENS,
            preferred_words * SUMMARY_COMPLETION_TOKENS_PER_WORD
            + SUMMARY_COMPLETION_FIXED_HEADROOM_TOKENS,
        ),
    )
    provider = str(settings.LOCAL_LLM_PROVIDER).strip().casefold()
    context_window_tokens = context_window_tokens_for_provider(provider)
    prompt = build_simple_investigation_prompt(
        transcription,
        transcript_segments=segments,
    )["prompt"]
    prompt_token_estimate = estimate_tokens(prompt)
    available_completion_tokens = max(
        0,
        context_window_tokens
        - SUMMARY_CONTEXT_SAFETY_RESERVE_TOKENS
        - prompt_token_estimate,
    )
    completion_token_budget = min(
        desired_completion_tokens,
        available_completion_tokens,
    )
    return {
        **source,
        "summary": summary,
        "summary_state": "generated",
        "summary_error": None,
        "summary_runtime": {
            "prompt_version": SIMPLE_INVESTIGATION_PROMPT_VERSION,
            "summary_generation": "single_prompt_llm",
            "llm_call_count": 1,
            "provider": provider,
            "user_prompt_applied": False,
            "length_contract": {
                "schema_version": "summary-length-contract-v2",
                "mode": "auto",
                "source_word_count": source_word_count,
                "proportional_ratio": 0.35,
                "preferred_words": preferred_words,
                "actual": actual_words,
                "compression_ratio": round(actual_words / source_word_count, 6),
                "maximum_enforced": False,
                "satisfied": True,
                "status": "accepted",
            },
            "context_budget": {
                "schema_version": "summary-context-budget-v1",
                "transcript_embedding_mode": "single_full_source_block",
                "token_counter": "utf8-bytes-over-2.8-ceiling",
                "context_window_tokens": context_window_tokens,
                "prompt_token_estimate": prompt_token_estimate,
                "source_token_estimate": estimate_tokens(transcription),
                "desired_completion_tokens": desired_completion_tokens,
                "available_completion_tokens": available_completion_tokens,
                "completion_token_budget": completion_token_budget,
                "safety_reserve_tokens": SUMMARY_CONTEXT_SAFETY_RESERVE_TOKENS,
                "source_occurrence_count": 1,
                "full_transcript_included": True,
                "fits_context_window": True,
                "completion_budget_clamped": (
                    completion_token_budget < desired_completion_tokens
                ),
            },
        },
    }


def test_success_accepts_current_one_call_adaptive_contract() -> None:
    context = {"analysis_status": "success", "analysis_text": "Phan tich."}
    baseline = capture_task_state(
        _task(status="summarized", result=_source_result(context=context))
    )

    report = verify_task_state(
        baseline,
        _task(status="summarized", result=_generated_result(context=context)),
    )

    assert report["status"] == "PASS"
    assert report["schema_version"] == "stt-summary-replay-v3"
    assert report["status_scope"] == (
        "one_call_summary_availability_and_persistence"
    )
    assert report["operational_status"] == "PASS"
    assert report["product_status"] == "BLOCKED"
    assert report["report_quality"]["status"] == "NOT_EVALUATED"
    assert report["outcome"] == "summarized"
    assert report["recovery"]["generation_path"] == "single_prompt_llm"
    assert report["report_availability"]["status"] == "AVAILABLE"
    assert report["failed_checks"] == []


def test_summary_replay_preserves_existing_analysis() -> None:
    context = {"analysis_status": "success", "analysis_text": "Khong duoc xoa."}
    baseline = capture_task_state(
        _task(status="summarized", result=_source_result(context=context))
    )
    changed = _generated_result(context=None)

    report = verify_task_state(
        baseline,
        _task(status="summarized", result=changed),
    )

    assert report["status"] == "FAIL"
    assert "context_analysis_shape_unchanged" in report["failed_checks"]
    assert "context_analysis_hash_unchanged" in report["failed_checks"]


def test_summary_replay_preserves_existing_analysis_attestation() -> None:
    context = {"analysis_status": "success", "analysis_text": "Khong duoc xoa."}
    attestation = {"version": "v2", "signature": "private-signature"}
    baseline = capture_task_state(
        _task(
            status="summarized",
            result=_source_result(
                context=context,
                context_attestation=attestation,
            ),
        )
    )
    changed = _generated_result(context=context)

    report = verify_task_state(
        baseline,
        _task(status="summarized", result=changed),
    )
    rendered = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "FAIL"
    assert "context_analysis_attestation_shape_unchanged" in report["failed_checks"]
    assert "context_analysis_attestation_hash_unchanged" in report["failed_checks"]
    assert "private-signature" not in rendered


@pytest.mark.parametrize(
    ("runtime_patch", "failed_check"),
    [
        ({"llm_call_count": 2}, "llm_call_count"),
        ({"llm_call_count": True}, "llm_call_count"),
        ({"llm_call_count": 1.0}, "llm_call_count"),
        ({"summary_generation": "writer_repair"}, "summary_generation"),
        ({"prompt_version": "stale"}, "prompt_version"),
        (
            {"length_contract": {"schema_version": "stale"}},
            "adaptive_length_schema",
        ),
        ({"length_contract": {"mode": "manual"}}, "adaptive_length_mode"),
        (
            {"length_contract": {"source_word_count": 999}},
            "adaptive_source_word_count",
        ),
        (
            {"length_contract": {"proportional_ratio": 0.25}},
            "soft_ratio_recorded",
        ),
        (
            {"length_contract": {"preferred_words": 999}},
            "adaptive_preferred_words",
        ),
        (
            {"length_contract": {"actual": 999}},
            "length_actual_matches_summary",
        ),
        (
            {"length_contract": {"compression_ratio": 0.5}},
            "compression_ratio_matches_summary",
        ),
        (
            {"length_contract": {"satisfied": False}},
            "adaptive_length_satisfied",
        ),
        (
            {"length_contract": {"status": "pending"}},
            "adaptive_length_status",
        ),
        (
            {"context_budget": {"schema_version": "stale"}},
            "context_budget_schema",
        ),
        (
            {"context_budget": {"source_occurrence_count": 2}},
            "single_full_source_block",
        ),
        (
            {"context_budget": {"fits_context_window": False}},
            "context_budget_fits",
        ),
        (
            {"context_budget": {"completion_token_budget": 20000}},
            "context_budget_arithmetic",
        ),
        (
            {"context_budget": {"token_counter": "approximate"}},
            "context_budget_arithmetic",
        ),
        (
            {"context_budget": {"context_window_tokens": 0}},
            "context_budget_arithmetic",
        ),
        (
            {"context_budget": {"prompt_token_estimate": 0}},
            "context_budget_arithmetic",
        ),
        (
            {"context_budget": {"source_token_estimate": 999}},
            "context_budget_arithmetic",
        ),
        (
            {"context_budget": {"desired_completion_tokens": 257}},
            "context_budget_arithmetic",
        ),
        (
            {"context_budget": {"available_completion_tokens": 0}},
            "context_budget_arithmetic",
        ),
        (
            {"context_budget": {"safety_reserve_tokens": -1}},
            "context_budget_arithmetic",
        ),
        (
            {"context_budget": {"completion_budget_clamped": True}},
            "context_budget_arithmetic",
        ),
        (
            {"context_budget": {"completion_budget_clamped": 0}},
            "context_budget_arithmetic",
        ),
        (
            {"length_contract": {"mode": "auto", "maximum_enforced": True}},
            "adaptive_maximum_not_enforced",
        ),
    ],
)
def test_obsolete_or_non_adaptive_runtime_contract_is_rejected(
    runtime_patch: dict,
    failed_check: str,
) -> None:
    baseline = capture_task_state(_task(status="summarized", result=_source_result()))
    result = _generated_result()
    replacement = runtime_patch.get("length_contract")
    if replacement is not None:
        result["summary_runtime"]["length_contract"].update(replacement)
        runtime_patch = {
            key: value for key, value in runtime_patch.items() if key != "length_contract"
        }
    context_replacement = runtime_patch.get("context_budget")
    if context_replacement is not None:
        result["summary_runtime"]["context_budget"].update(context_replacement)
        runtime_patch = {
            key: value for key, value in runtime_patch.items() if key != "context_budget"
        }
    result["summary_runtime"].update(runtime_patch)

    report = verify_task_state(
        baseline,
        _task(status="summarized", result=result),
    )

    assert report["status"] == "FAIL"
    assert failed_check in report["failed_checks"]


@pytest.mark.parametrize(
    "coherent_patch",
    [
        {
            "context_window_tokens": 999999,
            "available_completion_tokens": 999999
            - SUMMARY_CONTEXT_SAFETY_RESERVE_TOKENS,
        },
        {
            "prompt_token_estimate": 1,
        },
        {
            "safety_reserve_tokens": 0,
        },
    ],
)
def test_context_budget_rejects_coherently_fabricated_root_inputs(
    coherent_patch: dict,
) -> None:
    baseline = capture_task_state(_task(status="summarized", result=_source_result()))
    result = _generated_result()
    budget = result["summary_runtime"]["context_budget"]
    budget.update(coherent_patch)
    budget["available_completion_tokens"] = max(
        0,
        budget["context_window_tokens"]
        - budget["safety_reserve_tokens"]
        - budget["prompt_token_estimate"],
    )
    budget["completion_token_budget"] = min(
        budget["desired_completion_tokens"],
        budget["available_completion_tokens"],
    )
    budget["completion_budget_clamped"] = (
        budget["completion_token_budget"] < budget["desired_completion_tokens"]
    )

    report = verify_task_state(
        baseline,
        _task(status="summarized", result=result),
    )

    assert report["status"] == "FAIL"
    assert "context_budget_arithmetic" in report["failed_checks"]


@pytest.mark.parametrize("malformed_error", ["", [], "stale-error"])
def test_malformed_summary_error_is_not_accepted_as_absent(
    malformed_error: object,
) -> None:
    baseline = capture_task_state(_task(status="summarized", result=_source_result()))
    result = _generated_result()
    result["summary_error"] = malformed_error

    report = verify_task_state(
        baseline,
        _task(status="summarized", result=result),
    )

    assert report["status"] == "FAIL"
    assert "summary_error_absent" in report["failed_checks"]


def test_writer_rejection_is_no_longer_an_accepted_product_outcome() -> None:
    baseline = capture_task_state(_task(status="failed", result=_source_result()))
    result = {
        **_source_result(),
        "summary": None,
        "summary_state": "unavailable",
        "summary_error": {"code": "INVESTIGATION_WRITER_REJECTED"},
        "summary_runtime": {"writer_status": "rejected", "llm_call_count": 3},
    }

    report = verify_task_state(
        baseline,
        _task(status="failed", result=result, error="Writer rejected."),
    )

    assert report["status"] == "FAIL"
    assert report["outcome"] == "unexpected_terminal_state"
    assert "terminal_outcome" in report["failed_checks"]


def test_replay_artifact_hashes_summary_without_serializing_it() -> None:
    baseline = capture_task_state(_task(status="summarized", result=_source_result()))
    result = _generated_result()
    result["summary"] = "Chi muon gui so dien thoai 0912345678 cho em."
    result["summary_runtime"]["length_contract"]["actual"] = len(
        result["summary"].split()
    )
    result["summary_runtime"]["length_contract"]["compression_ratio"] = round(
        len(result["summary"].split()) / 3,
        6,
    )

    report = verify_task_state(
        baseline,
        _task(status="summarized", result=result),
    )
    rendered = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "PASS"
    assert report["current"]["summary_sha256"]
    assert "0912345678" not in rendered


def test_capture_hashes_task_error_without_serializing_it() -> None:
    sentinel = "private current error sentinel 0912345678"
    baseline = capture_task_state(
        _task(status="failed", result=_source_result(), error=sentinel)
    )
    rendered = json.dumps(baseline, ensure_ascii=False)

    assert baseline["error_present"] is True
    assert baseline["error_sha256"]
    assert sentinel not in rendered
    assert "0912345678" not in rendered


def test_source_hash_change_fails_even_when_summary_is_available() -> None:
    baseline = capture_task_state(_task(status="summarized", result=_source_result()))
    result = _generated_result()
    result["transcription"] = "Noi dung da bi thay doi"

    report = verify_task_state(
        baseline,
        _task(status="summarized", result=result),
    )

    assert report["status"] == "FAIL"
    assert "transcription_hash_unchanged" in report["failed_checks"]
    assert report["report_quality"]["reason_code"] == "REPLAY_ELIGIBILITY_FAILED"


def _run_wrapper_fixture(tmp_path: Path, payload: dict) -> subprocess.CompletedProcess:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable")
    fixture = tmp_path / "verification.json"
    fixture.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "replay_summary_task.ps1"),
            "-VerificationResultPath",
            str(fixture),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_replay_wrapper_maps_verifier_failure_to_exit_two(tmp_path: Path) -> None:
    completed = _run_wrapper_fixture(
        tmp_path,
        {
            "status": "FAIL",
            "outcome": "unexpected_terminal_state",
            "recovery": {"generation_path": "invalid_summary_generation"},
            "report_availability": {"status": "UNAVAILABLE"},
        },
    )

    assert completed.returncode == 2
    assert "Replay invariants failed" in (completed.stdout + completed.stderr)


def test_replay_wrapper_maps_one_call_summary_to_exit_zero(tmp_path: Path) -> None:
    completed = _run_wrapper_fixture(
        tmp_path,
        {
            "status": "PASS",
            "outcome": "summarized",
            "recovery": {"generation_path": "single_prompt_llm"},
            "report_availability": {"status": "AVAILABLE"},
        },
    )

    assert completed.returncode == 0
    assert "Summary replay verified" in (completed.stdout + completed.stderr)


def test_python_verifier_cli_preserves_zero_two_one_exit_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    baseline_task = _task(status="summarized", result=_source_result())
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(capture_task_state(baseline_task)),
        encoding="utf-8",
    )
    accepted_task = _task(status="summarized", result=_generated_result())
    monkeypatch.setattr(replay_verifier, "_load_task", lambda _task_id: accepted_task)

    assert replay_verifier.main(
        ["verify", "--task-id", "task-1", "--baseline", str(baseline_path)]
    ) == 0

    changed_result = {**_generated_result(), "transcription": "Noi dung da thay doi"}
    monkeypatch.setattr(
        replay_verifier,
        "_load_task",
        lambda _task_id: _task(status="summarized", result=changed_result),
    )
    assert replay_verifier.main(
        ["verify", "--task-id", "task-1", "--baseline", str(baseline_path)]
    ) == 2

    def fail_load(_task_id: str):
        raise LookupError("task unavailable")

    monkeypatch.setattr(replay_verifier, "_load_task", fail_load)
    assert replay_verifier.main(
        ["verify", "--task-id", "task-1", "--baseline", str(baseline_path)]
    ) == 1


def test_s2_r0_evidence_artifact_remains_an_immutable_historical_record() -> None:
    artifact_path = ROOT / "docs" / "reviews" / "artifacts" / "s2-r0-summary-recovery.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert artifact["verdict"] == "PASS"
    assert artifact["product_status"] == "BLOCKED"
    assert artifact["environment"]["source_scope"] == "working_tree_exact_allowlist"
    assert len(artifact["environment"]["git_head"]) == 40
    for relative, recorded_hash in artifact["source_sha256"].items():
        assert not Path(relative).is_absolute()
        assert len(recorded_hash) == 64
        assert all(character in "0123456789abcdef" for character in recorded_hash)
    for directory, replay in artifact["live_replays"].items():
        replay_root = ROOT / "output" / "summary-replay" / directory
        for filename, evidence in replay["files"].items():
            path = replay_root / filename
            assert path.stat().st_size == evidence["bytes"]
            assert _sha256_file(path) == evidence["sha256"]
