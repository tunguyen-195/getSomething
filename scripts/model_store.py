"""Inspect and verify the repository-local model store without network access."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.model_runtime import ManifestValidationError, ModelStore  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory and verify pinned offline model artifacts."
    )
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--store-root", type=Path)
    parser.add_argument("--manifest-dir", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("inventory", "verify", "preflight"):
        command = subparsers.add_parser(name)
        command.add_argument("--model", action="append", default=[])
        command.add_argument("--task", action="append", default=[])
        command.add_argument("--profile", action="append", default=[])
        command.add_argument("--json", action="store_true")
    return parser


def _store(args: argparse.Namespace) -> ModelStore:
    repo_root = args.repo_root.resolve()
    return ModelStore(
        store_root=(args.store_root or repo_root / "models"),
        manifest_dir=(args.manifest_dir or repo_root / "config" / "models"),
    )


def _selected(store: ModelStore, args: argparse.Namespace):
    manifests = store.load_manifests()
    return store.select(
        manifests,
        model_ids=args.model,
        tasks=args.task,
        profiles=args.profile,
    )


def _inventory(store: ModelStore, args: argparse.Namespace) -> int:
    records = store.inventory(_selected(store, args))
    if args.json:
        print(json.dumps([asdict(record) for record in records], indent=2))
        return 0
    if not records:
        print("No deployed model manifests matched the selection.")
        return 0
    for record in records:
        quantization = record.quantization or "none"
        print(
            f"{record.model_id} {record.version} {record.status} "
            f"backend={record.backend}/{record.format}/{quantization} "
            f"size={record.observed_size_bytes}/{record.expected_size_bytes} "
            f"path={record.relative_path}"
        )
    return 0


def _verification(store: ModelStore, args: argparse.Namespace) -> int:
    manifests = _selected(store, args)
    report = store.preflight(manifests)
    if args.json:
        payload = {
            "offline": True,
            "valid": report.valid,
            "manifests_found": report.manifests_found,
            "results": [
                {
                    **asdict(result),
                    "model_path": str(result.model_path),
                    "valid": result.valid,
                    "status": result.status,
                }
                for result in report.results
            ],
        }
        print(json.dumps(payload, indent=2))
    elif not report.results:
        print("FAIL: no deployed model manifests matched the selection.")
    else:
        for result in report.results:
            print(
                f"{'PASS' if result.valid else 'FAIL'}: {result.model_id} "
                f"{result.verified_size_bytes}/{result.expected_size_bytes} bytes"
            )
            for issue in result.issues:
                print(
                    f"  {issue.severity.upper()} {issue.code} "
                    f"{issue.path}: {issue.message}"
                )
    return 0 if report.valid else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        store = _store(args)
        if args.command == "inventory":
            return _inventory(store, args)
        return _verification(store, args)
    except ManifestValidationError as exc:
        print(f"Manifest error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
