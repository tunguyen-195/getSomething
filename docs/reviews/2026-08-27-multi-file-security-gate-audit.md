# Multi-File Batch Security Gate Audit

> **Disposition 2026-08-28:** This is the pre-implementation gate audit and its
> BLOCK verdict describes the source inspected on 2026-08-27. The canonical V2
> persistence/API/worker/UI implementation now closes the listed P0/P1 gates
> through deterministic tests. Current executed evidence and residual risks are
> recorded in `docs/reviews/2026-08-28-multi-file-release-verification.md`.

**Date:** 2026-08-27
**Scope:** proposed batch upload, batch transcription, and merged-summary flow
**Primary plan:** `docs/plans/2026-08-27-optional-prompt-and-multi-file-workflow.md`
**Verdict:** **BLOCK** - the roadmap is directionally sound, but the current
compatibility endpoints and worker are not a secure canonical batch workflow.

## Objective And Evidence

This audit asks whether a batch request can be replayed, authorized, bounded,
processed, summarized, and returned without silently changing its source set or
exposing prompt/provider data. It is based on the current local source, not a
deployed environment or a live-model claim.

Evidence inspected:

- `src/api/endpoints/audio.py`: `/batch`, `/process-tasks`, `/summarize-multi`,
  and `/summarize-case`;
- `src/api/endpoints/audio_v2.py`: canonical single-file upload/transcribe/summary;
- `src/core/auth.py`: `assert_case_access` and `assert_task_access`;
- `src/services/audio_storage.py`: filename containment, staging, size, content,
  and SHA-256 checks;
- `src/services/audio_service.py`: file/Task/AudioFile transaction and cleanup;
- `src/worker/tasks/summarize_task.py`: `summarize_multi_task`;
- `src/services/summarization/summary_service_v2.py`: multi-source prompt and
  failure contracts;
- `src/database/models/models.py`: `Task`, `AudioFile`, and `Summary` storage.

During the audit, a concurrent backend/data change added draft `AudioBatch` and
`AudioBatchItem` models plus migration `f7a8b9c0d3`. The draft provides useful
status checks and unique `(user_id, case_id, idempotency_key)`, position, task,
and audio constraints. It does not yet provide an endpoint/repository/runtime
contract, source manifest, or summary job, so it reduces Phase 1 work but does
not change the BLOCK verdict.

## Existing Controls Worth Preserving

| Control | Current evidence | Assessment |
| --- | --- | --- |
| Case/task authorization | `assert_case_access` enforces role/action and archived-case rules; `assert_task_access` resolves the task before delegating to its case | Sound building block; canonical batch endpoints must call it before returning batch/item existence or enqueueing work |
| Path traversal prevention | `sanitize_upload_filename` rejects decoded separators, `.`/`..`, and unsupported suffixes; stored paths are UUID-based and `_ensure_under_root` contains reads/deletes | Good per-file containment; retain negative tests for encoded traversal, NUL, absolute paths, and both slash types |
| Per-file admission | `_copy_upload_to_temp` streams in 1 MiB chunks, rejects empty or over-limit files, runs `ffprobe`, computes SHA-256, and removes failed staging files | Good per-file control; it does not bound total multipart parsing or aggregate batch bytes |
| File/row compensation | `save_audio_and_create_task` uses `commit=False`, rolls the DB session back, and deletes staged/final files on failure | Good single-file behavior; batch-level atomicity/idempotency is still absent |
| Investigation release fail-closed | multi-file `investigation` summaries return `MULTI_INVESTIGATION_RELEASE_REQUIRED` | Preserve this until a hash-bound released case narrative exists |
| User preference privacy boundary | shared prompt work normalizes and renders `user_prompt` as a bounded untrusted preference and reports only `user_prompt_applied` | Apply the same rule to batch jobs; never store raw prompt in batch/job rows or public errors |

## Findings

### P0-1 - Selected sources can be silently omitted

`summarize_multi_task` appends a transcript only when a task/result/transcription
exists, and proceeds when at least one remains. The service independently filters
blank/non-string transcripts. Therefore `[ready, missing, ready]` can become a
successful two-source summary without an explicit omission record.

Security impact: the output appears to cover the operator's selection while its
evidence set changed. This violates fail-closed provenance and can conceal a
failed or tampered source.

Required gate: every selected manifest row must be present, authorized, in the
allowed transcript state, non-blank, revision/hash matched, and unique before any
GPU/LLM call. Any mismatch returns a typed non-retryable error and `llm_call_count=0`.

### P0-2 - No immutable source manifest or per-source prompt boundary exists

The worker accepts mutable `task_ids` and reloads current task results. The
service receives only strings, concatenates them into one block, and returns a
count. It has no ordered task/audio IDs, transcript revision IDs, transcript
hashes, manifest digest, or persisted summary job. A transcript can change
between submission and execution without detection.

The combined prompt also uses raw source text inside delimiter-like markup.
Escaping only `user_prompt` is insufficient: ASR/user-controlled transcript text
can itself contain closing tags, fake file labels, or instruction text.

Required manifest (`merged-summary-source-manifest-v1`):

```text
batch_id, case_id, ordered[position, task_id, audio_id, audio_sha256,
transcript_revision_id, transcript_sha256], manifest_sha256
```

The worker must load this persisted manifest, reauthorize its case ownership,
recompute every current source hash, and reject additions, omissions, duplicates,
reordering, or revision changes. Encode every transcript and every metadata value
with a reversible structured serializer before adding it to one envelope per
manifest row. Tests must decode each envelope back to the exact source and prove
that attacker-supplied closing tags do not create extra envelopes.

### P0-3 - Canonical authorization is not yet bound to one case

Existing compatibility endpoints authorize a case or each task, but the worker
does not verify that all `task_ids` belong to its `case_id`. The proposed endpoint
must reject cross-case selection even when the caller independently has access to
both cases. Broker task arguments must not be treated as authorization evidence.

Required gate: create the persisted manifest only after resolving every ID in one
DB query constrained by `batch_id`, `case_id`, active item membership, and caller
permission. The worker consumes a summary-job ID, not client-originated task IDs.
Unauthorized and foreign-case IDs must cause no task read outside the authorized
set, no enqueue, and no existence/detail leak.

### P0-4 - Batch upload has no count, aggregate-byte, or parser-level bound

`/batch` calls the upload limiter once, then accepts an unbounded list. The 100 MB
check is per file and occurs while the endpoint copies an already parsed
`UploadFile`. Multipart parsing/spooling can therefore consume disk before the
per-file loop runs. One request also consumes one hourly upload token regardless
of file count.

Required gate:

- application contract: `1 <= file_count <= 20`, per-file bytes <= 100 MB, and
  aggregate bytes <= the configured batch maximum;
- ingress contract: reverse proxy/ASGI multipart body, part-count, header, and
  spool limits reject oversized requests before unbounded temporary storage;
- rate accounting charges accepted file count and aggregate bytes, not only one
  request;
- filename has a bounded Unicode/encoded length and rejects control/bidi
  characters used for log/UI spoofing;
- all temporary files created by rejected, disconnected, or timed-out requests
  are removed and verified by a before/after directory inventory.

The `1 GB` roadmap default conflicts with `20 * 100 MB`; choose one explicit
aggregate limit based on target free disk and concurrency rather than assuming
the arithmetic maximum is safe.

### P1-1 - Idempotency has no durable contract

The compatibility upload loops over independently committed single-file writes.
A timeout followed by retry creates duplicate Task/AudioFile rows and files.
There is no parent batch, request fingerprint, unique key, summary job, or
idempotent finalizer.

Required gate: unique `(user_id, case_id, idempotency_key)` plus a server-derived
fingerprint over ordered content hashes and normalized options. Same key/same
fingerprint returns the original parent and items; same key/different fingerprint
returns `409` without mutation. Transcribe, cancel, finalizer, and merged-summary
submission each require their own idempotent state transition and uniqueness
constraint. Never use a raw prompt in the fingerprint; use the normalized prompt
only through an approved keyed digest, or keep it request-scoped and bind a random
summary-job idempotency key.

### P1-2 - Initial partial-upload semantics are ambiguous

The plan requires staging/validation before committing rows but also asks for
mixed-validity partial results. The current endpoint commits each success and
returns ad-hoc errors. This ambiguity makes replay and cleanup behavior
unverifiable.

Required decision before implementation: for the first canonical release prefer
atomic admission (one invalid item rejects the batch and cleans every staged
file). If partial admission is retained, persist every request position exactly
once with explicit `accepted` or `rejected` state in the same parent transaction,
and replay the identical result for the same idempotency key. In neither policy
may a rejected item appear in `task_ids` or a finalized file lack an item row.

### P1-3 - Compatibility paths can bypass selection/provenance limits

`/summarize-multi` accepts arbitrary transcript strings with no count or aggregate
character bound. Case summaries enumerate available transcripts and omit missing
ones; they do not capture explicit selection, stable ordering, or a manifest.
`/process-tasks` runs model work in an API `ThreadPoolExecutor`.

Required gate: after canonical cutover these routes either delegate to the same
batch/job contracts or return a documented deprecation response. They must not
remain a second state machine. Direct transcript input, if retained for a narrow
compatibility use, needs strict count/aggregate limits and must never claim
case-derived provenance.

### P1-4 - Public projection and privacy need a strict allowlist

The canonical status and summary responses must not serialize raw prompt,
transcript text, provider response/traceback, filesystem path, Celery broker
payload, release attestation internals, or unreviewed model metadata. Original
filenames are sensitive case data and may be returned only after batch access is
authorized.

Required gate: response models use `extra="forbid"` on input and a field allowlist
on output. Oversized/malformed values return safe typed errors without echoing
raw input. Logs contain stable IDs, counts, byte totals, hashes only where needed,
and error codes; never transcript/prompt content.

### P1-5 - Batch deletion and membership policy remain incomplete

The revised concurrent draft now validates UUID4 IDs, child binding case/owner,
audio-to-task pairing, exact item count, and succeeded/cancelled counters. It also
uses `RESTRICT` for AudioBatchItem references to Task and AudioFile. However, the
existing audio delete path still deletes those rows without a batch-aware policy,
so authorized deletion can become a foreign-key failure after batch admission.
Whether one Task/AudioFile may belong to more than one upload batch also remains
an application policy rather than a global constraint.

Required gate: document and test delete/archive behavior for batch, item, task,
audio, summary manifest, and stored file in both directions. Adapt the delete
endpoint to return a safe conflict or archive the source; never leak a database
exception. Choose and enforce duplicate membership policy explicitly.

### P1-6 - Draft backend/frontend contracts already diverge

Several initial mismatches were corrected during this audit: byte limits and
integer `audio_id` now match, and the backend added exact item count,
`cancelled_count`, UUID4, Unicode control checks, and matching response field
names/types. One state mismatch remains: backend items support
`cancel_requested`, while the frontend item enum does not. The final multipart
field name is also not testable until the endpoint exists.

A deterministic no-DB recheck confirmed the backend corrections: a response with
`requested_count=2, items=[]` is rejected, and aggregation of
`['failed', 'cancelled']` returns terminal counts `failed=1, cancelled=1`.

Required gate: generate or test all state/limit schemas from one canonical
backend artifact or one explicit API projection adapter, then run a static parity
test for limits, enums, field names, scalar types, multipart names, and terminal
counts.

### P1-7 - Replay ordering and creator-only policy need endpoint proof

The revised repository now fails on item-count mismatch and validates every
Task/AudioFile/case/user binding. It explicitly chooses creator-only batch access
for Phase 1, narrower than general case owner/member/admin action permissions.
That policy must be visible in product requirements and tested so authorized case
participants do not encounter unexplained behavior.

The remaining idempotency risk is orchestration order. The endpoint must
stage/hash first, detect an existing parent, and only then create new Task and
AudioFile bindings. If it creates bindings before discovering a successful
replay, the repository's replay branch correctly returns the old batch but ignores
the newly created bindings, leaving duplicates or orphans.

## Mandatory Test Matrix

| Gate | Deterministic test |
| --- | --- |
| Auth isolation | owner/member allowed per role; viewer cannot upload/process/cancel; foreign user and cross-case selected IDs cause no enqueue; archived case is read-only; batch/item/summary IDs do not expose foreign metadata |
| Idempotent upload | replay same key and bytes returns identical batch/item/task/audio IDs and creates no new file; same key with changed order/content/options returns `409`; concurrent same-key requests create one parent |
| Idempotent work | duplicate transcribe/cancel/finalizer/summary requests keep one legal state transition and one persisted result; retry after API/worker restart creates no duplicate tasks or summaries |
| Path/name | reject raw/percent-encoded `../`, `..\\`, absolute/UNC/device names, NUL, separators, unsupported extensions, overlong and control/bidi names; generated storage paths always resolve under the case root |
| Resource bounds | 0/1/20/21 files; per-file limit-1/limit/limit+1; aggregate limit-1/limit/limit+1; disconnect/timeout; assert no orphan spool/staging/final files and no rows after rejection |
| Media validation | extension/content mismatch, malformed container, zero audio stream, `ffprobe` timeout/unavailable return safe codes and no finalized file |
| Manifest closed set | duplicate IDs, missing transcript, failed/running task, blank source, foreign batch item, changed transcript revision/hash, reordered manifest, extra case file all fail before model call |
| Source rendering | each structured source envelope occurs once, decodes byte-for-byte, follows manifest order, and survives literal closing tags/fake labels/Unicode obfuscation without creating an instruction boundary |
| Prompt injection | blank prompt equals `None`; 2,000 Unicode chars pass and 2,001 fail without reflection; prompt requesting fabricated cross-file links or system data remains one escaped untrusted preference and cannot alter manifest/release gates |
| Privacy | recursively scan response, DB job/batch metadata, captured logs, exceptions, and Celery result for prompt sentinel, transcript sentinel, local path, provider traceback, and attestation fields |
| Failure/restart | one permanent and one transient item failure produce explicit parent counts; restart preserves ordered item state; no implicit omission; cancellation prevents new dispatch and is idempotent |
| Row lifecycle | parent/item case-owner equality; terminal counters recompute from items; Task/AudioFile delete/archive policy; duplicate membership; malformed batch UUID; no foreign-key failure leaks |
| Cross-layer parity | backend/frontend file and byte limits, status enums, ID scalar types, multipart field names, terminal counts, and safe errors are identical |
| Repository integrity | refresh never shrinks requested_count; item bindings prove Task/Audio/case/user equality; replay creates no ignored bindings; creator/member/admin policy is explicit |

## Completion Gates

The batch feature is security-ready only when all of the following are direct
test evidence:

1. migration constraints and concurrent idempotency tests pass on PostgreSQL;
2. ingress and application count/byte limits fail before unbounded spooling;
3. all object and action authorization occurs before retrieval/enqueue;
4. merged-summary worker consumes one persisted, ordered, hash-bound manifest and
   fails closed with zero model calls on any mismatch;
5. transcript and user-preference breakout tests pass with exact decoding;
6. public-response/log/DB/Celery privacy scans find no raw prompt, transcript,
   provider exception, or storage path outside explicitly authorized source views;
7. compatibility routes delegate or are disabled, with parity/deprecation tests;
8. restart, cancellation, retry, partial failure, and cleanup tests leave no
   duplicate rows, summaries, task dispatches, or orphan files.

## Residual Uncertainty

- Draft parent/item models and a migration now exist in the dirty tree, but no
  canonical endpoint/repository/runtime path exists yet; authorization,
  concurrency, migration downgrade, deletion, and idempotency remain unverified.
- ASGI/reverse-proxy multipart limits were not established from current source;
  a deployment-specific ingress rehearsal remains mandatory.
- This static audit did not execute audio/model workloads. Summary quality and
  resistance to semantic prompt injection require a separate fixed-corpus model
  evaluation after the deterministic source/release gates pass.
