# SpeechToInformation Lite - RTX2050 Win11 Deployment

## Target Hardware

- CPU: Intel Core i5-12450HX, 8C/12T.
- GPU: NVIDIA GeForce RTX 2050 4GB GDDR6.
- RAM: 12GB DDR5.
- SSD: 512GB NVMe.
- OS: Windows 11 Home Single Language.

## Edition Contract

Lite stays in the same repo and product line. It is enabled only by config:

```env
APP_EDITION=lite
APP_DISPLAY_NAME=SpeechToInformation Lite
RUNTIME_PROFILE=single_machine_lite
PROCESSING_RUNNER=single_job_db_lease
MAX_ACTIVE_JOBS=1
RATE_LIMIT_ENABLED=false
UVICORN_RELOAD=false
```

Full mode remains unchanged:

```env
APP_EDITION=full
RUNTIME_PROFILE=full
PROCESSING_RUNNER=celery
```

Full mode continues to use Redis, Celery, and the existing async/sync paths.

## Runtime

- Lite does not run Celery, Flower, or Redis.
- Backend must run with one Uvicorn worker.
- Do not use `--reload` while a Lite job may be running.
- Single-job coordination is stored in `runtime_job_leases`.
- The lease key is `single_machine_lite`.
- Active operations are limited to `transcribe`, `summarize`, and `visualize`.
- Lease defaults:

```env
LITE_JOB_LEASE_TTL_SECONDS=900
LITE_JOB_HEARTBEAT_SECONDS=15
```

Lite request flow:

1. Endpoint acquires the DB lease.
2. Endpoint updates `Task.status`.
3. Endpoint starts an in-process background thread.
4. Endpoint returns `runner_job_id` immediately.
5. Background job opens its own DB session.
6. Heartbeat uses its own DB sessions.
7. Lease is released in `finally`.

If another job is active, endpoints return `409 Busy` with active task metadata.

## ASR Defaults

Safe default for RTX2050 4GB:

```env
ASR_PROVIDER=faster_whisper_ct2
ASR_PROFILE=rtx2050_safe
ENABLE_DIARIZATION_DEFAULT=false
WHISPER_MODEL=small
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=int8
WHISPER_BATCH_SIZE=1
WHISPER_BEAM_SIZE=5
```

Profiles:

- `rtx2050_safe`: faster-whisper small, CUDA int8, batch 1. Default.
- `rtx2050_fast`: faster-whisper small, CUDA int8_float16. Promote only after benchmark.
- `balanced`: faster-whisper medium, CUDA int8.
- `cpu_safe`: faster-whisper small, CPU int8.
- `offline_cpp`: whisper.cpp CLI with configured GGML model.
- `phowhisper_cpp_candidate`: hidden until model SHA, source manifest, and smoke test pass.
- `quality_local`: larger local faster-whisper model, benchmark before regular use.

whisper.cpp settings:

```env
WHISPER_CPP_BIN=tools/whisper.cpp/whisper-cli.exe
WHISPER_CPP_MODEL=models/asr/whisper_cpp/ggml-small-q5_0.bin
WHISPER_CPP_THREADS=6
WHISPER_CPP_LANGUAGE=vi
WHISPER_CPP_TIMEOUT_SECONDS=3600
```

PhoWhisper.cpp candidate:

```env
PHOWHISPER_CPP_MODEL=models/asr/phowhisper_cpp/ggml-phowhisper-large-q5_0.bin
PHOWHISPER_CPP_SHA256=1ECFF4DB87EF84AD1356D2955D2ECEA03E6C240B46FE1CA87F07EA8390E3109C
PHOWHISPER_CPP_SIZE_BYTES=1080732108
```

SHA only proves the file is unchanged. The app keeps `phowhisper_cpp_candidate` hidden until a sidecar validation manifest exists at:

```text
models/asr/phowhisper_cpp/ggml-phowhisper-large-q5_0.bin.manifest.json
```

Required manifest contract:

```json
{
  "source_url": "https://...",
  "source_license": "license or source note",
  "whisper_cpp_binary_sha256": "SHA256_OF_WHISPER_CLI_EXE",
  "whisper_cpp_version": "commit/tag/version",
  "model_architecture": "PhoWhisper-large converted to whisper.cpp ggml",
  "whisper_cpp_compatible": true,
  "smoke_test": {
    "status": "pass",
    "language": "vi",
    "duration_seconds": 20,
    "json_parse_pass": true
  },
  "benchmark": {
    "status": "pass",
    "baseline": "faster_whisper_ct2_small_int8",
    "keyword_recall_pass": true,
    "max_relative_wer_regression": 0.0
  }
}
```

Promotion also requires a 10-30 second Vietnamese smoke test, JSON parse pass, and a benchmark gate showing keyword recall is acceptable and WER/RTF/RAM cost does not exceed the chosen threshold.

## LLM And Analysis

Lite is API-first for deep analysis:

```env
ANALYSIS_INTELLIGENCE_LLM_ENABLED=true
ANALYSIS_LLM_PROVIDER=openai
ANALYSIS_LLM_BASE_URL=https://api.openai.com/v1
ANALYSIS_LLM_MODEL=gpt-5-mini
ANALYSIS_LLM_FALLBACK_MODEL=gpt-4.1-mini
ANALYSIS_LLM_API_KEY=
ANALYSIS_LLM_TIMEOUT_SECONDS=60
ANALYSIS_LLM_MAX_INPUT_CHARS=24000
ANALYSIS_LLM_MAX_OUTPUT_TOKENS=2000
ANALYSIS_LLM_DAILY_BUDGET_USD=
```

Rules:

- API key is read server-side only.
- Do not log prompt text, transcripts, or raw provider responses.
- Structured JSON schema is required.
- Evidence must locate back to transcript; otherwise drop the item or mark it `requires_review=true`.
- If no API key is configured, analysis falls back to deterministic extraction and UI shows LLM disabled.

Local LLM fallback can use llama.cpp server:

```env
ANALYSIS_LLM_PROVIDER=llama_cpp_server
ANALYSIS_LLM_BASE_URL=http://localhost:8080/v1
ANALYSIS_LLM_MODEL=qwen3-4b-q4
```

Official llama.cpp server docs: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

Do not default to 7B/8B models on 12GB RAM.

## Setup

1. Copy `.env.lite.example` to `.env`.
2. Start Postgres only:

```powershell
docker compose -f docker-compose.lite.yml --env-file .env up -d db
```

3. Install backend dependencies in the local Python environment.
4. Run migrations:

```powershell
alembic upgrade head
```

5. Start backend with no reload:

```powershell
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1
```

6. Start frontend:

```powershell
Push-Location frontend
cmd /c npm install
cmd /c npm run dev
Pop-Location
```

7. Open `http://localhost:3000`.

## Runtime Checks

```powershell
python scripts/check_lite_runtime.py
```

The frontend header also shows edition, ASR provider/profile, LLM status, and active job state.

## Regression Checks

- Lite DB lease rejects a second active job with `409 Busy`.
- Lite startup repairs only stale leases whose TTL has expired.
- Lite jobs do not reuse the request DB session in background threads.
- Lite can run without Redis, Celery, or Flower.
- Full mode `PROCESSING_RUNNER=celery` still uses Celery by default.
- Full mode `async_mode=false` still runs the existing synchronous endpoint path.
- Missing LLM API key falls back to deterministic analysis.
- whisper.cpp subprocess calls use argv lists, timeout, and temp cleanup.

## Benchmark Gate

- Benchmark set:
    - 5 clean Vietnamese files.
    - 5 noisy Vietnamese files.
    - 3 silence/non-speech files.
    - 2 conversations over 10 minutes.
- Metrics:
    - RTF.
    - Peak RAM.
    - Peak VRAM.
    - Failure count.
    - Non-speech hallucination.
    - Phone/date/money extraction recall.
- Promotion rules:
    - `rtx2050_fast` promoted only if no OOM and improves RTF over `rtx2050_safe`.
    - `phowhisper_cpp_cli` promoted only if smoke test passes and matches/beats `faster_whisper_ct2` small/int8 without unacceptable RTF/RAM cost.

Run benchmark scaffold:

```powershell
python scripts/benchmark_lite_asr.py --profile rtx2050_safe --files path\to\a.wav path\to\b.wav --output lite_benchmark.json
```

## Safety Notes

- Keep original audio and transcripts.
- Treat ASR and LLM output as machine-suggested, not forensic conclusions.
- Avoid diarization by default on RTX2050 Lite unless the benchmark proves the machine can handle it.
- Never store API keys in frontend code.
