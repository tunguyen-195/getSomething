"""Export a reviewable release candidate without changing the real Git index."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.audit_release_inventory import (
        _frontend_requirements,
        _is_analyzable_source,
        _module_path,
        _python_requirements,
        classify_path,
    )
except ModuleNotFoundError:  # Direct script execution puts scripts/ on sys.path.
    from audit_release_inventory import (
        _frontend_requirements,
        _is_analyzable_source,
        _module_path,
        _python_requirements,
        classify_path,
    )


SCHEMA_VERSION = "stt-release-candidate-rehearsal-v5"
AUTOMATIC_RELEASE_CLASSES = {
    "CONFIG_MANIFEST",
    "DOC_REQUIRED",
    "RUNTIME_REQUIRED",
    "TEST_REQUIRED",
}
REDACTED_EXCLUSION_CLASSES = {
    "GENERATED_LOCAL",
    "SENSITIVE_LOCAL",
}
EXPLICIT_RELEASE_PATHS = {
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "alembic.ini",
    "docker-compose.test.yml",
    "docker-compose.yml",
    "Dockerfile.backend",
    "entrypoint.bat",
    "frontend/Dockerfile",
    "frontend/index.html",
    "frontend/nginx.conf",
    "frontend/package-lock.json",
    "frontend/package.json",
    "frontend/public/logo/black_on_trans.png",
    "frontend/public/logo/trans_bg.png",
    "frontend/public/logo/white_on_trans.png",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
    "package-lock.json",
    "package.json",
    "requirements-constraints-py311.txt",
    "requirements-torch-cu121.txt",
    "requirements.txt",
    "setup.py",
    # The v1 API still loads this module dynamically through tasks/__init__.py.
    "src/worker/tasks.py",
    # A current backend regression test still verifies this compatibility view.
    "src/web_interface/app.py",
}
MAX_CONTENT_SCAN_BYTES = 2 * 1024 * 1024
CASE_IDENTIFIER_RE = re.compile(
    r"(?i)[\"'](?:case_id|task_id|audio_id|file_id)[\"']\s*[:=]\s*[\"']"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}[\"']"
)
CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:secret(?:_key)?|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password)\b\s*[:=]\s*([\"'])"
    r"([A-Za-z0-9_./+=:@-]{16,})\1"
)
SECRET_RULES = (
    (
        "private_key_block",
        "critical",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"),
    ),
    ("aws_access_key", "critical", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "github_token",
        "critical",
        re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\b"),
    ),
    ("openai_api_key", "critical", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", "critical", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    (
        "slack_token",
        "critical",
        re.compile(r"\bxox(?:b|p|a|r|s)-[0-9A-Za-z-]{20,}\b"),
    ),
)
PLACEHOLDER_MARKERS = (
    "change-me",
    "example",
    "generate",
    "local-dev",
    "must-not-appear",
    "placeholder",
    "replace-me",
    "your-",
)
EXPLICIT_RELEASE_PREFIXES = (
    "config/",
    "src/database/migrations/",
)
DOCUMENT_SCRIPT_RE = re.compile(
    r"(?i)\bscripts[\\/][A-Za-z0-9_.-]+\.(?:bat|ps1|py)\b"
)


def _normalize(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def _run_git(
    root: Path,
    *args: str,
    env: dict[str, str] | None = None,
    check: bool = True,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        input=input_bytes,
        env=env,
        check=check,
    )


def _paths(payload: bytes) -> list[str]:
    return [
        _normalize(item.decode("utf-8", errors="surrogateescape"))
        for item in payload.split(b"\0")
        if item
    ]


def _real_index_fingerprint(root: Path) -> str:
    payload = _run_git(root, "ls-files", "--stage", "-z").stdout
    return hashlib.sha256(payload).hexdigest()


def _workspace_fingerprint(root: Path, paths: list[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        target = root / Path(*path.split("/"))
        digest.update(path.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        try:
            digest.update(hashlib.sha256(target.read_bytes()).digest())
        except OSError:
            digest.update(b"MISSING")
        digest.update(b"\0")
    return digest.hexdigest()


def _file_digest(path: Path) -> tuple[int | None, str | None]:
    try:
        content = path.read_bytes()
    except OSError:
        return None, None
    return len(content), hashlib.sha256(content).hexdigest()


def _git_clean_blob_oid(root: Path, path: str, target: Path) -> str | None:
    """Hash bytes through the repository's clean filters for a candidate path."""

    try:
        content = target.read_bytes()
    except OSError:
        return None
    result = _run_git(
        root,
        "hash-object",
        f"--path={path}",
        "--stdin",
        input_bytes=content,
    ).stdout.decode().strip()
    return result if re.fullmatch(r"[0-9a-f]{40,64}", result) else None


def _temporary_index_blob_oids(root: Path, env: dict[str, str]) -> dict[str, str]:
    entries: dict[str, str] = {}
    for record in _run_git(root, "ls-files", "--stage", "-z", env=env).stdout.split(
        b"\0"
    ):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        fields = metadata.split()
        if len(fields) != 3 or fields[2] != b"0":
            raise RuntimeError("Temporary candidate index contains an invalid stage")
        path = _normalize(raw_path.decode("utf-8", errors="surrogateescape"))
        entries[path] = fields[1].decode("ascii")
    return entries


def _release_selection(
    path: str,
    document_script_paths: set[str] | None = None,
) -> tuple[bool, str, str, str]:
    classification, disposition, rationale = classify_path(path)
    documented = path in (document_script_paths or set())
    selected = (
        classification in AUTOMATIC_RELEASE_CLASSES
        or documented
        or path in EXPLICIT_RELEASE_PATHS
        or path.startswith(EXPLICIT_RELEASE_PREFIXES)
    )
    selection_reason = (
        "automatic_release_class"
        if classification in AUTOMATIC_RELEASE_CLASSES
        else "canonical_document_reference"
        if documented
        else "explicit_release_path"
        if path in EXPLICIT_RELEASE_PATHS
        else "explicit_release_prefix"
        if path.startswith(EXPLICIT_RELEASE_PREFIXES)
        else "excluded_by_release_policy"
    )
    return selected, selection_reason, classification, disposition or rationale


def _document_script_references(root: Path) -> tuple[dict[str, list[str]], list[str]]:
    tracked = set(_paths(_run_git(root, "ls-files", "-z").stdout))
    untracked = set(
        _paths(_run_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout)
    )
    workspace_paths = {
        path
        for path in tracked | untracked
        if (root / Path(*path.split("/"))).is_file()
    }
    references: dict[str, set[str]] = defaultdict(set)
    for path in sorted(workspace_paths):
        if classify_path(path)[0] != "DOC_REQUIRED":
            continue
        target = root / Path(*path.split("/"))
        try:
            content = target.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        for raw_reference in DOCUMENT_SCRIPT_RE.findall(content):
            reference = _normalize(raw_reference)
            references[reference].add(path)
    normalized = {
        path: sorted(sources) for path, sources in sorted(references.items())
    }
    missing = sorted(path for path in normalized if path not in workspace_paths)
    return normalized, missing


def _workspace_paths(root: Path) -> set[str]:
    tracked = set(_paths(_run_git(root, "ls-files", "-z").stdout))
    untracked = set(
        _paths(_run_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout)
    )
    return {
        path
        for path in tracked | untracked
        if (root / Path(*path.split("/"))).is_file()
    }


def _dependency_closure(
    root: Path,
    selected_paths: set[str],
) -> tuple[set[str], list[dict], list[dict]]:
    workspace_paths = _workspace_paths(root)
    closure = set(selected_paths)
    edges = []
    parse_errors = []
    pending = sorted(path for path in closure if _is_analyzable_source(path))
    visited: set[str] = set()

    while pending:
        path = pending.pop(0)
        if path in visited:
            continue
        visited.add(path)
        target = root / Path(*path.split("/"))
        try:
            content = target.read_bytes()
        except OSError as exc:
            parse_errors.append({"source": path, "error": f"OSError: {exc}"})
            continue
        if path.endswith(".py"):
            references, error = _python_requirements(path, content, workspace_paths)
            dependencies = [
                (_module_path(reference, workspace_paths), reference)
                for reference in sorted(references)
            ]
        else:
            references, error = _frontend_requirements(path, content, workspace_paths)
            dependencies = [(reference, reference) for reference in sorted(references)]
        if error:
            parse_errors.append({"source": path, "error": error})
            continue
        for dependency, reference in dependencies:
            if not dependency:
                continue
            edges.append(
                {
                    "source": path,
                    "reference": reference,
                    "dependency": dependency,
                    "added_by_closure": dependency not in selected_paths,
                }
            )
            if dependency in closure:
                continue
            closure.add(dependency)
            if _is_analyzable_source(dependency):
                pending.append(dependency)

    return closure, edges, parse_errors


def _candidate_untracked_paths(
    root: Path,
    document_script_paths: set[str],
) -> tuple[list[str], list[dict]]:
    untracked = _paths(
        _run_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    )
    included: list[str] = []
    excluded: list[dict] = []
    for path in sorted(untracked):
        selected, selection_reason, classification, _ = _release_selection(
            path,
            document_script_paths,
        )
        _classification, disposition, rationale = classify_path(path)
        if selected:
            included.append(path)
        else:
            excluded.append(
                {
                    "path": path,
                    "classification": classification,
                    "suggested_disposition": disposition,
                    "rationale": rationale,
                    "selection_reason": selection_reason,
                }
            )
    return included, excluded


def _tracked_selection(
    root: Path,
    document_script_paths: set[str],
) -> tuple[list[str], list[dict]]:
    tracked = _paths(_run_git(root, "ls-files", "-z").stdout)
    included = []
    excluded = []
    for path in sorted(tracked):
        selected, selection_reason, classification, _ = _release_selection(
            path,
            document_script_paths,
        )
        _classification, disposition, rationale = classify_path(path)
        if selected:
            included.append(path)
        else:
            excluded.append(
                {
                    "path": path,
                    "classification": classification,
                    "suggested_disposition": disposition,
                    "rationale": rationale,
                    "selection_reason": selection_reason,
                }
            )
    return included, excluded


def _exclusion_summary(items: list[dict]) -> dict:
    """Keep reviewable exclusions while suppressing local or case-data paths."""

    classification_counts: dict[str, int] = {}
    review_items = []
    redacted_path_count = 0
    for item in items:
        classification = item["classification"]
        classification_counts[classification] = (
            classification_counts.get(classification, 0) + 1
        )
        if classification in REDACTED_EXCLUSION_CLASSES:
            redacted_path_count += 1
        else:
            review_items.append(item)
    return {
        "total_count": len(items),
        "classification_counts": dict(sorted(classification_counts.items())),
        "redacted_path_count": redacted_path_count,
        "review_items": review_items,
    }


def _entropy(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def _content_finding_severity(path: str, severity: str) -> str:
    if path.startswith(("docs/", "tests/", "frontend/tests/")) and severity != "critical":
        return "review"
    return severity


def _content_scan(export_root: Path, candidate_paths: list[str]) -> dict:
    findings = []
    scanned_file_count = 0
    skipped_binary_count = 0
    skipped_large_count = 0
    skipped_symlink_count = 0

    for path in candidate_paths:
        target = export_root / Path(*path.split("/"))
        if target.is_symlink():
            skipped_symlink_count += 1
            findings.append(
                {
                    "path": path,
                    "line": None,
                    "category": "scan_coverage",
                    "rule": "symlink_not_scanned",
                    "severity": "high",
                }
            )
            continue
        try:
            size = target.stat().st_size
        except OSError:
            findings.append(
                {
                    "path": path,
                    "line": None,
                    "category": "scan_coverage",
                    "rule": "file_unreadable",
                    "severity": "high",
                }
            )
            continue
        if size > MAX_CONTENT_SCAN_BYTES:
            skipped_large_count += 1
            findings.append(
                {
                    "path": path,
                    "line": None,
                    "category": "scan_coverage",
                    "rule": "file_too_large_to_scan",
                    "severity": "review",
                }
            )
            continue
        payload = target.read_bytes()
        if b"\0" in payload[:4096]:
            skipped_binary_count += 1
            continue
        try:
            content = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            skipped_binary_count += 1
            continue
        scanned_file_count += 1

        for rule, severity, pattern in SECRET_RULES:
            for match in pattern.finditer(content):
                findings.append(
                    {
                        "path": path,
                        "line": content.count("\n", 0, match.start()) + 1,
                        "category": "secret",
                        "rule": rule,
                        "severity": _content_finding_severity(path, severity),
                    }
                )

        for match in CREDENTIAL_ASSIGNMENT_RE.finditer(content):
            value = match.group(2)
            lowered = value.casefold()
            if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
                continue
            if _entropy(value) < 3.5:
                continue
            findings.append(
                {
                    "path": path,
                    "line": content.count("\n", 0, match.start()) + 1,
                    "category": "secret",
                    "rule": "high_entropy_credential_assignment",
                    "severity": _content_finding_severity(path, "high"),
                }
            )

        for match in CASE_IDENTIFIER_RE.finditer(content):
            severity = (
                "review"
                if path.startswith(("docs/", "tests/", "frontend/tests/"))
                else "high"
            )
            findings.append(
                {
                    "path": path,
                    "line": content.count("\n", 0, match.start()) + 1,
                    "category": "case_data",
                    "rule": "investigation_record_identifier",
                    "severity": severity,
                }
            )

        lowered_content = content.casefold()
        if target.suffix.casefold() in {".json", ".jsonl"} and all(
            marker in lowered_content
            for marker in ('"segments"', '"text"', '"speaker"')
        ):
            severity = "review" if path.startswith("tests/") else "high"
            findings.append(
                {
                    "path": path,
                    "line": None,
                    "category": "case_data",
                    "rule": "structured_transcript_payload",
                    "severity": severity,
                }
            )

    severity_counts = Counter(item["severity"] for item in findings)
    blocking_count = sum(
        count for severity, count in severity_counts.items() if severity in {"critical", "high"}
    )
    verdict = "BLOCKED" if blocking_count else "REVIEW" if findings else "PASS"
    return {
        "verdict": verdict,
        "blocking_finding_count": blocking_count,
        "finding_count": len(findings),
        "severity_counts": dict(sorted(severity_counts.items())),
        "scanned_file_count": scanned_file_count,
        "skipped_binary_count": skipped_binary_count,
        "skipped_large_count": skipped_large_count,
        "skipped_symlink_count": skipped_symlink_count,
        "max_file_size_bytes": MAX_CONTENT_SCAN_BYTES,
        "findings": findings,
        "matched_values_recorded": False,
    }


def _candidate_manifest(
    root: Path,
    candidate_root: Path,
    candidate_paths: list[str],
    untracked_included: list[str],
    document_script_paths: set[str],
    dependency_added_paths: set[str],
    candidate_tree_blob_oids: dict[str, str],
) -> dict:
    tracked_paths = set(_paths(_run_git(root, "ls-files", "-z").stdout))
    untracked_paths = set(untracked_included)
    entries = []
    for path in candidate_paths:
        source_size, source_sha256 = _file_digest(root / Path(*path.split("/")))
        candidate_size, candidate_sha256 = _file_digest(
            candidate_root / Path(*path.split("/"))
        )
        source_git_clean_blob_oid = _git_clean_blob_oid(
            root,
            path,
            root / Path(*path.split("/")),
        )
        candidate_git_clean_blob_oid = _git_clean_blob_oid(
            root,
            path,
            candidate_root / Path(*path.split("/")),
        )
        candidate_tree_blob_oid = candidate_tree_blob_oids.get(path)
        classification, disposition, rationale = classify_path(path)
        selected, selection_reason, _classification, _ = _release_selection(
            path,
            document_script_paths,
        )
        dependency_added = path in dependency_added_paths
        review_required = not selected and not dependency_added
        entries.append(
            {
                "path": path,
                "origin": (
                    "workspace_untracked"
                    if path in untracked_paths
                    else "workspace_tracked"
                    if path in tracked_paths
                    else "head_only"
                ),
                "classification": classification,
                "classification_rationale": rationale,
                "suggested_disposition": disposition,
                "selection_reason": (
                    "local_dependency_closure" if dependency_added else selection_reason
                ),
                "review_required": review_required,
                "review_status": "pending" if review_required else "provisionally_selected",
                "source_size_bytes": source_size,
                "source_sha256": source_sha256,
                "candidate_size_bytes": candidate_size,
                "candidate_sha256": candidate_sha256,
                "source_candidate_raw_match": (
                    source_sha256 is not None
                    and source_sha256 == candidate_sha256
                    and source_size == candidate_size
                ),
                "source_git_clean_blob_oid": source_git_clean_blob_oid,
                "candidate_git_clean_blob_oid": candidate_git_clean_blob_oid,
                "candidate_tree_blob_oid": candidate_tree_blob_oid,
                "source_candidate_match_basis": (
                    "git_clean_blob_oid_and_candidate_tree_blob_oid"
                ),
                "source_candidate_match": (
                    source_git_clean_blob_oid is not None
                    and source_git_clean_blob_oid == candidate_git_clean_blob_oid
                    and source_git_clean_blob_oid == candidate_tree_blob_oid
                ),
            }
        )
    classification_counts = Counter(item["classification"] for item in entries)
    origin_counts = Counter(item["origin"] for item in entries)
    pending_count = sum(item["review_required"] for item in entries)
    mismatch_count = sum(not item["source_candidate_match"] for item in entries)
    raw_mismatch_count = sum(
        not item["source_candidate_raw_match"] for item in entries
    )
    return {
        "verdict": "BLOCKED" if pending_count or mismatch_count else "PASS",
        "entry_count": len(entries),
        "pending_review_count": pending_count,
        "source_candidate_mismatch_count": mismatch_count,
        "source_candidate_raw_mismatch_count": raw_mismatch_count,
        "classification_counts": dict(sorted(classification_counts.items())),
        "origin_counts": dict(sorted(origin_counts.items())),
        "entries": entries,
    }


def _temporary_git_environment(root: Path, temporary_root: Path) -> dict[str, str]:
    git_dir_raw = _run_git(root, "rev-parse", "--git-dir").stdout.decode().strip()
    git_dir = Path(git_dir_raw)
    if not git_dir.is_absolute():
        git_dir = (root / git_dir).resolve()
    object_directory = temporary_root / "objects"
    object_directory.mkdir(parents=True)
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str((temporary_root / "index").resolve())
    env["GIT_OBJECT_DIRECTORY"] = str(object_directory.resolve())
    env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str((git_dir / "objects").resolve())
    return env


def _initialize_candidate_repository(
    candidate_root: Path,
    candidate_paths: list[str],
    expected_tree_oid: str,
) -> str:
    """Create clean-clone Git metadata whose index exactly matches the candidate tree."""

    _run_git(candidate_root, "init", "--quiet")
    _run_git(candidate_root, "config", "user.name", "STT Release Harness")
    _run_git(candidate_root, "config", "user.email", "release-harness@example.invalid")
    if candidate_paths:
        _run_git(candidate_root, "add", "-f", "--", *candidate_paths)
    materialized_tree_oid = _run_git(candidate_root, "write-tree").stdout.decode().strip()
    if materialized_tree_oid != expected_tree_oid:
        raise RuntimeError(
            "Materialized candidate repository tree does not match temporary index tree"
        )
    commit_env = os.environ.copy()
    commit_env.update(
        {
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        }
    )
    _run_git(
        candidate_root,
        "commit",
        "--quiet",
        "--message",
        f"Release candidate tree {expected_tree_oid}",
        env=commit_env,
    )
    return _run_git(candidate_root, "rev-parse", "HEAD").stdout.decode().strip()


def build_candidate(repo_root: Path, export_root: Path) -> dict:
    root = Path(
        _run_git(repo_root.resolve(), "rev-parse", "--show-toplevel")
        .stdout.decode()
        .strip()
    ).resolve()
    export_root = export_root.resolve()
    if export_root.exists() and any(export_root.iterdir()):
        raise ValueError(f"Candidate export directory is not empty: {export_root}")
    export_root.mkdir(parents=True, exist_ok=True)

    real_index_before = _real_index_fingerprint(root)
    document_script_references, missing_document_script_references = (
        _document_script_references(root)
    )
    document_script_paths = set(document_script_references)
    untracked_included, untracked_excluded = _candidate_untracked_paths(
        root,
        document_script_paths,
    )
    tracked_included, tracked_excluded = _tracked_selection(
        root,
        document_script_paths,
    )
    policy_selected_paths = set(tracked_included) | set(untracked_included)
    selected_paths, dependency_edges, dependency_parse_errors = _dependency_closure(
        root,
        policy_selected_paths,
    )
    dependency_added_paths = selected_paths - policy_selected_paths

    with tempfile.TemporaryDirectory(prefix="stt-release-index-") as temp_name:
        temporary_root = Path(temp_name)
        env = _temporary_git_environment(root, temporary_root)
        _run_git(root, "read-tree", "--empty", env=env)
        ordered_selected_paths = sorted(selected_paths)
        if ordered_selected_paths:
            _run_git(root, "add", "-f", "--", *ordered_selected_paths, env=env)

        candidate_tree = _run_git(root, "write-tree", env=env).stdout.decode().strip()
        candidate_paths = _paths(_run_git(root, "ls-files", "-z", env=env).stdout)
        candidate_tree_blob_oids = _temporary_index_blob_oids(root, env)
        prefix = str(export_root) + os.sep
        _run_git(
            root,
            "checkout-index",
            "--all",
            "--force",
            f"--prefix={prefix}",
            env=env,
        )

    content_scan = _content_scan(export_root, candidate_paths)
    candidate_manifest = _candidate_manifest(
        root,
        export_root,
        candidate_paths,
        untracked_included,
        document_script_paths,
        dependency_added_paths,
        candidate_tree_blob_oids,
    )
    candidate_repository_revision = _initialize_candidate_repository(
        export_root,
        candidate_paths,
        candidate_tree,
    )

    real_index_after = _real_index_fingerprint(root)
    if real_index_after != real_index_before:
        raise RuntimeError("Real Git index changed during candidate rehearsal")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": {
            "root": str(root),
            "head_revision": _run_git(root, "rev-parse", "HEAD").stdout.decode().strip(),
            "branch": _run_git(root, "branch", "--show-current").stdout.decode().strip(),
        },
        "mode": "temporary_index_and_object_database",
        "real_index": {
            "fingerprint_before": real_index_before,
            "fingerprint_after": real_index_after,
            "unchanged": real_index_after == real_index_before,
        },
        "candidate": {
            "tree_oid": candidate_tree,
            "repository_revision": candidate_repository_revision,
            "export_root": str(export_root),
            "file_count": len(candidate_paths),
            "paths": candidate_paths,
            "workspace_content_fingerprint_sha256": _workspace_fingerprint(
                root,
                candidate_paths,
            ),
            "materialized_content_fingerprint_sha256": _workspace_fingerprint(
                export_root,
                candidate_paths,
            ),
        },
        "content_scan": content_scan,
        "candidate_manifest": candidate_manifest,
        "selection": {
            "automatic_release_classes": sorted(AUTOMATIC_RELEASE_CLASSES),
            "explicit_release_paths": sorted(EXPLICIT_RELEASE_PATHS),
            "explicit_release_prefixes": list(EXPLICIT_RELEASE_PREFIXES),
            "document_script_references": document_script_references,
            "missing_document_script_references": missing_document_script_references,
            "dependency_closure": {
                "policy_selected_count": len(policy_selected_paths),
                "added_path_count": len(dependency_added_paths),
                "added_paths": sorted(dependency_added_paths),
                "edge_count": len(dependency_edges),
                "edges": dependency_edges,
                "parse_errors": dependency_parse_errors,
            },
            "tracked_included_count": len(tracked_included),
            "untracked_included_count": len(untracked_included),
            "untracked_included": untracked_included,
            "untracked_excluded": _exclusion_summary(untracked_excluded),
            "tracked_excluded": _exclusion_summary(tracked_excluded),
        },
        "limitations": [
            "The temporary candidate index is built from current workspace content, not the real staged index.",
            "Raw workspace and materialized fingerprints are bound separately because checkout filters may change line endings; Git-clean blob OIDs bind both forms to the candidate tree.",
            "The export contains synthetic local Git metadata with a clean root commit whose tree equals candidate.tree_oid; the commit is for clean-clone test behavior, not source-history provenance.",
            "Automatic inclusion does not authorize release; every included path still requires human manifest review.",
            "Generated and sensitive exclusion paths are counted by class but redacted from the report.",
            "Content findings record rule, severity, candidate path, and line only; matched values are never serialized.",
            "Content scanning is heuristic and limited to UTF-8 text files no larger than the configured size cap.",
            "Canonical documentation script references are selected automatically; missing referenced scripts block the rehearsal.",
            "Local Python and frontend import closure is added transitively and recorded in the manifest.",
            "Export proves source selection only until independent install, test, build, migration, and runtime checks execute inside the candidate tree.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--export-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = build_candidate(args.repo_root, args.export_root)
    output = args.output
    if not output.is_absolute():
        output = args.repo_root.resolve() / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "candidate_tree": report["candidate"]["tree_oid"],
                "export_root": report["candidate"]["export_root"],
                "file_count": report["candidate"]["file_count"],
                "real_index_unchanged": report["real_index"]["unchanged"],
                "content_scan_verdict": report["content_scan"]["verdict"],
                "manifest_verdict": report["candidate_manifest"]["verdict"],
                "manifest_pending_review": report["candidate_manifest"]["pending_review_count"],
                "missing_document_scripts": len(
                    report["selection"]["missing_document_script_references"]
                ),
                "dependency_paths_added": report["selection"]["dependency_closure"][
                    "added_path_count"
                ],
                "output": str(output),
            },
            ensure_ascii=True,
        )
    )
    blocked = (
        report["content_scan"]["verdict"] == "BLOCKED"
        or report["candidate_manifest"]["verdict"] == "BLOCKED"
        or report["selection"]["missing_document_script_references"]
        or report["selection"]["dependency_closure"]["parse_errors"]
    )
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
