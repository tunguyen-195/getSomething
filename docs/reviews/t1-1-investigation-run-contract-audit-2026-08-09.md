# T1.1 InvestigationRun Contract Audit

**Date:** 2026-08-09

**Scope:** Fail-closed contracts for adaptive investigative Summary and Analysis.

**T1.1 remediation verdict:** **PASS**

**Production verdict:** **BLOCK** until real T2/T4 authorities, runtime integration,
persistence, UI projection and Vietnamese quality evaluation are complete.

## 1. RTK objective

T1.1 must make the following claims falsifiable:

1. A raw LLM/JSON payload cannot self-assert that evidence is resolved.
2. A raw payload cannot self-classify a sensitive accusation as release-safe.
3. Insight, hypothesis and verification action are distinct typed intelligence,
   not generic template fields or relabelled facts.
4. Summary and Analysis are projections of one canonical released ledger.
5. Unsupported or partially supported material cannot enter factual narrative.
6. A successful run records replayable code and Git provenance.
7. The pre-release extraction aliases used by the committed evaluator remain
   compatible.
8. Contract modules can be imported in any order without circular-import failure.

The harness is the focused contract suite plus the evaluator/context/knowledge
regression suites, static checks, cross-process schema hashing and import-order
subprocess tests.

## 2. Owned architecture

- `src/services/investigation/contracts.py`
  - shared strict envelopes, evidence/provenance primitives and the legacy
    extraction/evaluation contract;
  - lazy compatibility facade for historical imports.
- `src/services/investigation/reasoning_contracts.py`
  - `EvidenceBackedInsight`, `Hypothesis` and `VerificationAction`.
- `src/services/investigation/run_contracts.py`
  - trusted release context, candidate/verification ledger, projections,
    lifecycle, manifest and release validation.
- `tests/test_adaptive_summary_contracts.py`
  - positive and adversarial contract harness.
- `docs/reviews/t1-1-investigation-run-contract-audit-2026-08-09.md`
  - this evidence record.

No worker, API, database, UI, prompt or model-runtime file is owned by this task.

## 3. Independent audit findings and remediation

Independent audits returned **BLOCK** while the snapshot was evolving. Every
high/medium finding was turned into an explicit remediation and regression
test.

| Independent finding | Remediation |
|---|---|
| Raw payload could fabricate T2 artifact refs and hashes | A `success` run now requires an opaque in-process validation context. Selector attestation must match verification/relationship ID, artifact ref, source revision, exact evidence-ref set, quote hash and source hash. |
| Raw payload could omit or self-tag risk as ordinary | Released claims, insights, hypotheses and relationships require a trusted risk assessment and an explicit payload risk tier matching that assessment. High-risk assertions cannot be released as facts or insights. |
| Insight/hypothesis/action were generic enum values | Three strict models now require distinct reasoning fields and distinct projection refs. Generic non-factual `GroundedClaim` items are rejected at release. |
| Released non-fact could use withheld premise | Released insight, hypothesis and non-factual relationship premises must be released `fact + supported` claims. |
| Partially supported facts could appear as ordinary facts | Every non-supported disposition requires human verification. Analysis uses a dedicated `qualified_claim_refs` bucket and factual narrative rejects it. |
| Run manifest provenance was optional | `InvestigationRunManifest` requires non-empty source-module hashes and Git revision. The legacy extraction manifest remains backward-compatible. |
| Public aliases changed semantics | `AdaptiveSummaryContract` and `AdaptiveAnalysisContract` again alias the extraction contract. Explicit release aliases are `InvestigationSummaryProjection` and `InvestigationAnalysisProjection`. |
| Initial module split introduced circular import risk | Eager re-exports were replaced by a lazy facade. Fresh-process tests cover reasoning-first, run-first and legacy-import order. |
| T2 attestation did not bind quote prefix/suffix | Trusted evidence fingerprints now include both optional context fields. Explicit `None` versus added content and any content mutation fail selector validation. |
| Withheld verification actions could reference missing evidence | Ledger graph validation now requires every action evidence ref to resolve before lifecycle-specific release checks. |
| Concept-targeted verification actions were declared but unreachable | `VerificationAction` now has typed `linked_concept_refs`; target membership, concept existence and concept-derived evidence are validated in ledger and release paths. |

The trusted boundary is implemented at
`src/services/investigation/run_contracts.py:141` and is required for successful
release at `src/services/investigation/run_contracts.py:208`. Diagnostic
`needs_review` and `failed` states remain parseable without release authority.

## 4. Adaptive reasoning contract

### 4.1 Evidence-backed insight

`EvidenceBackedInsight` is defined at
`src/services/investigation/reasoning_contracts.py:18`.

It requires:

- a typed derivation;
- single-source scope;
- released premise claims;
- evidence refs derived from those premises;
- counterevidence status and refs when present;
- explicit risk tier;
- no free-form chain-of-thought.

A released insight additionally requires completed counterevidence review,
trusted factual eligibility, trusted ordinary-risk screening and a factual
sentence mapping containing every premise claim. It is projected as an insight,
never relabelled as a raw fact.

### 4.2 Hypothesis

`Hypothesis` is defined at
`src/services/investigation/reasoning_contracts.py:62`.

It requires premises, evidence, alternative explanations, counterevidence
status, an uncertainty reason, explicit risk tier and
`requires_human_verification=true`. It can be high-risk, but it is projected
only through typed hypothesis refs and has no field that permits insertion into
factual narrative.

### 4.3 Verification action

`VerificationAction` is defined at
`src/services/investigation/reasoning_contracts.py:105`.

It requires a resolvable linked target, required source type, concrete question,
promotion criterion, rejection criterion and human verification. It is an
investigative task, not a fact or generic placeholder such as "cần xác minh thêm".

## 5. Release invariants

A `success` `InvestigationRun` at
`src/services/investigation/run_contracts.py:661` enforces:

- one ledger and one shared Summary/Analysis released claim set;
- exact projection coverage of all non-withheld verified claims;
- exact trusted reasoning registry coverage;
- exact equality of typed reasoning sets in Summary and Analysis;
- one primary theme for every released claim, insight, hypothesis and action;
- factual narrative cites only supported facts and verified insights;
- insight sentences map every premise claim;
- qualified claims stay outside the fact bucket;
- projected relationships use current-revision trusted selector artifacts;
- released non-factual relationships use released supported premises;
- all released assertions match trusted risk screening;
- successful manifest schema hash matches the current lifecycle schema.

`no_extractable_claims`, `needs_review` and `failed` preserve their
fail-closed lifecycle semantics and cannot publish successful projections.

## 6. Negative harness

The focused suite now directly falsifies:

- success without trusted context;
- a plain dictionary pretending to be trusted context;
- fabricated selector artifact refs;
- fabricated quote/source hashes while payload says `resolved`;
- fabricated quote prefix/suffix after trusted selector attestation;
- omitted risk tier for a crime accusation;
- payload risk tier conflicting with trusted screening;
- missing insight derivation, premises, evidence or risk;
- insight depending on a withheld premise;
- insight released before counterevidence review;
- hypothesis missing alternatives, counterevidence state, uncertainty reason or
  human-review flag;
- hypothesis injection into factual narrative;
- verification action missing target, source, question, promotion or rejection
  criterion;
- verification action referencing missing evidence in a diagnostic ledger;
- concept-targeted action without a typed, resolvable concept link;
- generic non-factual claim used instead of a typed reasoning contract;
- partially supported claim in factual narrative or fact bucket;
- non-factual relationship depending on a withheld premise;
- missing source-module hashes or Git revision;
- import cycles under alternate module import orders.

Principal release-boundary tests start at
`tests/test_adaptive_summary_contracts.py:820`; typed reasoning tests start at
`tests/test_adaptive_summary_contracts.py:944`; action graph tests start at
`tests/test_adaptive_summary_contracts.py:1212`; manifest tamper tests start at
`tests/test_adaptive_summary_contracts.py:1751`.

## 7. Verification evidence

### 7.1 Extended regression

```powershell
venv\Scripts\python.exe -m pytest `
  tests/test_adaptive_summary_contracts.py `
  tests/test_adaptive_eval_harness.py `
  tests/test_context_analysis.py `
  tests/test_investigation_knowledge.py `
  tests/test_context_eval_harness.py -q
```

Result: **148 passed**, 13 pre-existing deprecation warnings, 56.34 seconds.

Focused contract result: **97 passed**, 13 pre-existing warnings, 40.16 seconds.

An earlier parallel invocation was discarded because two pytest processes reset
the same dedicated PostgreSQL test database concurrently, producing DDL races.
The authoritative result above comes from a single serial rerun with no other
pytest process active.

### 7.2 Static and import gates

```powershell
venv\Scripts\python.exe -m black --check `
  src/services/investigation/contracts.py `
  src/services/investigation/reasoning_contracts.py `
  src/services/investigation/run_contracts.py `
  tests/test_adaptive_summary_contracts.py

venv\Scripts\python.exe -m flake8 `
  src/services/investigation/contracts.py `
  src/services/investigation/reasoning_contracts.py `
  src/services/investigation/run_contracts.py `
  tests/test_adaptive_summary_contracts.py --max-line-length=88

venv\Scripts\python.exe -m mypy `
  src/services/investigation/contracts.py `
  src/services/investigation/reasoning_contracts.py `
  src/services/investigation/run_contracts.py `
  tests/test_adaptive_summary_contracts.py --explicit-package-bases

venv\Scripts\python.exe -m compileall -q src/services/investigation
```

Results:

- Black: pass.
- Flake8: pass.
- MyPy: pass, no issues in the three source modules or contract harness.
- Compileall: pass.
- Fresh-process reasoning-first, run-first and legacy imports: pass.
- `git diff --check`: pass; only Git line-ending notices remain.

### 7.3 Final independent re-audit

The final read-only audit returned **PASS with no blocking findings** on the
exact implementation and test hashes recorded below. It independently verified
prefix/suffix tamper rejection, action evidence referential integrity, typed
concept-target actions, manifest and semantic registry binding, partial-support
separation, lifecycle states and compatibility imports. The auditor also
confirmed **97 focused** and **148 extended** tests passed and made no file or
Git changes.

### 7.4 Stable schemas

The hashes were identical for `PYTHONHASHSEED=1,2,123,random`:

- extraction schema:
  `969ec21fcb872c536a29956baeafb5789fef791fe2a63a226e4e2a1339f4c5f1`;
- InvestigationRun schema:
  `9533c34a6f06a55c0938c8c2250a588fbf0e1eead3cfb1b08f28f4e6fe45e82a`.

Owned implementation hashes:

- `contracts.py`:
  `A51E4A11EC0BC1A72E661158A2A9C95B558534D8E46F94C569D6AFA1B0B668E8`;
- `reasoning_contracts.py`:
  `BAF4DC3149A4D3A10DD7E2C9E7AA2F2B651A72FBB0A3108F86450877B2686323`;
- `run_contracts.py`:
  `7F2B9BFDE93DFBD163F6527118EFC74A70EE5B701D6E5B29DAF003C53091E984`;
- `test_adaptive_summary_contracts.py`:
  `DA77A5D51CA4BB1688D77730C10CC8AAA7CC848623E4072426DA8EB762ADFB0C`.

## 8. Decision and residual risk

**T1.1 code and harness satisfy the isolated contract gate.**

This does not claim that the current product already performs adaptive
intelligence. The contract makes that future implementation auditable; T3/T5
must still research, implement and benchmark the real discovery, reasoning and
narrative pipeline instead of prompting the LLM to fill a fixed form.

Production remains **BLOCKED** because:

1. T2 must build and authenticate immutable source revisions and robust evidence
   selector artifacts. The private T1 factory is only an adapter seam.
2. T4 must implement calibrated verifier and risk-screening authorities; an
   in-process object is not a cryptographic security boundary.
3. T3/T5 must implement open-schema discovery, graph reasoning, bounded
   insight/hypothesis/action generation and Vietnamese grounded synthesis.
4. T6 must persist append-only runs and make Summary, Analysis and Visualization
   deterministic projections of the same run.
5. T7 must expose evidence, epistemic type, uncertainty and human-review state in
   the UI.
6. Offline model/runtime packaging and Vietnamese/noisy-ASR baseline, ablation and
   human evaluation remain mandatory before any quality claim.
