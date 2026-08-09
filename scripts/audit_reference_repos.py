"""Create a repeatable static evidence bundle for repository reuse decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".cmd",
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".ps1",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
MODEL_SUFFIXES = {
    ".bin",
    ".gguf",
    ".onnx",
    ".pt",
    ".pth",
    ".safetensors",
    ".tflite",
}
MANIFEST_NAMES = {
    "docker-compose.yml",
    "docker-compose.yaml",
    "package-lock.json",
    "package.json",
    "poetry.lock",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
}
PATH_CATEGORIES = {
    "analysis": re.compile(r"analysis|investigat|knowledge|insight|visual", re.I),
    "asr": re.compile(r"asr|transcri|whisper|phoguard|sage", re.I),
    "diarization": re.compile(r"diari|speaker|vbx|resemblyzer|speechbrain", re.I),
    "evaluation": re.compile(
        r"(^|/)(test|tests|eval|evaluation|benchmark|research)(/|$)", re.I
    ),
    "forensics": re.compile(
        r"forensic|evidence|provenance|custody|audit|hash|sha256", re.I
    ),
    "offline_packaging": re.compile(
        r"docker|offline|model[_-]?sync|manifest|bundle|vendor", re.I
    ),
    "prompts": re.compile(r"prompt|schema|contract|template", re.I),
    "summary": re.compile(r"summar", re.I),
}
CONTENT_PROBES = {
    "external_api": re.compile(
        r"\b(openai|anthropic|gemini|ollama|vllm)\b|https?://", re.I
    ),
    "forensic_integrity": re.compile(
        r"sha[-_ ]?256|chain[-_ ]of[-_ ]custody|provenance|legal hold", re.I
    ),
    "local_only": re.compile(
        r"local_files_only|HF_HUB_OFFLINE|TRANSFORMERS_OFFLINE|NO_NETWORK", re.I
    ),
    "model_download": re.compile(
        r"snapshot_download|hf_hub_download|from_pretrained|wget|curl", re.I
    ),
    "prompt_contract": re.compile(
        r"system[_ -]?prompt|prompt[_ -]?version|json[_ -]?schema|structured[_ -]?output",
        re.I,
    ),
    "remote_code": re.compile(r"trust_remote_code\s*=\s*True", re.I),
}
SKIP_MODEL_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__"}
UNTRACKED_EXCLUDE_PARTS = {
    ".agent",
    ".cache",
    ".git",
    ".mypy_cache",
    ".playwright-cli",
    ".pytest_cache",
    ".vendor",
    "__pycache__",
    "data",
    "logs",
    "models",
    "node_modules",
    "output",
    "storage",
    "tmp",
    "uploads",
    "venv",
    "venv_wsl",
}


def run_git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def include_untracked(relative: str) -> bool:
    parts = {part.lower() for part in Path(relative).parts}
    if parts & UNTRACKED_EXCLUDE_PARTS:
        return False
    return not any(part.lower().startswith(".venv") for part in Path(relative).parts)


def git_file_inventory(root: Path) -> tuple[list[str], dict[str, int]]:
    tracked = run_git(root, "ls-files", "-z").split("\0")
    untracked = run_git(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    ).split("\0")
    tracked_paths = [path.replace("\\", "/") for path in tracked if path]
    untracked_paths = [path.replace("\\", "/") for path in untracked if path]
    selected_untracked = [path for path in untracked_paths if include_untracked(path)]
    files = sorted(set(tracked_paths + selected_untracked))
    return files, {
        "tracked": len(tracked_paths),
        "untracked_total": len(untracked_paths),
        "untracked_selected": len(selected_untracked),
    }


def is_text_candidate(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name.lower() in MANIFEST_NAMES


def read_text(path: Path, max_bytes: int = 2 * 1024 * 1024) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def find_root_licenses(root: Path) -> list[str]:
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_file()
        and re.match(r"^(license|licence|copying|notice)(\..*)?$", entry.name, re.I)
    )


def dependency_manifests(root: Path, files: Iterable[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in files:
        path = root / relative
        name = path.name.lower()
        if (
            name in MANIFEST_NAMES
            or re.match(r"requirements.*\.txt$", name)
            or name.startswith("dockerfile")
            or name.startswith("docker-compose")
        ):
            try:
                records.append(
                    {
                        "path": relative,
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
            except OSError:
                continue
    return records


def model_store_inventory(root: Path) -> dict[str, Any]:
    models_root = root / "models"
    if not models_root.exists():
        return {"present": False, "files": 0, "bytes": 0, "largest": []}

    records: list[tuple[int, str]] = []
    license_files: list[str] = []
    suffixes: Counter[str] = Counter()
    for current_root, dirs, names in os.walk(models_root):
        dirs[:] = [name for name in dirs if name.lower() not in SKIP_MODEL_DIRS]
        for name in names:
            path = Path(current_root) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            relative = path.relative_to(root).as_posix()
            records.append((size, relative))
            suffixes[path.suffix.lower() or "<none>"] += 1
            if re.match(
                r"^(license|licence|notice|copying)(\..*)?$",
                path.name,
                re.I,
            ):
                license_files.append(relative)

    model_weights = [
        record for record in records if Path(record[1]).suffix.lower() in MODEL_SUFFIXES
    ]
    return {
        "present": True,
        "files": len(records),
        "bytes": sum(size for size, _ in records),
        "weight_files": len(model_weights),
        "weight_bytes": sum(size for size, _ in model_weights),
        "suffix_counts": dict(sorted(suffixes.items())),
        "license_files": sorted(license_files),
        "largest": [
            {"path": path, "bytes": size}
            for size, path in sorted(records, reverse=True)[:25]
        ],
    }


def classify_files(
    root: Path, files: list[str]
) -> tuple[dict[str, Any], dict[str, str]]:
    category_paths: dict[str, list[str]] = {name: [] for name in PATH_CATEGORIES}
    probe_paths: dict[str, list[str]] = {name: [] for name in CONTENT_PROBES}
    hashes: dict[str, str] = {}
    suffixes: Counter[str] = Counter()

    for relative in files:
        path = root / relative
        if not path.is_file():
            continue
        suffixes[path.suffix.lower() or "<none>"] += 1
        for category, pattern in PATH_CATEGORIES.items():
            if pattern.search(relative):
                category_paths[category].append(relative)
        try:
            size = path.stat().st_size
            if size <= 16 * 1024 * 1024:
                hashes[relative] = sha256_file(path)
        except OSError:
            continue
        if not is_text_candidate(path):
            continue
        content = read_text(path)
        if content is None:
            continue
        for probe, pattern in CONTENT_PROBES.items():
            if pattern.search(content):
                probe_paths[probe].append(relative)

    summary = {
        "category_counts": {name: len(paths) for name, paths in category_paths.items()},
        "category_examples": {
            name: paths[:80] for name, paths in category_paths.items()
        },
        "content_probe_counts": {
            name: len(paths) for name, paths in probe_paths.items()
        },
        "content_probe_examples": {
            name: paths[:80] for name, paths in probe_paths.items()
        },
        "suffix_counts": dict(sorted(suffixes.items())),
    }
    return summary, hashes


def inspect_repo(label: str, root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    files, inventory_counts = git_file_inventory(root)
    classification, hashes = classify_files(root, files)
    status_lines = run_git(root, "status", "--short", "--branch").splitlines()
    remotes = run_git(root, "remote", "-v", check=False).splitlines()
    record = {
        "label": label,
        "root": str(root.resolve()),
        "git": {
            "head": run_git(root, "rev-parse", "HEAD"),
            "branch": run_git(root, "branch", "--show-current", check=False),
            "remotes": remotes,
            "status": status_lines,
            "dirty": len(status_lines) > 1,
        },
        "file_count": len(files),
        "inventory_counts": inventory_counts,
        "root_licenses": find_root_licenses(root),
        "dependency_manifests": dependency_manifests(root, files),
        "model_store": model_store_inventory(root),
        **classification,
    }
    return record, hashes


def compare_hashes(repo_hashes: dict[str, dict[str, str]]) -> dict[str, Any]:
    labels = list(repo_hashes)
    comparisons: list[dict[str, Any]] = []
    for left_index, left in enumerate(labels):
        for right in labels[left_index + 1 :]:
            left_hashes = repo_hashes[left]
            right_hashes = repo_hashes[right]
            shared = sorted(set(left_hashes) & set(right_hashes))
            exact = [path for path in shared if left_hashes[path] == right_hashes[path]]
            changed = [
                path for path in shared if left_hashes[path] != right_hashes[path]
            ]
            comparisons.append(
                {
                    "left": left,
                    "right": right,
                    "shared_paths": len(shared),
                    "exact_paths": len(exact),
                    "changed_paths": len(changed),
                    "exact_examples": exact[:100],
                    "changed_examples": changed[:100],
                }
            )
    return {"pairs": comparisons}


def source_evidence_record(
    label: str,
    root: Path,
    relative: str,
    recommendation_ids: list[str],
    purpose: str,
) -> dict[str, Any]:
    normalized = Path(relative).as_posix()
    relative_path = Path(normalized)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"unsafe source evidence path: {relative}")

    path = root / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"source evidence file not found: {label}={relative}")

    tracked = bool(
        run_git(root, "ls-files", "--error-unmatch", "--", normalized, check=False)
    )
    status = run_git(root, "status", "--short", "--", normalized, check=False)
    if not tracked:
        tracked_state = "untracked"
    elif status:
        tracked_state = "modified"
    else:
        tracked_state = "tracked_clean"

    head_blob = (
        run_git(root, "rev-parse", f"HEAD:{normalized}", check=False) or None
        if tracked
        else None
    )
    current_blob = run_git(root, "hash-object", "--", normalized, check=False) or None
    digest = sha256_file(path)
    return {
        "repo": label,
        "path": normalized,
        "recommendation_ids": sorted(set(recommendation_ids)),
        "purpose": purpose,
        "tracked_state": tracked_state,
        "git_status": status or None,
        "head_commit": run_git(root, "rev-parse", "HEAD"),
        "head_git_blob": head_blob,
        "worktree_git_blob": current_blob,
        "bytes": path.stat().st_size,
        "sha256": digest,
        "source_identity": f"sha256:{digest}",
    }


def build_source_evidence(
    spec_path: Path, repositories: dict[str, Path]
) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if spec.get("schema_version") != "reference-reuse-source-spec-v1":
        raise ValueError("unsupported source evidence specification")

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in spec.get("sources", []):
        try:
            label = item["repo"]
            root = repositories[label]
            records.append(
                source_evidence_record(
                    label,
                    root,
                    item["path"],
                    item["recommendation_ids"],
                    item["purpose"],
                )
            )
        except (KeyError, OSError, ValueError) as exc:
            errors.append(str(exc))

    return {
        "spec_path": str(spec_path.resolve()),
        "spec_sha256": sha256_file(spec_path),
        "records": records,
        "errors": errors,
    }


def parse_repo(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("repository must use LABEL=PATH")
    label, raw_path = value.split("=", 1)
    root = Path(raw_path).expanduser().resolve()
    if not label.strip() or not (root / ".git").exists():
        raise argparse.ArgumentTypeError(f"invalid git repository: {value}")
    return label.strip(), root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", required=True, type=parse_repo)
    parser.add_argument("--source-evidence-spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    repo_records: list[dict[str, Any]] = []
    repo_hashes: dict[str, dict[str, str]] = {}
    repo_roots = dict(args.repo)
    for label, root in args.repo:
        record, hashes = inspect_repo(label, root)
        repo_records.append(record)
        repo_hashes[label] = hashes

    payload = {
        "schema_version": "reference-repo-audit-v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repositories": repo_records,
        "comparison": compare_hashes(repo_hashes),
        "source_evidence": build_source_evidence(
            args.source_evidence_spec.resolve(), repo_roots
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
