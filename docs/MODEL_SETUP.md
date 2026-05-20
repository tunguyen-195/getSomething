# Model Setup and Artifact Handoff

This repository does not commit model binaries. The pull-ready target for a new
machine is the Lite RTX2050 profile:

```env
APP_EDITION=lite
PROCESSING_RUNNER=single_job_db_lease
ASR_PROVIDER=faster_whisper_ct2
ASR_PROFILE=balanced
WHISPER_MODEL=medium
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=int8
WHISPER_MODEL_PATH=models/whisper
```

Full Cherry/PhoWhisper offline models are optional. If an artifact is not
downloadable by a repo script, install it by copying a prepared manual bundle
into the documented path, then run verification. They are not required for Lite
pull-readiness.

## Decisions

- Public/gated-public models: download with pinned revisions and verify locally.
- Unavailable/internal/offline-only models: copy manually from a prepared
  internal bundle and verify locally.
- Git: track only docs, scripts, manifest, expected paths, size, checksum, and
  license/source notes.
- Pull-ready acceptance: Lite RTX2050 can run upload, transcribe, deterministic
  analysis, and visualize after setup. Summarization is available only after a
  server-side LLM provider/API key is configured.
- Full/offline Cherry/PhoWhisper: documented optional profile, not a blocker for
  a new Lite machine.

Do not put model weights or public model cache into Git tracking in this runtime
patch. If a model is unavailable online, the handoff is explicit manual copy
plus `verify_models.py`.

See the machine-readable manifest:

```powershell
type docs\model_artifacts.required.json
```

## Lite RTX2050 Required Model

Required artifact:

- `faster_whisper_medium`
- Source: `Systran/faster-whisper-medium`
- Runtime cache root: `models/whisper`
- Local setup command:

```powershell
python scripts\precache_lite_models.py --model medium
```

Docker setup command:

```powershell
docker compose --env-file .env --profile setup run --rm model_sync
```

Verify:

```powershell
python scripts\verify_models.py --profile lite_rtx2050
python scripts\check_lite_runtime.py --gpu-smoke --offline-models-only
```

`scripts/precache_lite_models.py` uses Hugging Face Hub `snapshot_download` with
the revision and file list pinned in `docs/model_artifacts.required.json`.
`verify_models.py` checks required file size and hash/blob metadata offline.
Strict verification may take a few seconds because `model.bin` is hashed.

The application does not pass `medium`, `small`, or another model name to faster-whisper at
runtime. It first verifies the local artifact and then loads faster-whisper from
the resolved local snapshot path. If a configured model is not in the manifest,
runtime fails with `model_artifact_not_manifested` instead of downloading latest.

`faster_whisper_small` remains optional as a fast fallback. It is no longer the
recommended default for Vietnamese transcript quality.

If the machine is offline, copy a prepared public `models/whisper` cache into
the repo root and run the verify commands above.

## Manual Copy Layout For Unavailable Models

Only use this section for artifacts that cannot be downloaded by repo scripts.
Copy the prepared bundle at the repository root and preserve these paths when
present:

```text
models/
  whisper/
  large-v2.pt
  phowhisper-safe/
  silero/
    silero_vad.jit
    utils_vad.py
  asr/
    whisper_cpp/
      ggml-small-q5_0.bin
    phowhisper_cpp/
      ggml-phowhisper-large-q5_0.bin
      ggml-phowhisper-large-q5_0.bin.manifest.json
```

After copy, verify:

```powershell
python scripts\verify_models.py --profile lite_rtx2050
python scripts\verify_models.py --profile full_offline
```

Important current state:

- The PR working tree does not currently contain `models/`.
- The old local workspace has a `models/` cache, but it is incomplete for
  `full_offline`: it lacks `models/large-v2.pt`, `models/phowhisper-safe`, and
  `models/asr/phowhisper_cpp/ggml-phowhisper-large-q5_0.bin`.
- Do not stage or commit copied model files. `/models/` remains ignored by Git.

## Full/Offline Optional Models

These are not in Git and are not currently downloadable by repo scripts. Copy
them manually if the full/offline profile is required:

- `models/large-v2.pt` or `models/whisper-large-v2/large-v2.pt`
- `models/phowhisper-safe`, `models/phowhisper`, or `models/phowhisper-full`
- `models/asr/phowhisper_cpp/ggml-phowhisper-large-q5_0.bin`
- `models/asr/phowhisper_cpp/ggml-phowhisper-large-q5_0.bin.manifest.json`

Manual-copy artifacts must have integrity metadata before they can verify
successfully. A required manual file needs `size_bytes` and `sha256`; a manual
directory or file set needs a `files[]` list with `path`, `size_bytes`, and
`sha256` for each required file, or a verified sidecar manifest. If copied files
exist but metadata is not declared, `verify_models.py` returns
`artifact_integrity_metadata_missing` instead of treating existence as success.

Do not set `.env` to `ASR_PROVIDER=cherry_whisper_v2` on a new Lite machine
unless the full/offline artifacts have been copied and verified.

## Optional Pyannote

Pyannote diarization is gated and optional for Lite:

```powershell
set HF_TOKEN=<your-hugging-face-token>
python download_pyannote_model.py
```

The user must accept the Hugging Face model terms before download.
Runtime Pyannote auto-download is disabled; use this script so the gated model
is downloaded at the pinned revision and verified before loading.

## Troubleshooting

If `verify_models.py` fails:

1. Read the missing artifact ID.
2. Check `docs/model_artifacts.required.json` for `path`, `cache_root`, or
   `setup_command`.
3. Download public Lite artifacts or copy the manual bundle artifacts.
4. Re-run verification.

If `check_lite_runtime.py --gpu-smoke --offline-models-only` fails with
`model_cache_missing_or_unverified`, the faster-whisper cache is missing,
modified, or the app cannot see `WHISPER_MODEL_PATH`.
