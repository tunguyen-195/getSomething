"""Create a portable Pyannote model bundle for offline transfer."""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.model_artifacts import (  # noqa: E402
    artifact_with_cache_root,
    find_artifact_for_pyannote_model,
    repo_local_name,
    verify_artifact,
)
from src.services.transcription.models.pyannote_loader import (  # noqa: E402
    DEFAULT_CACHE_DIR,
    DEFAULT_MODEL_ID,
)


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_").lower()


def _iter_files(path: Path) -> list[Path]:
    return sorted(item for item in path.rglob("*") if item.is_file())


def _readme_text(*, repo_id: str, revision: str, cache_root: str, local_dir: Path) -> str:
    windows_cache_root = cache_root.replace("/", "\\")
    local_name = repo_local_name(repo_id)
    return f"""Pyannote diarization model bundle

Model: {repo_id}
Revision: {revision}
Packed at UTC: {datetime.now(timezone.utc).isoformat()}

Copy instructions on the target machine:

1. Put this zip anywhere, for example C:\\Users\\Admin\\Downloads.
2. Open PowerShell:
   cd D:\\Workspace\\SpeechToInfomation-pr
   Expand-Archive C:\\Users\\Admin\\Downloads\\pyannote_community_1_*.zip -DestinationPath . -Force

Expected final path:
   D:\\Workspace\\SpeechToInfomation-pr\\{windows_cache_root}\\{local_name}

Docker sees the same files at:
   /app/{cache_root}/{local_name}

Restart after extracting:
   docker compose --env-file .env up -d --build

Smoke check:
   docker compose exec backend python3 -c "from src.services.transcription.models.pyannote_manager import get_pyannote_manager; print(get_pyannote_manager().is_available())"

Source directory used to create this bundle:
   {local_dir}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack local Pyannote model cache into a transfer zip.")
    parser.add_argument("--no-dotenv", action="store_true", help="Do not load .env before reading PYANNOTE_* values.")
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--manifest", default="docs/model_artifacts.required.json")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=Path("dist") / "model-bundles")
    args = parser.parse_args()

    if not args.no_dotenv:
        load_dotenv(args.root / ".env")

    root = args.root.resolve()
    model_id = args.model_id or os.getenv("PYANNOTE_MODEL_ID", DEFAULT_MODEL_ID)
    cache_dir = args.cache_dir or os.getenv("PYANNOTE_CACHE_DIR", DEFAULT_CACHE_DIR)
    artifact = find_artifact_for_pyannote_model(model_id, root=root, manifest=args.manifest)
    if artifact is None:
        print("[ERROR] model_artifact_not_manifested")
        print("PYANNOTE_MODEL_ID must match a pinned gated_hf artifact in docs\\model_artifacts.required.json.")
        return 2

    artifact = artifact_with_cache_root(artifact, cache_dir)
    repo_id = str(artifact["repo_id"])
    revision = str(artifact["revision"])
    cache_root = str(artifact["cache_root"]).replace("\\", "/")
    local_dir = (root / cache_root / repo_local_name(repo_id)).resolve()

    result = verify_artifact(artifact, root=root, candidate_path=local_dir, write_provenance=True)
    if not result.ok or result.resolved_path is None:
        print("[ERROR] pyannote_model_not_ready")
        print(f"Expected local dir: {local_dir}")
        print("Run on a machine with Hugging Face access:")
        print("  python download_pyannote_model.py")
        print("Then retry:")
        print("  python scripts\\pack_pyannote_model.py")
        if result.errors:
            print(f"Verification errors: {';'.join(result.errors)}")
        return 3

    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = f"{_safe_name(str(artifact['id']))}_{revision[:8]}.zip"
    output_path = output_dir / output_name

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for file_path in _iter_files(local_dir):
            bundle.write(file_path, file_path.relative_to(root).as_posix())
        bundle.writestr(
            "PYANNOTE_TRANSFER_README.txt",
            _readme_text(repo_id=repo_id, revision=revision, cache_root=cache_root, local_dir=local_dir),
        )

    print(f"[OK] Packed {repo_id}@{revision}")
    print(f"[OK] Bundle: {output_path}")
    print(f"[OK] Extract into repo root on target machine: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
