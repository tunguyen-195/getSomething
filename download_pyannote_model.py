"""Download Pyannote diarization models into the project-local model cache."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from src.services.transcription.models.pyannote_loader import (
    DEFAULT_CACHE_DIR,
    DEFAULT_FALLBACK_MODEL_ID,
    DEFAULT_MODEL_ID,
    _pipeline_from_pretrained,
    model_local_dir,
)


def _download_model(model_id: str, hf_token: str, cache_dir: str | Path) -> Path:
    from huggingface_hub import snapshot_download

    local_dir = model_local_dir(model_id, cache_dir)
    local_dir.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {model_id} -> {local_dir.resolve()}")
    snapshot_download(repo_id=model_id, token=hf_token, local_dir=str(local_dir))
    print(f"Verifying local Pyannote load from {local_dir.resolve()}")
    _pipeline_from_pretrained(local_dir)
    return local_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Pyannote models into models/pyannote")
    parser.add_argument("--no-dotenv", action="store_true", help="Do not load .env before reading HF_TOKEN")
    args = parser.parse_args()

    if not args.no_dotenv:
        load_dotenv()

    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        raise SystemExit(
            "HF_TOKEN is required to download gated pyannote models. "
            "Accept the model conditions on Hugging Face, then set HF_TOKEN in your shell or .env."
        )

    model_id = os.getenv("PYANNOTE_MODEL_ID", DEFAULT_MODEL_ID)
    fallback_model_id = os.getenv("PYANNOTE_FALLBACK_MODEL_ID", DEFAULT_FALLBACK_MODEL_ID)
    cache_dir = os.getenv("PYANNOTE_CACHE_DIR", DEFAULT_CACHE_DIR)

    errors: list[str] = []
    for candidate in dict.fromkeys([model_id, fallback_model_id]):
        try:
            local_dir = _download_model(candidate, hf_token, cache_dir)
            print("")
            print(f"Pyannote model ready: {candidate}")
            print(f"Local dir: {local_dir.resolve()}")
            print(
                "Verify with: python -c "
                "\"from src.services.transcription.models.pyannote_manager import get_pyannote_manager; "
                "print(get_pyannote_manager().is_available())\""
            )
            return
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
            print(f"Failed to download/load {candidate}: {exc}")

    raise SystemExit("Unable to prepare any Pyannote model:\n" + "\n".join(errors))


if __name__ == "__main__":
    main()
