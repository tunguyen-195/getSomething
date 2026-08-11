"""Capture and verify read-only database invariants for a summary replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASELINE_SCHEMA_VERSION = "stt-summary-replay-v1"
VERIFICATION_SCHEMA_VERSION = "stt-summary-replay-v2"
GENERIC_FAILURE = "Summary generation failed."
EXPECTED_FAILURE_CODE = "INVESTIGATION_WRITER_REJECTED"
NON_DELTA_FAILURE_CODES = frozenset(
    {
        "INVESTIGATION_COVERAGE_FAILED",
        "INVESTIGATION_LENGTH_CONFLICT",
    }
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _normalized_error_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def _is_generic_failure(value: Any) -> bool:
    normalized = _normalized_error_text(value).casefold().rstrip(".")
    generic = GENERIC_FAILURE.casefold().rstrip(".")
    return bool(normalized) and normalized == generic


def _task_result(task: Any) -> dict[str, Any]:
    result = getattr(task, "result", None)
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = {}
    return result if isinstance(result, dict) else {}


def capture_task_state(task: Any) -> dict[str, Any]:
    result = _task_result(task)
    transcription = result.get("transcription")
    segments = result.get("segments")
    context = result.get("context_analysis")
    if not isinstance(transcription, str):
        transcription = ""
    if not isinstance(segments, list):
        segments = []
    error_text = _normalized_error_text(getattr(task, "error", None))

    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "task_id": str(getattr(task, "id", "")),
        "task_status": getattr(task, "status", None),
        "error_present": bool(error_text),
        "error_is_generic_failure": _is_generic_failure(error_text),
        "error_sha256": _sha256_text(error_text) if error_text else None,
        "transcription_sha256": _sha256_text(transcription),
        "transcription_length": len(transcription),
        "segments_sha256": _sha256_json(segments),
        "segment_count": len(segments),
        "context_analysis_is_object": isinstance(context, dict),
        "context_analysis_sha256": _sha256_json(context)
        if isinstance(context, dict)
        else None,
    }


def _add_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    *,
    scope: str,
    expected: Any,
    observed: Any,
) -> None:
    checks.append(
        {
            "name": name,
            "scope": scope,
            "status": "PASS" if passed else "FAIL",
            "expected": expected,
            "observed": observed,
        }
    )


def verify_task_state(
    baseline: dict[str, Any],
    task: Any,
) -> dict[str, Any]:
    current = capture_task_state(task)
    result = _task_result(task)
    runtime = result.get("summary_runtime")
    if not isinstance(runtime, dict):
        runtime = {}
    budgets = runtime.get("token_budgets")
    if not isinstance(budgets, list):
        budgets = []
    budget_kinds = [
        item.get("prompt_kind") if isinstance(item, dict) else None
        for item in budgets
    ]
    llm_call_count = runtime.get("llm_call_count")
    summary_error = result.get("summary_error")
    if not isinstance(summary_error, dict):
        summary_error = {}
    summary_authority = result.get("summary_authority")
    if not isinstance(summary_authority, dict):
        summary_authority = {}
    summary_preview = result.get("summary_preview")
    if not isinstance(summary_preview, dict):
        summary_preview = {}

    checks: list[dict[str, Any]] = []
    _add_check(
        checks,
        "task_id_unchanged",
        current["task_id"] == baseline.get("task_id"),
        scope="eligibility",
        expected=baseline.get("task_id"),
        observed=current["task_id"],
    )
    _add_check(
        checks,
        "transcription_hash_unchanged",
        current["transcription_sha256"]
        == baseline.get("transcription_sha256"),
        scope="eligibility",
        expected=baseline.get("transcription_sha256"),
        observed=current["transcription_sha256"],
    )
    _add_check(
        checks,
        "transcription_length_unchanged",
        current["transcription_length"]
        == baseline.get("transcription_length"),
        scope="eligibility",
        expected=baseline.get("transcription_length"),
        observed=current["transcription_length"],
    )
    _add_check(
        checks,
        "segments_hash_unchanged",
        current["segments_sha256"] == baseline.get("segments_sha256"),
        scope="eligibility",
        expected=baseline.get("segments_sha256"),
        observed=current["segments_sha256"],
    )
    _add_check(
        checks,
        "segment_count_unchanged",
        current["segment_count"] == baseline.get("segment_count"),
        scope="eligibility",
        expected=baseline.get("segment_count"),
        observed=current["segment_count"],
    )
    _add_check(
        checks,
        "context_analysis_is_object",
        current["context_analysis_is_object"],
        scope="eligibility",
        expected=True,
        observed=current["context_analysis_is_object"],
    )

    task_status = current["task_status"]
    summary = result.get("summary")
    summary_text = summary if isinstance(summary, str) else ""
    valid_call_count = (
        isinstance(llm_call_count, int)
        and not isinstance(llm_call_count, bool)
        and 1 <= llm_call_count <= 3
    )
    expected_budget_kinds = (
        ["initial", "repair", "delta_repair"][:llm_call_count]
        if valid_call_count
        else []
    )
    valid_budget_sequence = (
        valid_call_count and budget_kinds == expected_budget_kinds
    )
    generation_path = "invalid_attempt_sequence"
    outcome = "unexpected_terminal_state"

    if task_status == "summarized":
        outcome = "summarized"
        if valid_budget_sequence:
            generation_path = {
                1: "initial_accepted",
                2: "repair_accepted",
                3: "delta_repair_accepted",
            }[llm_call_count]
        for name, passed, expected, observed in (
            (
                "top_level_error_cleared",
                not current["error_present"],
                False,
                current["error_present"],
            ),
            (
                "summary_non_empty",
                bool(summary_text.strip()),
                "non-empty string",
                {"type": type(summary).__name__, "length": len(summary_text)},
            ),
            (
                "summary_error_absent",
                not summary_error,
                "absent",
                summary_error.get("code"),
            ),
            (
                "summary_state",
                result.get("summary_state") == "source_grounded_narrative",
                "source_grounded_narrative",
                result.get("summary_state"),
            ),
            (
                "writer_status",
                runtime.get("writer_status") == "accepted",
                "accepted",
                runtime.get("writer_status"),
            ),
            (
                "llm_call_count",
                valid_call_count,
                "integer from 1 through 3",
                llm_call_count,
            ),
            (
                "token_budget_sequence",
                valid_budget_sequence,
                expected_budget_kinds,
                budget_kinds,
            ),
            (
                "summary_authority_present",
                bool(summary_authority),
                "non-empty object",
                bool(summary_authority),
            ),
            (
                "summary_authority_not_released",
                summary_authority.get("world_facts_released") is False,
                False,
                summary_authority.get("world_facts_released"),
            ),
            (
                "summary_preview_present",
                bool(summary_preview),
                "non-empty object",
                bool(summary_preview),
            ),
            (
                "summary_preview_not_released",
                summary_preview.get("world_facts_released") is False,
                False,
                summary_preview.get("world_facts_released"),
            ),
        ):
            _add_check(
                checks,
                name,
                passed,
                scope="recovery",
                expected=expected,
                observed=observed,
            )
    elif task_status == "failed" and summary_error.get("code") in {
        EXPECTED_FAILURE_CODE,
        *NON_DELTA_FAILURE_CODES,
    }:
        outcome = "typed_writer_rejection"
        failure_code = summary_error.get("code")
        delta_exhausted = (
            failure_code == EXPECTED_FAILURE_CODE
            and llm_call_count == 3
            and valid_budget_sequence
        )
        non_delta_rejection = (
            failure_code in NON_DELTA_FAILURE_CODES
            and llm_call_count == 2
            and budget_kinds == ["initial", "repair"]
        )
        if delta_exhausted:
            generation_path = "all_attempts_rejected"
        elif non_delta_rejection:
            generation_path = "bounded_non_delta_rejection"
        for name, passed, expected, observed in (
            (
                "typed_failure_code",
                failure_code in {EXPECTED_FAILURE_CODE, *NON_DELTA_FAILURE_CODES},
                sorted({EXPECTED_FAILURE_CODE, *NON_DELTA_FAILURE_CODES}),
                failure_code,
            ),
            (
                "generic_failure_not_used",
                not current["error_is_generic_failure"],
                False,
                current["error_is_generic_failure"],
            ),
            (
                "summary_absent",
                not summary_text.strip(),
                "empty",
                len(summary_text),
            ),
            (
                "summary_state",
                result.get("summary_state") == "unavailable",
                "unavailable",
                result.get("summary_state"),
            ),
            (
                "writer_status",
                runtime.get("writer_status") == "rejected",
                "rejected",
                runtime.get("writer_status"),
            ),
            (
                "bounded_recovery_path",
                delta_exhausted or non_delta_rejection,
                (
                    "three-call delta exhaustion for writer rejection or exactly "
                    "two calls (initial, repair) for a typed non-delta rejection"
                ),
                {
                    "code": failure_code,
                    "llm_call_count": llm_call_count,
                    "token_budget_kinds": budget_kinds,
                },
            ),
        ):
            _add_check(
                checks,
                name,
                passed,
                scope="recovery",
                expected=expected,
                observed=observed,
            )
    else:
        _add_check(
            checks,
            "terminal_outcome",
            False,
            scope="recovery",
            expected="summarized or a typed bounded investigation rejection",
            observed={
                "status": task_status,
                "summary_error_code": summary_error.get("code"),
                "error_present": current["error_present"],
                "error_is_generic_failure": current["error_is_generic_failure"],
                "error_sha256": current["error_sha256"],
            },
        )

    eligibility_failed = [
        check["name"]
        for check in checks
        if check["scope"] == "eligibility" and check["status"] == "FAIL"
    ]
    recovery_failed = [
        check["name"]
        for check in checks
        if check["scope"] == "recovery" and check["status"] == "FAIL"
    ]
    failed_checks = [*eligibility_failed, *recovery_failed]
    operational_status = "PASS" if not failed_checks else "FAIL"
    report_available = bool(summary_text.strip()) and task_status == "summarized"
    summary_sha256 = _sha256_text(summary_text) if report_available else None
    validator = {
        "name": "validate_investigative_report_body",
        "required_phase": "S2-R5",
        "available": False,
        "version": None,
    }
    if eligibility_failed:
        report_quality = {
            "status": "BLOCKED",
            "reason_code": "REPLAY_ELIGIBILITY_FAILED",
            "subject_sha256": summary_sha256,
            "validator": validator,
            "checks": [],
            "failed_checks": eligibility_failed,
        }
    elif recovery_failed:
        report_quality = {
            "status": "BLOCKED",
            "reason_code": "RECOVERY_INVARIANTS_FAILED",
            "subject_sha256": summary_sha256,
            "validator": validator,
            "checks": [],
            "failed_checks": recovery_failed,
        }
    elif report_available:
        report_quality = {
            "status": "NOT_EVALUATED",
            "reason_code": "R5_SHARED_VALIDATOR_UNAVAILABLE",
            "subject_sha256": summary_sha256,
            "validator": validator,
            "checks": [],
            "failed_checks": [],
        }
    else:
        report_quality = {
            "status": "BLOCKED",
            "reason_code": "NO_REPORT_BODY",
            "subject_sha256": None,
            "validator": validator,
            "checks": [],
            "failed_checks": [],
        }
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "artifact_type": "summary_replay_verification",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "task_id": current["task_id"],
        "status": operational_status,
        "status_scope": "availability_and_recovery_only",
        "operational_status": operational_status,
        "product_status": "BLOCKED",
        "quality_included_in_status": False,
        "quality_included_in_exit_code": False,
        "outcome": outcome,
        "eligibility": {
            "status": "PASS" if not eligibility_failed else "FAIL",
            "failed_checks": eligibility_failed,
        },
        "recovery": {
            "status": "PASS" if not recovery_failed else "FAIL",
            "generation_path": generation_path,
            "failed_checks": recovery_failed,
        },
        "report_availability": {
            "status": "AVAILABLE" if report_available else "UNAVAILABLE",
            "reason_code": (
                "SUMMARY_BODY_PRESENT" if report_available else "NO_REPORT_BODY"
            ),
        },
        "report_quality": report_quality,
        "checks": checks,
        "failed_checks": failed_checks,
        "current": {
            **current,
            "summary_error_code": summary_error.get("code"),
            "summary_state": result.get("summary_state"),
            "writer_status": runtime.get("writer_status"),
            "llm_call_count": llm_call_count,
            "token_budget_kinds": budget_kinds,
            "summary_sha256": summary_sha256,
            "summary_length": len(summary_text),
            "summary_word_count": len(summary_text.split()),
        },
    }


def _load_task(task_id: str) -> Any:
    from sqlalchemy.orm import load_only

    from src.database.config.database import SessionLocal
    from src.database.models.models import Task

    db = SessionLocal()
    try:
        task = (
            db.query(Task)
            .options(load_only(Task.id, Task.status, Task.result, Task.error))
            .filter(Task.id == task_id)
            .first()
        )
        if task is None:
            raise LookupError(f"Task {task_id} not found")
        return SimpleNamespace(
            id=task.id,
            status=task.status,
            result=task.result,
            error=task.error,
        )
    finally:
        db.rollback()
        db.close()


def _write_report(report: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture", help="Capture a safe baseline.")
    capture.add_argument("--task-id", required=True)
    capture.add_argument("--output", type=Path)

    verify = subparsers.add_parser("verify", help="Verify after replay.")
    verify.add_argument("--task-id", required=True)
    verify.add_argument("--baseline", type=Path, required=True)
    verify.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        task = _load_task(args.task_id)
        if args.command == "capture":
            report = capture_task_state(task)
        else:
            baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
            if baseline.get("schema_version") != BASELINE_SCHEMA_VERSION:
                raise ValueError("Unsupported baseline schema")
            report = verify_task_state(baseline, task)
        _write_report(report, args.output)
        return 0 if report.get("status", "PASS") == "PASS" else 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema_version": (
                        BASELINE_SCHEMA_VERSION
                        if getattr(args, "command", None) == "capture"
                        else VERIFICATION_SCHEMA_VERSION
                    ),
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
