import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.assert_summary_replay as replay_verifier
from scripts.assert_summary_replay import capture_task_state, verify_task_state


ROOT = Path(__file__).resolve().parents[1]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _budgets(count: int) -> list[dict[str, str]]:
    return [
        {"prompt_kind": kind}
        for kind in ["initial", "repair", "delta_repair"][:count]
    ]


def _task(*, status: str, result: dict, error: str | None = None):
    return SimpleNamespace(id="task-1", status=status, result=result, error=error)


def _source_result() -> dict:
    return {
        "transcription": "Noi dung goc",
        "segments": [{"start": 0.0, "end": 1.0, "text": "Noi dung goc"}],
        "context_analysis": {"summary": "context"},
    }


def test_success_preserves_source_and_accepts_grounded_writer() -> None:
    baseline = capture_task_state(_task(status="failed", result=_source_result()))
    result = {
        **_source_result(),
        "summary": "Ban tin da duoc xac minh boi cac gate nguon.",
        "summary_state": "source_grounded_narrative",
        "summary_authority": {"world_facts_released": False},
        "summary_preview": {"world_facts_released": False},
        "summary_runtime": {
            "writer_status": "accepted",
            "llm_call_count": 3,
            "token_budgets": _budgets(3),
        },
    }

    report = verify_task_state(
        baseline,
        _task(status="summarized", result=result),
    )

    assert report["status"] == "PASS"
    assert report["schema_version"] == "stt-summary-replay-v2"
    assert report["status_scope"] == "availability_and_recovery_only"
    assert report["product_status"] == "BLOCKED"
    assert report["report_quality"]["status"] == "NOT_EVALUATED"
    assert report["report_quality"]["reason_code"] == (
        "R5_SHARED_VALIDATOR_UNAVAILABLE"
    )
    assert report["quality_included_in_status"] is False
    assert report["outcome"] == "summarized"
    assert report["failed_checks"] == []


def test_typed_writer_rejection_keeps_diagnostics() -> None:
    baseline = capture_task_state(_task(status="failed", result=_source_result()))
    result = {
        **_source_result(),
        "summary": None,
        "summary_state": "unavailable",
        "summary_error": {
            "code": "INVESTIGATION_WRITER_REJECTED",
            "message": "The investigative bulletin writer rejected the draft.",
        },
        "summary_runtime": {
            "writer_status": "rejected",
            "llm_call_count": 3,
            "token_budgets": _budgets(3),
        },
    }

    report = verify_task_state(
        baseline,
        _task(
            status="failed",
            result=result,
            error="The investigative bulletin writer rejected the draft.",
        ),
    )

    assert report["status"] == "PASS"
    assert report["outcome"] == "typed_writer_rejection"
    assert report["recovery"]["generation_path"] == "all_attempts_rejected"
    assert report["report_availability"]["status"] == "UNAVAILABLE"
    assert report["report_quality"]["status"] == "BLOCKED"


def test_two_call_writer_rejection_is_not_misreported_as_recovered() -> None:
    baseline = capture_task_state(_task(status="failed", result=_source_result()))
    result = {
        **_source_result(),
        "summary": None,
        "summary_state": "unavailable",
        "summary_error": {"code": "INVESTIGATION_WRITER_REJECTED"},
        "summary_runtime": {
            "writer_status": "rejected",
            "llm_call_count": 2,
            "token_budgets": _budgets(2),
        },
    }

    report = verify_task_state(
        baseline,
        _task(status="failed", result=result, error="Quality gate rejected."),
    )

    assert report["status"] == "FAIL"
    assert report["eligibility"]["status"] == "PASS"
    assert report["recovery"]["status"] == "FAIL"
    assert "bounded_recovery_path" in report["failed_checks"]


def test_two_call_typed_coverage_rejection_is_bounded_non_delta_outcome() -> None:
    baseline = capture_task_state(_task(status="failed", result=_source_result()))
    result = {
        **_source_result(),
        "summary": None,
        "summary_state": "unavailable",
        "summary_error": {"code": "INVESTIGATION_COVERAGE_FAILED"},
        "summary_runtime": {
            "writer_status": "rejected",
            "llm_call_count": 2,
            "token_budgets": _budgets(2),
        },
    }

    report = verify_task_state(
        baseline,
        _task(status="failed", result=result, error="Coverage gate rejected."),
    )

    assert report["status"] == "PASS"
    assert report["recovery"]["generation_path"] == (
        "bounded_non_delta_rejection"
    )
    assert report["report_quality"]["status"] == "BLOCKED"


def test_non_delta_rejection_requires_exactly_initial_and_repair_calls() -> None:
    baseline = capture_task_state(_task(status="failed", result=_source_result()))

    for call_count in (1, 3):
        result = {
            **_source_result(),
            "summary": None,
            "summary_state": "unavailable",
            "summary_error": {"code": "INVESTIGATION_LENGTH_CONFLICT"},
            "summary_runtime": {
                "writer_status": "rejected",
                "llm_call_count": call_count,
                "token_budgets": _budgets(call_count),
            },
        }

        report = verify_task_state(
            baseline,
            _task(status="failed", result=result, error="Length gate rejected."),
        )

        assert report["status"] == "FAIL"
        assert report["recovery"]["generation_path"] == "invalid_attempt_sequence"
        assert "bounded_recovery_path" in report["failed_checks"]
        assert report["report_quality"]["status"] == "BLOCKED"
        assert report["report_quality"]["reason_code"] == (
            "RECOVERY_INVARIANTS_FAILED"
        )


def test_replay_artifact_hashes_report_body_without_serializing_it() -> None:
    baseline = capture_task_state(_task(status="failed", result=_source_result()))
    sensitive_body = "Chi muon gui so dien thoai 0912345678 cho em."
    result = {
        **_source_result(),
        "summary": sensitive_body,
        "summary_state": "source_grounded_narrative",
        "summary_authority": {"world_facts_released": False},
        "summary_preview": {"world_facts_released": False},
        "summary_runtime": {
            "writer_status": "accepted",
            "llm_call_count": 1,
            "token_budgets": _budgets(1),
        },
    }

    report = verify_task_state(
        baseline,
        _task(status="summarized", result=result),
    )
    rendered = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "PASS"
    assert report["report_quality"]["status"] == "NOT_EVALUATED"
    assert report["current"]["summary_sha256"]
    assert sensitive_body not in rendered
    assert "0912345678" not in rendered


def test_replay_artifact_hashes_task_error_without_serializing_it() -> None:
    sentinel = "private transcript sentinel 0912345678"
    task = _task(status="failed", result=_source_result(), error=sentinel)

    baseline = capture_task_state(task)
    rendered = json.dumps(baseline, ensure_ascii=False)

    assert baseline["error_present"] is True
    assert baseline["error_is_generic_failure"] is False
    assert baseline["error_sha256"]
    assert sentinel not in rendered
    assert "0912345678" not in rendered


def test_verification_hashes_task_error_without_serializing_current_or_checks() -> None:
    baseline = capture_task_state(_task(status="failed", result=_source_result()))
    sentinel = "private current error sentinel 0912345678"
    result = {
        **_source_result(),
        "summary": None,
        "summary_state": "unavailable",
        "summary_error": {"code": "INVESTIGATION_LENGTH_CONFLICT"},
        "summary_runtime": {
            "writer_status": "rejected",
            "llm_call_count": 2,
            "token_budgets": _budgets(2),
        },
    }

    report = verify_task_state(
        baseline,
        _task(status="failed", result=result, error=sentinel),
    )
    rendered = json.dumps(report, ensure_ascii=False)

    assert report["status"] == "PASS"
    assert report["current"]["error_present"] is True
    assert report["current"]["error_sha256"]
    assert sentinel not in rendered
    assert "0912345678" not in rendered


def test_generic_failure_is_not_accepted_as_verification() -> None:
    baseline = capture_task_state(_task(status="failed", result=_source_result()))
    result = {
        **_source_result(),
        "summary": None,
        "summary_state": "unavailable",
        "summary_error": {"code": "SUMMARY_GENERATION_FAILED"},
        "summary_runtime": {},
    }

    report = verify_task_state(
        baseline,
        _task(status="failed", result=result, error="Summary generation failed."),
    )

    assert report["status"] == "FAIL"
    assert report["outcome"] == "unexpected_terminal_state"
    assert "terminal_outcome" in report["failed_checks"]


def test_source_hash_change_fails_even_when_summary_is_accepted() -> None:
    baseline = capture_task_state(_task(status="failed", result=_source_result()))
    result = {
        **_source_result(),
        "transcription": "Noi dung da bi thay doi",
        "summary": "Ban tin.",
        "summary_state": "source_grounded_narrative",
        "summary_authority": {"world_facts_released": False},
        "summary_preview": {"world_facts_released": False},
        "summary_runtime": {
            "writer_status": "accepted",
            "llm_call_count": 1,
            "token_budgets": _budgets(1),
        },
    }

    report = verify_task_state(
        baseline,
        _task(status="summarized", result=result),
    )

    assert report["status"] == "FAIL"
    assert "transcription_hash_unchanged" in report["failed_checks"]
    assert report["report_quality"]["status"] == "BLOCKED"
    assert report["report_quality"]["reason_code"] == (
        "REPLAY_ELIGIBILITY_FAILED"
    )


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


@pytest.mark.parametrize(
    ("generation_path", "expected_text"),
    [
        ("all_attempts_rejected", "rejected all three attempts"),
        (
            "bounded_non_delta_rejection",
            "bounded initial and repair attempts",
        ),
    ],
)
def test_replay_wrapper_typed_rejections_exit_three_with_distinct_messages(
    tmp_path: Path,
    generation_path: str,
    expected_text: str,
) -> None:
    completed = _run_wrapper_fixture(
        tmp_path,
        {
            "status": "PASS",
            "outcome": "typed_writer_rejection",
            "recovery": {"generation_path": generation_path},
            "report_availability": {"status": "UNAVAILABLE"},
        },
    )

    assert completed.returncode == 3
    rendered = " ".join((completed.stdout + completed.stderr).split())
    assert expected_text in rendered


def test_replay_wrapper_maps_verifier_failure_to_exit_two(tmp_path: Path) -> None:
    completed = _run_wrapper_fixture(
        tmp_path,
        {
            "status": "FAIL",
            "outcome": "unexpected_terminal_state",
            "recovery": {"generation_path": "invalid_attempt_sequence"},
            "report_availability": {"status": "UNAVAILABLE"},
        },
    )

    assert completed.returncode == 2
    assert "Replay invariants failed" in (completed.stdout + completed.stderr)


def test_replay_wrapper_maps_available_summary_to_exit_zero(tmp_path: Path) -> None:
    completed = _run_wrapper_fixture(
        tmp_path,
        {
            "status": "PASS",
            "outcome": "summarized",
            "recovery": {"generation_path": "initial_accepted"},
            "report_availability": {"status": "AVAILABLE"},
        },
    )

    assert completed.returncode == 0
    assert "Summary replay verified" in (completed.stdout + completed.stderr)


def test_python_verifier_cli_preserves_zero_two_one_exit_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    baseline_task = _task(status="failed", result=_source_result())
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(capture_task_state(baseline_task)),
        encoding="utf-8",
    )
    accepted_result = {
        **_source_result(),
        "summary": "Ban tin da duoc xac minh boi cac gate nguon.",
        "summary_state": "source_grounded_narrative",
        "summary_authority": {"world_facts_released": False},
        "summary_preview": {"world_facts_released": False},
        "summary_runtime": {
            "writer_status": "accepted",
            "llm_call_count": 1,
            "token_budgets": _budgets(1),
        },
    }
    accepted_task = _task(status="summarized", result=accepted_result)
    monkeypatch.setattr(replay_verifier, "_load_task", lambda _task_id: accepted_task)

    assert replay_verifier.main(
        ["verify", "--task-id", "task-1", "--baseline", str(baseline_path)]
    ) == 0

    changed_result = {**accepted_result, "transcription": "Noi dung da thay doi"}
    changed_task = _task(status="summarized", result=changed_result)
    monkeypatch.setattr(replay_verifier, "_load_task", lambda _task_id: changed_task)
    assert replay_verifier.main(
        ["verify", "--task-id", "task-1", "--baseline", str(baseline_path)]
    ) == 2

    def fail_load(_task_id: str):
        raise LookupError("task unavailable")

    monkeypatch.setattr(replay_verifier, "_load_task", fail_load)
    assert replay_verifier.main(
        ["verify", "--task-id", "task-1", "--baseline", str(baseline_path)]
    ) == 1


def test_s2_r0_evidence_artifact_matches_current_sources_and_replays() -> None:
    artifact_path = (
        ROOT / "docs" / "reviews" / "artifacts" / "s2-r0-summary-recovery.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert artifact["verdict"] == "PASS"
    assert artifact["product_status"] == "BLOCKED"
    assert set(artifact["commit_allowlist"]) == {
        "src/services/summarization/bulletin_writer.py",
        "scripts/assert_summary_replay.py",
        "scripts/replay_summary_task.ps1",
        "tests/test_investigative_bulletin_quality.py",
        "tests/test_assert_summary_replay.py",
        "docs/runbooks/celery-summary-replay.md",
        "docs/reviews/artifacts/s2-r0-summary-recovery.json",
    }
    for relative, expected_hash in artifact["source_sha256"].items():
        assert _sha256_file(ROOT / relative) == expected_hash
    for directory, replay in artifact["live_replays"].items():
        replay_root = ROOT / "output" / "summary-replay" / directory
        for filename, evidence in replay["files"].items():
            path = replay_root / filename
            assert path.stat().st_size == evidence["bytes"]
            assert _sha256_file(path) == evidence["sha256"]
    for filename in ("baseline.json", "verification.json"):
        for path in (ROOT / "output" / "summary-replay").glob(f"*/{filename}"):
            assert '"error"' not in path.read_text(encoding="utf-8")
