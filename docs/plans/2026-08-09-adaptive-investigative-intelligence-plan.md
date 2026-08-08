# Adaptive Investigative Intelligence Implementation Plan

**Date:** 2026-08-09
**Status:** Active, implementation gated task by task
**Research input:** `docs/research/evidence-preserving-adaptive-investigative-summary-2026-08-09.md`
**Source audit:** `docs/reviews/adaptive-summary-research-source-audit-2026-08-09.md`
**Parent plan:** `docs/plans/2026-08-08-remediation-plan.md`

## 1. Objective

Replace the current fixed-form Summary/Analysis behavior with one offline,
evidence-preserving intelligence pipeline that uses the LLM for adaptive
discovery, cross-turn synthesis, theme formation, and relationship reasoning.
The LLM must not be reduced to filling a predetermined investigation form, and
its unsupported inferences must never be released as facts.

The implementation is accepted only when it improves critical-fact coverage on
a human-labelled Vietnamese evaluation set while preserving attribution,
numeric accuracy, authorization boundaries, and explicit human verification for
high-risk hypotheses.

## 2. Locked product rules

1. Summary and Analysis consume the same canonical claim ledger; they must not
   independently invent or re-extract factual content from one another.
2. The business ontology stays open. Safety, provenance, versioning, and release
   state are strict; `claim_type` and sparse claim attributes are extensible.
3. Concepts absent from the conversation are omitted. The system does not emit
   `null`, empty cards, `Không có thông tin`, or `Cần xác minh thêm` to fill a
   template.
4. Names, people, roles, events, time, location, money, account/phone/ID values,
   quantities, vehicles, objects, documents, and other salient exact values are
   coverage targets, not a mandatory output form.
5. Every released factual sentence resolves to verified claims and source spans.
6. Crime, deception, hidden relationships, surveillance, and risk remain
   hypotheses requiring human verification, even when transcript-grounded.
7. Reasoning emits three distinct products: evidence-backed insights with
   released premises, hypotheses that never enter factual projections, and
   verification actions that state what evidence would promote or reject them.
8. The system stores structured justification, not free-form chain-of-thought.
9. Transcript-grounded truth is reported separately from audio-grounded truth.
10. Case creation time and file upload time remain user-facing metadata only and
   are not injected into model prompts or investigative reasoning.
11. All runtime models, prompts, schemas, configs, and evaluation data required
   for deployment are versioned and replayable offline.
12. Each task ends with review, negative tests, a durable evidence artifact, and
   an atomic commit/push before the next task is promoted.

## 3. Baseline evidence

- Current `investigation` summary is a fixed 12-section form and explicitly asks
  the model to fill absent sections.
- Context Analysis and narrative Summary are generated independently; legacy
  visualization can then extract again from model-generated summary text.
- Existing contract suite passes `30/30`, but this proves parser/safety behavior,
  not investigative quality.
- Current local comparison contains 72 evaluations: 41 pass and 31 fail. It is
  diagnostic smoke evidence, not a valid `investigation` baseline: Summary used
  `brief` mode and only the first four of eight fixtures.
- The artifact explicitly declares
  `FIXTURE_SMOKE_ONLY_NO_HUMAN_GROUND_TRUTH`; the current eight fixtures cannot
  authorize a production quality claim.

## 4. Canonical architecture

```text
immutable source revision
        |
        v
turn-aware chunk planning + deterministic exact-value detectors
        |
        v
open-schema LLM discovery candidates
        |
        v
evidence selector resolution + atomic claim verification
        |
        v
versioned canonical claim ledger
        |
        v
bounded insight / hypothesis / verification-action reasoner
        |
        +----------------------+----------------------+--------------------+
        |                      |                      |                    |
        v                      v                      v                    v
grounded overview       adaptive themes       entities/events/relations  review actions
        |                      |                      |                    |
        +----------------------+----------------------+--------------------+
                               |
                               v
             sentence-to-claim + hypothesis-leakage post-check
                               |
                               v
             append-only run + quality/release manifest
```

`Summary` is the evidence-grounded narrative projection. `Analysis` is the
queryable graph/timeline/hypothesis projection. Both are derived from the same
ledger and source revision.

## 5. Task sequence and gates

### T0 - Research, evaluation contract, and baseline lock

**Deliverables**

- Source-backed architecture research.
- Primary-source audit with observation/proposal boundaries and source limits.
- Artifact inventory, hashes, model/config metadata, and limitations.
- This implementation plan.
- Separate `brief-v1` and fixed-form `investigation-v1` baselines on all eight
  smoke fixtures using the same model/config/repetition policy.
- A versioned scorer/annotation pilot before T3-T5 quality gates are used.
- An offline bundle manifest covering model/tokenizer/template/license hashes,
  runtime/container or wheelhouse lock, local paths, and a network-denied smoke.

**Current offline audit block**

- Model-store code, tests, and `config/models/**` are not tracked as one coherent
  clean-clone surface, and no production `*.manifest.json` is available.
- Qwen3-8B GGUF exists locally and its hash matches the Ollama model layer, but
  the llama.cpp adapter searches a different filename and the installed
  `llama_cpp_python` exposes only the CPU backend.
- Required tokenizer/template/license/model-card/runtime/dependency-lock roles
  are not mandatory in manifest v1.
- Pyannote paths do not resolve to a complete local pipeline and still contain
  Hugging Face download paths.
- Docker/runtime dependencies are not bundled for a network-denied clean machine.
- Container Summary/Analysis cannot currently reach host Ollama: the client uses
  `localhost:11434`, compose defines no Ollama/host-gateway service, and the
  container does not receive the local `DEFAULT_AI_MODEL` selection.

**T0.1 offline manifest foundation**

- Track the model-store schema/loader/tests and real manifests as one atomic
  Git surface.
- Require artifact roles for weights, tokenizer/template, license, model card,
  runtime binary, and dependency lock, all with immutable revision, provenance,
  SHA-256, byte size, platform/runtime version, and `network_required=false`.
- Add validated runtime profiles for interactive and batch quality modes; reject
  any external Ollama/Hugging Face cache path as the deployment source of truth.
- Fail closed when diarization, runtime binary, license, template, or lockfile is
  missing; do not call a downloader or runtime `pip install`.
- Treat network-denied end-to-end replay as T0.2; a checksum-only socket test is
  insufficient.

**Evaluation-contract work**

- Freeze train/dev/blind-test boundaries and prohibit blind-test samples from
  prompt examples or tuning.
- Define sampling strata for region/dialect, ASR noise, duration, speaker count,
  claim prevalence, and critical-value category.
- Define salience weights, hallucination-severity taxonomy, semantic-duplicate
  scoring, and every metric denominator, including the valid no-output case.
- Set annotator qualification and agreement gates, adjudication protocol, and a
  power/uncertainty plan for human preference comparison.
- Hash the runner, imported pipeline modules, prompt/schema text, tracked dirty
  state, and relevant untracked task artifacts so an eval is replayable from the
  recorded code surface.

**Gate**

- Research distinguishes observation from proposal.
- Source audit records exact primary URL, support strength, limitation, access
  date, and Vietnamese/offline applicability for every adopted mechanism.
- Current smoke results are not presented as production evidence.
- Independent source and architecture audits have no unresolved critical flaw.
- Both Summary modes run all eight smoke cases; category/slice coverage is
  reported rather than hidden by input order.
- Scorer tamper tests define empty-output denominators and catch a missing
  critical claim, hallucinated value, unsupported span, null row, duplicate
  theme, and source-hash mismatch.
- Offline network-denied smoke resolves every required model/runtime artifact
  from local storage.
- Qwen/Whisper preflight verifies real tracked hashes, and a profile referencing
  external user caches, floating revisions, or missing diarization/runtime
  artifacts fails.

**Dependency rule:** T1 code may be developed in parallel, but T1 cannot be
promoted and T3-T5 cannot claim quality until the applicable T0 gates pass.

**Commit boundary:** research/plan only after audit.

### T1 - Versioned open-schema contracts

**Owned surface**

- New canonical contract module under the neutral
  `src/services/investigation/` domain, shared by Summary and Analysis.
- Focused contract tests.

**Implementation**

- Strict envelope and provenance objects with `extra="forbid"`.
- Open `claim_type` and sparse `attributes` without a fixed business enum.
- Recursive empty/placeholder sanitizer that preserves `0`, `false`, explicit
  negation, and valid verification states.
- Deterministic schema hash, exact prompt hash, model/config manifest, and JSON
  Schema export.
- Unique candidate IDs and valid intra-envelope references.
- A single canonical contract explicitly shared by Summary and Analysis.
- Separate `EvidenceBackedInsight`, `Hypothesis`, and `VerificationAction`
  contracts. Insights require released premises and a typed derivation;
  hypotheses require alternatives/counterevidence and human review; actions
  require a resolvable target, required source type, and promotion criterion.
- Store structured justification only; do not persist free-form chain-of-thought.
- `claims=[]` is valid only with `run_status="no_extractable_claims"`; that state
  cannot contain evidence, themes, or factual narrative.
- Manifest hooks for hashes of source modules plus tracked and relevant untracked
  task state.

**Falsification tests**

- Unseen claim types or attributes are rejected.
- Extra envelope fields are accepted.
- Null/empty/placeholder optional values survive release or are silently treated
  as valid required content.
- Required content becomes valid after sanitizing to empty.
- Duplicate IDs or dangling references pass validation.
- An insight references an unreleased/cross-source premise; a hypothesis appears
  in a factual projection; an action has no target or promotion criterion.
- Same prompt/schema/config produces different hashes without input change.

**Gate**

- All positive and negative contract tests pass on the pinned repository
  dependency profile.
- Exported schema contains no closed enum for the business ontology.
- Schema canonicalization produces the same SHA-256 across independent Python
  processes.
- Cross-case/cross-file reasoning references fail unless the authorization scope
  and source revision explicitly include every referenced source.
- Backward P4/P6 tests remain green.
- T1 tests make no network or model call and do not claim LLM quality gains.

**Commit boundary:** contracts + tests + T1 audit.

### T2 - Immutable source revision and robust evidence selectors

**Implementation**

- Seal raw transcript, normalized transcript, segment IDs, speaker/time, audio
  hash, and transcript revision hash.
- Store exact quote, raw and normalized offsets, prefix/suffix, occurrence index,
  segment/time, and source hash.
- Resolve repeated quotes and Unicode/whitespace normalization deterministically.
- Fail closed on source revision mismatch.

**Gate**

- 100% selector resolution on duplicate-quote, Unicode, whitespace, repeated
  phrase, and transcript-revision fixtures.
- Cross-source and cross-case evidence references are rejected.
- Creation/upload timestamps remain absent from the model source manifest.

**Commit boundary:** selector implementation + fixture harness + T2 audit.

### T3 - Adaptive discovery

**Implementation**

- Turn-aware and position-balanced chunk planner.
- Deterministic candidates for exact values such as phone/account/ID, money,
  quantity/unit, dates/times, URLs, coordinates, and vehicle/document identifiers.
- LLM discovery prompt asks for salient atomic claims and relationships without a
  fixed list of required categories.
- Add a compact open-type entity challenger (GLiNER/UniversalNER-style) as a
  separate candidate channel; it cannot assert relations or release facts.
- User focus can alter ranking but cannot override evidence, schema, or safety.

**Gate**

- Tier-A critical recall is no worse than the locked T0 `investigation-v1`
  baseline in any category.
- Unseen entity/claim-type recall is reported separately from known categories.
- Empty optional emission is zero.
- Prompt injection does not alter the instruction hierarchy or release gate.
- Model digest, quantization, context, decoding config, prompt hash, and chunk
  manifest are recorded.

**Required ablations**

- Fixed form versus open discovery.
- One-shot transcript versus turn-aware chunks.
- LLM-only versus deterministic exact-value detectors plus LLM.
- LLM-only versus compact open-type entity challenger plus LLM.

**Commit boundary:** extractor + benchmark output + T3 audit.

### T4 - Verification, merge, contradiction, and uncertainty

**Implementation**

- Atomic claim splitter, atomicity checks, verifiable disposition, and
  exact-value/owner/unit checks.
- Claim/entity merge without collapsing distinct people, values, or events.
- Preserve negation, uncertainty, hearsay, conditional statements, and explicit
  contradictions.
- Deterministic verification first; optional local NLI/QA adapters are secondary
  signals and cannot override missing evidence.
- MiniCheck/RefChecker-style local checkers are ablation candidates only; their
  output cannot promote a claim without a resolvable source span and Vietnamese
  calibration evidence.

**Gate**

- Released critical precision is at least 0.98 on the locked labelled set.
- Severe hallucination count is zero.
- Exact numeric/value accuracy is at least 0.99.
- Contradiction pairs and absence-versus-unknown fixtures remain distinct.
- Duplicate claim/evidence IDs and unsupported high-risk releases are zero.
- Checker disagreement is retained as a review signal instead of being silently
  merged into `supported`.

**Commit boundary:** verifier/merge + benchmark output + T4 audit.

### T5 - Grounded overview, adaptive themes, and analysis projections

**Implementation**

- Build a claim graph and discover themes from verified content.
- Run a bounded reasoner over released claims to produce evidence-backed
  insights, clearly labelled hypotheses, and concrete verification actions.
- Assign every claim one primary theme; cross-links do not duplicate narrative.
- Generate a concise overview from verified claims, preserving critical exact
  values and event relations.
- Produce Summary and Analysis projections from the same ledger.
- Map every factual sentence back to one or more released claim IDs.
- Map every insight to released premises; exclude every hypothesis/action from
  factual overview and factual graph projections.

**Gate**

- Factual sentence-to-claim coverage is at least 0.99.
- Evidence-backed insight premise coverage is 1.00 and human entailment
  precision meets the locked T0 threshold.
- Hypothesis leakage into factual projections is zero.
- Every verification action resolves a gap/contradiction/hypothesis and declares
  an answerable question, source type, and promotion/rejection criterion.
- Primary-theme duplicate assignment is zero.
- Weighted salience coverage improves at least 10 percentage points over the
  fixed-form baseline, with no slice dropping more than 2 points.
- Blind human preference lower-bound 95% bootstrap CI exceeds 0.50.

**Required ablations**

- Narrative from raw transcript versus verified ledger only.
- Themes/deduplication on versus off.
- Bounded reasoner off versus insight-only versus
  insight+hypothesis+verification-action.
- Temperature 0, 0.1, and 0.2 versus current 0.7.

**Commit boundary:** synthesis/projections + benchmark output + T5 audit.

### T6 - Append-only persistence and canonical API ownership

**Implementation**

- Add versioned append-only intelligence runs with source revision, supersession,
  ledger, narrative, projections, quality report, release state, model digests,
  prompt/schema hashes, config, and Git revision.
- One idempotent orchestration path owns generation and persistence.
- Summarize and Visualize endpoints request projections from that run instead of
  starting overlapping model/persistence flows.
- Retain backward reads while preventing mutable legacy JSON from becoming the
  authoritative evidence store.

**Gate**

- Migration rehearses fresh DB and production-like clone.
- Replaying a manifest reproduces the same contracts/hashes.
- Duplicate completion requests do not create conflicting current runs.
- Cross-user/case access, retention, and legal-hold tests pass.

**Commit boundary:** migration/model/repository/API + T6 audit.

### T7 - File-aware adaptive UI/UX

**Implementation**

- Keep selected file identity visible across Transcript, Diarization, Summary,
  and Analysis.
- Render only themes/projections with evidence; no empty tabs or fake unknown
  rows.
- Present factual insights, hypotheses, and verification actions as visibly
  separate sections; accepting/rejecting a hypothesis creates a human event and
  never rewrites the model run.
- Overview has its own copy action.
- Each detail exposes quote, speaker, time, source file, verification badge, and
  audio-span navigation when available.
- Diarization groups are collapsible per file and remain usable on mobile.

**Gate**

- Browser E2E covers multiple files, absent concepts, evidence playback,
  keyboard/mobile, sensitive reveal, copy overview, and task completion.
- No blank page, stale selected file, duplicate operation, or empty card/tab.

**Commit boundary:** UI/API types/E2E + T7 audit.

### T8 - Full Vietnamese evaluation corpus and local model selection

**Implementation**

- Expand the T0 scorer/annotation pilot into the versioned Tier A/B/C corpus with
  privacy/legal status and hashes.
- Two annotators plus adjudication for blind test; report agreement.
- Atomic claim/span, exact value, omission severity, hallucination, contradiction,
  duplication, insight entailment, hypothesis leakage, verification-action
  utility, human quality, latency, RAM/VRAM, and replay metrics.
- Add RULER-style multi-needle/multi-hop/aggregation cases and LongCite-style
  sentence citation regression adapted to Vietnamese claim spans.
- Compare Qwen3 and Sailor2 on identical prompt/schema/quantization profiles via
  the pinned llama.cpp bundle. Add XGrammar or SGLang only when platform and
  workload requirements are proven by a separate runtime benchmark.
- Compare current Ollama path with supported offline runtimes only after the
  canonical pipeline is stable; use the T0 offline bundle contract and record
  quantization and hardware profiles.

**Gate**

- Tampered negative fixtures catch missing critical claim, unsupported span,
  hallucinated number, duplicate theme, null row, and source-hash mismatch.
- No model/runtime is promoted from synthetic smoke alone.
- No English-only checker, open-NER model, multilingual model-card claim, or
  advertised context length is promoted without Vietnamese/noisy-ASR and
  effective-context evidence on the locked corpus.
- Offline model files, licenses, manifests, checksums, runtime packages, and
  tokenizer/templates satisfy the T0 network-denied deployment contract without
  committing secrets or private case data.

**Commit boundary:** evaluator/corpus protocol/model manifest + T8 audit.

### T9 - Shadow, canary, rollback, and release audit

**Implementation**

- Run old/new pipelines in offline shadow mode without overwriting user output.
- Lock thresholds before blind review.
- Opt-in canary with manual release for all high-risk hypotheses.
- Preserve hypothesis/action history append-only; a reviewer decision creates a
  new human assertion event with reviewer/time/source, not a mutation of model
  evidence.
- Feature flag rollback to the old projection; preserve append-only new runs for
  audit.

**Immediate rollback conditions**

- Unsupported high-risk release.
- Evidence selector/hash mismatch.
- Cross-case provenance.
- Severe hallucination.
- Unexplained critical-recall regression.
- Authorization or legal-hold failure.

**Commit boundary:** release controls + final completion audit.

## 6. Evaluation corpus and privacy boundary

The eight current fixtures remain smoke tests only. The release corpus is built
as versioned, synthetic/de-identified data:

| Tier | Initial size | Purpose |
|---|---:|---|
| A | 240 short/minimal-pair conversations | Exact values, absence, negation, contradiction, injection, open ontology |
| B | 120 scripted conversations, 5-30 minutes | Multi-speaker realistic Vietnamese, dialect, indirect relations, evidence-backed insights, competing hypotheses, multiple themes |
| C | 30 paired calls, 30-90 minutes | Human transcript versus noisy ASR, overlap, disfluency, lost-middle, multi-needle/multi-hop/aggregation |

Real operational conversations are not committed. If later approved for internal
evaluation, they require a separate access-controlled store, de-identification,
legal basis, retention policy, and audit trail.

## 7. Per-task audit protocol

Every task must publish a review artifact containing:

1. Requirement-to-evidence table.
2. Files changed and interfaces affected.
3. Test, negative-test, build, and runtime commands with results.
4. Dataset/model/prompt/config/hash manifest for AI tasks.
5. Baseline and ablation comparison where a quality claim is made.
6. Security/privacy/authorization review.
7. Performance and memory evidence where runtime behavior changes.
8. Residual uncertainty and explicit rollback trigger.
9. Clean staged-snapshot verification.
10. Atomic commit hash and push confirmation.

## 8. Current progress

- Case/file creation and upload timestamps: complete and pushed in `b947b986`.
- Analysis completion blank-page defect: complete and pushed in `92e45f5e`.
- T0 research: drafted; source audit completed with corrective findings;
  architecture audit and evaluation-contract remediation remain in progress.
- T1 contracts: isolated canonical contract complete, audited from a clean
  staged snapshot, and pushed in `7cf771ea`; it is not integrated into the live
  pipeline and cannot be promoted until applicable T0/T2 gates pass.
- T0 baselines: local `llama3.2:3b` full-eight-case runs completed for
  `brief-v1` and fixed-form `investigation-v1`; the Qwen2.5 14B interactive run
  timed out after 904 seconds. Artifacts remain local until their evaluator and
  code surface become replay-complete.
- T2-T9: not started and must not be represented as complete.

## 9. Completion boundary

This plan is complete only when T0-T9 have direct evidence and the final release
audit passes. Passing parser/unit tests or producing fluent local model output is
not sufficient evidence of investigative quality.
