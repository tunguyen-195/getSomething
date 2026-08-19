# Analysis V7 Evidence-First Minimal Protocol

Status: confirmatory candidate, locked before round-5 replay
Date: 2026-08-14

## Hypothesis

A shorter evidence-first prompt that defaults risky optional collections to
empty, binds each event/action to one supporting quote, and explicitly
separates organizational rules from participant requests will reduce semantic
regressions on the locked four-task replay while preserving exactly one LLM
generation call.

## Change Boundary

- Prompt-only semantic guidance and provider-schema descriptions.
- No critic, repair, retry, semantic rewrite, or second model call.
- The normalizer continues to parse tolerant JSON, validate shape, and attach
  deterministic metrics/source-quality warnings without rewriting semantics.

## Locked Evaluation

- Tasks: `84c115af-c025-4d0e-b0ef-cf2d4b099cc6`,
  `d59205bd-7955-4143-a721-3cb40ca4ba7c`,
  `cd6f85d0-ac0a-438d-86b1-a1df43d0767d`, and
  `c5923a81-3c7a-4e9c-aa06-29ef2c8dd887`.
- Exactly one generation call per non-failed task.
- Database fingerprints unchanged by replay.
- Automated Analysis v2 gates pass.
- Manual audit has zero material actor/object, modality, evidence-binding,
  noisy-ASR strengthening, invented-participant, or answered-follow-up errors.

## Prediction

V7 will improve over V6 on the booking and election tasks and will not regress
the sparse/noisy or organizational-description tasks. Any new material error,
or any unchanged material V6 blocker, rejects this candidate.

## Reproduction

```powershell
.\venv\Scripts\python.exe -m pytest `
  tests/test_context_analysis.py `
  tests/test_analysis_visualization_v2_eval_harness.py -q

.\venv\Scripts\python.exe scripts/evaluate_analysis_visualization_v2.py `
  --all-known `
  --output output/analysis-v2-eval/<timestamp>/round5-replay.json
```

This workspace is not release-safe yet, so the protocol is recorded as a
durable artifact rather than committed before replay.
