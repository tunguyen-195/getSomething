import os
from pathlib import Path

import torch


def main() -> None:
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        raise SystemExit(
            "HF_TOKEN is required to download gated pyannote models. "
            "Set it in your shell or .env, never hardcode it in this file."
        )

    models_dir = Path("models/pyannote")
    models_dir.mkdir(parents=True, exist_ok=True)

    print("Downloading pyannote speaker-diarization-3.1...")
    print(f"Cache dir: {models_dir.absolute()}")

    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token,
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    pipeline.to(device)
    print(f"Pipeline ready on: {device}")


if __name__ == "__main__":
    main()
