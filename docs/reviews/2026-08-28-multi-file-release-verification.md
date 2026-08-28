# Multi-File STT Release Verification

**Date:** 2026-08-28
**Repository:** `https://github.com/tunguyen-195/getSomething`
**Branch:** `feature/architecture-refactor`
**RTK goal:** `01a047a2-7e3b-7312-a0e0-0640c9547545`

## Objective And Falsification

The feature passes only if one authorized case can atomically admit ordered
audio files, queue an exact transcription subset, create one merged summary
from an ordered hash-bound manifest with an optional untrusted prompt, restore
progress after refresh, and expose usable Analysis data without weakening the
existing single-file path. Duplicate rows, implicit source omission, prompt
leakage, stale worker code, a blank Analysis view, or a failing full suite
falsifies completion.

## Implemented Surface

- Migration-backed `AudioBatch`, `AudioBatchItem`, and
  `AudioBatchSummaryJob` persistence.
- Canonical V2 create/status/transcribe/cancel/summary endpoints.
- Atomic staged upload with 20-file, 100 MB/file, and 1 GB/batch limits.
- Creator/case authorization, replay-safe idempotency, ordered exact subsets,
  per-item status, cancellation, and safe error envelopes.
- Celery batch transcription and merged-summary jobs with source transcript
  SHA-256/revision revalidation before and after model execution.
- Optional 2,000-character `user_prompt` applied as untrusted preferences; raw
  prompt is excluded from persistence, logs, Celery results, and public API.
- Active React workflow for one multipart upload, selection, bulk actions,
  refresh recovery, merged-summary prompt/provenance, and responsive Analysis.

## Executed Gates

| Gate | Result |
| --- | --- |
| `python -m py_compile` on new batch API/service/worker modules | PASS |
| Focused batch contract/API/worker tests | `36 passed` |
| Full backend `python -m pytest tests -q` | `1256 passed, 1 skipped` |
| Frontend `npm test` | `50 passed` |
| Frontend `npm run lint` | PASS, zero warnings allowed |
| Frontend `npm run build` | PASS; Vite production bundle generated |
| Alembic downgrade/upgrade rehearsal | PASS |
| Alembic current/head | `f7a8b9c0d3 (head)` |
| OpenAPI canonical batch route inventory | PASS, all six routes present |
| Backend and pinned llama-server health | PASS on ports 8000 and 8088 |
| Live Celery runtime-contract probe after restart | PASS; both batch tasks registered |
| Playwright desktop/mobile Analysis inspection | PASS; structured content rendered without overlap |
| Playwright ordered two-file uploader smoke | PASS with a mocked 202 boundary; no case data persisted |
| `git diff --check` | PASS before release audit |

The frontend build reports a non-failing chunk-size warning. The current
environment's `pip check` also reports optional legacy `resemblyzer` and
`simple-diarizer` packages that are deliberately excluded from the canonical
requirements; a clean environment created from the pinned manifests is the
authoritative dependency gate. Frontend runtime audit has no high/critical
finding; one moderate transitive `yaml` advisory remains in the development
toolchain.

## Runtime Evidence

At verification time PostgreSQL, Redis, pinned llama-server, FastAPI, Celery
solo worker, and Vite were live on ports 5432, 6379, 8088, 8000, and 3000. The
first Celery probe correctly failed against a stale process. Restarting only
that worker made the implementation fingerprint match and registered:

```text
tasks.transcribe_audio_batch
tasks.summarize_audio_batch_job
```

Browser screenshots are generated under `output/playwright/` and intentionally
remain outside Git. They cover the Overview uploader, accepted ordered batch,
populated Analysis view, and 390x844 mobile layout.

## Clean-Machine And Model Policy

`docs/NEW_MACHINE_SETUP.md` is the canonical Windows bootstrap. Qwen3 GGUF,
llama.cpp b10331 and faster-whisper large-v2 are reproducibly downloadable by
the pinned installers and are not packed into Git. Pyannote 3.1 is gated by
Hugging Face terms/token, so it alone has package/restore scripts for a private
Drive transfer. Every acquired artifact is checked by size, SHA-256, immutable
revision and local cache reference before offline runtime is enabled.

## Residual Uncertainty

- RTX 3060 latency and sustained 20-file capacity must be measured on the new
  machine; the current evidence establishes compatibility gates, not that SLO.
- A true air-gapped production bundle remains blocked until installers,
  wheelhouse/npm cache, service runtimes and license artifacts are packaged and
  verified together. Online bootstrap followed by strict offline runtime is the
  supported path.
- The browser upload acceptance used a mocked HTTP 202 to avoid mutating real
  case evidence. Real endpoint persistence, authorization, rollback and replay
  behavior are covered by API/database tests; the target operator should run
  the non-sensitive two-file acceptance flow in the clean-machine runbook.
- Existing Pydantic/FastAPI deprecation warnings and the Vite chunk-size warning
  are maintenance work, not failures of this feature contract.
- `alembic check` on the long-lived development database reports legacy tables
  that still exist in PostgreSQL but are no longer represented in current
  SQLAlchemy metadata, and therefore proposes destructive `remove_table`
  operations. This pre-existing metadata drift is outside the batch migration;
  it must be reconciled in a separately reviewed migration rather than folded
  into this release. The batch revision itself passed downgrade/upgrade and the
  database is at `f7a8b9c0d3 (head)`.
