# Local LLM Runtime - Independent Audit

Date: 2026-08-09
Branch: `feature/architecture-refactor`
Snapshot: `674ca91d` with dirty target-owned runtime changes
Status: **BLOCK**

## Objective

Independently review the repository-local `llama-server` / OpenAI-compatible
path for strict offline operation, approved-model binding, structured-output
safety, benchmark integrity, and single-GPU lifecycle control.

## Verdict

The pinned runtime and model manifests are a useful packaging baseline, and the
request envelope matches the pinned llama.cpp API. The current application path
is not ready for production investigative data. A configuration error, proxy,
or redirect can transmit prompts outside loopback; an unapproved loaded model
can be selected or reported with the approved manifest digest; structured and
streaming failures can be returned as successful text; and the external server
can retain VRAM after the repository GPU lease is released.

## Findings

### Critical - strict offline mode does not close the network path

- `src/core/config.py` declares `OFFLINE_STRICT`, but the OpenAI-compatible path
  does not require a literal loopback address.
- `OpenAICompatibleClient` accepts any base URL, uses a default
  `requests.Session` with environment proxy support, follows redirects, and
  sends the complete prompt to the configured endpoint.
- A mock probe accepted `http://192.0.2.55:8088`; no offline or loopback guard
  rejected it.

Required gate: parse the URL, allow only `http` over an explicit loopback IP and
approved port in strict mode, disable environment proxies, disable redirects,
and reject any resolved or redirected non-loopback destination before a prompt
or API credential is sent.

### High - model allowlist and provenance binding fail open

- When the configured llama-server alias is absent, model selection returns the
  first advertised model.
- The Ollama path also falls through to priority or first-installed models, and
  an explicit caller model bypasses the configured default selection.
- Availability checks model IDs only; they do not bind the server process,
  loaded model path, or loaded model bytes to the approved manifests.
- The benchmark copies the approved Qwen digest and size from the local manifest
  into every requested advertised model. It hashes only the `/props` model-path
  string, not the loaded file bytes.
- A mock rogue-server probe reported `installed=true` and the approved
  `d98cdc...` digest for `C:/rogue/other.gguf`.

Required gate: use one release profile manifest as the only source of model ID,
alias, path, byte size, SHA-256, runtime build, template digest, and decoding
configuration. Refuse startup, request execution, benchmark, and promotion on
any mismatch. Never use `models[0]` in a production profile.

### High - structured-output failure is downgraded to successful free text

- The context analyzer can produce an explicit failed structured result, but
  the summary service then performs a separate unconstrained text generation
  and returns `available=true`.
- A mock probe converted `INVALID_STRUCTURED_OUTPUT` into a successful dedicated
  LLM summary.
- The forensic path can silently fall through to ordinary detailed or
  investigation output when its specialist runtime is unavailable or raises,
  while preserving a forensic-facing request label.

Required gate: investigation and forensic requests must fail closed or return a
visible degraded diagnostic state. They must not substitute an unconstrained
summary or another semantic mode without explicit user-visible authorization.

### High - single-GPU lifecycle is not enforced across processes

- `scripts/start_llama_server.ps1` checks free VRAM but does not acquire the
  repository cross-process GPU lease.
- For the external server provider, `LLMManager.unload_model()` reports cleanup
  while performing no unload.
- The summary service ignores whether cleanup actually released model state.
- The server can therefore retain VRAM after the application lease is released,
  allowing ASR or diarization to begin against an occupied GPU.

Required gate: implement one lifecycle coordinator for server start, wake,
sleep, stop, and audio-stage admission. If llama.cpp idle sleep is used, verify
`/props.is_sleeping`, measured VRAM release, wake latency, timeout behavior, and
failure recovery before granting the GPU to ASR or diarization.

### High - streaming and termination handling fail open

- Malformed SSE JSON lines are ignored.
- `[DONE]` is skipped rather than treated as a terminal protocol event.
- Empty or truncated streams can return a successful result.
- Non-streaming and streaming paths do not reject truncating finish reasons such
  as `length`.
- Existing tests cover only a successful SSE stream.

Required gate: reject malformed events, missing terminal state, empty output,
unexpected event shapes, server error events, and any non-accepted finish
reason. Add negative protocol fixtures and bounded-size/error-body handling.

### Medium - Ollama benchmark preflight and execution can target different servers

- Ollama preflight reads `BenchmarkConfig.base_url`.
- Runtime execution remains hard-coded to `localhost:11434`.
- A report can therefore describe one endpoint while measuring another.
- The current promotion gate cannot pass because summary claim support is marked
  non-evaluable; this prevents a false promotion but also means the harness is
  not yet a usable quality gate.

Required gate: inject the same immutable endpoint/provider profile into both
preflight and execution, then bind the report to that profile digest.

### Medium - documentation exceeds current live evidence

- Research text names llama-server as the production choice and describes a 16K
  balanced context, while tracked startup/config currently use 8192.
- Current evidence does not include a successful live CUDA request benchmark or
  a human-labelled Vietnamese/noisy-ASR investigative release set.

Required gate: keep this path labelled `candidate` until live runtime evidence,
resource measurements, and human-labelled quality gates pass. Reconcile the
context value across manifest, startup, config, benchmark, and documentation.

## Positive Evidence

- The pinned llama.cpp `b10331` server documentation confirms that
  `response_format={"type":"json_schema","schema":...}` is accepted. The
  response envelope is not a finding.
- The startup script keeps the API key out of the process command line.
- No direct API-key logging was found in the reviewed path.
- Python AST parsing passed for the reviewed target files.

## Harness Evidence And Limitations

Reviewed files:

- `src/core/config.py`
- `src/services/summarization/models/openai_compatible_client.py`
- `src/services/summarization/models/llm_manager.py`
- `src/services/summarization/summary_service_v2.py`
- `scripts/start_llama_server.ps1`
- `scripts/benchmark_summary_runtime.py`
- `tests/test_openai_compatible_llm.py`
- `tests/test_summary_runtime_benchmark.py`
- `docs/runbooks/local-llm-llama-server.md`
- `docs/research/local-ai-stack-2026-08-09.md`

Source check:

- pinned upstream README:
  `https://raw.githubusercontent.com/ggml-org/llama.cpp/7ba604f1c/tools/server/README.md`

One targeted pytest attempt produced `7 passed` and two database setup/teardown
errors because another process concurrently reset the shared PostgreSQL test
database. Those database errors are concurrency contamination, not runtime test
regressions, and must not be used as pass/fail evidence. Subsequent probes were
mock-only and did not access the database, GPU, model, or network runtime.

## Release Gates

Production status remains BLOCKED until all of these pass:

1. network-denial tests prove prompts and credentials cannot leave loopback;
2. the running runtime/model/template bytes match the signed release manifest;
3. malformed, empty, truncated, and structurally invalid output fails closed;
4. forensic/investigation semantic modes cannot silently downgrade;
5. the external server demonstrably sleeps/stops and releases VRAM before audio
   stages receive the GPU lease;
6. preflight and execution use the same immutable endpoint/profile;
7. a live CUDA benchmark and human-labelled Vietnamese/noisy-ASR quality set
   pass without unsupported investigative claims.
