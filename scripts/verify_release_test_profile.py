"""Verify and optionally execute the candidate-bound backend release test profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

try:
    from scripts.audit_release_inventory import classify_path
    from scripts.rehearse_release_candidate import (
        _dependency_closure,
        _document_script_references,
        _release_selection,
        _workspace_paths,
        _workspace_fingerprint,
    )
except ModuleNotFoundError:  # Direct execution puts scripts/ on sys.path.
    from audit_release_inventory import classify_path
    from rehearse_release_candidate import (
        _dependency_closure,
        _document_script_references,
        _release_selection,
        _workspace_paths,
        _workspace_fingerprint,
    )


PROFILE_SCHEMA_VERSION = "stt-release-test-profile-v1"
REPORT_SCHEMA_VERSION = "stt-release-test-profile-verification-v1"
DEFAULT_PROFILE = Path("config/release/backend-source-test-profile.v1.json")
ALLOWED_CATEGORIES = {
    "external_artifact",
    "historical_evidence",
    "legacy_noncanonical",
}
IGNORED_CANDIDATE_PREFIXES = (
    ".git/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    "frontend/dist/",
    "frontend/node_modules/",
    "node_modules/",
    "venv/",
)
IGNORED_CANDIDATE_PARTS = {"__pycache__"}


class ReleaseProfileError(ValueError):
    """Raised when a release profile or candidate binding is invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseProfileError(f"Cannot read JSON from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseProfileError(f"JSON root must be an object: {path}")
    return payload


def _safe_relative_path(raw_path: str, *, prefix: str | None = None) -> str | None:
    path = _normalize(raw_path)
    pure = PurePosixPath(path)
    if not path or pure.is_absolute() or ".." in pure.parts:
        return None
    if prefix and not path.startswith(prefix):
        return None
    return path


def validate_profile(repo_root: Path, profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if profile.get("schema_version") != PROFILE_SCHEMA_VERSION:
        errors.append("profile_schema_version_invalid")
    if not isinstance(profile.get("profile_id"), str) or not profile.get("profile_id"):
        errors.append("profile_id_missing")
    test_root = profile.get("test_root")
    normalized_test_root = (
        _safe_relative_path(test_root) if isinstance(test_root, str) else None
    )
    if not normalized_test_root:
        errors.append("test_root_invalid")
    elif not (repo_root / Path(*normalized_test_root.split("/"))).is_dir():
        errors.append("test_root_missing")

    pytest_args = profile.get("pytest_args")
    if not isinstance(pytest_args, list) or not all(
        isinstance(item, str) and item for item in pytest_args
    ):
        errors.append("pytest_args_invalid")

    selection = profile.get("selection")
    if not isinstance(selection, dict):
        errors.append("selection_missing")
        entries: list[Any] = []
    else:
        if (
            selection.get("release_blocking_rule")
            != "all_collected_tests_except_declared_non_release"
        ):
            errors.append("release_blocking_rule_invalid")
        entries = selection.get("non_release_tests")
        if not isinstance(entries, list):
            errors.append("non_release_tests_invalid")
            entries = []

    seen: set[str] = set()
    for index, entry in enumerate(entries):
        prefix = f"non_release_tests[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}:entry_invalid")
            continue
        nodeid = entry.get("nodeid")
        if not isinstance(nodeid, str) or "::" not in nodeid:
            errors.append(f"{prefix}:nodeid_invalid")
            continue
        nodeid = _normalize(nodeid)
        test_path = nodeid.split("::", 1)[0]
        if _safe_relative_path(test_path, prefix="tests/") is None:
            errors.append(f"{prefix}:test_path_invalid")
        elif not (repo_root / Path(*test_path.split("/"))).is_file():
            errors.append(f"{prefix}:test_path_missing")
        if nodeid in seen:
            errors.append(f"{prefix}:nodeid_duplicate")
        seen.add(nodeid)
        if entry.get("category") not in ALLOWED_CATEGORIES:
            errors.append(f"{prefix}:category_invalid")
        for field in ("reason_code", "rationale", "separate_gate"):
            if not isinstance(entry.get(field), str) or not entry.get(field):
                errors.append(f"{prefix}:{field}_missing")
        required_paths = entry.get("required_paths")
        if not isinstance(required_paths, list) or not required_paths:
            errors.append(f"{prefix}:required_paths_invalid")
        elif any(
            not isinstance(path, str) or _safe_relative_path(path) is None
            for path in required_paths
        ):
            errors.append(f"{prefix}:required_path_invalid")

    binding = profile.get("candidate_binding")
    if not isinstance(binding, dict) or binding.get("required") is not True:
        errors.append("candidate_binding_required")
    else:
        accepted = binding.get("accepted_rehearsal_schema_versions")
        if not isinstance(accepted, list) or not accepted or not all(
            isinstance(item, str) and item for item in accepted
        ):
            errors.append("accepted_rehearsal_schema_versions_invalid")
        if (
            binding.get("fingerprint_field")
            != "candidate.workspace_content_fingerprint_sha256"
        ):
            errors.append("candidate_fingerprint_field_invalid")
        if binding.get("manifest_verdict_required") != "PASS":
            errors.append("candidate_manifest_requirement_invalid")
        if binding.get("content_scan_blocked_forbidden") is not True:
            errors.append("candidate_content_scan_requirement_invalid")
    return errors


def _current_release_paths(repo_root: Path) -> tuple[set[str], list[dict]]:
    document_references, _missing_references = _document_script_references(repo_root)
    documented_paths = set(document_references)
    policy_selected = {
        path
        for path in _workspace_paths(repo_root)
        if _release_selection(path, documented_paths)[0]
    }
    closure, _edges, parse_errors = _dependency_closure(repo_root, policy_selected)
    return closure, parse_errors


def _candidate_extra_path_state(
    candidate_root: Path,
    candidate_paths: set[str],
) -> dict[str, Any]:
    review_paths: list[str] = []
    generated_count = 0
    sensitive_count = 0
    for target in candidate_root.rglob("*"):
        if not target.is_file():
            continue
        relative = target.relative_to(candidate_root).as_posix()
        if relative in candidate_paths:
            continue
        if relative.startswith(IGNORED_CANDIDATE_PREFIXES) or any(
            part in IGNORED_CANDIDATE_PARTS for part in PurePosixPath(relative).parts
        ):
            continue
        classification = classify_path(relative)[0]
        if classification == "GENERATED_LOCAL":
            generated_count += 1
        elif classification == "SENSITIVE_LOCAL":
            sensitive_count += 1
        else:
            review_paths.append(relative)
    return {
        "review_path_count": len(review_paths),
        "review_paths": sorted(review_paths),
        "generated_path_count": generated_count,
        "sensitive_path_count": sensitive_count,
        "sensitive_paths_recorded": False,
    }


def verify_candidate_binding(
    source_root: Path,
    profile: dict[str, Any],
    rehearsal: dict[str, Any],
    *,
    candidate_root: Path | None = None,
) -> dict[str, Any]:
    candidate_root = source_root if candidate_root is None else candidate_root
    errors: list[str] = []
    binding = profile.get("candidate_binding") or {}
    accepted_versions = set(binding.get("accepted_rehearsal_schema_versions") or [])
    if rehearsal.get("schema_version") not in accepted_versions:
        errors.append("candidate_rehearsal_schema_not_accepted")

    candidate = rehearsal.get("candidate")
    if not isinstance(candidate, dict):
        candidate = {}
        errors.append("candidate_section_missing")
    raw_paths = candidate.get("paths")
    if not isinstance(raw_paths, list) or not all(
        isinstance(path, str) and _safe_relative_path(path) is not None
        for path in raw_paths or []
    ):
        errors.append("candidate_paths_invalid")
        candidate_paths: list[str] = []
    else:
        candidate_paths = sorted({_normalize(path) for path in raw_paths})
        if len(candidate_paths) != len(raw_paths):
            errors.append("candidate_paths_duplicate")

    expected_fingerprint = candidate.get("workspace_content_fingerprint_sha256")
    if not isinstance(expected_fingerprint, str) or len(expected_fingerprint) != 64:
        errors.append("candidate_fingerprint_invalid")
        expected_fingerprint = None
    source_fingerprint = (
        _workspace_fingerprint(source_root, candidate_paths) if candidate_paths else None
    )
    candidate_fingerprint = (
        _workspace_fingerprint(candidate_root, candidate_paths)
        if candidate_paths
        else None
    )
    if expected_fingerprint and source_fingerprint != expected_fingerprint:
        errors.append("candidate_source_stale")
    if expected_fingerprint and candidate_fingerprint != expected_fingerprint:
        errors.append("candidate_materialization_mismatch")

    manifest = rehearsal.get("candidate_manifest")
    if not isinstance(manifest, dict):
        errors.append("candidate_manifest_missing")
        manifest_paths: set[str] = set()
    else:
        if manifest.get("verdict") != binding.get("manifest_verdict_required"):
            errors.append("candidate_manifest_not_pass")
        entries = manifest.get("entries")
        if not isinstance(entries, list) or not all(
            isinstance(entry, dict) and isinstance(entry.get("path"), str)
            for entry in entries or []
        ):
            errors.append("candidate_manifest_entries_invalid")
            manifest_paths = set()
        else:
            manifest_paths = {_normalize(entry["path"]) for entry in entries}
            if manifest_paths != set(candidate_paths):
                errors.append("candidate_manifest_path_mismatch")

    content_scan = rehearsal.get("content_scan")
    if not isinstance(content_scan, dict):
        errors.append("candidate_content_scan_missing")
    elif content_scan.get("verdict") == "BLOCKED":
        errors.append("candidate_content_scan_blocked")

    selection = rehearsal.get("selection")
    if not isinstance(selection, dict):
        errors.append("candidate_selection_missing")
    else:
        if selection.get("missing_document_script_references"):
            errors.append("candidate_document_script_missing")
        closure = selection.get("dependency_closure")
        if not isinstance(closure, dict):
            errors.append("candidate_dependency_closure_missing")
        elif closure.get("parse_errors"):
            errors.append("candidate_dependency_parse_error")

    current_release_paths, current_dependency_parse_errors = _current_release_paths(
        source_root
    )
    unexpected_release_paths = sorted(current_release_paths - set(candidate_paths))
    if unexpected_release_paths:
        errors.append("candidate_unmanifested_release_path")
    if current_dependency_parse_errors:
        errors.append("current_dependency_parse_error")

    missing_paths = sorted(
        path
        for path in candidate_paths
        if not (candidate_root / Path(*path.split("/"))).is_file()
    )
    if missing_paths:
        errors.append("candidate_path_missing")
    extra_paths = _candidate_extra_path_state(candidate_root, set(candidate_paths))
    if extra_paths["review_path_count"]:
        errors.append("candidate_unmanifested_path")
    if extra_paths["sensitive_path_count"]:
        errors.append("candidate_unmanifested_sensitive_path")
    return {
        "status": "BLOCKED" if errors else "PASS",
        "errors": errors,
        "source_root": str(source_root),
        "candidate_root": str(candidate_root),
        "candidate_tree_oid": candidate.get("tree_oid"),
        "candidate_path_count": len(candidate_paths),
        "expected_workspace_content_fingerprint_sha256": expected_fingerprint,
        "source_workspace_content_fingerprint_sha256": source_fingerprint,
        "candidate_content_fingerprint_sha256": candidate_fingerprint,
        "source_stale": "candidate_source_stale" in errors,
        "candidate_materialization_matches": (
            "candidate_materialization_mismatch" not in errors
        ),
        "missing_candidate_path_count": len(missing_paths),
        "unexpected_release_path_count": len(unexpected_release_paths),
        "unexpected_release_paths": unexpected_release_paths,
        "current_dependency_parse_error_count": len(current_dependency_parse_errors),
        "unmanifested_candidate_paths": extra_paths,
    }


def parse_collected_nodeids(output: str) -> list[str]:
    nodeids = []
    for raw_line in output.splitlines():
        line = _normalize(raw_line.strip())
        if line.startswith("tests/") and "::" in line:
            nodeids.append(line)
    return sorted(set(nodeids))


def collect_nodeids(
    repo_root: Path,
    profile: dict[str, Any],
    *,
    python_executable: str,
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
    command = [
        python_executable,
        "-m",
        "pytest",
        str(profile["test_root"]),
        "--collect-only",
        "-q",
    ]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed, parse_collected_nodeids(completed.stdout), command


def assess_collection(
    profile: dict[str, Any],
    collected_nodeids: Sequence[str],
) -> dict[str, Any]:
    collected = {_normalize(nodeid) for nodeid in collected_nodeids}
    excluded_entries = profile["selection"]["non_release_tests"]
    excluded = {_normalize(entry["nodeid"]) for entry in excluded_entries}
    missing = sorted(excluded - collected)
    release_nodeids = sorted(collected - excluded)
    category_counts = Counter(entry["category"] for entry in excluded_entries)
    return {
        "status": "BLOCKED" if missing or not release_nodeids else "PASS",
        "collected_test_count": len(collected),
        "release_blocking_test_count": len(release_nodeids),
        "declared_non_release_test_count": len(excluded),
        "non_release_category_counts": dict(sorted(category_counts.items())),
        "missing_declared_nodeids": missing,
        "release_nodeids_sha256": hashlib.sha256(
            ("\n".join(release_nodeids) + "\n").encode("utf-8")
        ).hexdigest(),
    }


def build_pytest_command(
    profile: dict[str, Any],
    *,
    python_executable: str,
    extra_args: Sequence[str] = (),
) -> list[str]:
    command = [
        python_executable,
        "-m",
        "pytest",
        str(profile["test_root"]),
        *profile["pytest_args"],
    ]
    for entry in profile["selection"]["non_release_tests"]:
        command.append(f"--deselect={_normalize(entry['nodeid'])}")
    command.extend(extra_args)
    return command


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_candidate_python(
    candidate_root: Path,
    requested: str | None,
) -> Path:
    if requested:
        candidate_python = Path(requested)
        if not candidate_python.is_absolute():
            candidate_python = candidate_root / candidate_python
    else:
        relative = (
            Path("venv/Scripts/python.exe")
            if os.name == "nt"
            else Path("venv/bin/python")
        )
        candidate_python = candidate_root / relative
    candidate_python = candidate_python.resolve()
    try:
        candidate_python.relative_to(candidate_root.resolve())
    except ValueError as exc:
        raise ReleaseProfileError(
            "Release-test Python interpreter must be inside the candidate root"
        ) from exc
    if not candidate_python.is_file():
        raise ReleaseProfileError(
            f"Candidate Python interpreter does not exist: {candidate_python}"
        )
    return candidate_python


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--candidate-root",
        type=Path,
        help="Candidate export root; defaults to candidate.export_root in the report.",
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--python",
        help=(
            "Python inside the candidate; defaults to venv/Scripts/python.exe "
            "on Windows or venv/bin/python elsewhere."
        ),
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--pytest-arg", action="append", default=[])
    args = parser.parse_args(argv)

    source_root = args.repo_root.resolve()
    candidate_report_path = args.candidate_report.resolve()
    output_path = args.output
    if output_path is not None and not output_path.is_absolute():
        output_path = source_root / output_path

    started_at = _utc_now()
    try:
        rehearsal = load_json(candidate_report_path)
        candidate_payload = rehearsal.get("candidate")
        if not isinstance(candidate_payload, dict):
            raise ReleaseProfileError("Candidate report has no candidate object")
        if args.candidate_root is not None:
            candidate_root = args.candidate_root.resolve()
        else:
            raw_export_root = candidate_payload.get("export_root")
            if not isinstance(raw_export_root, str) or not raw_export_root:
                raise ReleaseProfileError(
                    "Candidate report has no export_root; pass --candidate-root"
                )
            candidate_root = Path(raw_export_root).resolve()
        if not candidate_root.is_dir():
            raise ReleaseProfileError(
                f"Candidate root does not exist or is not a directory: {candidate_root}"
            )
        profile_path = args.profile
        if not profile_path.is_absolute():
            profile_path = candidate_root / profile_path
        profile = load_json(profile_path)
        profile_errors = validate_profile(candidate_root, profile)
        candidate_python = resolve_candidate_python(candidate_root, args.python)
        binding = verify_candidate_binding(
            source_root,
            profile,
            rehearsal,
            candidate_root=candidate_root,
        )
    except ReleaseProfileError as exc:
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "status": "BLOCKED",
            "errors": [str(exc)],
            "release_suite_executed": False,
        }
        _write_report(output_path, report)
        print(json.dumps(report, sort_keys=True))
        return 2

    collection: dict[str, Any]
    collect_command: list[str] = []
    if profile_errors or binding["status"] != "PASS":
        collection = {"status": "NOT_RUN"}
    else:
        completed, nodeids, collect_command = collect_nodeids(
            candidate_root,
            profile,
            python_executable=str(candidate_python),
        )
        if completed.returncode != 0:
            collection = {
                "status": "BLOCKED",
                "collection_exit_code": completed.returncode,
                "stdout_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
                "stderr_sha256": hashlib.sha256(completed.stderr.encode("utf-8")).hexdigest(),
            }
        else:
            collection = assess_collection(profile, nodeids)
            collection["collection_exit_code"] = 0

    preflight_errors = list(profile_errors) + list(binding["errors"])
    if collection.get("status") == "BLOCKED":
        preflight_errors.append("pytest_collection_blocked")
    preflight_status = "BLOCKED" if preflight_errors else "PASS"
    pytest_command = build_pytest_command(
        profile,
        python_executable=str(candidate_python),
        extra_args=args.pytest_arg,
    )

    test_exit_code: int | None = None
    if args.execute and preflight_status == "PASS":
        completed = subprocess.run(pytest_command, cwd=candidate_root, check=False)
        test_exit_code = completed.returncode

    release_suite_status = (
        "NOT_RUN"
        if not args.execute or preflight_status != "PASS"
        else "PASS"
        if test_exit_code == 0
        else "FAIL"
    )
    status = (
        "BLOCKED"
        if preflight_status != "PASS"
        else "PASS"
        if release_suite_status in {"PASS", "NOT_RUN"}
        else "FAIL"
    )
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "started_at": started_at,
        "status": status,
        "scope": profile.get("scope"),
        "source_root": str(source_root),
        "candidate_root": str(candidate_root),
        "candidate_python": str(candidate_python),
        "profile": {
            "profile_id": profile.get("profile_id"),
            "path": str(profile_path),
            "sha256": _sha256(profile_path),
            "validation_errors": profile_errors,
        },
        "candidate_binding": binding,
        "collection": collection,
        "preflight_status": preflight_status,
        "preflight_errors": preflight_errors,
        "release_suite_executed": args.execute and preflight_status == "PASS",
        "release_suite_status": release_suite_status,
        "test_exit_code": test_exit_code,
        "commands": {
            "collection": collect_command,
            "release_suite": pytest_command,
        },
        "overall_release_ready": False,
        "limitations": profile.get("limitations") or [],
    }
    _write_report(output_path, report)
    print(
        json.dumps(
            {
                "status": status,
                "preflight_status": preflight_status,
                "release_suite_status": release_suite_status,
                "release_blocking_test_count": collection.get(
                    "release_blocking_test_count"
                ),
                "output": str(output_path) if output_path else None,
            },
            sort_keys=True,
        )
    )
    if preflight_status != "PASS":
        return 2
    if args.execute:
        return test_exit_code or 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
