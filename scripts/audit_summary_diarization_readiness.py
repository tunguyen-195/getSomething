"""Conservative readiness audit for investigative summaries and diarization."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True

CANONICAL_ROOT = Path(r"E:\research\STT")
AUDIT_OUTPUT_ROOTS = (
    Path("output/audits"),
    Path("docs/reviews/artifacts"),
)
BASE_SOURCE_INPUT_PATHS = (
    "scripts/audit_summary_diarization_readiness.py",
    "scripts/audit_pyannote_migration_config.py",
    "scripts/capture_diarization_primary_sources.py",
    "docs/research/2026-08-09-investigative-bulletin-diarization-evidence-refresh.md",
    "docs/plans/2026-08-09-investigative-bulletin-diarization-plan.md",
    "docs/reviews/2026-08-09-pyannote-migration-config-audit.md",
    "docs/reviews/artifacts/2026-08-09-diarization-primary-source-verification.json",
    "docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json",
    "tests/test_summary_diarization_audit_harness.py",
)
PACKAGE_EVIDENCE_REQUIREMENTS = {
    "p0a": {
        "artifact": "docs/reviews/artifacts/p0-test-isolation.json",
        "checks": {
            "non_test_database_rejected",
            "concurrent_runs_isolated",
            "application_database_unchanged",
            "sequential_targeted_suite_passed",
        },
    },
    "s1": {
        "artifact": "docs/reviews/artifacts/s1-summary-schema.json",
        "checks": {
            "strict_nested_schema",
            "typed_summary_sentences",
            "legacy_adapter_separated",
            "ungrounded_items_rejected",
            "no_model_or_network_call",
        },
    },
    "s2": {
        "artifact": "docs/reviews/artifacts/s2-narrative-release.json",
        "checks": {
            "sentence_semantic_support_100_percent",
            "released_claim_narrative_coverage_100_percent",
            "critical_claim_placement_100_percent",
            "severe_hallucination_zero",
            "hypothesis_leakage_zero",
        },
    },
    "s3": {
        "artifact": "docs/reviews/artifacts/s3-summary-request-contract.json",
        "checks": {
            "invalid_type_rejected_all_entrypoints",
            "invalid_type_no_gpu_or_model_call",
            "short_complete_summary_passed",
            "maximum_length_enforced",
            "direct_api_celery_multi_parity",
        },
    },
    "s4": {
        "artifact": "docs/reviews/artifacts/s4-summary-state-transitions.json",
        "checks": {
            "false_success_never_persisted",
            "legacy_v2_direct_celery_parity",
            "failure_transition_idempotent",
            "sensitive_transcript_not_logged",
        },
    },
    "g1": {
        "artifact": "docs/reviews/artifacts/gpu-handoff-live.json",
        "checks": {
            "same_owner_cross_process_rejected",
            "sleeping_requires_exact_boolean_true",
            "direct_celery_parity",
            "cleanup_failure_retains_quarantine",
            "recovery_requires_live_sleep",
            "live_sleep_wake_vram_passed",
        },
    },
    "f1a": {
        "artifact": "docs/reviews/artifacts/runtime-profile-contract-tests.json",
        "checks": {
            "alias_path_hash_server_binding",
            "blocked_on_mismatch",
            "legacy_result_unverified",
            "frontend_uses_only_available_aliases",
        },
    },
    "q1": {
        "artifact": "docs/reviews/artifacts/q1-source-coverage.json",
        "checks": {
            "authorized_source_coverage_100_percent",
            "missing_chunk_zero",
            "critical_candidate_recall_not_regressed",
            "lost_middle_negative_passed",
            "multi_file_skip_negative_passed",
        },
    },
    "c1": {
        "artifact": "docs/reviews/artifacts/c1-intelligence-run.json",
        "checks": {
            "migration_rehearsal_passed",
            "idempotency_passed",
            "cross_case_authorization_passed",
            "source_and_diarization_revision_replay_passed",
            "legacy_reads_marked_unverified",
        },
        "dynamic_bound_path_field": "alembic_version_path",
    },
    "d1": {
        "artifact": "docs/reviews/artifacts/pyannote-community-1-network-denied-loader.json",
        "checks": {
            "authorized_acquisition_verified",
            "full_tree_hashes_verified",
            "runtime_stack_compatible",
            "clean_install_reproducible",
            "asr_regression_and_gpu_handoff_passed",
            "network_denied",
            "model_loaded",
            "output_api_compatible",
            "legacy_api_negative_passed",
            "missing_or_tampered_rejected_before_audio",
            "one_speaker_state_distinct",
        },
    },
    "d2": {
        "artifact": "docs/reviews/artifacts/diarization-contract-tests.json",
        "checks": {
            "method_allowlist_all_entrypoints",
            "verified_one_speaker_distinct_from_failure",
            "overlap_tie_zero_duration_unmapped",
            "actual_vs_estimated_word_timestamps",
            "unique_temp_conversion",
            "per_file_speaker_namespace",
        },
    },
    "x1": {
        "artifact": "docs/reviews/artifacts/x1-speaker-claim-release.json",
        "checks": {
            "wrong_speaker_sensitive_value_zero",
            "speaker_dependent_precision_threshold_met",
            "withholding_accuracy_threshold_met",
            "diarization_revision_replay_rejected",
            "human_mapping_append_only",
        },
    },
    "f1b": {
        "artifact": "docs/reviews/artifacts/f1b-file-aware-evidence.json",
        "checks": {
            "legacy_unverified_provenance",
            "per_file_speaker_namespace",
            "no_empty_placeholder_views",
            "mobile_keyboard_playback_passed",
            "evidence_authorization_enforced",
            "sensitive_content_absent_from_logs",
        },
    },
    "e1a": {
        "artifact": "docs/reviews/artifacts/e1a-baseline-lock.json",
        "checks": {
            "corpus_hash_locked",
            "scorer_hash_locked",
            "leakage_check_passed",
            "tampered_input_rejected",
            "baseline_all_slices_complete",
            "confidence_intervals_recorded",
            "privacy_methodology_audit_passed",
        },
    },
    "e1": {
        "artifact": "docs/reviews/artifacts/e1-promotion-audit.json",
        "checks": {
            "zero_tolerance_safety_gates_passed",
            "summary_quality_thresholds_passed",
            "diarization_absolute_floors_passed",
            "diarization_non_regression_passed",
            "human_preference_protocol_passed",
            "performance_pareto_gate_passed",
        },
    },
}
PYANNOTE_COMMUNITY_1_REVISION = "3533c8cf8e369892e6b79ff1bf80f7b0286a54ee"
PYANNOTE_REQUIRED_FILES = (
    "config.yaml",
    "embedding/pytorch_model.bin",
    "plda/plda.npz",
    "plda/xvec_transform.npz",
    "segmentation/pytorch_model.bin",
)


def _normalized_absolute(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _canonical_repo(repo_root: Path) -> Path:
    """Reject a noncanonical workspace before importing or reading from it."""

    if _normalized_absolute(repo_root) != _normalized_absolute(CANONICAL_ROOT):
        raise ValueError(
            "Refusing noncanonical workspace. Expected exactly "
            f"{CANONICAL_ROOT}, received {repo_root}."
        )
    return CANONICAL_ROOT


def _validated_output(repo_root: Path, output: Path | None) -> Path | None:
    if output is None:
        return None
    candidate = output if output.is_absolute() else repo_root / output
    candidate = candidate.resolve(strict=False)
    allowed = [
        (repo_root / relative_root).resolve(strict=False)
        for relative_root in AUDIT_OUTPUT_ROOTS
    ]
    within_allowed_root = False
    for root in allowed:
        try:
            within_allowed_root = (
                os.path.commonpath((str(candidate), str(root))) == str(root)
            )
        except ValueError:
            within_allowed_root = False
        if within_allowed_root:
            break
    if not within_allowed_root:
        raise ValueError(
            "Audit output must stay under output/audits or docs/reviews/artifacts"
        )
    return candidate


def _validated_generated_at(value: str | None) -> tuple[str, str]:
    if value is None:
        return datetime.now(timezone.utc).isoformat(), "system_clock"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--generated-at must be a valid RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("--generated-at must include a timezone offset")
    return parsed.isoformat(), "provided_rfc3339"


def _run(repo_root: Path, *command: str, check: bool = True) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        command,
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )


def _stdout(repo_root: Path, *command: str) -> str:
    return _run(repo_root, *command).stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_relative_source_path(value: str) -> str | None:
    normalized = value.strip().replace("\\", "/")
    candidate = Path(normalized)
    if (
        not normalized
        or candidate.is_absolute()
        or ".." in candidate.parts
        or normalized.startswith("/")
    ):
        return None
    return candidate.as_posix()


def _plan_package_allowlists(
    repo_root: Path,
) -> tuple[dict[str, tuple[str, ...]], list[str]]:
    """Read exact task paths from the plan table so the validator cannot drift."""

    plan_path = (
        repo_root
        / "docs/plans/2026-08-09-investigative-bulletin-diarization-plan.md"
    )
    lines = plan_path.read_text(encoding="utf-8").splitlines()
    allowlists: dict[str, tuple[str, ...]] = {}
    errors: list[str] = []
    in_table = False
    for line in lines:
        if line.startswith("| Package | Exact initial production/config paths |"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            if allowlists:
                break
            continue
        columns = [column.strip() for column in line.split("|")[1:-1]]
        if len(columns) != 3:
            errors.append("malformed_package_allowlist_row")
            continue
        package = columns[0].casefold()
        if package in allowlists:
            errors.append(f"duplicate_package_allowlist:{package}")
            continue
        raw_paths = re.findall(r"`([^`]+)`", " ".join(columns[1:]))
        normalized_paths: list[str] = []
        for raw_path in raw_paths:
            normalized = _normalized_relative_source_path(raw_path)
            if normalized is None:
                errors.append(f"invalid_package_path:{package}:{raw_path}")
            elif normalized in normalized_paths:
                errors.append(f"duplicate_package_path:{package}:{normalized}")
            else:
                normalized_paths.append(normalized)
        allowlists[package] = tuple(normalized_paths)

    expected = set(PACKAGE_EVIDENCE_REQUIREMENTS)
    observed = set(allowlists)
    for package in sorted(expected - observed):
        errors.append(f"missing_package_allowlist:{package}")
    for package in sorted(observed - expected):
        errors.append(f"unexpected_package_allowlist:{package}")
    for package, requirement in PACKAGE_EVIDENCE_REQUIREMENTS.items():
        artifact = str(requirement["artifact"])
        if artifact not in allowlists.get(package, ()):
            errors.append(f"package_artifact_not_allowlisted:{package}:{artifact}")
    c1_row = next(
        (line for line in lines if line.startswith("| C1 |")),
        "",
    )
    if "exact new Alembic version path recorded by the C1 preflight" not in c1_row:
        errors.append("c1_dynamic_alembic_allowlist_rule_missing")
    return allowlists, errors


def _dynamic_c1_alembic_path(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    normalized = _normalized_relative_source_path(
        str(payload.get("alembic_version_path", ""))
    )
    if (
        normalized is None
        or not normalized.startswith("src/database/migrations/versions/")
        or not normalized.endswith(".py")
    ):
        return None
    return normalized


def _package_bound_paths(repo_root: Path, package: str) -> set[str]:
    allowlists, _ = _plan_package_allowlists(repo_root)
    artifact = str(PACKAGE_EVIDENCE_REQUIREMENTS[package]["artifact"])
    return set(allowlists.get(package, ())) - {artifact}


def _source_hashes(repo_root: Path) -> dict[str, str | None]:
    allowlists, _ = _plan_package_allowlists(repo_root)
    relative_paths = set(BASE_SOURCE_INPUT_PATHS)
    for paths in allowlists.values():
        relative_paths.update(paths)
    c1_artifact = _load_manifest(
        repo_root / str(PACKAGE_EVIDENCE_REQUIREMENTS["c1"]["artifact"])
    )
    c1_alembic_path = _dynamic_c1_alembic_path(c1_artifact)
    if c1_alembic_path is not None:
        relative_paths.add(c1_alembic_path)
    return {
        relative: _sha256(repo_root / relative)
        if (repo_root / relative).is_file()
        else None
        for relative in sorted(relative_paths)
    }


def _git_state(repo_root: Path) -> dict[str, Any]:
    upstream = _stdout(
        repo_root,
        "git",
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{u}",
    )
    behind_ahead = _stdout(
        repo_root,
        "git",
        "rev-list",
        "--left-right",
        "--count",
        f"{upstream}...HEAD",
    ).split()
    tracked = _stdout(
        repo_root,
        "git",
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    ).splitlines()
    untracked = sorted(
        _stdout(
            repo_root,
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
        ).splitlines()
    )
    audit_outputs = sorted(
        path
        for path in untracked
        if (
            path.replace("\\", "/").startswith("output/audits/")
            or path.replace("\\", "/").startswith("docs/reviews/artifacts/")
        )
        and "summary-diarization-readiness" in Path(path).name
    )
    return {
        "branch": _stdout(repo_root, "git", "branch", "--show-current"),
        "head": _stdout(repo_root, "git", "rev-parse", "HEAD"),
        "upstream": upstream,
        "behind": int(behind_ahead[0]),
        "ahead": int(behind_ahead[1]),
        "tracked_changes": len(tracked),
        "untracked_files_total": len(untracked),
        "untracked_files_excluding_generated_audit": len(untracked) - len(audit_outputs),
        "generated_audit_outputs_present": audit_outputs,
    }


def _walk_object_schemas(schema: Any, path: str = "$") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            rows.append(
                {
                    "path": path,
                    "additional_properties": schema.get("additionalProperties"),
                }
            )
        for key, value in schema.items():
            rows.extend(_walk_object_schemas(value, f"{path}.{key}"))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            rows.extend(_walk_object_schemas(value, f"{path}[{index}]"))
    return rows


def _schema_property_definition(
    schema: dict[str, Any],
    property_name: str,
) -> dict[str, Any]:
    property_schema = schema.get("properties", {}).get(property_name, {})
    items = property_schema.get("items", {})
    reference = items.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/$defs/"):
        return items
    return schema.get("$defs", {}).get(reference.rsplit("/", 1)[-1], {})


def _strict_array_contract(
    property_schema: dict[str, Any],
    *,
    min_items: int = 1,
) -> bool:
    return (
        property_schema.get("type") == "array"
        and int(property_schema.get("minItems", 0)) >= min_items
    )


def _function_swallows_exception(path: Path, function_name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            for handler in (
                child for child in ast.walk(node) if isinstance(child, ast.ExceptHandler)
            ):
                if not any(isinstance(child, ast.Raise) for child in ast.walk(handler)):
                    returns_false = any(
                        isinstance(child, ast.Return)
                        and isinstance(child.value, ast.Constant)
                        and child.value.value is False
                        for child in ast.walk(handler)
                    )
                    if not returns_false:
                        return True
    return False


def _summary_contract(repo_root: Path) -> dict[str, Any]:
    from src.services.investigation.contracts import NarrativeSentence
    from src.services.summarization.models.context_analysis import ContextAnalysisPayload

    schema = ContextAnalysisPayload.model_json_schema()
    objects = _walk_object_schemas(schema)
    non_strict = [
        row["path"]
        for row in objects
        if row["additional_properties"] is not False
    ]
    draft_list_schema = schema.get("properties", {}).get("summary_sentences", {})
    draft_definition = _schema_property_definition(schema, "summary_sentences")
    draft_fields = set(draft_definition.get("properties", {}))
    draft_required = set(draft_definition.get("required", []))
    required_draft_fields = {
        "draft_id",
        "text",
        "sentence_role",
        "evidence_quotes",
    }
    narrative_schema = NarrativeSentence.model_json_schema()
    narrative_fields = set(narrative_schema.get("properties", {}))
    narrative_required = set(narrative_schema.get("required", []))
    required_release_fields = {
        "sentence_id",
        "text",
        "claim_refs",
        "evidence_refs",
        "content_sha256",
        "semantic_attestation_ref",
    }
    context_source = (
        repo_root / "src/services/summarization/models/context_analysis.py"
    ).read_text(encoding="utf-8")
    service_source = (
        repo_root / "src/services/summarization/summary_service_v2.py"
    ).read_text(encoding="utf-8")
    run_source = (
        repo_root / "src/services/investigation/run_contracts.py"
    ).read_text(encoding="utf-8")
    untyped_paths = []
    for relative in (
        "src/services/summarization/summary_service_v2.py",
        "src/api/endpoints/audio.py",
        "src/worker/tasks/summarize_task.py",
    ):
        if "summary_type: str" in (repo_root / relative).read_text(encoding="utf-8"):
            untyped_paths.append(relative)
    return {
        "object_schema_count": len(objects),
        "all_objects_forbid_additional_properties": not non_strict,
        "non_strict_object_paths": non_strict,
        "summary_compatibility_schema": schema.get("properties", {}).get("summary", {}),
        "summary_sentence_fields": sorted(draft_fields),
        "summary_sentence_contract_present": (
            required_draft_fields.issubset(draft_fields)
            and required_draft_fields.issubset(draft_required)
            and _strict_array_contract(draft_list_schema)
            and draft_definition.get("additionalProperties") is False
            and _strict_array_contract(
                draft_definition.get("properties", {}).get("evidence_quotes", {})
            )
        ),
        "canonical_legacy_key_point_coercion_present": (
            "upgrade_legacy_key_points" in context_source
        ),
        "raw_context_summary_release_present": 'context.get("summary")' in service_source,
        "hard_minimum_length_present": "min_length <= actual <= max_length" in service_source,
        "shared_summary_contract_module_present": (
            repo_root / "src/services/summarization/contracts.py"
        ).is_file(),
        "untyped_summary_type_paths": sorted(untyped_paths),
        "release_sentence_fields": sorted(narrative_fields),
        "release_sentence_contract_present": (
            required_release_fields.issubset(narrative_fields)
            and required_release_fields.issubset(narrative_required)
            and narrative_schema.get("additionalProperties") is False
            and _strict_array_contract(
                narrative_schema.get("properties", {}).get("claim_refs", {})
            )
            and _strict_array_contract(
                narrative_schema.get("properties", {}).get("evidence_refs", {})
            )
        ),
        "semantic_attestation_module_present": (
            repo_root / "src/services/investigation/narrative_attestation.py"
        ).is_file(),
        "released_claim_narrative_coverage_gate_present": (
            "narrated_claim_refs" in run_source
        ),
    }


def _load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _evidence_artifact_pass(
    repo_root: Path,
    path: Path,
    required_checks: set[str],
    bound_paths: set[str],
    *,
    dynamic_bound_path_field: str | None = None,
) -> bool:
    payload = _load_manifest(path)
    if (
        not payload
        or payload.get("schema_version") != "rtk-evidence-v1"
        or payload.get("verdict") != "PASS"
        or payload.get("exit_code") != 0
        or not isinstance(payload.get("command"), list)
        or not payload["command"]
        or not isinstance(payload.get("environment"), dict)
    ):
        return False
    try:
        observed_at = datetime.fromisoformat(
            str(payload.get("observed_at", "")).replace("Z", "+00:00")
        )
    except ValueError:
        return False
    if observed_at.tzinfo is None:
        return False
    harness_relative = payload.get("harness_path")
    harness_sha256 = payload.get("harness_sha256")
    if not isinstance(harness_relative, str) or not isinstance(harness_sha256, str):
        return False
    harness_path = (repo_root / harness_relative).resolve(strict=False)
    if (
        not harness_path.is_file()
        or os.path.commonpath((str(harness_path), str(repo_root.resolve())))
        != str(repo_root.resolve())
        or _sha256(harness_path) != harness_sha256
    ):
        return False
    source_hashes = payload.get("source_sha256")
    if not isinstance(source_hashes, dict):
        return False
    for relative in bound_paths:
        source_path = repo_root / relative
        if not source_path.is_file() or source_hashes.get(relative) != _sha256(source_path):
            return False
    if dynamic_bound_path_field is not None:
        if dynamic_bound_path_field != "alembic_version_path":
            return False
        dynamic_relative = _dynamic_c1_alembic_path(payload)
        if dynamic_relative is None:
            return False
        dynamic_path = repo_root / dynamic_relative
        if (
            not dynamic_path.is_file()
            or source_hashes.get(dynamic_relative) != _sha256(dynamic_path)
        ):
            return False
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        return False
    return all(checks.get(name) is True for name in required_checks)


def _primary_source_state(repo_root: Path) -> dict[str, Any]:
    from scripts.capture_diarization_primary_sources import (
        MIGRATION_SOURCE_IDS,
        source_binding,
        validate_capture_payload,
    )

    path = (
        repo_root
        / "docs/reviews/artifacts/2026-08-09-diarization-primary-source-verification.json"
    )
    payload = _load_manifest(path)
    validation_errors: list[str] = []
    valid = False
    if payload:
        valid, validation_errors = validate_capture_payload(repo_root, payload)
    rows = {
        str(item.get("id")): item
        for item in (payload or {}).get("sources", [])
        if isinstance(item, dict) and item.get("id")
    }
    migration_source_bindings = (
        {source_id: source_binding(rows[source_id]) for source_id in MIGRATION_SOURCE_IDS}
        if valid and all(source_id in rows for source_id in MIGRATION_SOURCE_IDS)
        else {}
    )
    return {
        "path": str(path),
        "sha256": _sha256(path) if path.is_file() else None,
        "valid": valid,
        "capture_id": (payload or {}).get("capture_id"),
        "observed_at": (payload or {}).get("observed_at"),
        "validation_errors": validation_errors,
        "migration_source_bindings": migration_source_bindings,
        "hf_metadata_content_sha256": rows.get("community_1_metadata", {}).get(
            "content_sha256"
        ),
        "source_count": len(rows),
    }


def _pyannote_migration_audit_state(repo_root: Path) -> dict[str, Any]:
    path = (
        repo_root
        / "docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json"
    )
    payload = _load_manifest(path)
    primary_capture = _primary_source_state(repo_root)
    observed_at_valid = False
    if payload:
        try:
            observed_at = datetime.fromisoformat(
                str(payload.get("observed_at", "")).replace("Z", "+00:00")
            )
            observed_at_valid = observed_at.tzinfo is not None
        except ValueError:
            observed_at_valid = False
    source_hashes = payload.get("source_sha256") if payload else None
    source_hashes_valid = isinstance(source_hashes, dict) and bool(source_hashes)
    if source_hashes_valid:
        source_hashes_valid = all(
            isinstance(relative, str)
            and isinstance(digest, str)
            and (repo_root / relative).is_file()
            and _sha256(repo_root / relative) == digest
            for relative, digest in source_hashes.items()
        )
    sources = (
        ((payload or {}).get("official_sources") or {}).get("sources", {})
        if payload
        else {}
    )
    hf_fields = (sources.get("community_1_metadata") or {}).get(
        "verified_fields", {}
    )
    pypi_fields = (sources.get("pyannote_audio_4_0_0_pypi") or {}).get(
        "verified_fields", {}
    )
    release_fields = (sources.get("pyannote_audio_4_0_0_release") or {}).get(
        "verified_fields", {}
    )
    pypi_requirements = set(pypi_fields.get("runtime_requirements") or [])
    expected_sources = primary_capture.get("migration_source_bindings") or {}
    capture_reference_valid = bool(
        primary_capture.get("valid")
        and ((payload or {}).get("official_sources") or {}).get("capture_path")
        == "docs/reviews/artifacts/2026-08-09-diarization-primary-source-verification.json"
        and ((payload or {}).get("official_sources") or {}).get("capture_sha256")
        == primary_capture.get("sha256")
        and ((payload or {}).get("official_sources") or {}).get("capture_id")
        == primary_capture.get("capture_id")
        and ((payload or {}).get("official_sources") or {}).get(
            "capture_observed_at"
        )
        == primary_capture.get("observed_at")
        and ((payload or {}).get("official_sources") or {}).get("capture_valid")
        is True
        and ((payload or {}).get("official_sources") or {}).get("capture_errors")
        == []
    )
    official_sources_valid = capture_reference_valid and set(sources) == {
        "community_1_metadata",
        "pyannote_audio_4_0_0_pypi",
        "pyannote_audio_4_0_0_release",
    } and sources == expected_sources and bool(
        hf_fields.get("model_id")
        == "pyannote/speaker-diarization-community-1"
        and hf_fields.get("revision") == PYANNOTE_COMMUNITY_1_REVISION
        and hf_fields.get("gated") == "auto"
        and str(hf_fields.get("license", "")).casefold() == "cc-by-4.0"
        and hf_fields.get("required_files_present") is True
        and pypi_fields.get("version") == "4.0.0"
        and pypi_fields.get("requires_python") == ">=3.10"
        and {
            "huggingface-hub>=0.28.1",
            "torch>=2.8.0",
            "torchaudio>=2.8.0",
            "torchcodec>=0.6.0",
        }.issubset(pypi_requirements)
        and release_fields.get("tag") == "4.0.0"
        and release_fields.get("published_at") == "2025-09-29T12:04:16Z"
        and release_fields.get("offline_local_load_documented") is True
        and release_fields.get("token_keyword_breaking_change") is True
        and release_fields.get("torchcodec_audio_io") is True
        and release_fields.get("community_output_object_documented") is True
    )
    recomputed_local_state_valid = False
    if payload and observed_at_valid:
        try:
            from scripts.audit_pyannote_migration_config import (
                build_report as build_pyannote_migration_report,
            )

            recomputed = build_pyannote_migration_report(
                repo_root,
                generated_at=str(payload["observed_at"]),
                no_network=True,
            )
            recomputed_local_state_valid = all(
                payload.get(key) == recomputed.get(key)
                for key in (
                    "migration_verdict",
                    "verdict",
                    "exit_code",
                    "harness_path",
                    "harness_sha256",
                    "source_sha256",
                    "migration_evidence",
                    "local_artifacts",
                    "effective_config",
                    "runtime_compatibility",
                    "official_sources",
                    "checks",
                    "blockers",
                )
            )
        except (ImportError, OSError, ValueError, json.JSONDecodeError):
            recomputed_local_state_valid = False
    valid = bool(
        payload
        and payload.get("schema_version") == "rtk-evidence-v1"
        and payload.get("artifact_type") == "pyannote-migration-config-audit"
        and payload.get("canonical_workspace") is True
        and payload.get("repo_root") == str(repo_root)
        and payload.get("scope")
        == "read_only_no_model_download_no_model_activation"
        and payload.get("migration_verdict") == "PASS_NO_ADDITIONAL_LOSS"
        and payload.get("verdict") in {"PASS", "BLOCKED"}
        and payload.get("exit_code") in {0, 2}
        and observed_at_valid
        and source_hashes_valid
        and official_sources_valid
        and recomputed_local_state_valid
        and payload.get("harness_path")
        == "scripts/audit_pyannote_migration_config.py"
        and payload.get("harness_sha256")
        == _sha256(repo_root / "scripts/audit_pyannote_migration_config.py")
    )
    return {
        "path": str(path),
        "valid": valid,
        "migration_verdict": (payload or {}).get("migration_verdict"),
        "product_verdict": (payload or {}).get("verdict"),
        "blockers": (payload or {}).get("blockers", []),
        "source_hashes_valid": source_hashes_valid,
        "capture_reference_valid": capture_reference_valid,
        "official_sources_valid": official_sources_valid,
        "recomputed_local_state_valid": recomputed_local_state_valid,
    }


def _model_state(
    repo_root: Path,
    primary_sources: dict[str, Any],
) -> dict[str, Any]:
    from src.core.config import settings
    from src.services.model_runtime import resolve_huggingface_snapshot

    pyannote_root = repo_root / "models/pyannote"
    files = sorted(path for path in pyannote_root.rglob("*") if path.is_file())
    community = resolve_huggingface_snapshot(
        pyannote_root,
        "pyannote/speaker-diarization-community-1",
        required_files=PYANNOTE_REQUIRED_FILES,
    )
    version_31 = resolve_huggingface_snapshot(
        pyannote_root,
        "pyannote/speaker-diarization-3.1",
    )
    community_missing = list(PYANNOTE_REQUIRED_FILES)
    community_external_paths: list[str] = []
    if community:
        community_missing = [
            relative
            for relative in PYANNOTE_REQUIRED_FILES
            if not (community / relative).is_file()
        ]
        for relative in PYANNOTE_REQUIRED_FILES:
            candidate = community / relative
            if candidate.exists() and os.path.commonpath(
                (str(candidate.resolve()), str(repo_root.resolve()))
            ) != str(repo_root.resolve()):
                community_external_paths.append(relative)
    manifest_path = (
        repo_root
        / "models/manifests/pyannote-speaker-diarization-community-1.json"
    )
    manifest = _load_manifest(manifest_path)
    acquisition_path = (
        repo_root / "docs/reviews/artifacts/pyannote-community-1-acquisition.json"
    )
    acquisition = _load_manifest(acquisition_path)
    community_relative = (
        community.relative_to(repo_root).as_posix() if community else None
    )
    manifest_rows = manifest.get("files", []) if manifest else []
    manifest_paths = [
        str(item.get("path"))
        for item in manifest_rows
        if isinstance(item, dict) and item.get("path")
    ]
    manifest_map = {
        str(item["path"]): item
        for item in manifest_rows
        if isinstance(item, dict) and item.get("path")
    }
    manifest_hashes_valid = bool(manifest_rows) and all(
        isinstance(item, dict)
        and isinstance(item.get("sha256"), str)
        and len(item["sha256"]) == 64
        and all(character in "0123456789abcdefABCDEF" for character in item["sha256"])
        and isinstance(item.get("size"), int)
        and not isinstance(item.get("size"), bool)
        and item["size"] > 0
        for item in manifest_rows
    )
    manifest_disk_match = bool(community) and all(
        relative in manifest_map
        and (community / relative).is_file()
        and (community / relative).stat().st_size == manifest_map[relative]["size"]
        and _sha256(community / relative).casefold()
        == str(manifest_map[relative]["sha256"]).casefold()
        for relative in PYANNOTE_REQUIRED_FILES
    )
    manifest_all_disk_match = bool(community) and bool(manifest_map) and all(
        not Path(relative).is_absolute()
        and ".." not in Path(relative).parts
        and isinstance(item.get("size"), int)
        and isinstance(item.get("sha256"), str)
        and (community / relative).is_file()
        and (community / relative).stat().st_size == item.get("size")
        and _sha256(community / relative).casefold()
        == str(item.get("sha256")).casefold()
        for relative, item in manifest_map.items()
    )
    manifest_valid = bool(
        manifest
        and manifest.get("model_id")
        == "pyannote/speaker-diarization-community-1"
        and manifest.get("revision") == PYANNOTE_COMMUNITY_1_REVISION
        and manifest.get("snapshot_revision") == PYANNOTE_COMMUNITY_1_REVISION
        and str(manifest.get("license", "")).casefold() == "cc-by-4.0"
        and manifest.get("source_url")
        == "https://huggingface.co/pyannote/speaker-diarization-community-1"
        and manifest.get("snapshot_path") == community_relative
        and len(manifest_paths) == len(set(manifest_paths))
        and set(PYANNOTE_REQUIRED_FILES).issubset(manifest_paths)
        and manifest_hashes_valid
        and manifest_disk_match
        and manifest_all_disk_match
        and acquisition_path.is_file()
        and manifest.get("acquisition_evidence_sha256") == _sha256(acquisition_path)
    )
    acquisition_valid = bool(
        acquisition
        and acquisition.get("model_id")
        == "pyannote/speaker-diarization-community-1"
        and acquisition.get("revision") == PYANNOTE_COMMUNITY_1_REVISION
        and acquisition.get("snapshot_path") == community_relative
        and acquisition.get("authorization_recorded") is True
        and acquisition.get("license_accepted") == "cc-by-4.0"
        and acquisition.get("source_metadata_content_sha256")
        == primary_sources.get("hf_metadata_content_sha256")
        and _evidence_artifact_pass(
            repo_root,
            acquisition_path,
            {
                "authorization_recorded",
                "license_accepted",
                "snapshot_revision_bound",
                "source_metadata_hash_bound",
                "all_manifest_files_hashed",
            },
            {
                "scripts/acquire_pyannote_community1.py",
                "docs/reviews/artifacts/2026-08-09-diarization-primary-source-verification.json",
            },
        )
    )
    loader_evidence_path = (
        repo_root
        / "docs/reviews/artifacts/pyannote-community-1-network-denied-loader.json"
    )
    loader_evidence = _load_manifest(loader_evidence_path)
    loader_harness_path = repo_root / "scripts/verify_pyannote_offline.py"
    loader_evidence_valid = bool(
        loader_evidence
        and loader_evidence.get("verdict") == "PASS"
        and loader_evidence.get("network_denied") is True
        and loader_evidence.get("revision") == PYANNOTE_COMMUNITY_1_REVISION
        and loader_evidence.get("external_cache_created") is False
        and loader_evidence.get("model_loaded") is True
        and manifest_path.is_file()
        and loader_evidence.get("model_manifest_sha256") == _sha256(manifest_path)
        and loader_harness_path.is_file()
        and loader_evidence.get("loader_harness_sha256")
        == _sha256(loader_harness_path)
        and loader_evidence.get("model_root") == str(community)
        and isinstance(loader_evidence.get("runtime_versions"), dict)
        and bool(loader_evidence.get("denial_mechanism"))
        and loader_evidence.get("external_cache_inventory_before")
        == loader_evidence.get("external_cache_inventory_after")
        and _evidence_artifact_pass(
            repo_root,
            loader_evidence_path,
            set(PACKAGE_EVIDENCE_REQUIREMENTS["d1"]["checks"]),
            _package_bound_paths(repo_root, "d1"),
        )
    )
    cherry_models = sorted((repo_root / "models").rglob("large-v2.pt"))
    return {
        "offline_strict": bool(settings.OFFLINE_STRICT),
        "transcription_engine": str(settings.TRANSCRIPTION_ENGINE),
        "local_llm_provider": str(getattr(settings, "LOCAL_LLM_PROVIDER", "")),
        "pyannote_file_count": len(files),
        "pyannote_bytes": sum(path.stat().st_size for path in files),
        "community_1_snapshot": str(community) if community else None,
        "speaker_diarization_31_snapshot": str(version_31) if version_31 else None,
        "community_1_required_files": list(PYANNOTE_REQUIRED_FILES),
        "community_1_missing_files": community_missing,
        "community_1_external_paths": community_external_paths,
        "community_1_complete": bool(community)
        and not community_missing
        and not community_external_paths,
        "community_1_manifest_path": str(manifest_path),
        "community_1_acquisition_path": str(acquisition_path),
        "community_1_acquisition_valid": acquisition_valid,
        "community_1_manifest_valid": manifest_valid and acquisition_valid,
        "network_denied_loader_evidence_path": str(loader_evidence_path),
        "network_denied_loader_evidence_valid": loader_evidence_valid,
        "cherry_large_v2_paths": [str(path) for path in cherry_models],
    }


def _diarization_contract(repo_root: Path) -> dict[str, Any]:
    service_source = (
        repo_root / "src/services/transcription/transcribe_service_v2.py"
    ).read_text(encoding="utf-8")
    manager_source = (
        repo_root / "src/services/transcription/models/pyannote_manager.py"
    ).read_text(encoding="utf-8")
    app_source = (repo_root / "frontend/src/App.tsx").read_text(encoding="utf-8")
    contract_path = repo_root / "src/services/transcription/contracts.py"
    evidence_path = repo_root / "docs/reviews/artifacts/diarization-contract-tests.json"
    return {
        "winner_take_all_alignment_present": "best_overlap > 0.3" in service_source,
        "multi_speaker_only_formatting_present": "num_speakers > 1" in service_source,
        "explicit_diarization_status_present": '"diarization_status"' in service_source,
        "degraded_reasons_present": '"degraded_reasons"' in service_source,
        "speaker_overlap_state_present": '"overlap_state"' in service_source,
        "word_timestamps_retained": '"words"' in service_source,
        "timestamp_provenance_present": '"timestamp_provenance"' in service_source,
        "sibling_wav_conversion_present": "with_suffix('.wav')" in manager_source,
        "shared_diarization_method_contract_present": contract_path.is_file()
        and "DiarizationMethod" in contract_path.read_text(encoding="utf-8"),
        "frontend_cross_file_segment_flattening_present": "flatMap(f => f.segments" in app_source,
        "contract_test_evidence_path": str(evidence_path),
        "contract_test_evidence_valid": _evidence_artifact_pass(
            repo_root,
            evidence_path,
            set(PACKAGE_EVIDENCE_REQUIREMENTS["d2"]["checks"]),
            _package_bound_paths(repo_root, "d2"),
        ),
    }


def _gpu_contract(repo_root: Path) -> dict[str, Any]:
    lease_path = repo_root / "src/services/model_runtime/gpu_lease.py"
    client_path = (
        repo_root
        / "src/services/summarization/models/openai_compatible_client.py"
    )
    startup_path = repo_root / "scripts/start_llama_server.ps1"
    lease_source = lease_path.read_text(encoding="utf-8")
    client_source = client_path.read_text(encoding="utf-8")
    startup_source = startup_path.read_text(encoding="utf-8")
    evidence_path = repo_root / "docs/reviews/artifacts/gpu-handoff-live.json"
    return {
        "process_instance_binding_present": "process_instance_id" in lease_source,
        "sleeping_requires_exact_true": (
            'get("is_sleeping") is True' in client_source
            or "get('is_sleeping') is True" in client_source
        ),
        "summary_cleanup_failure_swallowed": _function_swallows_exception(
            repo_root / "src/services/summarization/summary_service_v2.py",
            "_safe_unload_llm",
        ),
        "transcription_cleanup_failure_swallowed": _function_swallows_exception(
            repo_root / "src/services/transcription/transcribe_service_v2.py",
            "_safe_unload_transcription_models",
        ),
        "recovery_cli_present": (
            repo_root / "scripts/recover_gpu_quarantine.py"
        ).is_file(),
        "startup_uses_gpu_state_machine": all(
            marker.casefold() in startup_source.casefold()
            for marker in ("gpu", "lease", "quarantine")
        ),
        "live_test_evidence_path": str(evidence_path),
        "live_test_evidence_valid": _evidence_artifact_pass(
            repo_root,
            evidence_path,
            set(PACKAGE_EVIDENCE_REQUIREMENTS["g1"]["checks"]),
            _package_bound_paths(repo_root, "g1"),
        ),
    }


def _frontend_contract(repo_root: Path) -> dict[str, Any]:
    paths = (
        "frontend/src/App.tsx",
        "frontend/src/components/SummarizeDialog.tsx",
        "frontend/src/components/TaskList.tsx",
    )
    sources = {
        relative: (repo_root / relative).read_text(encoding="utf-8")
        for relative in paths
    }
    hardcoded = {
        relative: sorted(
            model
            for model in ("llama3.2:3b", "gemma2:9b")
            if model in source
        )
        for relative, source in sources.items()
    }
    hardcoded = {key: value for key, value in hardcoded.items() if value}
    system_path = repo_root / "src/api/endpoints/system.py"
    system_source = (
        system_path.read_text(encoding="utf-8") if system_path.is_file() else ""
    )
    evidence_path = repo_root / "docs/reviews/artifacts/runtime-profile-contract-tests.json"
    return {
        "runtime_profile_endpoint_present": "runtime-profile" in system_source,
        "hardcoded_legacy_models": hardcoded,
        "verified_alias_binding_contract_present": (
            "release_eligible" in system_source
            and "model_sha256" in system_source
            and "server_live" in system_source
        ),
        "contract_test_evidence_path": str(evidence_path),
        "contract_test_evidence_valid": _evidence_artifact_pass(
            repo_root,
            evidence_path,
            set(PACKAGE_EVIDENCE_REQUIREMENTS["f1a"]["checks"]),
            _package_bound_paths(repo_root, "f1a"),
        ),
    }


def _architecture_state(repo_root: Path) -> dict[str, Any]:
    return {
        "adaptive_chunk_planner_present": (
            repo_root / "src/services/investigation/chunk_planner.py"
        ).is_file(),
        "deterministic_exact_value_detector_present": (
            repo_root / "src/services/investigation/exact_detectors.py"
        ).is_file(),
        "append_only_intelligence_run_present": "class IntelligenceRun"
        in (repo_root / "src/database/models/models.py").read_text(encoding="utf-8"),
        "quality_corpus_manifest_present": (
            repo_root / "tests/eval/summary_diarization_corpus_manifest.json"
        ).is_file(),
        "quality_baseline_present": (
            repo_root / "docs/evals/runs/summary-diarization-baseline-v1.json"
        ).is_file(),
        "quality_scorer_protocol_present": (
            repo_root / "tests/eval/summary-diarization-scoring-v1.json"
        ).is_file(),
    }


def _package_evidence_state(repo_root: Path) -> dict[str, Any]:
    allowlists, definition_errors = _plan_package_allowlists(repo_root)
    state: dict[str, Any] = {}
    for package, requirement in PACKAGE_EVIDENCE_REQUIREMENTS.items():
        relative = str(requirement["artifact"])
        path = repo_root / relative
        bound_paths = set(allowlists.get(package, ())) - {relative}
        package_errors = [
            error
            for error in definition_errors
            if error.endswith(f":{package}")
            or f":{package}:" in error
            or error.startswith("missing_package_allowlist:") and error.endswith(package)
        ]
        state[package] = {
            "path": str(path),
            "bound_paths": sorted(bound_paths),
            "definition_errors": package_errors,
            "valid": not package_errors
            and _evidence_artifact_pass(
                repo_root,
                path,
                set(requirement["checks"]),
                bound_paths,
                dynamic_bound_path_field=requirement.get("dynamic_bound_path_field"),
            ),
        }
    state["contract"] = {
        "valid": not definition_errors,
        "errors": definition_errors,
        "plan_packages": sorted(allowlists),
        "validator_packages": sorted(PACKAGE_EVIDENCE_REQUIREMENTS),
        "exact_package_set_match": set(allowlists)
        == set(PACKAGE_EVIDENCE_REQUIREMENTS),
        "c1_dynamic_alembic_binding_required": True,
    }
    return state


def _http_status(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            return {"status": response.status, "body": body}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": None, "error": f"{type(exc).__name__}: {exc}"}


def _windows_process_state(repo_root: Path) -> dict[str, Any]:
    script = r"""
$ports = @(3000, 8000, 8088, 11434)
$rows = foreach ($port in $ports) {
  $listeners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
  foreach ($listener in $listeners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $current = $process
    $fromCanonical = $false
    $originDepth = $null
    for ($depth = 0; $depth -lt 8 -and $null -ne $current; $depth++) {
      if (($current.ExecutablePath -like 'E:\research\STT*') -or ($current.CommandLine -like '*E:\research\STT*')) {
        $fromCanonical = $true
        $originDepth = $depth
        break
      }
      if (-not $current.ParentProcessId) { break }
      $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($current.ParentProcessId)" -ErrorAction SilentlyContinue
    }
    [pscustomobject]@{
      port = $port
      pid = $listener.OwningProcess
      name = $process.Name
      executable = $process.ExecutablePath
      from_canonical_workspace = $fromCanonical
      canonical_origin_depth = $originDepth
    }
  }
}
$old = @(Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match 'D:\\Workspace\\SpeechToInfomation' -and
  $_.Name -match 'python|node|celery|uvicorn|llama'
}).Count
[pscustomobject]@{ listeners = @($rows); old_repo_process_count = $old } |
  ConvertTo-Json -Depth 5 -Compress
"""
    completed = _run(
        repo_root,
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        script,
        check=False,
    )
    if completed.returncode != 0:
        return {"error": completed.stderr.strip() or "PowerShell process probe failed"}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"invalid PowerShell JSON: {exc}"}
    return payload


def _redis_ping() -> bool:
    try:
        import redis

        from src.core.config import settings

        client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None,
            socket_timeout=3,
        )
        return client.ping() is True
    except Exception:
        return False


def _nvidia_compute_processes(repo_root: Path) -> dict[str, Any]:
    completed = _run(
        repo_root,
        "nvidia-smi",
        "--query-compute-apps=pid,process_name,used_gpu_memory",
        "--format=csv,noheader,nounits",
        check=False,
    )
    if completed.returncode != 0:
        return {"error": completed.stderr.strip() or "nvidia-smi failed"}
    rows: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",", 2)]
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[0])
            used_mib = int(parts[2])
        except ValueError:
            continue
        rows.append(
            {
                "pid": pid,
                "process_name": parts[1],
                "used_gpu_memory_mib": used_mib,
            }
        )
    return {"processes": rows}


def _runtime_state(repo_root: Path) -> dict[str, Any]:
    ports: dict[str, bool] = {}
    for port in (3000, 8000, 5432, 6379, 8088, 11434):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(0.5)
            ports[str(port)] = client.connect_ex(("127.0.0.1", port)) == 0
    celery = _run(
        repo_root,
        str(repo_root / "venv/Scripts/celery.exe"),
        "-A",
        "src.worker.worker",
        "inspect",
        "ping",
        "--timeout",
        "5",
        check=False,
    )
    return {
        "ports": ports,
        "frontend_http": _http_status("http://127.0.0.1:3000/"),
        "backend_health": _http_status("http://127.0.0.1:8000/api/v1/health"),
        "celery_ping": "pong" in celery.stdout.casefold(),
        "celery_logical_nodes": celery.stdout.count(": OK"),
        "redis_pong": _redis_ping(),
        "processes": _windows_process_state(repo_root),
        "gpu_compute_processes": _nvidia_compute_processes(repo_root),
    }


def _database_state() -> dict[str, Any]:
    from sqlalchemy import create_engine, text

    from src.core.config import settings

    engine = create_engine(str(settings.DATABASE_URL))
    statements = {
        "summary_contract": """
            SELECT
              count(*) FILTER (WHERE COALESCE(result->>'summary', '') <> '') AS summaries,
              count(*) FILTER (WHERE result::jsonb ? 'context_analysis') AS context_key,
              count(*) FILTER (
                WHERE (result->'context_analysis')::jsonb ? 'investigation_knowledge'
              ) AS grounded_knowledge_key,
              count(*) FILTER (WHERE result::jsonb ? 'summary_runtime') AS summary_runtime_key
            FROM tasks WHERE result IS NOT NULL
        """,
        "diarization_contract": """
            SELECT
              count(*) FILTER (WHERE result::jsonb ? 'has_diarization') AS contract_rows,
              count(*) FILTER (WHERE result->>'has_diarization' = 'true') AS diarization_true,
              count(*) FILTER (WHERE result->>'num_speakers' = '1') AS one_speaker,
              count(*) FILTER (WHERE result->>'num_speakers' = '2') AS two_speakers,
              count(*) FILTER (
                WHERE COALESCE(result->>'fallback_reason', '') <> ''
              ) AS fallback_reason_rows
            FROM tasks WHERE result IS NOT NULL
        """,
        "latest_engine_provenance": """
            SELECT updated_at, result->>'engine_used' AS engine_used,
              result->>'fallback_reason' AS fallback_reason,
              result->>'has_diarization' AS has_diarization,
              result->>'num_speakers' AS num_speakers,
              result->>'diarization_time' AS diarization_time
            FROM tasks
            WHERE result IS NOT NULL AND result::jsonb ? 'engine_used'
            ORDER BY updated_at DESC NULLS LAST LIMIT 1
        """,
        "recent_100_diarization": """
            WITH recent AS (
              SELECT result::jsonb AS result FROM tasks WHERE result IS NOT NULL
              ORDER BY updated_at DESC NULLS LAST LIMIT 100
            )
            SELECT count(*) AS rows,
              count(*) FILTER (WHERE result ? 'has_diarization') AS contract_rows,
              count(*) FILTER (WHERE result->>'has_diarization' = 'true') AS diarization_true,
              count(*) FILTER (WHERE result->>'num_speakers' = '1') AS one_speaker,
              count(*) FILTER (
                WHERE COALESCE(result->>'fallback_reason', '') <> ''
              ) AS fallback_reason_rows
            FROM recent
        """,
    }
    try:
        with engine.connect() as connection:
            state = {"select_1": connection.execute(text("SELECT 1")).scalar_one()}
            for name, statement in statements.items():
                row = connection.execute(text(statement)).mappings().first()
                state[name] = dict(row) if row else None
            state["database_name"] = engine.url.database
            return state
    finally:
        engine.dispose()


def _blockers(
    primary_sources: dict[str, Any],
    pyannote_migration_audit: dict[str, Any],
    package_evidence: dict[str, Any],
    summary: dict[str, Any],
    models: dict[str, Any],
    diarization: dict[str, Any],
    gpu: dict[str, Any],
    frontend: dict[str, Any],
    architecture: dict[str, Any],
    runtime: dict[str, Any] | None,
    database: dict[str, Any] | None,
) -> list[str]:
    checks = {
        "primary_source_verification_artifact_invalid": not primary_sources["valid"],
        "pyannote_migration_config_audit_invalid": not pyannote_migration_audit[
            "valid"
        ],
        "package_evidence_contract_invalid": not package_evidence["contract"]["valid"],
        "nested_schema_not_strict": not summary["all_objects_forbid_additional_properties"],
        "typed_summary_sentence_contract_missing": not summary["summary_sentence_contract_present"],
        "canonical_legacy_key_point_coercion_present": summary["canonical_legacy_key_point_coercion_present"],
        "live_summary_releases_raw_context_summary": summary["raw_context_summary_release_present"],
        "minimum_length_is_hard_enforced": summary["hard_minimum_length_present"],
        "shared_summary_type_length_contract_missing": not summary["shared_summary_contract_module_present"],
        "summary_type_untyped_outside_v2_api": bool(summary["untyped_summary_type_paths"]),
        "release_sentence_attestation_contract_missing": not summary["release_sentence_contract_present"],
        "semantic_attestation_authority_missing": not summary["semantic_attestation_module_present"],
        "released_claim_narrative_coverage_gate_missing": not summary["released_claim_narrative_coverage_gate_present"],
        "cherry_large_v2_missing": not models["cherry_large_v2_paths"],
        "pyannote_community_1_incomplete": not models["community_1_complete"],
        "pyannote_manifest_invalid_or_missing": not models["community_1_manifest_valid"],
        "pyannote_network_denied_loader_evidence_missing_or_invalid": not models["network_denied_loader_evidence_valid"],
        "winner_take_all_speaker_alignment": diarization["winner_take_all_alignment_present"],
        "single_speaker_success_collapsed_with_failure": diarization["multi_speaker_only_formatting_present"],
        "diarization_status_missing": not diarization["explicit_diarization_status_present"],
        "diarization_degraded_reasons_missing": not diarization["degraded_reasons_present"],
        "speaker_overlap_uncertainty_missing": not diarization["speaker_overlap_state_present"],
        "word_timestamps_not_retained": not diarization["word_timestamps_retained"],
        "timestamp_provenance_missing": not diarization["timestamp_provenance_present"],
        "unsafe_sibling_wav_conversion": diarization["sibling_wav_conversion_present"],
        "shared_diarization_method_contract_missing": not diarization["shared_diarization_method_contract_present"],
        "frontend_cross_file_speaker_merge_risk": diarization["frontend_cross_file_segment_flattening_present"],
        "diarization_contract_test_evidence_missing_or_invalid": not diarization["contract_test_evidence_valid"],
        "gpu_quarantine_process_instance_binding_missing": not gpu["process_instance_binding_present"],
        "llama_sleep_verifier_accepts_truthy_non_boolean": not gpu["sleeping_requires_exact_true"],
        "summary_cleanup_failure_swallowed": gpu["summary_cleanup_failure_swallowed"],
        "transcription_cleanup_failure_swallowed": gpu["transcription_cleanup_failure_swallowed"],
        "gpu_quarantine_recovery_cli_missing": not gpu["recovery_cli_present"],
        "llama_startup_outside_gpu_state_machine": not gpu["startup_uses_gpu_state_machine"],
        "gpu_live_handoff_evidence_missing_or_invalid": not gpu["live_test_evidence_valid"],
        "configured_llm_provider_not_repository_local": models["local_llm_provider"].casefold() != "llama_cpp_server",
        "verified_runtime_profile_contract_missing": not frontend["verified_alias_binding_contract_present"],
        "frontend_hardcoded_legacy_models": bool(frontend["hardcoded_legacy_models"]),
        "runtime_profile_contract_test_evidence_missing_or_invalid": not frontend["contract_test_evidence_valid"],
        "adaptive_long_audio_chunk_planner_missing": not architecture["adaptive_chunk_planner_present"],
        "deterministic_exact_value_detector_missing": not architecture["deterministic_exact_value_detector_present"],
        "append_only_intelligence_run_missing": not architecture["append_only_intelligence_run_present"],
        "quality_corpus_manifest_missing": not architecture["quality_corpus_manifest_present"],
        "quality_baseline_missing": not architecture["quality_baseline_present"],
        "quality_scorer_protocol_missing": not architecture["quality_scorer_protocol_present"],
    }
    checks.update(
        {
            f"{package}_evidence_missing_or_invalid": not package_evidence[package][
                "valid"
            ]
            for package in PACKAGE_EVIDENCE_REQUIREMENTS
        }
    )
    if runtime is not None:
        processes = runtime.get("processes", {})
        listeners = processes.get("listeners", []) if isinstance(processes, dict) else []
        noncanonical_listener = any(
            listener.get("port") in (3000, 8000, 8088)
            and listener.get("from_canonical_workspace") is not True
            for listener in listeners
        )
        checks.update(
            {
                "frontend_health_unavailable": runtime["frontend_http"].get("status") != 200,
                "backend_health_unavailable": runtime["backend_health"].get("status") != 200,
                "celery_ping_failed": not runtime["celery_ping"],
                "postgres_listener_unavailable": not runtime["ports"]["5432"],
                "redis_listener_unavailable": not runtime["ports"]["6379"],
                "redis_ping_failed": not runtime["redis_pong"],
                "runtime_process_probe_failed": bool(processes.get("error")),
                "noncanonical_application_listener_detected": noncanonical_listener,
                "old_repo_application_process_detected": bool(
                    processes.get("old_repo_process_count")
                ),
                "repository_local_llama_server_not_live": not runtime["ports"]["8088"],
                "ollama_listener_still_active": runtime["ports"]["11434"],
                "gpu_process_probe_failed": bool(
                    runtime.get("gpu_compute_processes", {}).get("error")
                ),
            }
        )
    if database is not None:
        checks.update(
            {
                "application_database_select_1_failed": database.get("select_1") != 1,
                "unexpected_application_database": database.get("database_name")
                != "speech_to_info",
            }
        )
    return sorted(name for name, failed in checks.items() if failed)


def build_report(
    repo_root: Path,
    *,
    include_database: bool,
    include_runtime: bool,
    generated_at: str | None,
) -> dict[str, Any]:
    repo_root = _canonical_repo(repo_root)
    repo_root_text = str(repo_root)
    if repo_root_text not in sys.path:
        sys.path.insert(0, repo_root_text)

    primary_sources = _primary_source_state(repo_root)
    pyannote_migration_audit = _pyannote_migration_audit_state(repo_root)
    package_evidence = _package_evidence_state(repo_root)
    summary = _summary_contract(repo_root)
    models = _model_state(repo_root, primary_sources)
    diarization = _diarization_contract(repo_root)
    gpu = _gpu_contract(repo_root)
    frontend = _frontend_contract(repo_root)
    architecture = _architecture_state(repo_root)
    runtime = _runtime_state(repo_root) if include_runtime else None
    timestamp, timestamp_source = _validated_generated_at(generated_at)
    database = _database_state() if include_database else None
    report: dict[str, Any] = {
        "schema_version": "summary-diarization-readiness-v2",
        "generated_at": timestamp,
        "generated_at_source": timestamp_source,
        "repo_root": str(repo_root),
        "canonical_workspace": True,
        "probe_mode": (
            "static"
            if not include_database and not include_runtime
            else "observed_live"
        ),
        "scope": "conservative_product_readiness_not_quality_prevalence",
        "git": _git_state(repo_root),
        "source_input_sha256": _source_hashes(repo_root),
        "primary_source_verification": primary_sources,
        "pyannote_migration_config_audit": pyannote_migration_audit,
        "package_evidence": package_evidence,
        "summary_contract": summary,
        "model_state": models,
        "diarization_contract": diarization,
        "gpu_contract": gpu,
        "frontend_contract": frontend,
        "architecture_and_evaluation": architecture,
    }
    if runtime is not None:
        report["runtime"] = runtime
    if database is not None:
        report["database_read_only"] = database
    blockers = _blockers(
        primary_sources,
        pyannote_migration_audit,
        package_evidence,
        summary,
        models,
        diarization,
        gpu,
        frontend,
        architecture,
        runtime,
        database,
    )
    report["verdict"] = "PASS" if not blockers else "BLOCKED"
    report["blockers"] = blockers
    report["limitations"] = [
        "Static source probes are conservative indicators, not substitutes for task tests.",
        "Database aggregates include legacy and test rows and do not estimate quality prevalence.",
        "Model quality still requires the pinned Vietnamese corpus and scorer protocol.",
    ]
    return report


def _write_manifest(
    repo_root: Path,
    manifest_path: Path,
    output_path: Path,
    source_hashes: dict[str, str | None],
    extra_paths: list[Path],
) -> None:
    rows = [
        (
            f"{digest}  {relative.replace('/', os.sep)}"
            if digest is not None
            else f"MISSING  {relative.replace('/', os.sep)}"
        )
        for relative, digest in sorted(source_hashes.items())
    ]
    for artifact_path in [output_path, *extra_paths]:
        artifact_relative = artifact_path.relative_to(repo_root).as_posix()
        rows.append(
            f"{_sha256(artifact_path)}  {artifact_relative.replace('/', os.sep)}"
        )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(rows) + "\n", encoding="ascii")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=CANONICAL_ROOT)
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--generated-at")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-extra", type=Path, action="append", default=[])
    args = parser.parse_args()

    try:
        repo_root = _canonical_repo(args.repo)
        output_path = _validated_output(repo_root, args.output)
        manifest_path = _validated_output(repo_root, args.manifest)
        manifest_extra_paths = [
            _validated_output(repo_root, path) for path in args.manifest_extra
        ]
        if manifest_path is not None and output_path is None:
            raise ValueError("--manifest requires --output")
        if manifest_path is None and manifest_extra_paths:
            raise ValueError("--manifest-extra requires --manifest")
        if any(path is None or not path.is_file() for path in manifest_extra_paths):
            raise ValueError("every --manifest-extra path must be an existing file")
        if args.generated_at is not None:
            _validated_generated_at(args.generated_at)
    except ValueError as exc:
        parser.error(str(exc))

    report = build_report(
        repo_root,
        include_database=args.database,
        include_runtime=args.runtime,
        generated_at=args.generated_at,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    if manifest_path is not None and output_path is not None:
        _write_manifest(
            repo_root,
            manifest_path,
            output_path,
            report["source_input_sha256"],
            [path for path in manifest_extra_paths if path is not None],
        )
    print(rendered)
    return 0 if report["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
