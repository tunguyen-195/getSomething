# Investigative Summary Redesign Plan

**Date:** 2026-08-10

**Workspace:** `E:\research\STT`

**Input contract:**
`docs/research/2026-08-10-investigative-summary-product-contract.md`

## Objective

Deliver a concise Vietnamese leadership bulletin that reconstructs the full
important content of an audio file or authorized case run, preserves every
material actor/event/object/value and epistemic state, and cannot release an
unsupported inference as fact.

## Dependency order

```text
T0 requirements/corpus lock
  -> T1 released NarrativeLedgerView
  -> T2 scenario and coverage planner
  -> T3 schema-constrained officer writer
  -> T4 semantic/legal/coverage critics
  -> T5 length conflict and bounded repair
  -> T6 run attestation, persistence, API and worker integration
  -> T7 reader projection and frontend states
  -> T8 Vietnamese quality/performance promotion
```

T1-T6 must use the same append-only `InvestigationRun`; Summary may not become a
parallel truth store. T7 cannot expose a released Summary before T6 PASS.

## T0 - Requirements, fixtures, and baseline lock

**Implementation**

- Freeze the public body contract, forbidden metadata list, epistemic/legal
  transition table, scenario overlay matrix, length profiles, and error/status
  union.
- Create de-identified Vietnamese fixtures covering ordinary administration,
  financial transfer, planning, threat, transport, conflict, digital evidence,
  identity/document, mixed scenarios, sparse audio, long audio, and noisy ASR.
- Label critical actors, roles, exact values, event states, contradictions,
  required source units, forbidden conclusions, and preferred officer-style
  bulletin text.
- Record baseline outputs from the current quote-only fallback and current writer.

**Negative tests**

- role reversal; cross-relation swap; lost negation; hearsay promotion; suspicion
  movement; future-to-completed conversion; invented identifier; delimiter and
  Vietnamese instruction injection; cross-case leakage; lost beginning/middle/end.

**Gate**

- Every explicit product requirement maps to at least one fixture and scorer
  assertion.
- Corpus, labels, scorer, prompt, schema, and baseline hashes are frozen.

**Artifacts**

- `tests/eval/investigative_summary_cases.jsonl`
- `tests/eval/investigative_summary_manifest.json`
- `scripts/evaluate_investigative_summary.py`
- `docs/reviews/artifacts/t0-investigative-summary-baseline.json`

## T1 - Released NarrativeLedgerViewV1

**Implementation**

- Build a deterministic view over a successful, attested `InvestigationRun`.
- Include released claims, entities, events, relationships, exact values,
  contradictions, and reviewed conditional assessments with stable refs.
- Preserve source order, described-event order, epistemic class, modality,
  polarity, attribution, owner/unit/source/destination bindings, salience, and
  criticality.
- Record `run_id`, source revision set, diarization revision set, ledger hash,
  coverage scope, and release authority.
- Reject partial, stale, superseded, cross-case, or un-attested inputs.

**Negative tests**

- stale transcript/diarization revision; missing file/chunk; dangling refs;
  duplicated refs; cross-user/case run; source assertion promoted to world fact;
  unreviewed hypothesis included as factual ledger row.

**Gate**

- 100% released critical claims and exact values appear once in the view.
- Unsupported or unauthorized rows: zero.
- Rebuilding the same run produces the same canonical hash.

**Commit boundary**

- Ledger view, canonicalization, tests, and RTK artifact only.

## T2 - Multi-label scenario and coverage planner

**Implementation**

- Always activate `general`; select up to three overlays from released claim and
  entity types, never from raw keyword counts.
- Add `digital_technical` and `identity_document` overlays.
- Produce deterministic section obligations, required refs, critical placement,
  dedup groups, and a minimum required word estimate.
- User focus may reorder non-critical material but cannot delete source strata or
  critical categories.

**Negative tests**

- finance + planning + threat in one file; public-administration audio with the
  generic word `sẽ`; slang/package without illegal-goods claim; similar names;
  audio time mistaken for event time; user prompt attempting to remove a critical
  person or value.

**Gate**

- Overlay selection is deterministic and independent of transcript instructions.
- Required coverage recall is 100% on T0 labels.
- Forbidden-inference codes exist for every overlay.

**Commit boundary**

- Planner, overlay registry, tests, frontend-independent API contract.

## T3 - LeadershipBulletinDraftV1 and officer-style prompt

**Implementation**

- Introduce strict `LeadershipBulletinDraftV1` with status union, scenario tags,
  sentence epistemic class, salience, claim/source refs, coverage requests, and
  typed length conflict.
- Assemble the prompt from immutable core rules, allowlisted overlays, coverage
  plan, escaped ledger rows, and JSON schema.
- Require connected Vietnamese report prose with no visible headings, metadata,
  notes, warnings, or recommendations.
- Configure low-temperature structured generation; record model alias, runtime,
  prompt/schema hash, tokens, latency, and call count.

**Negative tests**

- extra JSON fields; wrong schema/profile; delimiter injection; transcript asking
  to reveal metadata or change schema; headings/bullets; evidence/offset/speaker
  leakage; unsupported crime conclusion; exact value with changed leading zero.

**Gate**

- Strict schema parse: 100%.
- Direct instruction-follow attacks from ledger data: zero.
- Public body forbidden-token leakage: zero.

**Commit boundary**

- Writer schema/prompt/provider adapter/tests only.

## T4 - Deterministic semantic, legal, and coverage critics

**Implementation**

- Reuse canonical claim semantics for actor/action/object/recipient, exact value,
  owner/unit, source/destination, polarity, modality, conditionality, attribution,
  and temporal state.
- Require each mandatory source/claim ref exactly once and detect proposition
  duplicates independent of surface wording.
- Preserve every material contradiction and block model-selected resolution.
- Add a legal-overclaim critic for guilt, crime type, legal article, motive,
  deception, dangerousness, capability, identity, and ownership.

**Negative tests**

- all T0 semantic attacks plus multi-clause reattachment, cross-sentence role
  movement, contradiction collapse, accusation laundering, and mixed modality.

**Gate**

- Semantic fidelity and exact-value binding: 100% on hard fixtures.
- Unsupported, severe hallucination, legal overclaim, and contradiction loss: zero.

**Commit boundary**

- Critics and adversarial fixtures only.

## T5 - Length conflict, repair, and completeness

**Implementation**

- Compute `minimum_required_words` before generation from mandatory refs.
- Return `length_conflict` when the hard maximum cannot contain required facts.
- Permit at most one bounded repair pass using the same immutable ref set; the
  repair may improve phrasing or deduplication but cannot change scenario,
  claims, criticality, or coverage obligations.
- A soft minimum never causes filler. Sparse complete audio may be shorter.
- Never truncate exact values, attribution, uncertainty, contradictions, or
  critical source units.

**Negative tests**

- mandatory facts over max; sparse audio below min; duplicate overview/detail;
  repair dropping a person, digit, negation, attribution, or contradiction;
  repair adding an unreferenced sentence.

**Gate**

- Silent truncation and filler: zero.
- Complete outputs cover 100% mandatory refs; otherwise typed conflict/request.
- Repair model calls are bounded and recorded.

**Commit boundary**

- Length planner, repair state machine, tests, performance artifact.

## T6 - Attestation, persistence, API, and worker integration

**Implementation**

- Convert only a `complete` draft into a narrative attestation bound to run ID,
  revisions, ledger hash, prompt/schema/model/runtime hashes, critic results, and
  content hash.
- Persist append-only summary revisions under the canonical investigation run.
- Route direct API, synchronous endpoint, Celery, retry, and multi-file summary
  through the same service and idempotency key.
- Invalid cached or legacy context must refresh from the current authorized run;
  stale source/revision mismatch remains fail-closed.
- Preserve preliminary transcript-only mode with
  `world_facts_released=false`; never label it as a released investigation summary.

**Negative tests**

- synchronous false success; worker retry duplicate; stale run; changed file set;
  changed diarization; tampered attestation; model unavailable; critic failure;
  DB persistence failure; legacy payload containing fake released fields.

**Gate**

- Direct/Celery/sync/multi parity and idempotency PASS.
- Failed release gates never persist `summarized` as released success.
- Cross-user/case and stale revision leakage: zero.

**Commit boundary**

- Run integration, persistence, API/worker state transitions, tests, DB rehearsal.

## T7 - Reader projection and frontend behavior

**Implementation**

- Show only report body text in Summary.
- Keep status, completeness, model/runtime truth, and review action outside the
  body in dedicated UI fields.
- Do not render fact/evidence IDs, offsets, speaker labels, hashes, or technical
  diagnostics in the main Summary.
- Distinguish `released`, `preliminary`, `partial`, `length_conflict`,
  `needs_review`, and `unavailable`; no disabled overlapping Analysis or
  Visualization controls.
- Summary, Analysis, and Visualization must project the same run revision.

**Negative tests**

- stale legacy preview metadata; offset/evidence leakage; screen-reader focus and
  `aria-hidden` conflict; mobile overflow; stale response race; released badge on
  preliminary content; Summary/Analysis revision drift.

**Gate**

- Frontend unit/E2E/build PASS.
- Forbidden metadata in rendered Summary: zero.
- Keyboard/mobile/accessibility checks PASS.

**Commit boundary**

- Reader projection and Summary UI only; do not mix model runtime or diarization.

## T8 - Vietnamese quality and performance promotion

**Implementation**

- Run T0 frozen corpus across transcript-only prototype, released single-stage
  writer, and any bounded two-stage challenger.
- Score atomic precision/recall, weighted salience, critical coverage, exact-value
  binding, semantic fidelity, contradiction retention, unsupported claims,
  duplication, reading time, and human leadership usefulness.
- Record cold/warm/cached latency, tokens, p50/p95, RAM/VRAM, model handoff,
  retries, and throughput on the same hardware/runtime.
- Conduct blinded Vietnamese human preference review with adjudication.

**Promotion gate**

- Severe hallucination, legal overclaim, wrong exact-value binding, stale release,
  prompt-injection execution, and cross-case leakage: zero.
- Critical precision `>=0.98`; macro critical recall `>=0.95`, no category below
  `0.90`; exact-value accuracy `>=0.99`; sentence-to-claim mapping `>=0.99`.
- Human preference lower bound exceeds `0.50` against the frozen baseline.
- Single-stage p95 regression `<=5%`; a bounded two-stage path may use up to
  `1.25x` p95 only with at least ten percentage points of weighted coverage gain
  and all hard safety gates PASS.

**Artifacts**

- immutable per-item JSONL and aggregate JSON;
- runtime/model/prompt/schema/config/hardware hashes;
- independent semantic and product audit reports;
- exact commit allowlist and rollback trigger.

## Current delta and immediate gate

The current working copy has completed a preliminary T3/T4 slice over grounded
context rather than the final released run:

- officer-briefing prompt v3 and seven scenario guidance profiles;
- full-source inventory augmentation, including sparse trusted cached context;
- exact-once source-unit references;
- role/action/target, exact value, polarity, modality, attribution, conditional,
  prompt injection, metadata leakage, and no-truncation tests;
- invalid cached context refresh from the current transcript;
- clean public preliminary bulletin projection.

Before any commit, this slice still requires:

1. full targeted backend regression;
2. frontend tests and production build;
3. `git diff --check` and secret/sensitive-log scan;
4. regenerated working-tree RTK evidence bound to exact source/test hashes;
5. independent semantic and repository audit with no unresolved high finding;
6. live E-workspace backend/Celery summary run and inspection of Vietnamese body,
   scenario, writer status, completeness, latency, and model metadata;
7. an exact allowlist; no `git add -A`, no unrelated file inclusion, no push when
   any gate fails.

## Residual blockers

- Final release still depends on production orchestration of the existing
  `InvestigationRun` and narrative attestation contracts.
- Multi-label scenario planning is not implemented in the current prototype.
- Diarization model/runtime and speaker-count quality remain separate product
  blockers and must not be claimed as solved by Summary work.
- The frozen Vietnamese promotion corpus and baseline do not yet exist, so
  fluent examples are not sufficient evidence of production quality.
