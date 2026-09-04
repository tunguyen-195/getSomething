# Multi-file analysis upgrade plan

## Objective

Make the multi-file workflow produce durable, inspectable analysis results. A
successful batch request must never overwrite one summary type with another,
and speaker labels from different files must remain distinguishable.

## Falsifiable requirements

1. A batch summary request may select one or more of `brief`, `detailed`,
   `investigation`, and `forensic`. The legacy singular `summary_type` request
   remains accepted.
2. Every selected type has one persisted result with its own status, text (when
   available), model/runtime metadata, and safe error code (when unavailable).
   Polling after a process restart returns the same results.
3. A result for one type cannot replace or mutate another type. Legacy clients
   still receive the selected singular result in `summary`.
4. The job status is `succeeded` when all selected types succeed, `partial` when
   at least one succeeds and one fails, and `failed` when none succeeds. The
   per-type status remains authoritative.
5. Diarization segments expose file-scoped provenance (`file_id`/`task_id` and
   a namespaced speaker key) while preserving the legacy local `speaker` field.
   Case-level visualizations group by file and never infer that `SPEAKER_00` in
   two files is the same person.
6. LLM unavailability is reported with a safe diagnostic and retryable result;
   it never produces a false successful summary or loses already-successful
   variants.

## Evidence collected

- `src/services/audio_batch_contracts.py` currently restricts batch summaries
  to `brief` and `detailed` and returns one `summary` field.
- `src/database/models/models.py` currently stores one `summary_id` on a batch
  job; the worker creates one `Summary(type="multi")` row.
- `src/services/summarization/summary_service_v2.py` supports the four semantic
  types for single-file requests, but multi-file investigation/forensic paths
  currently fail closed with explicit provider/release errors.
- Frontend Analysis currently flattens segments from multiple files, allowing
  local speaker labels to collide.

## Design

- Add `summary_types` (ordered, unique allow-list) to the batch request. If it
  is omitted, normalize the legacy `summary_type` to a one-element list.
- Add a JSON `summary_results` column to the existing job row. It stores a
  deterministic array keyed by `summary_type`; successful entries reference an
  individual `Summary` row, while failed entries retain only safe diagnostics.
  Keep `summary_id` as the legacy projection for compatibility.
- Execute selected types sequentially under the existing GPU lease. Persist
  each result independently and then derive the aggregate job status.
- Extend the public response with `summary_type` and `summary_results`; retain
  `summary` for legacy callers. Frontend renders one panel per type and shows
  unavailable types explicitly instead of replacing the whole output.
- Add file provenance to transcript segments and expose `file_groups` to the
  analysis/diarization UI. Speaker keys are namespaced by task/file.

## Test and release gates

- Contract tests: all four types, duplicate/empty selections, legacy requests.
- Worker tests: per-type persistence, no overwrite, partial/all failure,
  idempotent polling, LLM unavailable/retryable diagnostics.
- Diarization tests: two files with the same local speaker label remain distinct
  in API and UI projections.
- Backend: `python -m pytest tests` (with the repository's normal exclusions).
- Frontend: `npm test -- --runInBand`, lint, and production build.
- Migration: `alembic upgrade head` on a clean database and an existing batch
  database.
- Runtime: backend/frontend/worker/Redis/PostgreSQL/llama-server health plus a
  real two-file upload -> transcribe -> multi-summary -> Analysis flow.

## Residual risk

Investigation and forensic multi-file generation remain provider-gated in the
current summarization service. The new contract preserves their explicit
failure state and does not fabricate evidence; enabling those providers is a
separate model/runtime release gate.
