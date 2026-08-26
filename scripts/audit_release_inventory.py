"""Build a read-only Git release inventory and clean-clone closure report."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import posixpath
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable


SCHEMA_VERSION = "stt-release-inventory-v2"
PYTHON_SUFFIX = ".py"
FRONTEND_SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx")
FRONTEND_RESOLUTION_SUFFIXES = (
    *FRONTEND_SOURCE_SUFFIXES,
    ".json",
    ".css",
    ".scss",
)

GENERATED_PREFIXES = (
    ".cursor/",
    ".planning/",
    ".playwright-cli/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "frontend/dist/",
    "frontend/build/",
)
SENSITIVE_PREFIXES = (
    ".gradio/",
    "data/",
    "logs/",
    "output/",
    "storage/audio/",
    "uploads/",
)
SENSITIVE_ROOT_FILES = {
    "cases.json",
    "tasks.json",
}
SENSITIVE_EXTENSIONS = {
    ".aac",
    ".avi",
    ".db",
    ".flac",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".sqlite",
    ".sqlite3",
    ".wav",
    ".webm",
}
SECRET_EXTENSIONS = {".key", ".kdbx", ".p12", ".pem", ".pfx", ".jks"}
SECRET_EXACT_NAMES = {
    ".env",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
    "service-account.json",
    "token.json",
}
SECRET_NAME_RE = re.compile(r"(?:credential|private[-_]?key|secret|token)", re.I)
JS_IMPORT_RE = re.compile(
    r"(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|\bimport\s*)"
    r"[\"']([^\"']+)[\"']"
)


def _normalize(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def _run_git(
    root: Path,
    *args: str,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _decode_paths(payload: bytes) -> list[str]:
    return [
        _normalize(item.decode("utf-8", errors="surrogateescape"))
        for item in payload.split(b"\0")
        if item
    ]


def _head_blobs(root: Path) -> dict[str, str]:
    exists = _run_git(root, "rev-parse", "--verify", "HEAD", check=False)
    if exists.returncode != 0:
        return {}
    result: dict[str, str] = {}
    payload = _run_git(root, "ls-tree", "-r", "-z", "HEAD").stdout
    for record in payload.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        _mode, object_type, oid = metadata.decode("ascii").split()
        if object_type == "blob":
            result[_normalize(raw_path.decode("utf-8", errors="surrogateescape"))] = oid
    return result


def _index_blobs(root: Path) -> tuple[dict[str, str], list[str]]:
    result: dict[str, str] = {}
    conflicts: set[str] = set()
    payload = _run_git(root, "ls-files", "--stage", "-z").stdout
    for record in payload.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        _mode, oid, stage = metadata.decode("ascii").split()
        path = _normalize(raw_path.decode("utf-8", errors="surrogateescape"))
        if stage == "0":
            result[path] = oid
        else:
            conflicts.add(path)
    return result, sorted(conflicts)


def _git_path_set(root: Path, *args: str) -> set[str]:
    return set(_decode_paths(_run_git(root, *args, "-z").stdout))


def _read_blobs(root: Path, oids: Iterable[str]) -> dict[str, bytes]:
    ordered = sorted(set(oids))
    if not ordered:
        return {}
    process = subprocess.Popen(
        ["git", "-C", str(root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(
        input=("\n".join(ordered) + "\n").encode("ascii")
    )
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace"))
    stream = io.BytesIO(stdout)
    result: dict[str, bytes] = {}
    for requested_oid in ordered:
        header = stream.readline().decode("ascii", errors="replace").strip()
        parts = header.split()
        if len(parts) != 3 or parts[1] != "blob":
            raise RuntimeError(f"Cannot read Git blob {requested_oid}: {header}")
        oid, _kind, raw_size = parts
        content = stream.read(int(raw_size))
        if stream.read(1) != b"\n":
            raise RuntimeError(f"Malformed git cat-file response for {requested_oid}")
        result[oid] = content
    return result


def _workspace_bytes(root: Path, path: str) -> bytes | None:
    target = root / Path(*PurePosixPath(path).parts)
    try:
        return target.read_bytes() if target.is_file() else None
    except OSError:
        return None


def _sha256(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _tree_fingerprint(items: Iterable[tuple[str, str]]) -> str:
    payload = json.dumps(sorted(items), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def classify_path(path: str) -> tuple[str, str, str]:
    """Return class, suggested disposition, and rule rationale."""

    normalized = _normalize(path)
    lowered = normalized.casefold()
    name = PurePosixPath(lowered).name
    suffix = PurePosixPath(lowered).suffix

    if lowered == ".env" or lowered.startswith(".env.") and lowered != ".env.example":
        return "SENSITIVE_LOCAL", "ignore_and_review_retention", "environment secret file"
    if (
        lowered in SENSITIVE_ROOT_FILES
        or lowered.startswith(SENSITIVE_PREFIXES)
        or suffix in SENSITIVE_EXTENSIONS
    ):
        return "SENSITIVE_LOCAL", "ignore_and_review_retention", "case data or runtime output"
    if lowered.startswith(GENERATED_PREFIXES) or "/__pycache__/" in lowered:
        return "GENERATED_LOCAL", "ignore", "rebuildable cache or generated output"
    if lowered in {"node_modules", "venv"} or lowered.startswith(("node_modules/", "venv/")):
        return "GENERATED_LOCAL", "ignore", "installed dependency tree"
    if any(marker in name for marker in ("_backup", ".backup", "_old")):
        return "LEGACY_REMOVE", "review_then_remove", "backup or old-name convention"
    if normalized in {
        "frontend/src/App_v2.tsx",
        "src/web_interface/app.py",
        "src/worker/tasks.py",
    }:
        return "LEGACY_COMPAT", "document_owner_tests_and_sunset", "known compatibility surface"
    if lowered.startswith("src/"):
        return "RUNTIME_REQUIRED", "track_and_test", "backend runtime source"
    if lowered.startswith("frontend/src/"):
        return "RUNTIME_REQUIRED", "track_and_test", "frontend runtime source"
    if lowered.startswith(("tests/", "frontend/tests/")):
        return "TEST_REQUIRED", "track_and_map_to_gate", "automated test surface"
    if lowered.startswith("scripts/"):
        script_name = PurePosixPath(lowered).name
        if script_name == "audit_release_inventory.py" or script_name.startswith(
            ("check_", "install_", "migrate_", "preflight_", "probe_", "reconcile_", "start_", "verify_")
        ):
            return "STARTUP_REQUIRED", "track_and_smoke", "release/startup harness"
        if script_name.startswith(("assert_", "audit_", "benchmark_", "e2e_", "evaluate_", "replay_")):
            return "TEST_REQUIRED", "track_and_map_to_gate", "evaluation or replay harness"
        return "RESEARCH_ONLY", "review_and_namespace", "non-canonical utility script"
    if lowered.startswith("config/"):
        return "CONFIG_MANIFEST", "track_without_secrets", "runtime/configuration manifest"
    if normalized in {"README.md", "docs/NEW_MACHINE_SETUP.md"} or lowered.startswith("docs/runbooks/"):
        return "DOC_REQUIRED", "track_after_command_validation", "canonical documentation"
    if lowered.startswith(("docs/evals/runs/", "docs/reviews/artifacts/")):
        return "EVIDENCE_CURATED", "privacy_provenance_size_review", "evaluation evidence"
    if lowered.startswith(("docs/plans/", "docs/research/", "docs/reviews/")):
        return "RESEARCH_ONLY", "review_and_namespace", "research, plan, or review document"
    if normalized == ".env.example" or name in {
        ".eslintrc.cjs",
        "alembic.ini",
        "docker-compose.yml",
        "docker-compose.test.yml",
        "package-lock.json",
        "package.json",
        "requirements.txt",
        "requirements-torch-cu121.txt",
        "setup.py",
    } or name.startswith(("dockerfile", "requirements")):
        return "CONFIG_MANIFEST", "track_without_secrets", "build or dependency configuration"
    if suffix in {".bat", ".ps1"}:
        return "STARTUP_REQUIRED", "track_and_smoke", "launcher or operations script"
    if suffix in {".md", ".txt"}:
        return "RESEARCH_ONLY", "review_and_namespace", "non-canonical document"
    return "UNCLASSIFIED", "manual_review", "no classification rule matched"


def _module_candidates(module: str) -> tuple[str, str]:
    base = module.replace(".", "/")
    return f"{base}.py", f"{base}/__init__.py"


def _module_path(module: str, paths: set[str]) -> str | None:
    return next((candidate for candidate in _module_candidates(module) if candidate in paths), None)


def _python_package(path: str) -> list[str]:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    else:
        parts = parts[:-1]
    return parts


def _resolve_from_module(path: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package = _python_package(path)
    ascend = node.level - 1
    if ascend > len(package):
        return None
    base = package[: len(package) - ascend]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _python_requirements(
    path: str,
    content: bytes,
    workspace_paths: set[str],
) -> tuple[set[str], str | None]:
    try:
        tree = ast.parse(content.decode("utf-8-sig"), filename=path)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return set(), f"{type(exc).__name__}: {exc}"

    requirements: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _module_path(alias.name, workspace_paths):
                    requirements.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from_module(path, node)
            if not base:
                continue
            if _module_path(base, workspace_paths):
                requirements.add(base)
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{base}.{alias.name}" if base else alias.name
                if _module_path(candidate, workspace_paths):
                    requirements.add(candidate)
    return requirements, None


def _frontend_candidate(source_path: str, reference: str, paths: set[str]) -> str | None:
    if not reference.startswith("."):
        return None
    reference = reference.split("?", 1)[0].split("#", 1)[0]
    parent = str(PurePosixPath(source_path).parent)
    base = posixpath.normpath(posixpath.join(parent, reference))
    candidates = [base]
    if not PurePosixPath(base).suffix:
        candidates.extend(f"{base}{suffix}" for suffix in FRONTEND_RESOLUTION_SUFFIXES)
        candidates.extend(
            f"{base}/index{suffix}" for suffix in FRONTEND_RESOLUTION_SUFFIXES
        )
    return next((candidate for candidate in candidates if candidate in paths), None)


def _is_analyzable_source(path: str) -> bool:
    normalized = _normalize(path)
    lowered = normalized.casefold()
    if lowered.endswith(PYTHON_SUFFIX):
        return lowered.startswith(("src/", "scripts/", "tests/"))
    if lowered.endswith(".d.ts"):
        return False
    return lowered.startswith(("frontend/src/", "frontend/tests/")) and lowered.endswith(
        FRONTEND_SOURCE_SUFFIXES
    )


def _frontend_requirements(
    path: str,
    content: bytes,
    workspace_paths: set[str],
) -> tuple[set[str], str | None]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return set(), f"UnicodeDecodeError: {exc}"
    requirements = {
        candidate
        for reference in JS_IMPORT_RE.findall(text)
        if (candidate := _frontend_candidate(path, reference, workspace_paths))
    }
    return requirements, None


def _dependency_report(
    *,
    source_name: str,
    source_paths: set[str],
    source_content: dict[str, bytes],
    target_paths: set[str],
    workspace_paths: set[str],
    index_paths: set[str],
) -> dict:
    missing: list[dict] = []
    parse_errors: list[dict] = []
    dependency_count = 0
    for path in sorted(source_paths):
        if not _is_analyzable_source(path):
            continue
        content = source_content.get(path)
        if content is None:
            continue
        if path.endswith(PYTHON_SUFFIX):
            modules, error = _python_requirements(path, content, workspace_paths)
            targets = [
                (_module_path(module, workspace_paths), module) for module in sorted(modules)
            ]
        else:
            modules, error = _frontend_requirements(path, content, workspace_paths)
            targets = [(module, module) for module in sorted(modules)]
        if error:
            parse_errors.append({"source": path, "error": error})
            continue
        for target, reference in targets:
            if not target:
                continue
            dependency_count += 1
            if target not in target_paths:
                missing.append(
                    {
                        "source": path,
                        "reference": reference,
                        "workspace_target": target,
                        "target_tracked_in_index": target in index_paths,
                    }
                )
    return {
        "snapshot": source_name,
        "source_file_count": len(source_paths),
        "local_dependency_count": dependency_count,
        "missing_local_dependencies": missing,
        "parse_errors": parse_errors,
        "closed": not missing and not parse_errors,
    }


def _secret_filename_risk(path: str) -> tuple[str, str] | None:
    lowered = _normalize(path).casefold()
    name = PurePosixPath(lowered).name
    suffix = PurePosixPath(name).suffix
    if name in SECRET_EXACT_NAMES or suffix in SECRET_EXTENSIONS:
        return "critical", "credential or private-key filename"
    if SECRET_NAME_RE.search(name):
        return "review", "filename contains a credential-related marker"
    return None


def _walk_secret_candidates(root: Path) -> set[str]:
    candidates: set[str] = set()
    prune = {
        ".git",
        ".mypy_cache",
        ".planning",
        ".playwright-cli",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "models",
        "node_modules",
        "venv",
    }
    for directory, dirs, files in os.walk(root):
        base = Path(directory)
        kept_dirs = []
        for item in dirs:
            if item in prune or item == "__pycache__":
                continue
            candidate = _normalize(str((base / item / ".scan").relative_to(root)))
            classification = classify_path(candidate)[0]
            if classification in {"GENERATED_LOCAL", "SENSITIVE_LOCAL"}:
                continue
            kept_dirs.append(item)
        dirs[:] = kept_dirs
        for filename in files:
            path = _normalize(str((base / filename).relative_to(root)))
            if _secret_filename_risk(path):
                candidates.add(path)
    return candidates


def _ignored_paths(root: Path, paths: Iterable[str]) -> set[str]:
    ordered = sorted(set(paths))
    if not ordered:
        return set()
    payload = b"\0".join(item.encode("utf-8") for item in ordered) + b"\0"
    completed = _run_git(
        root,
        "check-ignore",
        "--stdin",
        "-z",
        input_bytes=payload,
        check=False,
    )
    return set(_decode_paths(completed.stdout))


def _group_paths(
    paths: Iterable[str],
    sample_limit: int = 10,
    *,
    redact_samples: bool = False,
) -> list[dict]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for path in sorted(paths):
        parts = PurePosixPath(path).parts
        if not parts:
            key = "."
        elif parts[0] == "frontend" and len(parts) > 1:
            key = "/".join(parts[:2])
        else:
            key = parts[0]
        grouped[key].append(path)
    return [
        {
            # A sensitive root-level filename is itself the secret. Keep only a
            # stable aggregate label when samples are redacted.
            "prefix": "[REDACTED]" if redact_samples else key,
            "count": len(values),
            "samples": [] if redact_samples else values[:sample_limit],
            "samples_redacted": redact_samples,
        }
        for key, values in sorted(grouped.items())
    ]


def build_report(repo_root: Path) -> dict:
    root = repo_root.resolve()
    toplevel = _run_git(root, "rev-parse", "--show-toplevel").stdout.decode().strip()
    if Path(toplevel).resolve() != root:
        root = Path(toplevel).resolve()

    head_blobs = _head_blobs(root)
    index_blobs, index_conflicts = _index_blobs(root)
    head_paths = set(head_blobs)
    index_paths = set(index_blobs)
    untracked_paths = _git_path_set(root, "ls-files", "--others", "--exclude-standard")
    staged_paths = _git_path_set(root, "diff", "--cached", "--name-only")
    unstaged_paths = _git_path_set(root, "diff", "--name-only")
    partial_staged = sorted(staged_paths & unstaged_paths)
    existing_index_paths = {
        path
        for path in index_paths
        if (root / Path(*PurePosixPath(path).parts)).is_file()
    }
    workspace_paths = existing_index_paths | untracked_paths

    source_head_paths = {path for path in head_paths if _is_analyzable_source(path)}
    source_index_paths = {path for path in index_paths if _is_analyzable_source(path)}
    source_workspace_tracked = {
        path for path in existing_index_paths if _is_analyzable_source(path)
    }
    required_oids = {
        head_blobs[path] for path in source_head_paths
    } | {index_blobs[path] for path in source_index_paths}
    blob_content = _read_blobs(root, required_oids)
    head_content = {path: blob_content[head_blobs[path]] for path in source_head_paths}
    index_content = {path: blob_content[index_blobs[path]] for path in source_index_paths}
    workspace_content = {
        path: content
        for path in source_workspace_tracked
        if (content := _workspace_bytes(root, path)) is not None
    }

    dependencies = {
        "head": _dependency_report(
            source_name="HEAD",
            source_paths=source_head_paths,
            source_content=head_content,
            target_paths=head_paths,
            workspace_paths=workspace_paths | head_paths,
            index_paths=index_paths,
        ),
        "index": _dependency_report(
            source_name="index",
            source_paths=source_index_paths,
            source_content=index_content,
            target_paths=index_paths,
            workspace_paths=workspace_paths | index_paths,
            index_paths=index_paths,
        ),
        "workspace_tracked": _dependency_report(
            source_name="workspace_tracked",
            source_paths=source_workspace_tracked,
            source_content=workspace_content,
            target_paths=index_paths,
            workspace_paths=workspace_paths,
            index_paths=index_paths,
        ),
    }

    classifications = {path: classify_path(path) for path in untracked_paths}
    tracked_sensitive = sorted(
        path
        for path in head_paths | index_paths
        if classify_path(path)[0] == "SENSITIVE_LOCAL"
    )
    tracked_generated = sorted(
        path
        for path in head_paths | index_paths
        if classify_path(path)[0] == "GENERATED_LOCAL"
    )
    untracked_generated = {
        path for path, value in classifications.items() if value[0] == "GENERATED_LOCAL"
    }
    untracked_sensitive = {
        path for path, value in classifications.items() if value[0] == "SENSITIVE_LOCAL"
    }
    untracked_release_relevant = (
        untracked_paths - untracked_generated - untracked_sensitive
    )

    secret_candidates = _walk_secret_candidates(root)
    ignored_secret_candidates = _ignored_paths(root, secret_candidates)
    secret_filename_risks = []
    secret_filename_risk_counts: Counter[str] = Counter()
    redacted_secret_filename_risk_count = 0
    for path in sorted(secret_candidates):
        risk = _secret_filename_risk(path)
        if not risk:
            continue
        classification = classify_path(path)[0]
        secret_filename_risk_counts[risk[0]] += 1
        if path not in index_paths and classification in {
            "GENERATED_LOCAL",
            "SENSITIVE_LOCAL",
        }:
            redacted_secret_filename_risk_count += 1
            continue
        secret_filename_risks.append(
            {
                "path": path,
                "severity": risk[0],
                "reason": risk[1],
                "classification": classification,
                "tracked_in_index": path in index_paths,
                "ignored": path in ignored_secret_candidates,
                "content_inspected": False,
            }
        )

    staged_prohibited = []
    for path in sorted(staged_paths):
        classification, disposition, rationale = classify_path(path)
        if classification in {"GENERATED_LOCAL", "SENSITIVE_LOCAL"}:
            staged_prohibited.append(
                {
                    "path": path,
                    "classification": classification,
                    "suggested_disposition": disposition,
                    "rationale": rationale,
                }
            )

    manifest_paths = (
        head_paths
        | index_paths
        | untracked_release_relevant
        | staged_paths
        | unstaged_paths
        | secret_candidates
    ) - untracked_generated - untracked_sensitive
    entries = []
    for path in sorted(manifest_paths):
        classification, disposition, rationale = classify_path(path)
        if classification == "SENSITIVE_LOCAL":
            continue
        workspace_content_bytes = None
        workspace_exists = path in workspace_paths or (
            root / Path(*PurePosixPath(path).parts)
        ).is_file()
        if workspace_exists and classification not in {"SENSITIVE_LOCAL", "GENERATED_LOCAL"}:
            workspace_content_bytes = _workspace_bytes(root, path)
        entries.append(
            {
                "path": path,
                "classification": classification,
                "classification_rationale": rationale,
                "suggested_disposition": disposition,
                "in_head": path in head_paths,
                "head_blob": head_blobs.get(path),
                "in_index": path in index_paths,
                "index_blob": index_blobs.get(path),
                "in_workspace": workspace_exists,
                "workspace_sha256": _sha256(workspace_content_bytes),
                "content_hash_redacted": classification == "SENSITIVE_LOCAL",
                "staged_change": path in staged_paths,
                "unstaged_change": path in unstaged_paths,
                "partial_staged": path in partial_staged,
                "untracked": path in untracked_paths,
                "review_required": (
                    path in untracked_paths
                    or classification
                    in {
                        "EVIDENCE_CURATED",
                        "LEGACY_COMPAT",
                        "LEGACY_REMOVE",
                        "RESEARCH_ONLY",
                        "SENSITIVE_LOCAL",
                        "UNCLASSIFIED",
                    }
                ),
            }
        )

    blockers = []
    if tracked_sensitive:
        blockers.append(
            {
                "code": "TRACKED_SENSITIVE_PATH",
                "count": len(tracked_sensitive),
                "detail": "Sensitive local data is already present in HEAD or the Git index.",
            }
        )
    workspace_missing = dependencies["workspace_tracked"]["missing_local_dependencies"]
    if workspace_missing:
        blockers.append(
            {
                "code": "TRACKED_IMPORTS_UNTRACKED",
                "count": len(workspace_missing),
                "detail": "Tracked workspace source depends on files absent from the Git index.",
            }
        )
    if not dependencies["index"]["closed"]:
        blockers.append(
            {
                "code": "INDEX_IMPORT_CLOSURE_FAILED",
                "count": len(dependencies["index"]["missing_local_dependencies"])
                + len(dependencies["index"]["parse_errors"]),
                "detail": "The staged/index source tree is not locally closed or parseable.",
            }
        )
    if partial_staged:
        blockers.append(
            {
                "code": "PARTIAL_STAGING_PRESENT",
                "count": len(partial_staged),
                "detail": "Paths differ in both index and workspace; tested content may not equal staged content.",
            }
        )
    if untracked_release_relevant:
        blockers.append(
            {
                "code": "UNTRACKED_RELEASE_RELEVANT",
                "count": len(untracked_release_relevant),
                "detail": "Release-relevant files require explicit manifest disposition.",
            }
        )
    if staged_prohibited:
        blockers.append(
            {
                "code": "STAGED_PROHIBITED_CLASS",
                "count": len(staged_prohibited),
                "detail": "Generated or sensitive local files are staged.",
            }
        )
    tracked_critical_secret_names = [
        item
        for item in secret_filename_risks
        if item["tracked_in_index"] and item["severity"] == "critical"
    ]
    if tracked_critical_secret_names:
        blockers.append(
            {
                "code": "TRACKED_SECRET_FILENAME_RISK",
                "count": len(tracked_critical_secret_names),
                "detail": "Tracked filenames resemble credential or private-key material; content was not read.",
            }
        )
    if index_conflicts:
        blockers.append(
            {
                "code": "INDEX_CONFLICTS",
                "count": len(index_conflicts),
                "detail": "The Git index contains unresolved merge stages.",
            }
        )

    branch = _run_git(root, "branch", "--show-current", check=False).stdout.decode().strip()
    head_revision = _run_git(root, "rev-parse", "HEAD", check=False).stdout.decode().strip() or None
    class_counts = Counter(entry["classification"] for entry in entries)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "read_only_git_inventory",
        "repository": {
            "root": str(root),
            "branch": branch,
            "head_revision": head_revision,
        },
        "verdict": "BLOCKED" if blockers else "PASS",
        "blockers": blockers,
        "snapshots": {
            "head": {
                "file_count": len(head_paths),
                "tree_fingerprint_sha256": _tree_fingerprint(head_blobs.items()),
            },
            "index": {
                "file_count": len(index_paths),
                "tree_fingerprint_sha256": _tree_fingerprint(index_blobs.items()),
                "conflicts": index_conflicts,
            },
            "workspace": {
                "tracked_existing_count": len(existing_index_paths),
                "untracked_count": len(untracked_paths),
                "staged_change_count": len(staged_paths),
                "unstaged_change_count": len(unstaged_paths),
                "partial_staged_count": len(partial_staged),
            },
        },
        "dependencies": dependencies,
        "partial_staged_paths": partial_staged,
        "staged_prohibited_paths": staged_prohibited,
        "tracked_prohibited": {
            "sensitive_count": len(tracked_sensitive),
            "sensitive_groups": _group_paths(
                tracked_sensitive,
                redact_samples=True,
            ),
            "generated_count": len(tracked_generated),
            "generated_groups": _group_paths(
                tracked_generated,
                redact_samples=True,
            ),
        },
        "untracked": {
            "release_relevant_count": len(untracked_release_relevant),
            "release_relevant_paths": sorted(untracked_release_relevant),
            "generated_count": len(untracked_generated),
            "generated_groups": _group_paths(
                untracked_generated,
                redact_samples=True,
            ),
            "sensitive_count": len(untracked_sensitive),
            "sensitive_groups": _group_paths(
                untracked_sensitive,
                redact_samples=True,
            ),
        },
        "secret_filename_risk_summary": {
            "total_count": sum(secret_filename_risk_counts.values()),
            "severity_counts": dict(sorted(secret_filename_risk_counts.items())),
            "redacted_path_count": redacted_secret_filename_risk_count,
        },
        "secret_filename_risks": secret_filename_risks,
        "classification_counts": dict(sorted(class_counts.items())),
        "manifest_entries": entries,
        "limitations": [
            "The harness never reads .env or other classified sensitive file content.",
            "Untracked generated and sensitive filenames are aggregated and redacted from the artifact.",
            "Filename secret checks are heuristic and require human review.",
            "Import closure covers Python local modules and relative frontend imports; runtime-generated imports require separate smoke tests.",
            "PASS proves Git/source inventory closure only, not dependency installation, model quality, migration rehearsal, or end-to-end runtime health.",
        ],
    }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, help="Optional JSON artifact path")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Return zero even when release blockers are detected",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = build_report(args.repo_root)
    serialized = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    if args.output:
        output = args.output
        if not output.is_absolute():
            output = args.repo_root.resolve() / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(
        json.dumps(
            {
                "schema_version": report["schema_version"],
                "verdict": report["verdict"],
                "blockers": report["blockers"],
                "output": str(args.output) if args.output else None,
            },
            ensure_ascii=True,
        )
    )
    return 0 if args.no_fail or report["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
