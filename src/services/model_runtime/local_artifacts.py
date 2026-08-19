"""Resolve local Hugging Face snapshots without provider/network fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def resolve_huggingface_snapshot(
    cache_root: Path,
    repository: str,
    *,
    required_files: Iterable[str] = ("config.yaml",),
) -> Path | None:
    """Return a deterministic complete snapshot contained by ``cache_root``."""

    root = cache_root.resolve()
    repo_parts = [part for part in repository.split("/") if part]
    if len(repo_parts) != 2:
        raise ValueError("repository must use owner/name form")

    required = tuple(required_files)
    direct_candidates = (
        root / repo_parts[1],
        root / "--".join(repo_parts),
        root / f"models--{'--'.join(repo_parts)}",
    )
    candidates: list[Path] = []
    for candidate in direct_candidates:
        snapshots = candidate / "snapshots"
        if snapshots.is_dir():
            candidates.extend(sorted(path for path in snapshots.iterdir() if path.is_dir()))
        candidates.append(candidate)

    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.is_dir() and all((resolved / name).is_file() for name in required):
            return resolved
    return None
