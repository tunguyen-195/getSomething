# Analysis Workspace Convergence Plan - 2026-08-09

## Product outcome

Chỉ còn một tab `Analysis`, là workspace điều tra/trinh sát âm thanh duy nhất. Workspace phải giúp điều tra viên nắm toàn bộ hội thoại theo case và từng file, nhưng luôn phân biệt fact, qualified fact, insight, hypothesis và verification action; mọi nội dung factual phải truy ngược về exact quote và audio time.

## Architecture target

```text
Authorized source revisions
        -> T3 candidate discovery
        -> T4 evidence verification + canonical claim ledger
        -> T5 adaptive reasoning (insight / hypothesis / action)
        -> one immutable AnalysisRun publication
        -> SummaryProjection + AnalysisProjection
        -> one Analysis Workspace
```

Visualization không còn là một LLM task. Graph, timeline, table và statistics là deterministic projections từ cùng canonical run.

## Task plan

### A0 - Lock contracts and epistemic gates

**Dependencies:** T3 complete; T4/T5 contracts required before factual release.

- Define one versioned AnalysisProjection covering executive insights, exact values, entities, relationships, events, timeline, topics/patterns, contradictions, evidence-backed insights, hypotheses and verification actions.
- Every item carries `case_id`, `file_id`, `source_revision_id`, evidence refs and epistemic type.
- Fact requires released claim; hypothesis requires alternative/counterevidence/human-review metadata; no coercion between them.
- Add legacy adapter that labels old `visualization_data/context_analysis` as `legacy_unverified`.

**Gate:** schema/property tests prove 100% refs resolve and hypothesis leakage into factual sections equals zero.

### A1 - Create single AnalysisRun owner

- Add `AnalysisRun` append-only persistence: run ID, authorized scope, source revision set hash, config hash, idempotency key, status, manifest, timestamps, error, supersedes and active/published flags.
- Add `AnalysisArtifact`: run ID, artifact type, schema version, payload, SHA-256.
- Add one endpoint module `src/api/endpoints/analysis.py` and one worker `src/worker/tasks/analysis_task.py`.
- POST returns `202 + run_id`; Celery/local worker is the only LLM executor.
- Idempotency key derives from authorized source revisions + analysis config. Atomic publish switches one active run pointer.
- Analysis failure/cancel/retry must not mutate transcript or summary lifecycle status.

**Gate:** 10 concurrent/retried POSTs create exactly one active run and one completion artifact.

### A2 - Converge old backend paths

- Route `/audio/*/visualize`, `tasks.visualize` and `/summaries/analyze` through the same AnalysisRun during a compatibility window.
- Remove direct synchronous LLM work from `async` request handlers.
- Stop `summary_service_v2` from generating a separate visualization/analysis artifact.
- Convert `visualization_service` into a pure projection/layout service, then delete obsolete write paths.
- Add migration/backfill with explicit `legacy_unverified` status; do not relabel legacy output as released fact.

**Gate:** all supported entrypoints return the same `run_id`; no path performs a second LLM generation or second DB publish.

### A3 - Build one Analysis Workspace

Create typed frontend surfaces:

- `AnalysisWorkspace.tsx`: overall orchestration and error boundary.
- `AnalysisScopeBar.tsx`: case/all-files/selected-files scope, active run, stale badge, Run/Refresh/Cancel.
- `ExecutiveInsights.tsx`: concise evidence-backed investigative overview.
- `ExactValuesTable.tsx`: people, identifiers, money, dates, times, locations, objects and quantities without dropping duplicate provenance.
- `EntityRelationGraph.tsx`: interactive graph filtered by file/evidence/epistemic status.
- `EventTimeline.tsx`: source and inferred temporal ordering displayed separately.
- `EpistemicSections.tsx`: Fact, Qualified, Insight, Hypothesis and Action sections.
- `EvidenceDrawer.tsx`: filename, segment, speaker, exact quote, timestamp and seek-to-audio.
- `AnalysisExport.tsx`: copy section/item and offline JSON/HTML/PDF export with scope/manifest/evidence labels.
- `types/investigation.ts`, `api/analysis.ts`, `hooks/useAnalysisRun.ts`: versioned contract, run polling/resume/cancel and stale-response guard.

Remove `VisualizationDialog`; replace FileTable Visualize with `Open Analysis` / `Run Analysis`; do not generate on tab/subview change.

**Gate:** changing subviews creates zero generation POSTs; switching case/file cannot overwrite current workspace state.

### A4 - Summary and Analysis share one knowledge source

- SummaryProjection selects concise overview and thematic sections from the released ledger/reasoning outputs.
- AnalysisProjection keeps the complete investigative structure and interactive visualizations.
- Both expose the same `analysis_run_id`, claim IDs and evidence refs.
- File creation/upload timestamps remain UI metadata only and never enter LLM inference payloads.

**Gate:** Summary and Analysis factual claim sets are consistent for the same run; differences are projection/detail only.

### A5 - Remove legacy duplicate surface

- Delete/archive `VisualizationDialog`, unused visualization panels/dashboard and old API client methods after compatibility telemetry is clean.
- Return `410 Gone` or remove old endpoints in a versioned breaking release.
- Remove legacy status values and mutable `Task.result.visualization_data` writes after backfill.
- Update runbooks, API docs and offline bundle manifests.

**Gate:** code search finds no generation call from visualization UI/service and no second top-level or modal analysis surface.

## UX information architecture

1. **Scope/header:** case, selected files, run version, freshness, model/config manifest.
2. **Executive view:** key evidence-backed insights and urgent verification gaps.
3. **Important exact values:** person, identifier, money, date/time, location, quantity and object, grouped without losing source attribution.
4. **Entities and relations:** graph plus evidence list; relation confidence/qualification visible.
5. **Events and timeline:** explicit source time separated from inferred order.
6. **Topics and patterns:** adaptive clusters, not a fixed police template.
7. **Contradictions and uncertainty:** conflicting claims, missing evidence and alternative explanations.
8. **Hypotheses and actions:** clearly non-factual, with counterevidence and next verification steps.

## End-to-end acceptance gates

- One run identity, one worker execution, one atomic publication.
- Analysis tabs/subviews never auto-trigger generation.
- Cross-case/file access fails closed; stale async completion cannot overwrite another scope.
- 100% factual UI items resolve to authorized released claim + EvidenceSpan + file/segment/audio time.
- Hypothesis leakage into fact overview/graph is zero.
- Duplicate exact surface values remain separate when provenance differs.
- Offline network-denied smoke passes; no cloud fallback.
- Malformed/legacy/empty/large payloads render through an error boundary, never a blank page.
- Copy/export preserves scope, epistemic labels, evidence refs and manifest; sensitive export requires explicit confirmation/audit event.
- Performance benchmark covers 30-90 minute audio and multi-file cases: API/event-loop responsiveness, worker cold/warm p50/p95, RAM/VRAM and graph/timeline render budget.

## Required harness

- Backend concurrency/idempotency tests; worker retry/crash/cancel; atomic publish; auth/cross-case; migration/backfill; network-denied run.
- Contract property tests resolving every fact/relation/insight/hypothesis/action reference.
- Frontend view-model tests for missing/legacy data, duplicate values, file attribution, stale requests and large graphs.
- Playwright flow: one POST/one completion, no auto-run on tabs, resume by run ID, evidence-to-audio navigation, blank-page regression, desktop/mobile, copy/export.
- RTK audit document and artifact hashes before each phase commit/push.

## Sequencing decision

Do not start by deleting components. Implement A0-A2 first so the UI has one authoritative run/data source; then build A3 and remove legacy surfaces in A5. T4 verification remains a hard prerequisite for publishing factual Analysis content.
