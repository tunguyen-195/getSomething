"""Explicitly acquire and verify the pinned staging ASR/diarization artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Sequence

from huggingface_hub import hf_hub_download


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASR_MANIFEST = Path("config/models/faster-whisper-large-v2.manifest.json")
PYANNOTE_MANIFEST = Path("config/models/pyannote-3.1-offline.manifest.json")


class InstallError(RuntimeError):
    """Raised when acquisition cannot satisfy the pinned artifact contract."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"cannot read manifest {path}: {exc}") from exc


def _inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise InstallError("manifest path must be a non-empty string")
    normalized = relative.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise InstallError(f"unsafe manifest path: {relative}")
    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise InstallError(f"manifest path escapes root: {relative}") from exc
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matches(path: Path, *, size: int, sha256: str) -> bool:
    try:
        return (
            path.is_file() and path.stat().st_size == size and _sha256(path) == sha256
        )
    except OSError:
        return False


def _install_verified_file(
    source: Path,
    destination: Path,
    *,
    size: int,
    sha256: str,
    force: bool,
) -> None:
    if _matches(destination, size=size, sha256=sha256):
        print(f"[REUSE] {destination}")
        return
    if destination.exists() and not force:
        raise InstallError(
            "existing artifact does not match its manifest; refusing overwrite "
            f"without --force: {destination}"
        )
    if not _matches(source, size=size, sha256=sha256):
        raise InstallError(f"downloaded artifact failed size/SHA-256: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.name}.partial-{uuid.uuid4().hex}")
    try:
        shutil.copyfile(source, partial)
        if not _matches(partial, size=size, sha256=sha256):
            raise InstallError(f"copied artifact failed size/SHA-256: {destination}")
        partial.replace(destination)
        print(f"[VERIFIED] {destination}")
    finally:
        partial.unlink(missing_ok=True)


def _write_ref(path: Path, revision: str, *, force: bool) -> None:
    expected = f"{revision}\n"
    if path.is_file():
        selected = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if selected == [revision]:
            print(f"[REUSE] {path}")
            return
    if path.exists() and not force:
        raise InstallError(
            f"refs/main does not select the pinned revision; use --force: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f"{path.name}.partial-{uuid.uuid4().hex}")
    try:
        partial.write_text(expected, encoding="utf-8")
        partial.replace(path)
        print(f"[PINNED REF] {path} -> {revision}")
    finally:
        partial.unlink(missing_ok=True)


def _download(
    *,
    repo_id: str,
    revision: str,
    filename: str,
    cache_dir: Path,
    token: str | None,
) -> Path:
    print(f"[DOWNLOAD] https://huggingface.co/{repo_id}/resolve/{revision}/{filename}")
    try:
        downloaded = hf_hub_download(
            repo_id=repo_id,
            revision=revision,
            filename=filename,
            cache_dir=cache_dir,
            token=token,
            local_files_only=False,
        )
    except Exception as exc:
        raise InstallError(
            f"Hugging Face acquisition failed for {repo_id}@{revision}:{filename}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return Path(downloaded)


def install_large_v2(repo_root: Path, cache_dir: Path, *, force: bool) -> None:
    manifest = _load_json(repo_root / ASR_MANIFEST)
    model = manifest.get("model")
    if not isinstance(model, dict):
        raise InstallError("large-v2 manifest has no model object")
    if (
        model.get("id") != "systran.faster-whisper-large-v2"
        or model.get("source", {}).get("repository")
        != "Systran/faster-whisper-large-v2"
        or model.get("source", {}).get("revision")
        != "f0fe81560cb8b68660e564f55dd99207059c092e"
    ):
        raise InstallError("canonical large-v2 manifest changed; review explicitly")

    repository = model["source"]["repository"]
    revision = model["source"]["revision"]
    snapshot = _inside(repo_root / "models", model["relative_path"])
    for spec in model["files"]:
        if spec.get("required") is not True:
            continue
        filename = str(spec["path"])
        destination = _inside(snapshot, filename)
        if _matches(
            destination,
            size=int(spec["size_bytes"]),
            sha256=str(spec["sha256"]),
        ):
            print(f"[REUSE] {destination}")
            continue
        if destination.exists() and not force:
            raise InstallError(
                "existing artifact does not match its manifest; refusing overwrite "
                f"without --force: {destination}"
            )
        source = _download(
            repo_id=repository,
            revision=revision,
            filename=filename,
            cache_dir=cache_dir,
            token=None,
        )
        _install_verified_file(
            source,
            destination,
            size=int(spec["size_bytes"]),
            sha256=str(spec["sha256"]),
            force=force,
        )
    _write_ref(snapshot.parent.parent / "refs" / "main", revision, force=force)


def _pyannote_sources(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    pipeline = manifest["pipeline"]
    sources = [(str(pipeline["model_id"]), str(pipeline["revision"]))]
    sources.extend(
        (str(row["model_id"]), str(row["revision"])) for row in manifest["dependencies"]
    )
    return sources


def install_pyannote(
    repo_root: Path,
    cache_dir: Path,
    *,
    force: bool,
    token: str | None,
    accepted_terms: bool,
) -> None:
    if not accepted_terms:
        raise InstallError(
            "pyannote acquisition requires --accept-pyannote-terms after the "
            "operator accepts the gated model conditions on Hugging Face"
        )
    if not token:
        raise InstallError("HF_TOKEN is required for pinned pyannote acquisition")

    manifest = _load_json(repo_root / PYANNOTE_MANIFEST)
    if (
        manifest.get("artifact_id") != "diarization.pyannote-3.1-offline"
        or manifest.get("pipeline", {}).get("revision")
        != "84fd25912480287da0247647c3d2b4853cb3ee5d"
    ):
        raise InstallError("canonical pyannote manifest changed; review explicitly")

    file_rows = list(manifest["files"])
    for model_id, revision in _pyannote_sources(manifest):
        owner, name = model_id.split("/", 1)
        cache_root = repo_root / "models" / "pyannote" / f"models--{owner}--{name}"
        prefix = f"models/pyannote/models--{owner}--{name}/snapshots/{revision}/"
        matched = [row for row in file_rows if str(row["path"]).startswith(prefix)]
        if not matched:
            raise InstallError(
                f"pyannote manifest has no files for {model_id}@{revision}"
            )
        for spec in matched:
            filename = str(spec["path"])[len(prefix) :]
            destination = _inside(repo_root, str(spec["path"]))
            if _matches(
                destination,
                size=int(spec["size"]),
                sha256=str(spec["sha256"]),
            ):
                print(f"[REUSE] {destination}")
                continue
            if destination.exists() and not force:
                raise InstallError(
                    "existing artifact does not match its manifest; refusing overwrite "
                    f"without --force: {destination}"
                )
            source = _download(
                repo_id=model_id,
                revision=revision,
                filename=filename,
                cache_dir=cache_dir,
                token=token,
            )
            _install_verified_file(
                source,
                destination,
                size=int(spec["size"]),
                sha256=str(spec["sha256"]),
                force=force,
            )
        _write_ref(cache_root / "refs" / "main", revision, force=force)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--include",
        action="append",
        choices=("large-v2", "pyannote"),
        default=[],
        help="Artifact group to acquire; omit to acquire both groups.",
    )
    parser.add_argument("--accept-pyannote-terms", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    selected = set(args.include or ("large-v2", "pyannote"))
    try:
        with tempfile.TemporaryDirectory(prefix="stt-model-acquisition-") as temp:
            cache_dir = Path(temp) / "huggingface-cache"
            if "large-v2" in selected:
                install_large_v2(repo_root, cache_dir, force=args.force)
            if "pyannote" in selected:
                install_pyannote(
                    repo_root,
                    cache_dir,
                    force=args.force,
                    token=os.getenv("HF_TOKEN"),
                    accepted_terms=args.accept_pyannote_terms,
                )
    except InstallError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: pinned staging audio models are installed and hash-verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
