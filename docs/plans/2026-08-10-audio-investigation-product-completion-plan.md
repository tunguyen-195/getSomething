# Audio Investigation Product Completion Plan

**Date:** 2026-08-10

**Workspace:** `E:\research\STT`

**Input:** `docs/research/2026-08-10-audio-investigation-product-patterns.md`

## Objective

Deliver a usable offline product for investigators that can ingest an audio
file and present:

- a reliable transcript and honest diarization state;
- all detected people, organizations, places, exact values, quantities, roles,
  events, relationships, and explicit flows;
- a described-event timeline;
- a complete readable investigation summary;
- bounded insights, contradictions, and gaps;
- deterministic visual views over the same modeled data.

The main Analysis UI will not show evidence quotes, segment IDs, or audio
offsets. Internal evidence binding remains mandatory for correctness.

## Definition of product done

A file is complete only when one current `AnalysisArtifact` exists and:

1. the transcript revision and diarization revision are frozen;
2. every transcript segment was processed or the artifact is visibly partial;
3. diarization is one of `verified_one_speaker`, `multi_speaker`,
   `degraded`, `unavailable`, or `failed`;
4. entities, exact values, events, relations, flows, and timeline are projected
   from the artifact;
5. Summary, Analysis, and Visualization share the same artifact ID/version;
6. stale artifacts are invalidated after transcript, diarization, or analyst
   correction;
7. desktop/mobile UI shows the useful content without raw technical evidence;
8. synchronous, async, persistence, restart, and offline paths behave the same.

## Delivery tracks

### Track A - Stop false success and create one Analysis owner

**Goal:** replace `/summaries/analyze` as the production owner.

Tasks:

1. Add a versioned `AnalysisArtifact` contract and persistence field/table.
2. Add idempotent `POST /api/v1/analysis/tasks/{task_id}/run`.
3. Persist lifecycle state, artifact version, source revisions, model/runtime
   profile, coverage, and failure/degraded reason.
4. Treat deterministic transcript fallback as `partial`, never
   `analysis_status=success` or released authority.
5. Invalidate legacy `deterministic-transcript-fallback-v1` and any artifact
   whose transcript/diarization revision changed.
6. Keep `/summaries/analyze` only as a compatibility adapter until the frontend
   cutover, then deprecate it.

Primary files:

- `src/api/endpoints/analysis.py` (new)
- `src/services/investigation/analysis_service.py` (new)
- `src/services/investigation/run_contracts.py`
- `src/services/task_service.py`
- database schemas/migration
- `src/worker/tasks/analyze_task.py` (new)

Acceptance:

- repeated requests return/reuse the same current run;
- stale v1 cache is recomputed;
- partial/failure can never render as ready;
- restart does not lose state;
- Summary input text is not used as Analysis source.

### Track B - Repair diarization as a product runtime

**Goal:** accurately distinguish who spoke when and never disguise failure as
one speaker.

Tasks:

1. Use an isolated diarization runtime rather than upgrading the shared ASR
   venv in place. Pin Python, Pyannote 4.x, Torch/Torchaudio/TorchCodec, CUDA,
   FFmpeg, and license metadata.
2. Acquire the exact Community-1 model revision into one absolute repo-local
   root with a full file/hash manifest.
3. Disable Pyannote telemetry in the offline product profile.
4. Update the adapter for the 4.x `token` API and output object
   (`speaker_diarization` and `exclusive_speaker_diarization`).
5. Support exact/min/max speaker hints, overlap state, and word-aware ASR
   assignment.
6. Persist requested engine, engine used, model revision/hash, speaker count,
   status, fallback reason, and ambiguity.
7. Add analyst correction for speaker labels and optional case-local identity
   mapping as a new revision.
8. Keep NeMo Sortformer as a second product profile for hard overlap/long audio
   after the default path is stable.

Primary files:

- `src/services/transcription/models/pyannote_manager.py`
- `src/cherry_core/adapters/diarization/pyannote_adapter.py`
- `src/services/transcription/transcribe_service_v2.py`
- `src/services/transcription/cherry_transcription_service.py`
- `src/services/model_runtime/`
- acquisition/verify/start/recovery scripts
- Transcript/Diarization frontend components

Acceptance:

- missing model -> `unavailable`, not one speaker;
- valid one-person audio -> `verified_one_speaker`;
- multi-speaker fixture returns multiple stable file-local speakers;
- overlap/tie remains ambiguous instead of forced;
- network-denied load and restart pass;
- UI exposes status/model/fallback but Analysis does not expose audio offsets.

### Track C - Full-transcript extraction and investigation modeling

**Goal:** model the whole conversation, not selected sentences.

Tasks:

1. Scan every transcript segment with a coverage manifest.
2. Run strict exact-value detectors over every segment.
3. Run chunked LLM discovery for typed atomic statements, entity mentions,
   roles, events, relationships, and flows.
4. Reuse T3 discovery, T4 deterministic verification, canonicalization,
   contradiction, and T5 release code already present.
5. Separate mention from canonical entity. Keep every occurrence count and
   alias, but merge identities only under conservative rules or analyst review.
6. Add a Vietnamese NER candidate stage with language-specific models and a
   false-positive filter. Do not use current broad case-insensitive person or
   location cue regexes.
7. Model described event time independently from audio occurrence.
8. Model source/destination, amount/unit/object/channel for money, goods, and
   communication flows.
9. Generate contradictions and gaps before insights.

Primary files:

- `src/services/investigation/discovery.py`
- `src/services/investigation/verification.py`
- `src/services/investigation/canonicalization.py`
- `src/services/investigation/contradictions.py`
- `src/services/investigation/analysis_projection.py`
- `src/services/investigation/exact_detectors.py`
- `src/services/summarization/models/context_analysis.py`
- `src/services/summarization/models/investigation_knowledge.py`

Acceptance:

- source coverage is 100% or artifact state is partial;
- no dangling internal binding;
- exact values preserve leading zeros and units;
- no audio time in described-event timeline;
- no sentence is automatically an event;
- allegations/plans/denials remain attributed statements;
- entity false-positive negative fixtures pass;
- repeated extraction is deterministic at the contract/hash layer.

### Track D - Summary and insight from the artifact

**Goal:** make the readable bulletin cover the whole audio without duplication.

Tasks:

1. Generate Summary only from the current artifact, never directly from an
   unconstrained transcript call after Analysis exists.
2. Sections are adaptive: overview, actors/roles, critical values, timeline,
   relationships/flows, contradictions, insights, and unresolved questions.
3. Omit absent sections and empty/null filler.
4. Deduplicate repeated facts while preserving distinct events and
   contradictions.
5. Enforce summary type allowlist and max length; minimum length remains
   advisory for sparse audio.
6. Derive insights only from explicit reviewed premises. Hypotheses remain
   separate and never enter the factual bulletin.
7. Case summary aggregates file artifacts with file identity and no cross-file
   speaker-ID merge.

Primary files:

- `src/services/summarization/summary_service_v2.py`
- investigation narrative/release adapters
- `src/api/endpoints/audio_v2.py`
- `src/api/endpoints/audio.py`
- summary frontend components

Acceptance:

- all critical entity/value/event/relation categories present in the artifact
  appear in the detailed summary;
- no unsupported identifiers or quantities;
- no duplicated key-point/insight blocks;
- sync and async results are identical in state and content authority;
- summary remains readable without technical evidence fields.

### Track E - Unified investigator workspace

**Goal:** make Analysis immediately understandable.

Tasks:

1. Keep Summary, Analysis, and Visualization actions visible and enabled when
   their prerequisites are met.
2. Analysis sections: Tổng quan, Đối tượng, Timeline sự kiện, Mối quan hệ,
   Dòng tiền/hàng hóa/liên lạc, Mâu thuẫn, Insight, Khoảng trống.
3. Visualization becomes view modes over the same artifact: network, timeline,
   flow, map, and speaker interaction.
4. Remove duplicate legacy panels and prevent summary/context fallback from
   becoming graph data.
5. Do not render evidence quotes, segment IDs, speaker/audio offsets, or model
   debug details in the main Analysis content.
6. Keep transcript/diarization correction in their own tab/workflow.
7. Support filters, search, file identity, case aggregation, responsive layout,
   keyboard navigation, loading/progress, degraded/error states, and retry.

Primary files:

- `frontend/src/components/AnalysisPanel.tsx`
- `frontend/src/components/VisualizationDialog.tsx`
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- remove/converge legacy Visualization panels after usage audit

Acceptance:

- investigator can understand actors, values, timeline, relations, and insights
  without opening transcript internals;
- no evidence/audio-offset text in Analysis DOM;
- Analysis and Visualization share artifact ID;
- no duplicated sections;
- desktop/mobile/keyboard E2E pass.

### Track F - Case intelligence and analyst workflow

Tasks:

1. Case-scoped cross-reference for repeated phones, accounts, plates, emails,
   organizations, locations, and aliases.
2. Analyst-editable entity merge/split, role assignment, speaker mapping, and
   relationship confirmation with audit history.
3. Saved network diagrams and filters that update the case model only through
   explicit analyst actions.
4. Search and facets across files, entities, values, event time, and status.
5. Export an authorized case bulletin and structured artifact with redaction.

Acceptance:

- no automatic cross-case merge;
- edits create revision/audit records;
- permissions apply before data retrieval, not only in prompts;
- export contains only authorized current artifacts.

### Track G - Offline runtime, recovery, and release

Tasks:

1. Complete shared GPU lease/quarantine/handoff across ASR, diarization, and LLM.
2. Add recovery CLI and operator status page.
3. Activate repository-local llama-server/model profile and verified model alias.
4. Complete offline model/runtime bundle, licenses, startup, DB/queue, FFmpeg,
   Node/Python caches, and network-denied install/run.
5. Add structured logs and health/readiness for every model service.

Acceptance:

- clean offline startup from the canonical release root;
- no cache/model download outside the root;
- model failure leaves an honest degraded state;
- restart/recovery does not corrupt task state;
- all sensitive paths are case-authorized and audited.

## Immediate implementation order

1. Finish and audit the current Analysis fallback v2 only as a `partial`
   compatibility preview; reject it if unsafe entity heuristics remain.
2. Implement Track A artifact/lifecycle/entrypoint so later work has one owner.
3. Start Track B isolated Pyannote Community-1 runtime and fix false one-speaker
   success.
4. Connect Track C to the existing T3/T4/T5 pipeline for full-transcript
   extraction.
5. Generate Track D Summary from the artifact.
6. Complete Track E UI convergence.
7. Add Track F case intelligence.
8. Close Track G offline/recovery/release blockers.

Tracks A and B may proceed in parallel with exclusive file ownership. Track C
depends on A; speaker-sensitive release depends on B. Tracks D and E depend on
the stable artifact from A/C.

## Product acceptance harness

This is product QA, not an academic benchmark.

Required repeatable cases:

- one speaker;
- two speakers with clean turns;
- overlapping speakers;
- phones/accounts/money/quantity/date/time;
- allegation, plan, denial, and reported speech;
- repeated entity aliases;
- events with and without described time;
- conflicting statements;
- long audio with important middle/tail content;
- model unavailable, stale cache, restart, and network denied.

Required checks:

- targeted and negative backend tests;
- frontend unit tests and production build;
- authenticated sync/async API flow;
- Celery/Uvicorn restart and persisted artifact check;
- desktop/mobile Playwright flow;
- independent audit;
- `git diff --check`;
- allowlist-only commit/push after PASS.

## Current blockers

- Community-1 model tree is absent and the installed Pyannote/Torch stack is
  incompatible with the 4.x code path.
- No production AnalysisArtifact owner exists.
- Strict T3/T4/T5 investigation pipeline is not connected end-to-end.
- No trusted cross-file speaker identity workflow exists.
- Offline release bundle and repository-local LLM activation remain incomplete.
- The worktree is heavily dirty; each delivery must use a narrow allowlist.
