# Portable Local LLM Deployment

Date: 2026-08-11
Status: benchmark-candidate procedure; clone-only deployment is currently BLOCKED

## Outcome and completion gates

This runbook defines how a clean Windows machine can verify and start the pinned
local summary/analysis model without downloading at runtime. A deployment is
portable only when all of these gates pass:

1. the application checkout is paired with the exact offline sidecar bundle;
2. model/runtime manifests, sizes, SHA-256 values, source revisions and licenses
   verify locally;
3. the selected hardware profile starts without hidden fallback;
4. structured-output smoke validates the JSON schema;
5. the production summary/analysis smoke records model ID, prompt/schema hashes,
   latency, token rates, RAM/VRAM and failure state.

Do not call a plain Git clone deployable today. `/models/` and `venv/` are
ignored, while the offline release bundle is still incomplete. The clean-machine
installer also still needs a pinned Python runtime/wheelhouse, Node runtime/cache,
FFmpeg, queue runtime and startup profile.

## Pinned baseline

- Model manifest: `config/models/qwen3-8b-q4_k_m.manifest.json`
- Model ID: `qwen.qwen3-8b-q4_k_m`
- Model artifact: `models/qwen3/Qwen3-8B-Q4_K_M.gguf`
- Model source: `Qwen/Qwen3-8B-GGUF` at the immutable revision in the manifest
- Model license: Apache-2.0, with the bundled `LICENSE` file verified by SHA-256
- Runtime manifest: `config/runtimes/llama.cpp-b10331-windows-cuda-12.4.runtime.json`
- Runtime artifact: `models/runtimes/llama.cpp/b10331/windows-cuda-12.4-x64`
- Runtime source: `ggml-org/llama.cpp` release `b10331`
- Runtime license: MIT, with all declared runtime files verified by SHA-256

Any challenger needs its own immutable manifest and profile. Never replace the
baseline GGUF under the same path or alias.

## Hardware profiles

### `win-cuda-12gb-qwen3-8b-q4`

- Intended hardware: NVIDIA GPU with at least 12 GB VRAM.
- Context: 8192 tokens; parallel slots: 1.
- Offload: all model layers requested with CUDA; Flash Attention enabled.
- KV cache: Q8_0 for K and V.
- Scheduling: ASR/diarization and LLM stages are serialized on a single GPU.
- Start command: `scripts/start_llama_server.ps1`.

The script's 6500 MiB free-VRAM check is specific to the pinned 5.03 GB Q4
artifact. Larger quantizations/models require a separately measured threshold;
do not reuse 6500 MiB blindly.

### `win-cpu-functional-qwen3-8b-q4`

- Intended hardware: x86-64 Windows host when CUDA is absent or unavailable.
- Context: 4096 tokens; parallel slots: 1.
- Offload: `--n-gpu-layers 0`; Flash Attention disabled.
- Purpose: functional/offline fallback, not a production latency claim.

CPU fallback uses the same model bytes, alias, prompt and schema so correctness
results remain attributable. Performance must be benchmarked on the destination
CPU before accepting an SLO.

## Clean-machine install contract

Until the full offline bundle is closed, use this as a staging checklist rather
than claiming a finished installer:

1. Clone the application at the approved Git revision.
2. Copy the signed/hashed offline sidecar bundle into the checkout, preserving
   the manifest-relative paths under `models/`.
3. Install the pinned Python runtime and wheelhouse from the sidecar; create
   `venv` without public-index access.
4. Install the pinned frontend cache/runtime, FFmpeg, database and queue runtime
   declared by the release bundle.
5. Copy `.env.example` to the deployment environment and set only local paths,
   loopback endpoints and secrets supplied by the operator.
6. Deny outbound network, then run all preflight and smoke gates below.

The bundle verifier is the source of truth for missing portable components:

```powershell
venv\Scripts\python.exe scripts\verify_offline_release_bundle.py `
  --json `
  --output docs/evals/runs/offline-bundle/latest.json
```

Current expected state is non-zero and `release_ready=false`. Do not bypass it
for a production clone.

## Artifact and hardware preflight

Run from the repository root with networking disabled:

```powershell
venv\Scripts\python.exe scripts\verify_llama_runtime.py --probe --json
venv\Scripts\python.exe scripts\model_store.py preflight `
  --model qwen.qwen3-8b-q4_k_m --json
```

GPU profile only:

```powershell
nvidia-smi `
  --query-gpu=name,memory.total,memory.used,memory.free,driver_version `
  --format=csv,noheader
```

CPU profile only:

```powershell
& models\runtimes\llama.cpp\b10331\windows-cuda-12.4-x64\bin\llama-server.exe `
  --version
```

Every preflight must identify runtime `b10331`, commit `7ba604f1c`, the expected
GPU for the CUDA profile, and zero manifest/hash issues.

## Start the server

GPU profile:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_llama_server.ps1
```

CPU functional profile, in a dedicated terminal after preflight:

```powershell
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$server = 'models\runtimes\llama.cpp\b10331\windows-cuda-12.4-x64\bin\llama-server.exe'
$model = 'models\qwen3\Qwen3-8B-Q4_K_M.gguf'
& $server `
  --model $model `
  --alias speechintel-qwen3-8b-q4_k_m `
  --host 127.0.0.1 `
  --port 8088 `
  --ctx-size 4096 `
  --n-gpu-layers 0 `
  --parallel 1 `
  --flash-attn off `
  --reasoning off `
  --jinja `
  --offline `
  --no-webui `
  --metrics `
  --slots
```

Do not run the GPU and CPU profiles simultaneously on port 8088.

## API and structured-output smoke

```powershell
Invoke-RestMethod http://127.0.0.1:8088/health
Invoke-RestMethod http://127.0.0.1:8088/v1/models

$body = @{
  model = 'speechintel-qwen3-8b-q4_k_m'
  messages = @(@{
    role = 'user'
    content = 'Tra ve JSON co truong status bang OK.'
  })
  temperature = 0
  max_tokens = 32
  reasoning_effort = 'none'
  response_format = @{
    type = 'json_object'
    schema = @{
      type = 'object'
      additionalProperties = $false
      properties = @{ status = @{ type = 'string'; const = 'OK' } }
      required = @('status')
    }
  }
} | ConvertTo-Json -Depth 10

$response = Invoke-RestMethod `
  -Uri http://127.0.0.1:8088/v1/chat/completions `
  -Method Post `
  -ContentType application/json `
  -Body $body
$response.choices[0].message.content | ConvertFrom-Json
```

The smoke fails if the model alias differs, the response is not parseable JSON,
`status` is not exactly `OK`, or extra fields are accepted.

## Full production-path smoke

Use the same frozen corpus, prompt/schema hashes and seed for every profile:

```powershell
venv\Scripts\python.exe scripts\benchmark_summary_runtime.py `
  --provider llama_cpp_server `
  --base-url http://127.0.0.1:8088 `
  --models speechintel-qwen3-8b-q4_k_m `
  --warmup 1 `
  --repetitions 3 `
  --load-states warm `
  --output docs/evals/runs/portable-qwen3-8b-q4.json
```

This is a synthetic runtime/contract gate. It does not prove investigative
quality. The current harness deliberately cannot promote a model while summary
claim support is not evaluable; retain that fail-closed behavior.

## Candidate promotion boundary

For each new model or quantization, record the official source URL, immutable
revision, license, exact file size/hash, conversion tool commit if applicable,
llama.cpp build, context/KV settings, prompt/schema/corpus hashes, GPU driver,
TTFT, prefill/decode token rates, end-to-end latency, peak RAM/VRAM and all raw
failures. Promote only after the Vietnamese human-labelled benchmark passes.

Schema-valid JSON proves syntax only. Critical fact recall, actor/action/object
roles, polarity/negation, exact identifiers, evidence precision and unsupported
claim count remain separate hard gates.
