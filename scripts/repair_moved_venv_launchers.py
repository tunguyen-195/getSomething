"""Repair absolute launcher paths after moving a Windows virtual environment."""

from __future__ import annotations

import argparse
import json
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from pip._vendor.distlib.scripts import ScriptMaker


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate console launchers and replace stale absolute paths in "
            "a copied Windows virtual environment. Preview is the default."
        )
    )
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--old-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _files_containing(scripts_dir: Path, needle: bytes) -> list[Path]:
    return sorted(
        path
        for path in scripts_dir.iterdir()
        if path.is_file() and needle in path.read_bytes()
    )


def _regenerate_console_launchers(scripts_dir: Path) -> list[str]:
    maker = ScriptMaker(None, str(scripts_dir))
    maker.clobber = True
    maker.variants = {""}
    maker.set_mode = True

    generated: list[str] = []
    entry_names: set[str] = set()
    for distribution in metadata.distributions():
        for entry_point in distribution.entry_points:
            if entry_point.group != "console_scripts":
                continue
            entry_names.add(entry_point.name)
            specification = f"{entry_point.name} = {entry_point.value}"
            generated.extend(maker.make(specification))

    python_versioned_pip = f"pip{sys.version_info.major}.{sys.version_info.minor}"
    if python_versioned_pip not in entry_names:
        generated.extend(
            maker.make(f"{python_versioned_pip} = pip._internal.cli.main:main")
        )
    return sorted(Path(path).name for path in generated)


def _replace_text_paths(paths: list[Path], old_root: str, new_root: str) -> list[str]:
    changed: list[str] = []
    for path in paths:
        if path.suffix.lower() == ".exe":
            continue
        content = path.read_text(encoding="utf-8")
        updated = content.replace(old_root, new_root)
        if updated != content:
            path.write_text(updated, encoding="utf-8", newline="")
            changed.append(path.name)
    return sorted(changed)


def repair(venv: Path, old_root: Path, apply: bool) -> dict[str, Any]:
    venv = venv.resolve()
    old_root_text = str(old_root.resolve())
    new_root_text = str(venv.parent)
    scripts_dir = venv / "Scripts"
    expected_python = (scripts_dir / "python.exe").resolve()

    if not expected_python.is_file():
        raise RuntimeError(f"Missing target interpreter: {expected_python}")
    if Path(sys.executable).resolve() != expected_python:
        raise RuntimeError(
            "Run this harness with the target venv interpreter: " f"{expected_python}"
        )
    if old_root_text.casefold() == new_root_text.casefold():
        raise RuntimeError("Old and new repository roots must differ")

    old_needle = old_root_text.encode("utf-8")
    before = _files_containing(scripts_dir, old_needle)
    result: dict[str, Any] = {
        "status": "PREVIEW" if not apply else "PENDING",
        "venv": str(venv),
        "interpreter": str(expected_python),
        "old_root": old_root_text,
        "new_root": new_root_text,
        "stale_file_count_before": len(before),
        "stale_files_before": [path.name for path in before],
        "generated_launchers": [],
        "patched_text_scripts": [],
    }
    if not apply:
        return result

    result["patched_text_scripts"] = _replace_text_paths(
        before, old_root_text, new_root_text
    )
    result["generated_launchers"] = _regenerate_console_launchers(scripts_dir)

    remaining = _files_containing(scripts_dir, old_needle)
    result["stale_file_count_after"] = len(remaining)
    result["stale_files_after"] = [path.name for path in remaining]
    result["status"] = "PASS" if not remaining else "FAIL"
    if remaining:
        raise RuntimeError(
            "Stale absolute paths remain: " + ", ".join(path.name for path in remaining)
        )
    return result


def main() -> int:
    args = _parse_args()
    try:
        result = repair(args.venv, args.old_root, args.apply)
    except Exception as exc:
        failure = {
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        print(json.dumps(failure, indent=2) if args.json else failure)
        return 1

    print(json.dumps(result, indent=2) if args.json else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
