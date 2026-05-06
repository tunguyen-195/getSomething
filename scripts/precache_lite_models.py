from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.model_artifacts import (  # noqa: E402
    artifact_with_cache_root,
    find_artifact_for_faster_whisper_model,
    verify_artifact,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-cache the pinned public faster-whisper artifact used by the Lite RTX2050 profile."
    )
    parser.add_argument("--model", default=os.getenv("WHISPER_MODEL", "small"))
    parser.add_argument("--cache-dir", default=os.getenv("WHISPER_MODEL_PATH", "models/whisper"))
    parser.add_argument("--manifest", default="docs/model_artifacts.required.json")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--revision", help="Compatibility check only; must match the manifest revision.")
    parser.add_argument("--local-dir", help=argparse.SUPPRESS)
    parser.add_argument("--offline", action="store_true", help="Use local cache only; do not contact Hugging Face.")
    parser.add_argument("--verify-load", action="store_true", help="Instantiate WhisperModel on CPU/int8 after verification.")
    args = parser.parse_args()

    root = args.root.resolve()
    artifact = find_artifact_for_faster_whisper_model(args.model, root=root, manifest=args.manifest)
    if artifact is None:
        print("[ERROR] model_artifact_not_manifested")
        print("Add a pinned faster-whisper artifact to docs\\model_artifacts.required.json before using this model.")
        return 2

    artifact = artifact_with_cache_root(artifact, args.cache_dir)
    revision = str(artifact["revision"])
    if args.revision and args.revision != revision:
        print(f"[ERROR] revision_mismatch: manifest={revision} requested={args.revision}")
        return 2
    if args.local_dir:
        print("[ERROR] local_dir_unsupported_for_hf_cache")
        print("Lite pre-cache must use the manifest cache_root layout under models\\whisper.")
        return 2

    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        print(f"[ERROR] huggingface_hub_unavailable:{exc.__class__.__name__}")
        return 2

    cache_dir = (root / str(artifact["cache_root"])).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {artifact['repo_id']}@{revision}")
    print(f"cache_dir={cache_dir}")

    kwargs = {
        "repo_id": artifact["repo_id"],
        "revision": revision,
        "cache_dir": str(cache_dir),
        "allow_patterns": artifact.get("allow_patterns") or [item["path"] for item in artifact.get("files", [])],
        "local_files_only": args.offline,
    }
    try:
        snapshot_path = Path(snapshot_download(**kwargs))
    except Exception as exc:
        print(f"[ERROR] snapshot_download_failed:{exc.__class__.__name__}")
        print("Check internet access, Hugging Face availability, or copy a prepared models\\whisper cache manually.")
        return 3

    result = verify_artifact(artifact, root=root, candidate_path=snapshot_path, write_provenance=True)
    if not result.ok:
        print(f"[ERROR] model_cache_missing_or_unverified:{';'.join(result.errors)}")
        return 4

    print(f"[OK] snapshot={result.resolved_path}")
    print("[OK] strict verification passed and portable provenance was written")

    if args.verify_load:
        try:
            from faster_whisper import WhisperModel

            WhisperModel(str(result.resolved_path), device="cpu", compute_type="int8")
            print("[OK] faster-whisper CPU/int8 load")
        except Exception as exc:
            print(f"[ERROR] verify_load_failed:{exc.__class__.__name__}")
            return 5

    print("Next: python scripts\\verify_models.py --profile lite_rtx2050")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
