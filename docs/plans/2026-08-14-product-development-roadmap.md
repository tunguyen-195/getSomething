# STT Product Development Roadmap

## Objective

Deliver a stable, portable audio-intelligence product whose Summary, Analysis,
and Visualization features use LLMs directly and predictably, then extend it
with research-backed capabilities for authorized investigative workflows.

## Task 1 - Research and lock Analysis/Visualization v2

Deliverables:

- insight and visualization taxonomy;
- compact tolerant JSON contract;
- Vietnamese prompt protocol;
- evaluation rubric and claim-to-evidence map.

Gate: every field is justified by a user question or visualization; optional
absence cannot fail the response.

## Task 2 - Implement the one-call backend

Deliverables:

- one full-transcript prompt and one model generation;
- tolerant JSON normalization and plain-text recovery;
- deterministic transcript/speaker metrics;
- compatible task persistence and cache behavior.

Gate: one call, complete transcript in prompt, no critic/repair/grounding loop,
and no rejection solely for missing optional fields.

## Task 3 - Implement the Analysis and Visualization workspace

Deliverables:

- overview and actionable analysis sections;
- timeline, relationship graph, speaker contribution, entity frequency, and
  action-status visualizations;
- partial payload and plain-text rendering;
- responsive desktop/mobile behavior.

Gate: changing tabs, filters, or layouts performs no LLM generation request.

## Task 4 - Replay and runtime verification

Deliverables:

- read-only replay harness and immutable input hashes;
- focused backend/frontend tests and production build;
- persisted real-task execution through the active API/Celery/LLM runtime.

Gate: all four locked real tasks return visible, non-empty Analysis results.

## Task 5 - Full repository review and audit

Review surfaces:

- architecture and active/legacy entrypoints;
- task state and persistence semantics;
- authentication, authorization, secrets, uploads, exports, and logs;
- dependency, configuration, migration, model, test, and frontend build health;
- stale/dead code and generated artifacts.

Gate: all P0/P1 findings are resolved or explicitly blocked with evidence.

## Task 6 - Clean-machine portability and release readiness

Deliverables:

- canonical clone/setup/run path for Windows and Docker-supported deployment;
- environment template validation, migration/preflight checks, dependency lock
  review, model manifest checks, and smoke commands;
- release manifest with versions, hashes, validation results, and limitations.

Gate: a clean checkout can reach frontend, API, database, Redis, Celery, ASR,
and LLM health using documented commands.

## Task 7 - Git release

Deliverables:

- reviewed change inventory;
- scoped commits with no accidental secrets or generated data;
- final diff, tests, build, and smoke results;
- push to the configured remote branch.

Gate: push only after repository ownership and all included dirty changes are
understood; never discard unrelated user work.

## Task 8 - Research the next product capabilities

Candidate capability families:

- multi-file case timeline and cross-file entity resolution with explicit
  uncertainty;
- query-driven evidence retrieval with audio seek;
- contradiction/change detection;
- exact-value and transaction/commodity flow extraction;
- analyst feedback, correction, and evaluation loops;
- Vietnamese ASR/diarization quality calibration;
- offline, access-controlled, auditable deployment.

Each capability requires a baseline, corpus, metric, falsification condition,
safety boundary, implementation plan, and promotion gate before coding.

