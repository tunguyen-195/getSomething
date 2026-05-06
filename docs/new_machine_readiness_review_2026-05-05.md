# New Machine Readiness Review

Date: 2026-05-05
Scope: setup/run documentation, model/bootstrap scripts, Git-tracked runtime context, offline/internal model handoff.

## Verdict

After the follow-up fixes, the project is pull-ready for the agreed target:
**Lite RTX2050**.

This means a new Windows RTX2050 machine can clone the repo, copy
`.env.lite.example` to `.env`, install dependencies, pre-cache the public
faster-whisper small model, verify the model cache, and start backend/frontend
without Celery/Redis.

The project is still not "clone and run full/offline Cherry/PhoWhisper" because
those models are not present in this PR working tree. Artifacts that are not
downloadable by repo scripts must be copied manually from a prepared internal
bundle and verified with `scripts/verify_models.py`.

## Decisions Captured

- Pull-ready profile: `lite_rtx2050`.
- Internal/offline-only model distribution: manual copy bundle by default.
- Git policy: do not commit model binaries or runtime model cache under
  `models/`.
- Full/offline Cherry/PhoWhisper is optional and must be verified separately.

## Findings Status

### Resolved for Lite pull-ready: missing Windows start script

Added:

- `START_LITE_RTX2050.bat`
- `START_ALL_SERVICES.bat` compatibility wrapper
- `entrypoint.bat` wrapper without hard-coded workspace paths

Docs now point new-machine setup to `START_LITE_RTX2050.bat`.

### Resolved for model handoff: missing artifact manifest

Added:

- `docs/MODEL_SETUP.md`
- `docs/model_artifacts.required.json`
- `scripts/verify_models.py`

The manifest lists Lite required artifacts and optional/full offline artifacts,
including target paths, source class, checksums where known, and manual copy
notes for unavailable artifacts.

### Resolved for Lite model download/cache: misleading scripts

Added:

- `scripts/precache_lite_models.py`

Updated compatibility wrappers:

- `scripts/download_whisper.py`
- `scripts/download_models.py`

The old names no longer pretend to check-only while being named downloaders;
they route to the Lite pre-cache or verifier.

### Remaining by design: full/offline Cherry/PhoWhisper models are not in Git

The following are not committed and should not be expected after clone:

- `models/large-v2.pt`
- `models/whisper-large-v2/large-v2.pt`
- `models/phowhisper-safe`
- `models/phowhisper`
- `models/phowhisper-full`
- `models/silero/silero_vad.jit`
- `models/silero/utils_vad.py`
- `models/asr/phowhisper_cpp/ggml-phowhisper-large-q5_0.bin`
- `models/asr/phowhisper_cpp/ggml-phowhisper-large-q5_0.bin.manifest.json`

This is acceptable for Lite pull-ready, but full/offline users must obtain the
manual bundle and run:

```powershell
python scripts\verify_models.py --profile full_offline
```

### Remaining cleanup: root sample/runtime-like files

The repo still tracks root sample/runtime-like files:

- `Tiếp nhận yêu cầu đặt phòng của khách lẻ qua điện thoại.mp3`
- `cases.json`
- `cases.txt`
- `tasks.json`
- `dummy_audio_test.txt`
- `test.py`

These are not a Lite pull-ready blocker. Later cleanup should either move them
under `tests/fixtures` or document why they are intentionally tracked.

## Confirmed Good

- `README.md`, `docs/NEW_MACHINE_SETUP.md`,
  `docs/DEPLOY_LITE_RTX2050_WIN11.md`, and `docs/MODEL_SETUP.md` exist.
- `.env.example` and `.env.lite.example` are tracked.
- `requirements.txt`, `requirements-torch-cu121.txt`, Dockerfiles, and compose
  files are tracked.
- Lite runtime check exists at `scripts/check_lite_runtime.py`.
- Lite pre-cache exists at `scripts/precache_lite_models.py` and uses pinned
  Hugging Face revisions from `docs/model_artifacts.required.json`.
- Artifact verifier exists at `scripts/verify_models.py` and performs offline
  size/hash/blob checks by default.
- `download_pyannote_model.py` remains the gated Pyannote downloader and does
  not fallback to unmanifested latest models.

## New Machine Lite Acceptance

```powershell
copy .env.lite.example .env
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements-torch-cu121.txt --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
cd frontend
npm install
cd ..
python -m src.database.scripts.init_db
python scripts\precache_lite_models.py --model small
python scripts\verify_models.py --profile lite_rtx2050
python scripts\check_lite_runtime.py --gpu-smoke --offline-models-only
.\START_LITE_RTX2050.bat
```
