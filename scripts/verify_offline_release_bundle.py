"""Verify a benchmark-candidate release bundle without network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path("config/release/benchmark-candidate.bundle.json")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.model_runtime import (  # noqa: E402
    OfflineBundleValidationError,
    load_offline_bundle,
    verify_offline_bundle,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify repository-local offline bundle closure."
    )
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def run(repo_root: Path, manifest_path: Path) -> tuple[dict, int]:
    root = repo_root.resolve()
    path = manifest_path if manifest_path.is_absolute() else root / manifest_path
    try:
        report = verify_offline_bundle(load_offline_bundle(path), root)
        return report, 0 if report["valid"] else 1
    except OfflineBundleValidationError as exc:
        return {
            "protocol_version": "offline-bundle-verification-v1",
            "offline": True,
            "status": "INVALID_MANIFEST",
            "valid": False,
            "release_ready": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }, 2


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report, exit_code = run(args.repo_root, args.manifest)
    rendered = json.dumps(report, ensure_ascii=True, indent=2)
    if args.output:
        output = args.output
        if not output.is_absolute():
            output = args.repo_root.resolve() / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    if args.json:
        print(rendered)
    else:
        print(
            f"{report.get('status', 'BLOCKED')}: "
            f"bundle={report.get('bundle_id', 'unknown')}"
        )
        for role in report.get("missing_roles") or []:
            print(f"  MISSING_ROLE: {role}")
        if report.get("error"):
            print(f"  {report['error']['type']}: {report['error']['message']}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
