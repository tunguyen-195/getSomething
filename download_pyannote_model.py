"""Download the pinned Pyannote diarization artifact into the local model cache."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
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
    _pipeline_from_pretrained,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download pinned Pyannote models into models/pyannote")
    parser.add_argument("--no-dotenv", action="store_true", help="Do not load .env before reading HF_TOKEN")
    parser.add_argument("--model-id", default=os.getenv("PYANNOTE_MODEL_ID", DEFAULT_MODEL_ID))
    parser.add_argument("--cache-dir", default=os.getenv("PYANNOTE_CACHE_DIR", DEFAULT_CACHE_DIR))
    parser.add_argument("--manifest", default="docs/model_artifacts.required.json")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--offline", action="store_true", help="Use local cache only; do not contact Hugging Face.")
    parser.add_argument("--skip-load-check", action="store_true", help="Skip pyannote.audio Pipeline load smoke check.")
    args = parser.parse_args()

    if not args.no_dotenv:
        load_dotenv()

    hf_token = os.getenv("HF_TOKEN")
    if not hf_token and not args.offline:
        print(
            "[ERROR] hf_token_required: accept the Pyannote model terms on Hugging Face, "
            "then set HF_TOKEN in your shell or .env."
        )
        return 2

    root = args.root.resolve()
    artifact = find_artifact_for_pyannote_model(args.model_id, root=root, manifest=args.manifest)
    if artifact is None:
        print("[ERROR] model_artifact_not_manifested")
        print("PYANNOTE_MODEL_ID must match a pinned gated_hf artifact in docs\\model_artifacts.required.json.")
        return 2

    artifact = artifact_with_cache_root(artifact, args.cache_dir)
    revision = str(artifact["revision"])
    local_dir = (root / str(artifact["cache_root"]) / repo_local_name(str(artifact["repo_id"]))).resolve()
    local_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        print(f"[ERROR] huggingface_hub_unavailable:{exc.__class__.__name__}")
        return 2

    print(f"Downloading {artifact['repo_id']}@{revision}")
    print(f"local_dir={local_dir}")
    try:
        snapshot_download(
            repo_id=artifact["repo_id"],
            revision=revision,
            token=hf_token or None,
            local_dir=str(local_dir),
            allow_patterns=artifact.get("allow_patterns") or [item["path"] for item in artifact.get("files", [])],
            local_files_only=args.offline,
        )
    except Exception as exc:
        print(f"[ERROR] snapshot_download_failed:{exc.__class__.__name__}")
        return 3

    result = verify_artifact(artifact, root=root, candidate_path=local_dir, write_provenance=True)
    if not result.ok:
        print(f"[ERROR] model_cache_missing_or_unverified:{';'.join(result.errors)}")
        return 4

    if not args.skip_load_check:
        try:
            print(f"Verifying local Pyannote load from {local_dir}")
            _pipeline_from_pretrained(local_dir)
        except Exception as exc:
            print(f"[ERROR] pyannote_load_check_failed:{exc.__class__.__name__}")
            return 5

    print(f"[OK] Pyannote model ready: {artifact['repo_id']}")
    print(f"[OK] Local dir: {local_dir}")
    print("[OK] strict verification passed and portable provenance was written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
