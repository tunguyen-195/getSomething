# Research Log

## 2026-08-14 - Product development objective locked

- User objective: simplify Analysis and Visualization around LLM capability,
  then complete a full engineering, audit, portability, Git release, and
  product-research cycle.
- Current evidence: the reachable Analysis endpoint is
  `POST /api/v1/summaries/analyze`; persisted output is
  `task.result.context_analysis`; Visualization reads that same payload.
- Decision: use one complete-transcript LLM call, a compact optional-field JSON
  contract, tolerant normalization, and deterministic UI projections.
- Safety boundary: visualizations present model output and deterministic
  transcript metrics; they do not create additional factual claims.
- Continuity limitation: this environment exposes neither `/loop` nor cron.
  Durable state, plans, tests, replay artifacts, and experiment logs are used
  instead.
- Worktree note: the repository contains extensive pre-existing user changes.
  No unrelated change will be reverted; commit/push waits for scope review and
  release gates.

## Baseline real-task set

| Task | Words | Segments | Speakers | Existing Analysis |
|---|---:|---:|---:|---|
| `84c115af-c025-4d0e-b0ef-cf2d4b099cc6` | 47 | 6 | 2 | none |
| `d59205bd-7955-4143-a721-3cb40ca4ba7c` | 838 | 65 | 2 | legacy grounded v1.1 |
| `cd6f85d0-ac0a-438d-86b1-a1df43d0767d` | 575 | 24 | 1 | none |
| `c5923a81-3c7a-4e9c-aa06-29ef2c8dd887` | 859 | 53 | 1 | none |

## 2026-08-14 - Analysis V6 rejected; V7 protocol locked

- Round 4 V6 used exactly one generation call on all four tasks and left all
  database fingerprints unchanged, but manual review found material semantic
  regressions in three tasks.
- Rejected errors included wrong request actor/object, unsupported evidence
  binding, invented generic participant, answered follow-ups, scheduled-event
  modality loss, and noisy-ASR semantic strengthening.
- Decision: retain the one-prompt/one-call architecture and replace only the
  prompt protocol with V7 evidence-first minimal guidance. No semantic repair,
  critic, retry, or second LLM call is introduced.
- Locked protocol: `experiments/analysis-v7-evidence-first-minimal/protocol.md`.
- Focused V7 contract/evaluation suite before live replay: 58 passed.
- Release remains blocked independently by dependency resolution, manifest
  review, clean-install proof, and Docker/runtime profile inconsistencies.

## 2026-08-14 - Analysis V7 rejected; V8 schema ablation locked

- Round 5 V7 passed all automated gates with one call and unchanged task
  fingerprints, but manual review still rejected it.
- V7 generated answered/non-question follow-ups, inferred a conflict and
  emotional stance from sparse ASR, and phrased a future email commitment as an
  event that had occurred.
- Finding: prompt wording alone does not reliably stop this model from filling
  high-risk fields that remain present in the provider JSON schema.
- Decision: V8 removes participants, events, relationships, contradictions and
  follow-ups from the provider schema. It retains only overview, evidence-bound
  key points, unresolved actions and source uncertainty.
- Locked protocol: `experiments/analysis-v8-minimal-core/protocol.md`.
- Focused V8 suite before replay: 59 passed.

## 2026-08-14 - Analysis V8 rejected; V9 quote-backed protocol locked

- Round 6 V8 again passed automated gates with one call and unchanged task
  fingerprints, but manual review found residual material correctness defects.
- V8 changed `6 triệu của 2 phòng` into `6 triệu cho 2 đêm`, inferred conflict
  from the sparse transcript, assigned `commitment/planned` to public election
  requests, and emitted evidence strings containing `...` that were not
  contiguous source quotations.
- The replay harness now checks contiguous evidence and controlled action enum
  values, so these defects can no longer hide behind an automated PASS.
- V9 makes key points and unresolved actions verbatim source spans while keeping
  one generated overview. No semantic repair or second generation is added.
- Locked protocol: `experiments/analysis-v9-quote-backed-core/protocol.md`.

## 2026-08-14 - Analysis V9 rejected; V10 extractive core locked

- Round 7 V9 passed automated gates, but manual review still rejected it.
- V9 treated answered booking questions and already-resolved requests as open
  actions, and its free-form overview added an unsupported district level to the
  election announcement.
- Finding: even a single free-form overview or action-selection field permits
  the local model to introduce material meaning not present in the source.
- V10 removes every generative factual field. The model only selects contiguous
  source quotes for `key_points` and `uncertainties`; the application ignores
  all other fields and restores accepted spans directly from the transcript.
- Public participants, events, actions, entities, relationships,
  contradictions and follow-ups remain empty compatibility arrays.
- Locked protocol: `experiments/analysis-v10-extractive-core/protocol.md`.

## 2026-08-14 - V10 safe but too narrow; V11 direct-text protocol locked

- V10 Round 8b passed all automated source-contiguity gates and removed model
  inference, but manual review found the `uncertainties` classifier noisy and
  the quote-only product surface did not satisfy the requested contextual
  analysis experience.
- Decision: stop turning Analysis into a structured extraction problem. V11
  sends one compact investigation-aware prompt over the complete transcript,
  receives plain Vietnamese prose, stores it as `analysis_text`, and displays
  it directly.
- V11 has no JSON schema, JSON decoder, semantic gate, critic, repair or retry.
  Deterministic metrics remain read-only metadata and legacy collections remain
  empty solely for compatibility.
- Locked protocol: `experiments/analysis-v11-direct-text/protocol.md`.

## 2026-08-14 - V11 rejected; V12 source-bounded direct text locked

- V11 Round 9 passed all automated direct-text gates and produced useful
  analyses for the three long transcripts.
- Manual audit rejected the 47-word noisy transcript: the model invented a
  two-person interaction, familiarity, dissatisfaction, conflict, anger and
  emotional reaction even though none was source-established.
- Root cause: generic scenario guidance still asked the model to reconstruct a
  story, participants and relationships. V12 removes that affordance and adds
  a strict sparse-source branch while retaining the one-prompt/one-response
  architecture.
- Locked protocol:
  `experiments/analysis-v12-source-bounded-direct-text/protocol.md`.

## 2026-08-14 - V12 rejected; V13 actor-bounded direct text locked

- V12 Round 10 passed automated gates but manual review still found a sparse
  source inference (two-person conversation and conflict) and a material booking
  actor reversal (`customer requested deposit` instead of `hotel required the
  customer to deposit`).
- V13 forces a two-part abstention response for transcripts under 80 words and
  requires actor-action-object checking for requests, deposits, payments,
  sending and commitments. Temperature is reduced to zero.
- Locked protocol: `experiments/analysis-v13-actor-bounded-direct-text/protocol.md`.

## 2026-08-14 - V13 prompt promoted; integration gates opened

- Round 11 automated replay: 4/4 PASS, exactly one call per task, plain-text
  responses, empty compatibility collections and unchanged task fingerprints.
- Manual audit passed all four locked tasks. The sparse task abstained without
  inferred interaction/emotion/conflict, and the booking task preserved the
  hotel as the party requiring the customer deposit.
- Promotion evidence:
  `experiments/analysis-v13-actor-bounded-direct-text/manual-audit.md`.
- Prompt promotion does not authorize release. Cache integrity, public
  projection, long-context behavior, legacy entrypoints, runtime persistence,
  UI and clean-clone gates remain open.
