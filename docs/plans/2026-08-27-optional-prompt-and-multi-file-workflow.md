# Plan: Optional Summary Prompt And Multi-File Workflow

**Date:** 2026-08-27
**Repository:** `https://github.com/tunguyen-195/getSomething`
**Branch:** `feature/architecture-refactor`
**RTK goal:** `01a019fa-ef7f-7022-be50-7e5eb1c69908`
**Status:** Research and implementation plan; no multi-file implementation is approved by this document alone.

## 1. Goal

Deliver one auditable workflow in which an operator can:

1. select and upload several audio files into one case;
2. queue transcription for the selected files without holding the HTTP request open;
3. monitor each file and the parent batch independently;
4. select a deterministic set of completed transcripts and create one merged summary;
5. optionally provide a user summary prompt that survives upload-independent summary paths;
6. inspect the transcript and merged-summary provenance in the existing Transcript and Summary tabs.

The existing single-file flow must remain behaviorally compatible. A blank prompt is equivalent to no prompt. A non-blank prompt may control focus or presentation only; it cannot override transcript-as-data, grounding, release, privacy, or output contracts.

## 2. Evidence From Current Source

The following observations were made against the current checkout, not inferred from old reports:

| Surface | Current evidence | Consequence |
| --- | --- | --- |
| Active upload UI | `frontend/src/App.tsx` mounts `frontend/src/components/CompactUploader.tsx`; `CompactUploader.handleUpload` loops over files and calls `/api/v1/audio/upload` once per file | The UI looks multi-file but has no parent batch, per-file response mapping, retry, or batch progress identity |
| Existing batch upload | `src/api/endpoints/audio.py:1143` exposes `/batch` and loops `save_audio_and_create_task` | It is a compatibility endpoint, not a durable batch job; partial failures are returned as ad-hoc rows and there is no idempotency key |
| Existing multi processing | `src/api/endpoints/audio.py:1097` exposes `/process-tasks` and invokes `_process_task_in_worker` through `ThreadPoolExecutor` | Long ASR work runs inside the API process and can contend for GPU/model state; it is not the canonical Celery path |
| Single transcription | `src/api/endpoints/audio_v2.py:146` exposes `/transcribe/{task_id}` and queues one `transcribe_audio_task` | There is no V2 parent batch endpoint or aggregate status contract |
| Single summary | `src/api/endpoints/audio_v2.py:181` exposes `/summarize/{task_id}`; current work now carries `user_prompt` | This is the correct contract to reuse for each selected summary path |
| Multi summary service | `src/services/summarization/summary_service_v2.py:1579` has `summarize_multi_transcripts_v2`; it concatenates normalized transcripts in input order and already has context-budget/release checks | The generation primitive exists, but source selection, ordering, manifest, persistence, and async orchestration are missing |
| Multi summary worker | `src/worker/tasks/summarize_task.py:336` has `summarize_multi_task(task_ids, ...)` | The worker can be extended to consume a durable batch manifest; it currently silently skips tasks without transcripts |
| Storage and limits | `src/services/audio_storage.py` streams each upload, validates extension/content and enforces `settings.MAX_UPLOAD_SIZE` (100 MB); `src/core/config.py` has upload/process hourly limits | Per-file safety exists; aggregate count/bytes and request-level rate accounting do not |
| Persistence | `src/database/models/models.py` has `Task`, `AudioFile`, and `Summary`; `Task.result` is JSON and `Summary.files` is JSONB | A first-class batch parent/item model is required for durable progress, idempotency, and source provenance |
| Current tests | Focused summary/security tests exist; no complete upload -> batch-transcribe -> merged-summary browser or API contract test | New tests must be added before claiming the feature is complete |

## 3. Product Contract

### 3.1 User-visible behavior

- The Overview uploader accepts several audio files in one selection or drag/drop operation.
- The server returns a `batch_id` and one item record per submitted file. A rejected file never appears as a successful item.
- The UI shows aggregate progress and per-file status. Refreshing the page does not lose the batch because status is persisted server-side.
- Bulk Transcribe acts on selected uploaded files. It does not automatically create summaries.
- “Merged Summary” acts only on selected files with released/usable transcripts. The default policy rejects an incomplete selection instead of silently omitting files.
- The Summary tab distinguishes per-file summaries from a merged summary and lists the source filenames/order without exposing internal model/provider details.
- A user prompt is optional. Whitespace is omitted. The canonical field is `user_prompt`, bounded to 2,000 Unicode characters and marked as an untrusted preference.

### 3.2 Non-goals for the first release

- No archive/ZIP extraction.
- No cross-case merge.
- No automatic concatenation of every transcript in a case without an explicit selection or explicit “all completed” action.
- No parallel GPU inference in the default solo-worker profile. Celery may fan out queue messages, but the GPU lease and worker profile remain serialized unless a separately benchmarked profile is enabled.
- No storage of raw user prompts in logs, error strings, public response projections, or batch metadata. If auditability requires it, store only a keyed hash and `user_prompt_applied` boolean after a separate privacy review.

## 4. Canonical API And Data Design

### 4.1 Batch entities

Add a migration-backed parent/item model rather than encoding a batch only in `Task.result`:

`AudioBatch`:

- `id` UUID/string primary key;
- `case_id`, `user_id` foreign keys;
- `status`: `created`, `queued`, `processing`, `partially_succeeded`, `succeeded`, `failed`, `cancel_requested`, `cancelled`;
- `requested_count`, `completed_count`, `failed_count`;
- `upload_options` JSON containing only non-sensitive operational options;
- `idempotency_key` scoped to user and case with a unique constraint;
- timestamps and a safe aggregate error code.

`AudioBatchItem`:

- `batch_id`, `task_id`, `audio_id` foreign keys;
- immutable `position` (zero-based request order);
- original filename and verified audio SHA-256;
- `status`, `error_code`, `celery_task_id`, timestamps;
- unique `(batch_id, position)` and `(batch_id, task_id)` constraints.

The merged summary must retain a source manifest in `Summary.files` or a new JSONB field containing ordered task/audio IDs, filenames, transcript SHA-256 values, and source revision identifiers. It must not retain the raw prompt by default.

### 4.2 Endpoints

Keep old endpoints for compatibility but define one canonical V2 surface:

| Endpoint | Contract |
| --- | --- |
| `POST /api/v1/audio/v2/batches` | `multipart/form-data`: `files[]`, `case_id`, `idempotency_key`, transcription options. Enforce `BATCH_MAX_FILES=20`, aggregate bytes <= 1 GB by default, and per-file existing 100 MB limit. Stage and validate files before committing item rows. Return `202` with `batch_id`, item rows, and initial status. |
| `GET /api/v1/audio/v2/batches/{batch_id}` | Authorized aggregate status, item status, progress, safe error codes, and ordered file metadata. No raw traceback, prompt, or provider response. |
| `POST /api/v1/audio/v2/batches/{batch_id}/transcribe` | Body contains diarization/language options. Verify all items belong to the caller/case, reject duplicate or already-running requests, queue Celery orchestration, return `202`. |
| `POST /api/v1/audio/v2/batches/{batch_id}/summary` | Body contains selected ordered `task_ids`, shared summary options, and optional `user_prompt`. Default requires every selected item to be transcript-ready. Return `202` with a summary job ID or `200` only for a deliberately synchronous compatibility mode. |
| `GET /api/v1/audio/v2/batches/{batch_id}/summary/{summary_job_id}` | Return safe summary status, final public projection, ordered source manifest, and `user_prompt_applied`; never return the raw prompt. |
| `POST /api/v1/audio/v2/batches/{batch_id}/cancel` | Mark queued work cancel-requested and prevent new item tasks. Running model calls finish or fail safely; cancellation is idempotent. |

For compatibility, `/api/v1/audio/batch`, `/process-tasks`, `/summarize-multi`, and `/summarize-case` must either delegate to the canonical implementation or be clearly marked legacy and covered by parity tests. They must not retain a second, conflicting batch state machine.

### 4.3 State and failure semantics

Use explicit item and parent transitions. A failed item is not silently removed. Parent completion is:

- `succeeded` when every requested item succeeds;
- `partially_succeeded` when at least one item succeeds and at least one fails;
- `failed` when no item succeeds or the parent contract fails before work starts.

Merged summary defaults to fail closed when any selected item is not `transcribed` or its transcript integrity/release contract is invalid. An explicit future `allow_partial=true` mode must record omitted IDs in the source manifest and UI; it must never be an implicit fallback.

## 5. Worker Orchestration

Use Celery Canvas primitives for orchestration:

1. Parent endpoint validates authorization, limits, idempotency, and item state.
2. A `group(transcribe_audio_task.s(item.task_id, ...))` queues item work.
3. A callback/chord finalizer reads persisted item states, computes aggregate counts, and writes the parent state. The callback must tolerate one or more item failures and must be idempotent.
4. Summary submission captures the ordered selected IDs and transcript hashes before queueing `summarize_multi_task`.
5. The summary worker loads exactly that manifest, rejects missing/changed transcripts, calls `summarize_multi_transcripts_v2`, persists the safe `Summary` projection, and updates the summary job.

Celery documentation defines `group` as parallel task application and `chord` as a group with a callback after all header tasks complete. The local worker is configured as solo/concurrency 1 for the GPU profile, so orchestration parallelism must not be confused with concurrent model execution. Item tasks must be idempotent; retries must be limited to transient failures and must not create duplicate files, summaries, or database rows.

## 6. Prompt And Grounding Rules For Merged Summary

Reuse the shared `user_prompt` contract from the current single-summary work:

- normalize at HTTP, worker, and service boundaries;
- trim; blank becomes `None`;
- maximum 2,000 Unicode characters;
- no raw prompt in logs, exception text, or public projections;
- include it only in an escaped, delimited block such as `<user_preferences trust="untrusted">...`;
- escape delimiter metacharacters before interpolation;
- state outside the block that it can affect focus or presentation only;
- place transcript/source/release constraints after or above the preference block so the user text cannot downgrade them;
- record only `user_prompt_applied` and, if approved, a non-reversible prompt hash.

For multi-file generation, each source must have a stable boundary and position, for example `<transcript file_index="0" task_id="...">`. The service must verify that each source appears exactly once in the model prompt and that the generated metadata points to the same ordered manifest. A prompt saying “ignore previous instructions”, asking for fabricated links between files, or asking to reveal system data is test input, not an authority escalation.

## 7. Frontend Workstream

The active `App.tsx` path should own the workflow; orphaned legacy screens should not become a second implementation.

1. Extend `CompactUploader` to submit one multipart batch request, preserve selected order, show per-file accepted/rejected rows, and retain the returned `batch_id`.
2. Add typed API client methods for batch status, bulk transcription, merged summary, cancellation, and safe error envelopes.
3. Add selection checkboxes and a stable bulk-action toolbar to `FileTable`. Keep single-file buttons as a compatibility path.
4. Add a batch progress/status region in Overview and Transcript tabs. Poll with backoff and stop on terminal states.
5. Add a merged-summary action/dialog with summary type, optional prompt, source-count confirmation, and an explicit incomplete-source error. Reuse the 2,000-character Unicode counter and blank omission.
6. Render merged summary separately from per-file summaries, including ordered source filenames and `user_prompt_applied` only.
7. Handle refresh, auth expiry, cancellation, retryable failure, partial success, and mobile layouts without overlapping controls.

## 8. Dev-Team Phases And Ownership

### Phase 0 - Contract lock and baseline

- Freeze current prompt diff and record the staged/unstaged tree.
- Add machine-readable limits and state vocabularies.
- Write request/response examples and a migration compatibility table.
- Gate: single-file prompt tests pass; no multi code is merged until the contract is reviewed.

**Owner:** primary/release owner.

### Phase 1 - Persistence and shared contracts

- Add `AudioBatch`/`AudioBatchItem` models, migration, indexes, constraints, and repository helpers.
- Add Pydantic request/response models with strict extras, aggregate limits, duplicate detection, and safe error codes.
- Gate: fresh database migration, downgrade rehearsal, idempotency/authorization unit tests.

**Owner:** backend/data owner.

### Phase 2 - Upload batch

- Implement canonical multipart batch endpoint using streaming staging and existing audio validation.
- Define partial-upload semantics, cleanup on failure, audit event, rate-limit accounting, and safe response projection.
- Replace active `CompactUploader` loop with one batch request.
- Gate: 1, 5, 20 valid files; mixed invalid files; oversized aggregate; duplicate idempotency replay; no orphan temp files or rows.

**Owners:** backend + frontend.

### Phase 3 - Batch transcription

- Add Celery group/chord orchestration and parent/item progress persistence.
- Reuse `transcribe_audio_task`; remove direct API `ThreadPoolExecutor` from the canonical path.
- Implement retry/cancel/idempotency behavior and serialized GPU lease verification.
- Gate: fake-ASR 20-item run, one transient retry, one permanent failure, restart/poll recovery, and no duplicate task IDs.

**Owners:** worker/backend.

### Phase 4 - Merged summary

- Add summary job persistence and ordered source manifest/hash capture.
- Extend multi-summary worker/service to reject incomplete or changed source input and to propagate `user_prompt`.
- Persist a public merged summary projection without raw prompt/provider internals.
- Gate: one/two/many transcript generation, long-source hierarchical fallback, prompt blank/non-blank parity, injection delimiter escape, source occurrence count, and fail-closed release behavior.

**Owners:** summarization/backend/security.

### Phase 5 - UI workflow

- Add bulk selection/actions, progress, merged-summary dialog, result cards, and responsive states.
- Keep active tab navigation coherent and refresh-safe.
- Gate: Playwright desktop/mobile upload -> transcribe -> merged summary -> refresh; network payload assertions; keyboard/accessibility smoke.

**Owners:** frontend/UI.

### Phase 6 - Verification and release

- Run focused and full backend/frontend suites, compile/type/lint/build, migration checks, secret scan, and dependency checks.
- Run deterministic performance benchmarks at 1/5/10/20 files with model/config/seed recorded.
- Run native services in documented order, then a clean clone rehearsal from the pushed commit.
- Gate: every requirement in this plan maps to a passing command/artifact; unresolved gaps are listed as blockers.

**Owner:** primary/release owner with independent verifier.

## 9. Test Matrix

### Contract and security

- maximum file count, per-file bytes, aggregate bytes, invalid media, duplicate filenames, path traversal, malformed IDs;
- cross-user and cross-case batch/item access denied;
- idempotency replay returns the original batch without duplicate rows/files;
- partial upload and partial transcription retain explicit per-item errors;
- cancellation is idempotent and cannot cancel another user's batch;
- blank/whitespace prompt is omitted and produces the same prompt/runtime contract as `None`;
- 2,000 Unicode characters pass and 2,001 fail without leaking input in HTTP errors;
- hostile prompt, embedded closing tag, Unicode obfuscation, and “ignore grounding” text remain untrusted data;
- public responses never contain raw prompt, provider traceback, task attestation, or unapproved metadata.

### Integration and persistence

- fresh Alembic database reaches one head and stores parent/item rows with foreign-key/index checks;
- batch status survives API restart and polling order is deterministic;
- selected transcript hash mismatch fails closed before LLM work;
- merged summary records exactly selected ordered sources and no implicit extra case files;
- legacy endpoints delegate or return a documented compatibility response.

### Frontend and browser

- one multipart request for N files, per-file result mapping, retryable error state;
- bulk selection does not submit uploaded-only or cross-case IDs;
- progress reaches terminal parent/item states and survives reload;
- merged summary prompt is trimmed/omitted and over-limit submit is disabled;
- Summary and Transcript tabs render per-file and merged artifacts without overlap at desktop/mobile widths.

### Performance

Record hardware profile, Python/Node versions, ASR/LLM model revisions, worker concurrency, file count, total duration/bytes, queue latency, per-item latency, wall time, peak RAM/VRAM, retry count, and failure disposition. The benchmark is a capacity/contract gate, not a claim of summary quality.

## 10. Verification Commands

Focused backend and security:

```powershell
venv\Scripts\python.exe -m pytest tests/test_summary_request_contract.py tests/test_summary_user_prompt_security.py tests/test_batch_workflow_contract.py -q
```

Full backend:

```powershell
venv\Scripts\python.exe -m pytest tests -q
```

Frontend:

```powershell
Set-Location frontend
npm test
npm run lint
npm run build
Set-Location ..
```

Migration and runtime:

```powershell
venv\Scripts\python.exe -m alembic upgrade head
venv\Scripts\python.exe -m alembic heads
powershell -ExecutionPolicy Bypass -File scripts\preflight_new_machine.ps1 `
  -HardwareProfile gpu12gb `
  -OutputPath docs\evals\runs\new-machine-preflight.json
venv\Scripts\python.exe scripts\probe_celery_worker_contract.py --timeout 30 --json
```

This command is a planned gate; its result must be captured before release and must not be inferred from a local healthy process list.

Browser verification follows the repository Playwright skill and stores screenshots under `output/playwright/`:

```powershell
Get-Command npx
& C:\Users\Admin\.codex\skills\playwright\scripts\playwright_cli.sh open http://127.0.0.1:3000 --headed
```

## 11. Release Gate

The feature is complete only when all of these are true:

- the active UI uses the canonical batch API and can recover a batch after refresh;
- all selected files have explicit parent/item status and no hidden omissions;
- Celery, not an API thread pool, owns long-running batch transcription;
- merged summaries use a persisted, ordered, hash-bound source manifest;
- optional prompt behavior is identical across single, resummarize, async, and merged paths;
- grounding, release, transcript-as-data, and public-projection security tests pass;
- fresh migration, full backend suite, frontend test/lint/build, runtime health, Celery probe, and browser smoke pass;
- the staged tree has no secrets, raw case artifacts, generated browser state, or undeclared runtime imports;
- the pushed commit reproduces the same gates from an independent clone.

Until these checks pass, the honest status is “single-file flow functional; multi-file feature in planned implementation,” not “multi-file production ready.”

## 12. Primary Sources Used

- FastAPI, “Request Files / Multiple File Uploads”: <https://fastapi.tiangolo.com/tutorial/request-files/>. It documents `List[UploadFile]` multipart handling and is relevant to the upload endpoint shape.
- Celery, “Canvas: Designing Work-flows”: <https://docs.celeryq.dev/en/stable/userguide/canvas.html>. It defines `group` and `chord` semantics used for the orchestration design.
- Celery, “Tasks”: <https://docs.celeryq.dev/en/stable/userguide/tasks.html>. It documents late acknowledgement, retry behavior, and the requirement that retried tasks be idempotent.
- PostgreSQL, “Constraints”: <https://www.postgresql.org/docs/current/ddl-constraints.html>. It documents foreign-key referential integrity and index/constraint considerations for parent/item persistence.
- OWASP, “LLM Prompt Injection Prevention Cheat Sheet”: <https://github.com/OWASP/CheatSheetSeries/blob/master/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.md>. It motivates structured separation of instructions and untrusted data; this plan treats prompt text as untrusted preference and retains application-side release/grounding gates.
