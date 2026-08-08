# Adaptive Investigative Contract T1 Review

**Date:** 2026-08-09
**Scope:** Research correction, canonical Summary/Analysis contract, and valid
fixed-prompt smoke baseline
**Production integration:** Not enabled

## Verdict

**PASS for the isolated T1 domain contract.** The new contract is suitable as
the strict canonical boundary for later Summary and Analysis projections.

**NOT YET PASS for production quality or pipeline promotion.** T0 still requires
the annotation/scorer pilot, replay-complete code manifest, network-denied
offline bundle, and locked `brief-v1`/`investigation-v1` comparison policy.

## Independent audit findings incorporated

1. The prior 72-evaluation artifact is diagnostic smoke, not a valid fixed-form
   `investigation` baseline: Summary used `brief` mode and only four of eight
   fixtures.
2. Summary, Context Analysis, and Visualization currently create independent
   LLM outputs and persist them through inconsistent paths.
3. The target architecture is one append-only `InvestigationRun`; Summary and
   Analysis are projections of one verified claim ledger.
4. Visualization must become deterministic: it must not call an LLM or write its
   own competing persistence state.
5. The evaluation/scorer contract and offline deployment bundle move to T0 so
   later quality gates are executable rather than aspirational.

The research and implementation plan were corrected before accepting T1.

## Contract design accepted

- Neutral domain ownership: `src/services/investigation/contracts.py`, not a
  Summary-specific namespace.
- `AdaptiveSummaryContract` and `AdaptiveAnalysisContract` are aliases of one
  canonical Pydantic model.
- Top-level, provenance, safety, evidence, claims, concepts, relationships,
  themes, narratives, and manifest envelopes reject undeclared properties.
- Business ontology stays open through string `claim_type`, `concept_type`,
  `relationship_type`, and sparse JSON-only `attributes`.
- Explicit `null`, blank strings, empty optional collections, and Unicode/case
  variants of filler placeholders fail validation.
- Meaningful `0`, `false`, negation, uncertainty, and verification state remain
  valid.
- `claims=[]` is valid only for `run_status=no_extractable_claims`, with no
  evidence, concept, relationship, theme, or narrative payload.
- Duplicate IDs, dangling evidence/node/theme refs, duplicate primary-theme
  assignment, invalid range, and self-relationship fail closed.
- High-risk content must be a transcript-grounded hypothesis requiring human
  verification and cannot be released as a factual narrative sentence.
- Prompt hash uses exact UTF-8 bytes; JSON Schema uses canonical sorted JSON;
  source module hashes and Git dirty/untracked state are manifest fields.
- Open values and decoding config are limited to valid JSON values; arbitrary
  Python objects, NaN, and infinity are rejected.

## Verification

```powershell
& 'C:\Users\Admin\AppData\Local\Temp\speechinfo-rtk-testenv-20260809\Scripts\python.exe' `
  -m pytest tests/test_adaptive_summary_contracts.py `
  tests/test_context_analysis.py `
  tests/test_investigation_knowledge.py `
  tests/test_context_eval_harness.py -q
```

Result: **60 passed**, 13 pre-existing deprecation warnings.

Additional gates:

- Clean staged-index snapshot: 30 T1 tests passed; compile, Black, Flake8
  (`max-line-length=88`), MyPy, and `git diff --cached --check` passed.
- `compileall` for the new domain/tests: PASS.
- `git diff --check` for T1/research/plan files: PASS.
- Cross-process canonical schema SHA-256 test: PASS.
- Current schema SHA-256:
  `5f59193d5ceacd7f470f87bd130ef3c65ab0c0e0686228c711ec377dee2c0ffa`.
- Tests perform no network or model call.

## Fixed-form runtime baseline

The configured runtime model `llama3.2:3b` was run on all eight fixtures using
the current fixed `investigation` prompt:

- Local diagnostic artifact:
  `docs/evals/runs/fixed-investigation-llama3.2-3b-2026-08-09.json`.
- Evaluated: 8; passed by the old smoke gate: 7; failed: 1.
- Mean critical-field recall: 0.9583.
- Mean latency: 8.043 seconds; p95: 12.219 seconds.
- Mean output length: 2,590 characters for short fixture conversations.
- Code-switching critical recall: 0.67.

This result demonstrates why the old gate is insufficient: it can report a high
pass rate while the fixed form still emits long outputs and does not measure
empty/placeholder rows, grounded atomic claims, duplication, or human utility.
The artifact is intentionally not included in the T1 commit because its current
runner/fixture/code surface is still untracked and therefore not replay-complete;
it will be promoted only with the coherent T0 evaluation-harness commit.

The same eight-case run on `qwen2.5:14b` exceeded the 904-second harness timeout
and did not produce a complete artifact. The timed-out evaluator process tree
was terminated and the Ollama model was unloaded. This is a FAIL for interactive
use under the current one-pass prompt/runtime configuration, not a model-quality
comparison result.

## Security and privacy review

- The contract stores hashes and references, not raw model chain-of-thought.
- Exact evidence quotes remain sensitive operational data and require later
  authorization, retention, legal-hold, and redaction controls in T2/T3/T6.
- Case creation and file upload timestamps are not contract/model inputs.
- No real operational transcript was added to Git; current fixtures are
  synthetic/de-identified smoke data.

## Residual risks and blocked claims

- No human-labelled Vietnamese investigative corpus exists yet.
- The new contract is not wired into LLM generation, persistence, API, worker,
  or UI; legacy form output remains the live behavior.
- Evidence selectors still need duplicate-occurrence, raw/normalized offset,
  prefix/suffix, and source-revision enforcement in T2.
- Current artifact does not yet hash the complete imported runtime code surface
  or prove network-denied offline replay.
- Passing T1 does not claim that any current model produces better Summary or
  Analysis output.

## Promotion decision

Commit and push T1 as a non-integrated canonical contract and test foundation.
Do not change the live Summary/Analysis path until T0 scorer/baseline gates and
T2 evidence selectors are complete.
