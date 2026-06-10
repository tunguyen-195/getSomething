from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.model_artifacts import (  # noqa: E402
    ModelArtifactError,
    artifacts_by_id,
    load_manifest,
    selected_artifact_ids,
    verify_artifact,
)


def _display_path(root: Path, value: Path | None) -> str:
    if value is None:
        return ""
    try:
        return value.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Strictly verify model artifacts for a runtime profile.")
    parser.add_argument("--profile", default="lite_rtx2050", help="Profile key from docs/model_artifacts.required.json")
    parser.add_argument("--include-optional", action="store_true")
    parser.add_argument("--manifest", default="docs/model_artifacts.required.json")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root, used by tests and custom installs.")
    parser.add_argument(
        "--write-provenance",
        action="store_true",
        help="Write portable PROVENANCE.json only after strict verification succeeds.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    try:
        manifest = load_manifest(root, args.manifest)
        selected_ids = selected_artifact_ids(manifest, args.profile, args.include_optional)
    except ModelArtifactError as exc:
        print(f"[ERROR] {exc.reason_code}:{exc.guidance or args.profile}")
        return 2

    artifacts = artifacts_by_id(manifest)
    required_ids = set(manifest["profiles"][args.profile].get("required") or [])
    optional_ids = set(manifest["profiles"][args.profile].get("optional") or []) if args.include_optional else set()

    print(f"Model artifact verification: profile={args.profile}")
    print("Strict hash verification may take a moment for large model files.")

    failures = 0
    for artifact_id in selected_ids:
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            print(f"[FAIL] {artifact_id} - missing_manifest_entry")
            failures += int(artifact_id in required_ids)
            continue

        result = verify_artifact(artifact, root=root, write_provenance=args.write_provenance)
        is_required = artifact_id in required_ids
        marker = "OK" if result.ok else ("WARN" if artifact_id in optional_ids and not is_required else "FAIL")
        details = _display_path(root, result.resolved_path) if result.ok else "; ".join(result.errors)
        print(f"[{marker}] {artifact_id} - {details}")
        for warning in result.warnings:
            print(f"  warning={warning}")
        if not result.ok and is_required:
            failures += 1

    if failures:
        print("Missing or unverified required artifacts. See docs/MODEL_SETUP.md and docs/model_artifacts.required.json.")
        return 1
    print("[OK] required model artifacts are present and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
