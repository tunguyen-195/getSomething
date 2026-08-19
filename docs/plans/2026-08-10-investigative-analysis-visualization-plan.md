# Investigative Analysis and Visualization Implementation Plan

**Date:** 2026-08-10

**Status:** Proposed; task-by-task promotion only

**Research:** `docs/research/investigative-analysis-visualization-capability-research-2026-08-10.md`

**Parent:** `docs/plans/2026-08-09-adaptive-investigative-intelligence-plan.md`

## 1. Objective

Deliver one evidence-first Analysis Workspace where Summary, Analysis, and
Visualization are projections of one released, append-only `InvestigationRun`.
The system must improve analyst ability to find exact evidence, reconstruct
events, understand explicit relationships and flows, compare hypotheses, and
plan verification without presenting unsupported model inferences as facts.

## 2. Locked product rules

1. Analysis may reason only over authorized released premises.
2. Visualization is deterministic and never invokes an LLM.
3. Transcript preview and released intelligence are different artifact types and
   cannot share an ambiguous success presentation.
4. Diarization labels are file-local anonymous clusters until human-verified.
5. Every factual item opens quote, file, speaker state, time, and audio span.
6. Audio occurrence time and described event time remain separate.
7. Facts, insights, hypotheses, actions, and contradictions remain distinct.
8. No guilt, criminality, deception, intent, protected-trait, or legal conclusion
   is released by the model.
9. Corrections create superseding revisions/runs; released artifacts are not
   mutated.
10. Each task requires review, negative tests, targeted tests, build/runtime
    evidence, an audit artifact, and a narrow commit allowlist.

## 3. Dependency map

```text
AV0 contract/baseline
    |
    +--> AV1 speaker-aware source foundation
    |        |
    |        +--> AV2 discovery/verification coverage
    |                    |
    |                    +--> AV3 insights/hypotheses/actions
    |                                |
    +--> AV4 append-only run ownership + entrypoint convergence
                     |               |
                     +-------> AV5 deterministic projectors
                                      |
                                      +--> AV6 Analysis Workspace UI
                                                  |
                                                  +--> AV7 security/export
                                                              |
                                                              +--> AV8 corpus/promotion
```

AV1-AV3 may develop against fixtures while AV4 is prepared, but no production
promotion occurs before one-run ownership and applicable evaluation gates pass.

## 4. Task backlog

### AV0 - Capability contract, baseline, and evaluator lock

**Deliverables**

- Versioned `AnalysisProjection` contract containing briefing, exact values,
  speaker attribution, events, relationships, flows, contradictions, insights,
  hypotheses, actions, quality, and provenance.
- Explicit distinction between source assertion and corroborated world finding.
- Current UI/API capability inventory and legacy adapter policy.
- Baseline export from current Analysis/Visualization on all existing fixtures.
- Mutation scorer for wrong owner/unit/speaker, reported speech, contradiction,
  stale revision, dangling edge, and hypothesis leakage.

**Primary surfaces**

- `src/services/investigation/run_contracts.py`
- `src/services/investigation/reasoning_contracts.py`
- `src/services/visualization/contracts.py`
- new focused contract/evaluator tests

**Negative tests**

- unknown top-level fields;
- blank/null placeholders;
- dangling premise/evidence/relationship refs;
- factual projection containing hypothesis/action;
- alleged/reported event represented as world fact;
- visualization artifact with mismatched run/revision/content hash.

**Gate**

- JSON Schema is strict at every envelope and stable across processes.
- Factual reference and visualization reference resolution are 100%.
- Hypothesis/action leakage is zero.
- Baseline artifact records code, prompt, schema, model/config, fixture, and hash.

### AV1 - Speaker-aware immutable source foundation

**Deliverables**

- Immutable audio/transcript/diarization source revision.
- Collection authority, custodian, acquisition method, original/archive/working
  copies, hashes, transfer history, enhancement/transcoding history, exact
  processing tool/version/settings, channel and codec metadata.
- Stable file-local segment/speaker IDs, word/segment timing, overlap,
  confidence, ambiguity, timestamp provenance, and degradation state.
- Separate human-reviewed speaker identity mapping artifact.
- Evidence selector resolves raw/normalized offsets, quote, prefix/suffix,
  occurrence, file, segment, speaker, and audio time.

**Primary surfaces**

- `src/services/investigation/source_revision.py`
- `src/services/investigation/evidence_selector.py`
- `src/cherry_core/ports/diarization_port.py`
- transcription/diarization adapters and result contracts

**Negative tests**

- repeated `SPEAKER_00` across files;
- overlap/tie and unattributed segment;
- zero/negative/out-of-range time;
- changed diarization revision;
- Unicode/whitespace/duplicate quote;
- wrong source hash;
- transcoded file presented as original.

**Gate**

- Selector resolution is 100% on adversarial fixtures.
- Wrong-speaker sensitive release is zero.
- Single-speaker, degraded diarization, unavailable diarization, and ambiguous
  diarization remain distinct.
- Creation/upload timestamps remain outside reasoning evidence.
- Enhancement output remains traceable to unprocessed audio and cannot replace
  the source of record.

### AV2 - Investigative discovery, exact values, events, relationships, and flows

**Deliverables**

- Position-balanced/turn-aware coverage manifest.
- Deterministic detectors for phone/account/ID, money, quantity/unit, dates,
  time, vehicle/document/device/URL/coordinate values.
- Open-schema candidate discovery for entities, source assertions, events,
  relationships, plans, instructions, and explicit flows.
- Verification for subject, owner, unit, polarity, modality, attribution, event
  status, described time, and speaker.
- Conservative coreference/canonicalization and contradiction preservation.

**Primary surfaces**

- `src/services/investigation/chunk_planner.py`
- `src/services/investigation/exact_detectors.py`
- `src/services/investigation/discovery.py`
- `src/services/investigation/verification.py`
- `src/services/investigation/canonicalization.py`
- `src/services/investigation/contradictions.py`

**Required ablations**

- fixed form versus open discovery;
- one-shot transcript versus turn-aware chunks;
- LLM-only versus deterministic exact-value detectors + LLM;
- transcript-only versus speaker/timing-aware evidence.

**Negative tests**

- leading-zero loss;
- wrong owner or unit;
- negation/polarity inversion;
- plan/denial/reported speech promoted to completed event;
- hidden middle/tail claim;
- hard merge of contradictory claims;
- malicious spoken instruction or filename controlling the prompt.

**Gate**

- Source coverage is 100%.
- Critical exact value + owner + unit accuracy is at least 0.99.
- Released factual event and relationship precision are at least 0.98.
- Severe unsupported high-risk release count is zero.

### AV3 - Bounded insights, competing hypotheses, and verification actions

**Deliverables**

- Typed insight derivations over released claims only.
- Competing hypotheses with premises, alternatives, counterevidence,
  falsification criteria, indicators, and human review.
- Verification actions with answerable question, target, authorized source type,
  owner, priority, and promotion/rejection criterion.
- Rules for repeated methods, explicit role coordination, contradictions,
  flow bottlenecks, beneficiaries, and intelligence gaps.
- No free-form chain-of-thought persistence.

**Primary surfaces**

- `src/services/investigation/reasoning_contracts.py`
- `src/services/investigation/reasoning.py` or equivalent bounded reasoner
- `src/services/investigation/narrative_attestation.py`
- verification and release gates

**Negative tests**

- insight with unreleased or cross-case premise;
- hypothesis rendered as risk/fact;
- one preferred hypothesis with alternatives suppressed;
- no counterevidence review;
- vague action with no source or criterion;
- crime/deception/intent/surveillance conclusion from model prose.

**Gate**

- Insight premise coverage is 1.00.
- Human entailment precision meets the AV0 locked threshold.
- Hypothesis leakage is zero.
- Every action resolves a concrete gap/hypothesis/contradiction.

### AV4 - Append-only run owner and entrypoint convergence

**Deliverables**

- Append-only analysis/intelligence run persistence with source revision,
  supersession, ledger, projections, quality report, release state, manifests,
  and human review events.
- One idempotent worker/orchestrator owns execution and publication.
- Atomic active-run pointer.
- Summary/analyze/visualize endpoints request or read projections from the same
  run; they do not create competing factual generations.
- Legacy reads remain compatible but cannot become authoritative.

**Primary surfaces**

- database models and Alembic migration
- task repository/service
- `src/api/endpoints/summary.py`
- `src/api/endpoints/audio_v2.py`
- analysis/summarize/visualize workers

**Negative tests**

- ten concurrent retries;
- crash before publish;
- stale async completion;
- post-release mutation;
- superseded run selected as active;
- cross-user/case replay;
- partial projection persistence.

**Gate**

- Concurrent/retried requests create one execution and one active released run.
- Publication is atomic and replayable from manifest.
- Cross-case authorization, retention, legal hold, and audit tests pass.

### AV5 - Deterministic projector expansion

**Deliverables**

- Projectors for briefing, exact-value table, speaker lanes, dual timelines,
  association graph, financial/commodity flow, contradiction matrix,
  competing-hypothesis matrix, action queue, and quality/provenance drawer.
- Stable ordering, aggregation, layout seeds, labels, filters, and hashes.
- Optional map only for explicit safely geocoded locations.
- No persistence or model call in projector code.

**Primary surfaces**

- `src/services/visualization/contracts.py`
- `src/services/visualization/projector.py`
- frontend projection validators/types

**Negative tests**

- withheld node used by released edge;
- edge direction reversal;
- missing amount/unit/date;
- audio time confused with event time;
- value-only deduplication;
- layout/ordering/hash changes across processes;
- graph implies guilt/causality absent from ledger.

**Gate**

- Dangling refs and hash mismatch are zero.
- Same run/config produces byte-identical canonical artifact.
- Projection p95 is below 1 second for 1,000 claims on the locked hardware.

### AV6 - Unified Analysis Workspace UI

**Deliverables**

- Scope/run/status bar with selected files and freshness.
- Evidence-backed briefing and sensitive exact-value table.
- File-aware speaker lanes and audio seek.
- Dual timeline, association graph, flow view, contradiction matrix,
  hypothesis/action board, evidence drawer, and provenance/quality panel.
- Clear labels for released, needs review, degraded, preview, stale, and
  superseded artifacts.
- Invalid/stale released artifacts show an explicit rejection reason; they do
  not silently downgrade to a transcript preview.
- Remove generation-on-navigation and complete compatibility cutover from the
  separate Visualization dialog/action.

**Primary surfaces**

- `frontend/src/components/AnalysisPanel.tsx`
- `frontend/src/components/VisualizationDialog.tsx`
- `frontend/src/utils/investigationProjection.ts`
- `frontend/src/api/client.ts`
- focused component and browser tests

**Negative tests**

- malformed/empty/large payload;
- stale run after file correction;
- removed or unauthorized file;
- missing evidence audio;
- transcript preview styled as released;
- mobile/keyboard hidden tab;
- blank-page object rendering;
- stale selected file or stale async overwrite.

**Gate**

- Navigation/filter/layout triggers zero LLM/API generation calls.
- Every visible item opens exact authorized evidence.
- Desktop/mobile/keyboard case -> item -> quote -> audio E2E is 100%.
- No blank page, duplicate action, empty card, or ambiguous artifact authority.

### AV7 - Security, privacy, review, and export

**Deliverables**

- Typed analyst focus instead of arbitrary prompt instructions.
- Direct/indirect prompt-injection suite for transcript, filename, document,
  prior output, and dictionary sources.
- Output escaping and no model-generated active links/HTML/tool arguments.
- Sensitive reveal, redaction profile, export confirmation, watermark/provenance,
  RBAC, audit log, retention, legal hold, and reviewer attestations.
- Purpose/authority metadata, minimization, access/export logs, and a hard ban
  on solely automated adverse decisions about a person.
- Export includes current source/run hashes and excluded/withheld state.

**Negative tests**

- multilingual/zero-width/role-tag/JSON-breakout spoken injection;
- prompt/system leakage;
- cross-case disclosure;
- malicious link/image;
- export bypass;
- console/log sensitive data;
- stale human attestation hash.

**Gate**

- Release/tool/network/leak/exfiltration injection success is zero.
- Unauthorized sensitive reveal/export is zero.
- Audit events are complete and tamper-evident.

### AV8 - Vietnamese corpus, usefulness study, and promotion

**Deliverables**

- Versioned Tier A-E corpus and manifest.
- Thirty-case double-annotation pilot, adjudication guide, agreement report, and
  paired-power simulation for blind test size.
- At least 100 blind cases and at least 30 cases per critical slice unless the
  locked power analysis requires more.
- Entity, value, event, relationship, time, speaker, claim, evidence,
  contradiction, injection, latency, resource, usefulness, and accessibility
  metrics.
- ASR WER/CER plus critical-field error rates; diarization DER/JER,
  speaker-count accuracy, overlap recall, and speaker-attributed WER; speaker
  recognition calibration/miss/false-alarm metrics if that capability exists.
- Baseline/current/challenger model/runtime/config matrix with offline replay.

**Negative tests**

- train/dev/blind leakage;
- scorer denominator drift;
- omitted failures;
- corpus/hash mutation;
- model/config/prompt mismatch;
- network fallback;
- metric pass caused by empty output.

**Gate**

- All non-zero safety gates from research pass.
- Blind analyst correctness and time-to-answer improve over baseline.
- Preference lower-bound 95% bootstrap CI exceeds 0.50.
- No critical slice falls below locked precision/recall/speaker/value thresholds.
- Network-denied replay passes from the release bundle.

## 5. Immediate implementation order

1. **AV0**: lock projection taxonomy and baseline before adding UI sections.
2. **AV1**: finish speaker/timing/source provenance because wrong speaker makes
   every downstream insight unsafe.
3. **AV4 foundation** in parallel: append-only owner and one entrypoint.
4. **AV2**: exact values, events, relations, flows, contradictions.
5. **AV3**: insights/hypotheses/actions only after verified premises exist.
6. **AV5** then **AV6**: deterministic projector before richer UI.
7. **AV7**: security/export gate before real sensitive-data canary.
8. **AV8**: corpus/promotion; no production quality claim before blind evidence.

## 6. First atomic task recommendation

Start with **AV0.1 - AnalysisProjection contract and negative fixture suite**.

**Allowlist**

- new/updated projection contracts under `src/services/investigation/`;
- `src/services/visualization/contracts.py` only if the shared envelope requires
  it;
- focused tests and one audit artifact;
- no API, worker, DB, or UI changes in this atomic task.

**Required pass conditions**

- strict nested JSON Schema;
- open business types but closed safety/provenance fields;
- separate source assertion, insight, hypothesis, and action;
- speaker and dual-time provenance;
- wrong-owner/unit/speaker and reported-speech negative fixtures;
- stable schema hash across processes;
- targeted tests, negative tests, compile/lint, and `git diff --check`;
- independent audit PASS before narrow commit/push.

## 7. Completion boundary

This plan is complete when the target design, tasks, dependencies, gates, source
evidence, and residual uncertainty are auditable. It does not mean the current
Analysis/Visualization product is production-ready.
