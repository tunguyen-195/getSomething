# Adaptive Evaluator Pilot Audit

**Date:** 2026-08-09
**Decision:** PASS for the deterministic T0 scorer pilot only
**Production quality decision:** NOT ESTABLISHED

## RTK objective

Verify that the offline evaluation harness can falsify common failures in the
planned adaptive Summary/Analysis pipeline. The scorer must reward discovery of
salient evidence-backed claims rather than fixed-form slot completion, and it
must fail on missing critical content, fabricated exact values, broken source
provenance, filler output, duplicate themes, and split leakage.

## Audited surface

- `scripts/evaluate_adaptive_contract.py`
- `tests/eval/adaptive_contract_cases.jsonl`
- `tests/test_adaptive_eval_harness.py`
- `docs/evals/adaptive-intelligence-protocol-v3.md`

The audit made no model, network, database-content, audio, or cloud call. The
pytest configuration initializes the repository's dedicated test database, but
the evaluator itself is model-free and network-free.

## Findings and corrections

1. The first independent type-check exposed ambiguous test variable inference.
   Explicit annotations were added and the exact targeted mypy command now
   passes.
2. The first scorer version validated evidence span hashes but trusted the
   prediction's source revision and transcript provenance. A hard provenance
   gate now checks the fixture revision ID, exact raw transcript SHA-256,
   normalized transcript SHA-256, and segment count.
3. Four provenance tamper tests were added, increasing the combined contract and
   evaluator suite from 47 to 51 tests.
4. The adaptive-discovery gate uses open claim types and fails a prediction that
   retains familiar identifiers but omits an unexpected verification claim. It
   also rejects legacy top-level business slots.
5. Empty optional values and placeholder rows are counted by an explicit
   denominator; a valid no-claim conversation is handled separately.

No unresolved critical defect remains in the scorer pilot's declared scope.

## Verification evidence

```powershell
venv\Scripts\python.exe -m pytest `
  tests/test_adaptive_summary_contracts.py `
  tests/test_adaptive_eval_harness.py -q
# 51 passed, 13 existing deprecation warnings

venv\Scripts\python.exe -m black --check `
  scripts/evaluate_adaptive_contract.py `
  tests/test_adaptive_eval_harness.py
# 2 files would be left unchanged

venv\Scripts\python.exe -m mypy --explicit-package-bases `
  scripts/evaluate_adaptive_contract.py `
  tests/test_adaptive_eval_harness.py
# Success: no issues found in 2 source files

venv\Scripts\python.exe -m compileall -q `
  scripts/evaluate_adaptive_contract.py `
  tests/test_adaptive_eval_harness.py
# exit 0
```

Artifact SHA-256 values at the audit gate:

| Artifact | SHA-256 |
|---|---|
| `scripts/evaluate_adaptive_contract.py` | `937006285fab3945c5e84bd12e074351e9c66d646e4f8991327baee79de4f4b7` |
| `tests/eval/adaptive_contract_cases.jsonl` | `26a5e80b4f161b116cbd9aa82b55251119cafcc026766dff23c7989d9e6683ab` |
| `tests/test_adaptive_eval_harness.py` | `4da6c9c9c4fd3fc2ca2209c09fa77201a41cc5bcb3edb428ffa9b13cc6ae42a8` |
| `docs/evals/adaptive-intelligence-protocol-v3.md` | `801da3bb2cf79baaf600439dd5f3327a85f2da0b5139a7d0ac1448cdb53f9f0f` |

## Gate decision

The T0 deterministic scorer pilot is accepted as a repeatable harness for
contract and tamper validation. It is suitable for guarding the next contract,
source-selector, discovery, verification, and projection tasks.

It does not prove that any current local model produces a good Vietnamese
investigative Summary or Analysis. Promotion claims remain blocked until a
human-labelled corpus, independent annotation, locked baselines, ablations, and
confidence intervals are available.

## Residual risks

- The corpus contains four synthetic cases and cannot estimate real-world
  quality, dialect robustness, ASR-noise sensitivity, or investigative utility.
- Claim pairing is deterministic and adequate for the pilot, but production
  evaluation with repeated same-type claims may require optimal bipartite
  matching rather than the current greedy assignment.
- The scorer detects fabricated numbers and unsupported atomic claims; it is not
  a semantic judge for every possible hallucinated paraphrase in narrative text.
- The committed blind rows enforce workflow separation, not secrecy. The later
  human blind set must be access-controlled until model and prompt freeze.
