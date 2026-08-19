# Lite RTX2050 Review Report

Date: 2026-05-04
Repo reviewed: `D:\Workspace\SpeechToInfomation-pr`
Branch: `feature/architecture-refactor-pr`

## Verdict

The Lite RTX2050 direction is technically reasonable, but this implementation is not ready to pull onto a clean machine yet. The current remote branch still points at `c1e7d143`; most Lite files are untracked or unstaged, and the runtime has several blocking correctness issues around background task state, migration portability, and the claimed API-first LLM flow.

## Findings

### Blocker: Lite work is not committed or pullable

`git status --porcelain=v2 --branch` shows `branch.ab +0 -0`, so the remote branch contains none of the Lite changes. Critical files such as `src/services/lite_runtime.py`, `src/services/transcription/asr_providers.py`, `src/api/endpoints/system.py`, both new Alembic migrations, `docker-compose.lite.yml`, and Lite scripts are untracked. `.env.lite.example` is also ignored by `.gitignore` because `.env.*` is ignored and only `.env.example` is re-included.

Fix: stage/commit/push the complete Lite change set. Add `!.env.lite.example` to `.gitignore` or rename the template to a non-ignored path.

### Blocker: Alembic chain depends on untracked migration

`a8c1d2e3f4b5_add_runtime_job_leases.py` has `down_revision = "f7a0b1c2d3e4"`, but the `f7a0b1c2d3e4_add_analysis_domain_templates.py` migration is untracked. A clean clone that receives only part of this work will not be able to resolve the migration graph.

Fix: include both migrations and the related model/service/router files, or split/rebase the migration chain so Lite does not depend on an omitted revision.

### High: Lite endpoint starts the background thread before marking task status

In `audio_v2.py`, transcribe/summarize/visualize call `start_lite_job(...)` first and update `Task.status` afterward. `start_lite_job` starts the thread before returning. If the background job fails or completes quickly, the request thread can overwrite a terminal state back to `transcribing`, `summarizing`, or `visualizing`. The docs describe the opposite order.

Fix: mark task status and commit before starting the thread, or make the background job the only writer for status transitions and remove post-start writes from the endpoint.

### High: Background failure state is flushed but not committed

`start_lite_job` catches exceptions and calls `update_task(..., db=job_db)`. With a supplied session, `update_task` only flushes; the session is then closed without commit, so the failed status can be rolled back while the lease is released. The UI can then show no active job while the task remains stuck in a processing state.

Fix: rollback any failed work, mark the task failed, and `job_db.commit()` before releasing the lease. Add tests for target exceptions before and after the target commits.

### High: API-first LLM contract is not implemented

`.env.lite.example` and docs configure `ANALYSIS_LLM_PROVIDER=openai`, but summarization still uses the Ollama-only `LLMManager` hard-coded to `http://localhost:11434`, and `analysis_intelligence.service` never calls the configured LLM provider. Runtime status can say LLM is configured even though the analysis path does not use the provider.

Fix: either implement the OpenAI-compatible provider with structured JSON/evidence validation, or downgrade docs/UI to say Lite currently has deterministic analysis plus legacy Ollama summarization only.

### Medium: PhoWhisper.cpp validation gate is weaker than the plan

The gate verifies model size/SHA and checks that a `.manifest.json` file exists. It does not validate source URL/license, source bundle hash, whisper-cli SHA/version, smoke-test status, parse status, or benchmark results. A dummy manifest can make the candidate visible.

Fix: parse and validate a strict manifest schema before setting `phowhisper_cpp_candidate_valid=true`.

### Medium: Lite tests are too thin for this change

`tests/test_lite_runtime.py` currently has three small tests for config/profile selection and candidate blocking. It does not cover lease contention, stale repair, background commit/release, Redis/Celery stopped, full-mode `async_mode=false`, whisper.cpp subprocess cleanup, or UI disabled state.

Fix: add backend contract tests for the DB lease and task state machine before treating Lite as ready.

### Medium: `WHISPER_BATCH_SIZE=1` is documented but not used by the new provider

The new provider runtime does not include or pass batch size into faster-whisper. The UI/docs claim `batch 1`, but the code path uses faster-whisper sequential transcribe without this setting.

Fix: either remove the batch-size claim from Lite docs/UI or wire it into the provider if a batched path is introduced.

### Medium: whisper.cpp subprocess output can grow unbounded

`subprocess.run(..., capture_output=True, text=True)` buffers stdout/stderr in memory for long audio. The benchmark gate includes conversations over 10 minutes, so this can waste RAM on the 12GB target machine.

Fix: write stderr/stdout to bounded temp files or suppress/limit logs, then parse the JSON output file.

### Medium: status endpoint still returns transcript and full result

`GET /api/v1/audio/v2/tasks/{task_id}/status` returns `transcript`, optional `segments`, `context_analysis`, and full `result`. This conflicts with the earlier privacy contract that list/status/polling should avoid raw transcript and keep transcript text behind a detail endpoint.

Fix: either explicitly scope that privacy contract out of Lite, or change polling to return metadata and use a detail endpoint for transcript text.

## Verification Run

- `python -m compileall src scripts -q`: pass.
- `python -m pytest tests/test_lite_runtime.py -q`: 3 passed, 2 Pydantic deprecation warnings.
- `cmd /c npm run build` in `frontend`: pass, with existing Vite chunk-size/CJS warnings.
- `alembic heads`: `a8c1d2e3f4b5 (head)`.
- `git diff --check`: no whitespace errors, CRLF warnings only.
- `git diff --cached --check`: pass.

## Clean-Machine Readiness

Not ready yet. A clean machine will not receive the Lite implementation until the complete set of tracked, untracked, and currently ignored files is committed and pushed. After that, the background job state and LLM-provider issues should be fixed before using the Lite branch for real audio processing.
