"""Run the working-tree RTK gate for the investigative summary prototype."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ROOT = Path(r"E:\research\STT")
SOURCE_PATHS = (
    "src/services/investigation/claim_semantics.py",
    "src/services/summarization/bulletin_writer.py",
    "src/services/summarization/context_service.py",
    "src/services/summarization/investigation_scenarios.py",
    "src/services/summarization/models/context_analysis.py",
    "src/services/summarization/models/investigation_knowledge.py",
    "src/services/summarization/public_projection.py",
    "src/services/summarization/summary_service_v2.py",
    "src/services/summarization/investigation_preview.py",
    "src/api/endpoints/audio.py",
    "src/api/endpoints/audio_v2.py",
    "src/services/audio_service.py",
    "src/services/cherry_summarizer.py",
    "src/worker/tasks/summarize_task.py",
    "src/worker/runtime_contract.py",
    "src/worker/summary_reconciliation.py",
    "src/worker/tasks/runtime_contract_task.py",
    "frontend/src/components/InvestigationSummaryCard.tsx",
    "frontend/src/components/SummarizeDialog.tsx",
    "frontend/src/components/TaskListItem.tsx",
    "frontend/src/utils/investigationAnalysis.ts",
    "frontend/src/utils/summaryDisplay.ts",
    "frontend/tests/investigationAnalysis.test.ts",
    "tests/test_context_analysis.py",
    "tests/test_investigation_knowledge.py",
    "tests/test_investigation_summary_runtime.py",
    "tests/test_investigative_bulletin_quality.py",
    "tests/test_public_summary_projection.py",
    "tests/test_summary_fail_closed.py",
    "tests/test_summary_request_contract.py",
    "tests/test_worker_runtime_contract.py",
    "tests/test_summary_reconciliation.py",
    "docs/research/2026-08-10-investigative-summary-product-contract.md",
    "docs/research/2026-08-11-investigative-summary-product-technology-scout.md",
    "docs/plans/2026-08-10-investigative-summary-redesign-plan.md",
    "docs/plans/2026-08-11-investigative-summary-product-implementation-plan.md",
    "scripts/audit_investigative_summary_contract.py",
    "scripts/probe_celery_worker_contract.py",
    "scripts/reconcile_stale_summary_tasks.py",
)
BACKEND_TESTS = (
    "tests/test_context_analysis.py",
    "tests/test_investigation_knowledge.py",
    "tests/test_investigation_summary_runtime.py",
    "tests/test_investigative_bulletin_quality.py",
    "tests/test_public_summary_projection.py",
    "tests/test_summary_fail_closed.py",
    "tests/test_summary_request_contract.py",
    "tests/test_worker_runtime_contract.py",
    "tests/test_summary_reconciliation.py",
)
DESELECTED_BACKEND_TESTS = (
    "tests/test_investigation_knowledge.py::test_committed_schema_artifact_matches_current_models",
)
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "huggingface_token": re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
}


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(name: str, command: list[str], cwd: Path) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    output = "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )
    return {
        "name": name,
        "command": command,
        "cwd": str(cwd),
        "exit_code": completed.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "output_tail": output[-6000:],
    }


def git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip()


def static_checks() -> dict[str, bool]:
    claim_semantics = (
        ROOT / "src/services/investigation/claim_semantics.py"
    ).read_text(encoding="utf-8")
    writer = (ROOT / "src/services/summarization/bulletin_writer.py").read_text(
        encoding="utf-8"
    )
    scenarios = (
        ROOT / "src/services/summarization/investigation_scenarios.py"
    ).read_text(encoding="utf-8")
    knowledge = (
        ROOT / "src/services/summarization/models/investigation_knowledge.py"
    ).read_text(encoding="utf-8")
    runtime_tests = (ROOT / "tests/test_investigation_summary_runtime.py").read_text(
        encoding="utf-8"
    )
    quality_tests = (ROOT / "tests/test_investigative_bulletin_quality.py").read_text(
        encoding="utf-8"
    )
    public_projection = (
        ROOT / "src/services/summarization/public_projection.py"
    ).read_text(encoding="utf-8")
    fail_closed_tests = (ROOT / "tests/test_summary_fail_closed.py").read_text(
        encoding="utf-8"
    )
    request_tests = (ROOT / "tests/test_summary_request_contract.py").read_text(
        encoding="utf-8"
    )
    summary_display = (
        ROOT / "frontend/src/utils/summaryDisplay.ts"
    ).read_text(encoding="utf-8")
    task_item = (
        ROOT / "frontend/src/components/TaskListItem.tsx"
    ).read_text(encoding="utf-8")
    dialog = (
        ROOT / "frontend/src/components/SummarizeDialog.tsx"
    ).read_text(encoding="utf-8")
    return {
        "canonical_workspace": ROOT.resolve() == EXPECTED_ROOT.resolve(),
        "officer_prompt_versioned": (
            "investigative-bulletin-prompt-v4-leadership-report" in writer
            and "cán bộ báo cáo lãnh đạo" in writer
        ),
        "whole_source_exact_once_rule": (
            "must_cover=true" in writer
            and "repeats a required source unit" in writer
            and "omits required source units" in writer
        ),
        "reader_metadata_forbidden": all(
            marker in writer
            for marker in (
                "offset âm thanh",
                "speaker label",
                "model/prompt metadata",
                "không tiêu đề",
            )
        ),
        "delimiter_data_escaped": all(
            marker in writer for marker in ('replace("<", "\\\\u003c")', 'replace(">", "\\\\u003e")')
        ),
        "seven_scenario_profiles_present": all(
            profile in scenarios
            for profile in (
                "general",
                "financial_asset",
                "coordination_planning",
                "threat_coercion",
                "goods_transport",
                "public_administration",
                "incident_conflict",
            )
        ),
        "epistemic_markers_checked": all(
            marker in knowledge
            for marker in (
                "changes source negation",
                "changes source uncertainty",
                "changes source attribution",
                "changes source conditionality",
                "changes planned action modality",
            )
        ),
        "shared_semantic_actions_cover_common_verbs": all(
            f'"{action}"' in claim_semantics
            for action in ("bán", "bảo", "đánh", "giữ", "hẹn", "ký", "lấy", "mượn")
        ),
        "semantic_negative_tests_present": (
            "test_writer_rejects_semantic_role_or_epistemic_reattachment"
            in quality_tests
        ),
        "coverage_and_injection_tests_present": all(
            test_name in quality_tests
            for test_name in (
                "test_writer_requires_each_source_unit_exactly_once",
                "test_writer_fails_length_conflict_without_silent_truncation",
                "test_transcript_prompt_injection_cannot_become_writer_conclusion",
                "test_writer_prompt_escapes_ledger_delimiter_injection",
            )
        ),
        "cache_and_writer_integration_tests_present": all(
            test_name in runtime_tests
            for test_name in (
                "test_source_grounded_writer_returns_reader_facing_report_body",
                "test_sparse_trusted_cached_context_is_augmented_from_full_transcript",
                "test_invalid_cached_context_is_refreshed_from_current_transcript",
            )
        ),
        "persistence_false_returns_fail_closed": all(
            test_name in fail_closed_tests
            for test_name in (
                "test_v2_sync_false_persistence_never_returns_success",
                "test_v2_async_persists_before_enqueue",
                "test_legacy_sync_false_persistence_never_returns_success",
                "test_celery_final_false_persistence_raises_safe_error",
                "test_preview_only_result_is_never_a_success_contract",
            )
        ),
        "ui_never_promotes_preview_to_summary": (
            "file?.summary_preview?.text" not in summary_display
            and "summaryPreview?.text" not in task_item
        ),
        "interactive_summary_defaults_to_investigation": (
            "DEFAULT_INTERACTIVE_SUMMARY_TYPE" in dialog
            and "DEFAULT_INVESTIGATION_SUMMARY_MAX_LENGTH" in dialog
        ),
        "reader_context_projection_redacts_internal_trails": all(
            marker in public_projection
            for marker in (
                "public-investigation-analysis-v1",
                "Remove evidence, offsets, speakers, hashes, model metadata, and internal refs",
            )
        ),
        "tiny_investigation_length_rejected_before_model": (
            "test_tiny_investigation_maximum_is_rejected_before_model_work"
            in request_tests
        ),
        "scenario_detection_handles_asr_and_negation": all(
            test_name in quality_tests
            for test_name in (
                "test_auto_scenario_handles_unaccented_asr_and_negated_absence",
                "test_auto_scenario_uses_general_for_equal_specialist_scores",
            )
        ),
    }


def hygiene_checks() -> dict[str, Any]:
    trailing_whitespace: list[str] = []
    missing_final_newline: list[str] = []
    secret_hits: list[str] = []
    for relative in SOURCE_PATHS:
        path = ROOT / relative
        data = path.read_text(encoding="utf-8")
        if data and not data.endswith("\n"):
            missing_final_newline.append(relative)
        for line_number, line in enumerate(data.splitlines(), start=1):
            if line.rstrip(" \t") != line:
                trailing_whitespace.append(f"{relative}:{line_number}")
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(line):
                    secret_hits.append(f"{label}:{relative}:{line_number}")
    return {
        "trailing_whitespace": trailing_whitespace,
        "missing_final_newline": missing_final_newline,
        "secret_hits": secret_hits,
        "passed": not trailing_whitespace and not missing_final_newline and not secret_hits,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="docs/reviews/artifacts/2026-08-11-investigative-summary-contract.json",
    )
    args = parser.parse_args()

    missing = [relative for relative in SOURCE_PATHS if not (ROOT / relative).is_file()]
    if missing:
        raise SystemExit(f"Missing audit paths: {', '.join(missing)}")

    commands = [
        run_command(
            "targeted_backend",
            [
                str(ROOT / "venv/Scripts/python.exe"),
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                *(
                    item
                    for test_name in DESELECTED_BACKEND_TESTS
                    for item in ("--deselect", test_name)
                ),
                *BACKEND_TESTS,
            ],
            ROOT,
        ),
        run_command("frontend_tests", ["npm.cmd", "test"], ROOT / "frontend"),
        run_command("frontend_build", ["npm.cmd", "run", "build"], ROOT / "frontend"),
        run_command("git_diff_check", ["git", "diff", "--check"], ROOT),
    ]
    static = static_checks()
    hygiene = hygiene_checks()
    passed = (
        all(result["exit_code"] == 0 for result in commands)
        and all(static.values())
        and hygiene["passed"]
    )

    artifact = {
        "schema_version": "rtk-evidence-v1",
        "artifact_id": "2026-08-11-investigative-summary-contract",
        "observed_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "verdict": "PASS" if passed else "FAIL",
        "verdict_scope": (
            "working-tree investigative summary prototype: officer prompt, semantic and "
            "coverage gates, runtime integration, frontend regression, and build"
        ),
        "exit_code": 0 if passed else 1,
        "environment": {
            "workspace": str(ROOT),
            "source_scope": "working_tree",
            "git_head": git_value("rev-parse", "HEAD"),
            "branch": git_value("branch", "--show-current"),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "network_used": False,
            "model_used": False,
            "worktree_dirty": bool(git_value("status", "--porcelain")),
        },
        "harness_path": "scripts/audit_investigative_summary_contract.py",
        "harness_sha256": sha256_path(Path(__file__)),
        "source_sha256": {
            relative: sha256_path(ROOT / relative) for relative in SOURCE_PATHS
        },
        "commands": commands,
        "deselected_tests": list(DESELECTED_BACKEND_TESTS),
        "checks": static,
        "hygiene": hygiene,
        "release_boundary": {
            "world_facts_released": False,
            "current_input": "GroundedContextAnalysisPayload",
            "target_input": "released InvestigationRun via NarrativeLedgerViewV1",
            "production_release_claimed": False,
        },
        "residual_uncertainty": [
            "The current writer is a grounded-context prototype, not final InvestigationRun release authority.",
            "The committed S1 git-index schema artifact is stale and is explicitly outside this working-tree S2 gate.",
            "Multi-label scenario planning, digital_technical, and identity_document overlays are planned but not implemented.",
            "The frozen Vietnamese quality corpus, baseline, human review, and performance promotion gate remain T0/T8 work.",
            "Diarization runtime/model correctness is outside this summary artifact and remains a separate blocker.",
            "Live model output quality is not claimed by this no-model regression artifact.",
        ],
    }

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": artifact["verdict"], "output": str(output)}))
    return artifact["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
