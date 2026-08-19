"""Verify the pinned repository-local llama.cpp runtime without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path(
    "config/runtimes/llama.cpp-b10331-windows-cuda-12.4.runtime.json"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RuntimeManifestError(ValueError):
    pass


def _inside(root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise RuntimeManifestError("runtime path must be a non-empty string")
    raw = relative_path.replace("\\", "/")
    candidate_path = Path(*raw.split("/"))
    if candidate_path.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate_path.parts
    ):
        raise RuntimeManifestError(f"unsafe relative path: {relative_path}")
    candidate = (root / candidate_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeManifestError(f"path escapes repository: {relative_path}") from exc
    return candidate


def load_runtime_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeManifestError(f"cannot read runtime manifest: {exc}") from exc
    if payload.get("schema_version") != 1:
        raise RuntimeManifestError("schema_version must be 1")
    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        raise RuntimeManifestError("runtime must be an object")
    required = {
        "id",
        "version",
        "commit",
        "relative_path",
        "platform",
        "architecture",
        "accelerator",
        "source",
        "license",
        "probe",
        "files",
    }
    missing = sorted(required - set(runtime))
    if missing:
        raise RuntimeManifestError(f"runtime missing fields: {', '.join(missing)}")
    if not isinstance(runtime["files"], list) or not runtime["files"]:
        raise RuntimeManifestError("runtime.files must be a non-empty array")
    seen = set()
    for index, row in enumerate(runtime["files"]):
        if not isinstance(row, dict) or set(row) != {"path", "size_bytes", "sha256"}:
            raise RuntimeManifestError(f"runtime.files[{index}] has invalid fields")
        if row["path"] in seen:
            raise RuntimeManifestError(f"duplicate runtime file: {row['path']}")
        seen.add(row["path"])
        if not isinstance(row["size_bytes"], int) or row["size_bytes"] < 0:
            raise RuntimeManifestError(f"runtime.files[{index}].size_bytes is invalid")
        if not isinstance(row["sha256"], str) or not SHA256_RE.fullmatch(
            row["sha256"]
        ):
            raise RuntimeManifestError(f"runtime.files[{index}].sha256 is invalid")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_runtime(
    manifest: dict[str, Any],
    repo_root: Path,
    *,
    probe: bool = False,
) -> dict[str, Any]:
    runtime = manifest["runtime"]
    runtime_root = _inside(repo_root, runtime["relative_path"])
    issues = []
    verified_files = 0
    verified_size = 0
    for row in runtime["files"]:
        try:
            path = _inside(runtime_root, row["path"])
        except RuntimeManifestError as exc:
            issues.append({"code": "unsafe_path", "path": row["path"], "message": str(exc)})
            continue
        if not path.is_file():
            issues.append({"code": "missing_file", "path": row["path"]})
            continue
        size = path.stat().st_size
        verified_size += size
        if size != row["size_bytes"]:
            issues.append(
                {
                    "code": "size_mismatch",
                    "path": row["path"],
                    "expected": row["size_bytes"],
                    "observed": size,
                }
            )
            continue
        actual_hash = _sha256(path)
        if actual_hash != row["sha256"]:
            issues.append(
                {
                    "code": "checksum_mismatch",
                    "path": row["path"],
                    "expected": row["sha256"],
                    "observed": actual_hash,
                }
            )
            continue
        verified_files += 1

    probe_report = None
    if probe and not issues:
        probe_spec = runtime["probe"]
        executable = _inside(runtime_root, probe_spec["executable"])
        version = subprocess.run(
            [str(executable), "--version"],
            cwd=executable.parent,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        devices = subprocess.run(
            [str(executable), "--list-devices"],
            cwd=executable.parent,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        version_output = f"{version.stdout}\n{version.stderr}"
        device_output = f"{devices.stdout}\n{devices.stderr}"
        version_match = probe_spec["version_contains"] in version_output
        device_match = probe_spec["device_contains"] in device_output
        probe_report = {
            "version_match": version_match,
            "device_match": device_match,
            "version_output": version_output.strip(),
            "device_output": device_output.strip(),
        }
        if not version_match:
            issues.append({"code": "version_probe_mismatch"})
        if not device_match:
            issues.append({"code": "device_probe_mismatch"})

    return {
        "offline": True,
        "runtime_id": runtime["id"],
        "version": runtime["version"],
        "commit": runtime["commit"],
        "runtime_root": str(runtime_root),
        "verified_file_count": verified_files,
        "verified_size_bytes": verified_size,
        "probe": probe_report,
        "issues": issues,
        "valid": not issues,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest_path = args.manifest
        if not manifest_path.is_absolute():
            manifest_path = args.repo_root / manifest_path
        report = verify_runtime(
            load_runtime_manifest(manifest_path),
            args.repo_root.resolve(),
            probe=args.probe,
        )
    except (RuntimeManifestError, OSError, subprocess.SubprocessError) as exc:
        report = {
            "valid": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{'PASS' if report.get('valid') else 'FAIL'}: llama.cpp runtime")
        for issue in report.get("issues") or []:
            print(f"  {issue['code']}: {issue.get('path', '')}")
    return 0 if report.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
