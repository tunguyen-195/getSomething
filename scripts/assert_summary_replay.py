"""Capture and verify read-only database invariants for a summary replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.summarization.adaptive_length import (  # noqa: E402
    adaptive_compression_ratio,
)
from src.services.investigation.chunk_planner import estimate_tokens  # noqa: E402
from src.core.config import settings  # noqa: E402
from src.services.summarization.summary_service_v2 import (
    SUMMARY_COMPLETION_FIXED_HEADROOM_TOKENS,
    SUMMARY_COMPLETION_TOKENS_PER_WORD,
    SUMMARY_MAX_COMPLETION_TOKENS,
    SUMMARY_MIN_COMPLETION_TOKENS,
    SUMMARY_CONTEXT_SAFETY_RESERVE_TOKENS,
    SIMPLE_INVESTIGATION_PROMPT_VERSION,
    build_simple_investigation_prompt,
    context_window_tokens_for_provider,
)  # noqa: E402

BASELINE_SCHEMA_VERSION = "stt-summary-replay-v2"
VERIFICATION_SCHEMA_VERSION = "stt-summary-replay-v3"
GENERIC_FAILURE = "Summary generation failed."


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
    context_attestation = result.get("context_analysis_attestation")
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
        "context_analysis_attestation_is_object": isinstance(
            context_attestation,
            dict,
        ),
        "context_analysis_attestation_sha256": _sha256_json(
            context_attestation
        )
        if isinstance(context_attestation, dict)
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
    length_contract = runtime.get("length_contract")
    if not isinstance(length_contract, dict):
        length_contract = {}
    context_budget = runtime.get("context_budget")
    if not isinstance(context_budget, dict):
        context_budget = {}
    llm_call_count = runtime.get("llm_call_count")
    raw_summary_error = result.get("summary_error")
    summary_error = raw_summary_error
    if not isinstance(raw_summary_error, dict):
        summary_error = {}

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
        "context_analysis_shape_unchanged",
        current["context_analysis_is_object"]
        == baseline.get("context_analysis_is_object"),
        scope="eligibility",
        expected=baseline.get("context_analysis_is_object"),
        observed=current["context_analysis_is_object"],
    )
    _add_check(
        checks,
        "context_analysis_hash_unchanged",
        current["context_analysis_sha256"]
        == baseline.get("context_analysis_sha256"),
        scope="eligibility",
        expected=baseline.get("context_analysis_sha256"),
        observed=current["context_analysis_sha256"],
    )
    _add_check(
        checks,
        "context_analysis_attestation_shape_unchanged",
        current["context_analysis_attestation_is_object"]
        == baseline.get("context_analysis_attestation_is_object"),
        scope="eligibility",
        expected=baseline.get("context_analysis_attestation_is_object"),
        observed=current["context_analysis_attestation_is_object"],
    )
    _add_check(
        checks,
        "context_analysis_attestation_hash_unchanged",
        current["context_analysis_attestation_sha256"]
        == baseline.get("context_analysis_attestation_sha256"),
        scope="eligibility",
        expected=baseline.get("context_analysis_attestation_sha256"),
        observed=current["context_analysis_attestation_sha256"],
    )

    task_status = current["task_status"]
    summary = result.get("summary")
    summary_text = summary if isinstance(summary, str) else ""
    summary_words = len(summary_text.split())
    transcription = result.get("transcription")
    transcription_text = transcription if isinstance(transcription, str) else ""
    transcript_segments = result.get("segments")
    if not isinstance(transcript_segments, list):
        transcript_segments = []
    source_words = len(transcription_text.split())
    expected_ratio = adaptive_compression_ratio(source_words)
    expected_preferred_words = max(20, math.ceil(source_words * expected_ratio))
    expected_source_tokens = estimate_tokens(transcription_text)
    replayed_prompt = build_simple_investigation_prompt(
        transcription_text,
        transcript_segments=transcript_segments,
    )["prompt"]
    expected_prompt_tokens = estimate_tokens(replayed_prompt)
    expected_provider = str(settings.LOCAL_LLM_PROVIDER).strip().casefold()
    expected_context_window_tokens = context_window_tokens_for_provider(
        expected_provider
    )
    expected_desired_completion_tokens = min(
        SUMMARY_MAX_COMPLETION_TOKENS,
        max(
            SUMMARY_MIN_COMPLETION_TOKENS,
            expected_preferred_words * SUMMARY_COMPLETION_TOKENS_PER_WORD
            + SUMMARY_COMPLETION_FIXED_HEADROOM_TOKENS,
        ),
    )
    context_window_tokens = context_budget.get("context_window_tokens")
    prompt_token_estimate = context_budget.get("prompt_token_estimate")
    safety_reserve_tokens = context_budget.get("safety_reserve_tokens")
    expected_available_completion_tokens = (
        max(0, context_window_tokens - safety_reserve_tokens - prompt_token_estimate)
        if all(
            type(value) is int
            for value in (
                context_window_tokens,
                safety_reserve_tokens,
                prompt_token_estimate,
            )
        )
        else None
    )
    expected_completion_token_budget = (
        min(
            expected_desired_completion_tokens,
            expected_available_completion_tokens,
        )
        if type(expected_available_completion_tokens) is int
        else None
    )
    generation_path = "invalid_summary_generation"
    outcome = "unexpected_terminal_state"

    if task_status == "summarized":
        outcome = "summarized"
        if (
            runtime.get("summary_generation") == "single_prompt_llm"
            and llm_call_count == 1
        ):
            generation_path = "single_prompt_llm"
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
                raw_summary_error is None
                or (isinstance(raw_summary_error, dict) and not raw_summary_error),
                "absent",
                {
                    "type": type(raw_summary_error).__name__,
                    "code": summary_error.get("code"),
                },
            ),
            (
                "summary_state",
                result.get("summary_state") == "generated",
                "generated",
                result.get("summary_state"),
            ),
            (
                "prompt_version",
                runtime.get("prompt_version")
                == SIMPLE_INVESTIGATION_PROMPT_VERSION,
                SIMPLE_INVESTIGATION_PROMPT_VERSION,
                runtime.get("prompt_version"),
            ),
            (
                "summary_generation",
                runtime.get("summary_generation") == "single_prompt_llm",
                "single_prompt_llm",
                runtime.get("summary_generation"),
            ),
            (
                "summary_prompt_replayable",
                runtime.get("provider") == expected_provider
                and runtime.get("user_prompt_applied") is False,
                {
                    "provider": expected_provider,
                    "user_prompt_applied": False,
                },
                {
                    "provider": runtime.get("provider"),
                    "user_prompt_applied": runtime.get("user_prompt_applied"),
                },
            ),
            (
                "llm_call_count",
                type(llm_call_count) is int and llm_call_count == 1,
                1,
                llm_call_count,
            ),
            (
                "adaptive_length_schema",
                length_contract.get("schema_version")
                == "summary-length-contract-v2",
                "summary-length-contract-v2",
                length_contract.get("schema_version"),
            ),
            (
                "adaptive_length_mode",
                length_contract.get("mode") == "auto",
                "auto",
                length_contract.get("mode"),
            ),
            (
                "adaptive_source_word_count",
                type(length_contract.get("source_word_count")) is int
                and length_contract.get("source_word_count") == source_words,
                source_words,
                length_contract.get("source_word_count"),
            ),
            (
                "adaptive_preferred_words",
                type(length_contract.get("preferred_words")) is int
                and length_contract.get("preferred_words")
                == expected_preferred_words,
                expected_preferred_words,
                length_contract.get("preferred_words"),
            ),
            (
                "adaptive_maximum_not_enforced",
                length_contract.get("maximum_enforced") is False,
                False,
                length_contract.get("maximum_enforced"),
            ),
            (
                "length_actual_matches_summary",
                type(length_contract.get("actual")) is int
                and length_contract.get("actual") == summary_words,
                summary_words,
                length_contract.get("actual"),
            ),
            (
                "soft_ratio_recorded",
                isinstance(length_contract.get("proportional_ratio"), (int, float))
                and not isinstance(length_contract.get("proportional_ratio"), bool)
                and float(length_contract["proportional_ratio"])
                == expected_ratio,
                expected_ratio,
                length_contract.get("proportional_ratio"),
            ),
            (
                "compression_ratio_matches_summary",
                isinstance(length_contract.get("compression_ratio"), (int, float))
                and not isinstance(length_contract.get("compression_ratio"), bool)
                and float(length_contract["compression_ratio"])
                == (
                    round(summary_words / source_words, 6)
                    if source_words
                    else None
                ),
                round(summary_words / source_words, 6) if source_words else None,
                length_contract.get("compression_ratio"),
            ),
            (
                "adaptive_length_satisfied",
                length_contract.get("satisfied") is True,
                True,
                length_contract.get("satisfied"),
            ),
            (
                "adaptive_length_status",
                length_contract.get("status") == "accepted",
                "accepted",
                length_contract.get("status"),
            ),
            (
                "context_budget_schema",
                context_budget.get("schema_version")
                == "summary-context-budget-v1",
                "summary-context-budget-v1",
                context_budget.get("schema_version"),
            ),
            (
                "single_full_source_block",
                context_budget.get("transcript_embedding_mode")
                == "single_full_source_block"
                and type(context_budget.get("source_occurrence_count")) is int
                and context_budget.get("source_occurrence_count") == 1
                and context_budget.get("full_transcript_included") is True,
                {
                    "transcript_embedding_mode": "single_full_source_block",
                    "source_occurrence_count": 1,
                    "full_transcript_included": True,
                },
                {
                    "transcript_embedding_mode": context_budget.get(
                        "transcript_embedding_mode"
                    ),
                    "source_occurrence_count": context_budget.get(
                        "source_occurrence_count"
                    ),
                    "full_transcript_included": context_budget.get(
                        "full_transcript_included"
                    ),
                },
            ),
            (
                "context_budget_fits",
                context_budget.get("fits_context_window") is True,
                True,
                context_budget.get("fits_context_window"),
            ),
            (
                "context_budget_arithmetic",
                all(
                    type(context_budget.get(key)) is int
                    for key in (
                        "context_window_tokens",
                        "prompt_token_estimate",
                        "source_token_estimate",
                        "desired_completion_tokens",
                        "available_completion_tokens",
                        "completion_token_budget",
                        "safety_reserve_tokens",
                    )
                )
                and context_budget.get("token_counter")
                == "utf8-bytes-over-2.8-ceiling"
                and context_budget.get("context_window_tokens")
                == expected_context_window_tokens
                and context_budget.get("prompt_token_estimate")
                == expected_prompt_tokens
                and context_budget.get("source_token_estimate", 0) > 0
                and context_budget.get("source_token_estimate")
                == expected_source_tokens
                and context_budget.get("desired_completion_tokens")
                == expected_desired_completion_tokens
                and context_budget.get("available_completion_tokens")
                == expected_available_completion_tokens
                and context_budget.get("available_completion_tokens", -1)
                >= SUMMARY_MIN_COMPLETION_TOKENS
                and context_budget.get("completion_token_budget")
                == expected_completion_token_budget
                and context_budget.get("completion_token_budget", 0) > 0
                and context_budget.get("safety_reserve_tokens")
                == SUMMARY_CONTEXT_SAFETY_RESERVE_TOKENS
                and type(context_budget.get("completion_budget_clamped")) is bool
                and context_budget.get("completion_budget_clamped")
                == (
                    expected_completion_token_budget
                    < expected_desired_completion_tokens
                ),
                "exact positive one-call context-budget derivation",
                {
                    key: context_budget.get(key)
                    for key in (
                        "token_counter",
                        "context_window_tokens",
                        "prompt_token_estimate",
                        "source_token_estimate",
                        "desired_completion_tokens",
                        "available_completion_tokens",
                        "completion_token_budget",
                        "safety_reserve_tokens",
                        "completion_budget_clamped",
                    )
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
            expected="summarized with a non-empty one-call LLM result",
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
    product_status = (
        "PASS" if report_quality.get("status") == "PASS" else "BLOCKED"
    )
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "artifact_type": "summary_replay_verification",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "task_id": current["task_id"],
        "status": operational_status,
        "status_scope": "one_call_summary_availability_and_persistence",
        "operational_status": operational_status,
        "product_status": product_status,
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
            "prompt_version": runtime.get("prompt_version"),
            "summary_generation": runtime.get("summary_generation"),
            "llm_call_count": llm_call_count,
            "length_mode": length_contract.get("mode"),
            "proportional_ratio": length_contract.get("proportional_ratio"),
            "maximum_enforced": length_contract.get("maximum_enforced"),
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
