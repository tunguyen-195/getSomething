# T4 Release Boundary - Independent Audit

Date: 2026-08-09
Branch: `feature/architecture-refactor`
Status: BLOCKED
Evidence baseline: working tree at `b2c90910` plus the T4 hardening changes
Scope: T4 verification, contradiction handling, canonicalization, release
adapter, adversarial tests, and structural evaluation harnesses.

## Executive Verdict

T4 structural validation and deterministic replay controls are strong, but the
release boundary is not a security boundary against arbitrary code in the same
Python process. The audit extracted the context builder and authority minter from
`release_investigation_run.__closure__` and used them to authorize a forged
validation context. Hiding or deleting module names does not change that result.

**Verdict: BLOCK.** Do not treat an in-process successful `InvestigationRun` as
authorized for factual persistence. Release requires the external process,
signed receipt, and persistence gate specified in
`docs/reviews/t4-external-release-authority-design-2026-08-09.md`.

## Falsifiable Requirements

| Requirement | State | Evidence |
|---|---|---|
| Arbitrary application-process Python cannot grant factual release | BLOCK | Closure inspection can recover same-process authority objects. |
| T3/T4/source artifacts are deterministically replayed | PASS | Raw artifacts are reparsed and replayed; wrapper inputs are rejected. |
| Source bytes, Git revision, and complete worktree state are rebound | PASS | Required module hashes and SHA-256 of complete porcelain status are compared. |
| Reported or attributed assertions remain withheld | PASS | Cue-family regressions cover `Theo lời`, `Theo Lan`, `Theo nguồn tin`, `Được cho là`, `cáo buộc`, and bare `tố`. |
| Semantic role reversal cannot become a factual projection | PASS | Ordered role bindings reject actor/object reversal. |
| Contradictions remain ledger-bound and block release | PASS | Count, ordered references, and contradiction-set digest are validated. |
| Risk identity binds the assessed subject | PASS | Risk artifact identity includes the canonical subject digest. |
| Factual persistence requires cryptographic authorization | BLOCK | No signed/MAC receipt or exclusive persistence gateway exists yet. |

## Confirmed Structural Controls

- `RepositoryState` hashes the complete
  `git status --porcelain=v1 --untracked-files=normal` output, not only dirty
  booleans.
- The adapter requires raw T3/T4 artifacts, replays them, verifies exact source
  module hashes, and performs a final repository-state comparison.
- Verification replay wrappers are explicitly non-authoritative.
- Opposite-polarity collisions are grouped without materializing the full
  Cartesian pair set.
- Reported, uncertain, conditional, question, instruction, and attributed
  assertions remain in diagnostic state rather than factual projections.

These controls defend against malformed artifacts and accidental misuse. They do
not defend against arbitrary code executing inside the authority-bearing Python
process.

## Current Harness Evidence

Rerunnable commands:

```text
python -m pytest tests/test_adaptive_summary_contracts.py -q
python -m pytest tests/test_investigation_verification.py tests/test_investigation_release_adapter.py tests/test_investigation_canonicalization.py tests/test_investigation_evidence_selectors.py -q
python scripts/evaluate_investigation_verification.py --skip-benchmark --output-dir <isolated-output>
```

Current verified results:

- adaptive summary/run contract integration: 97 passed;
- owned T4 slice with expanded cue cases: 104 passed;
- locked structural fixture manifest: 11 cases;
- in-process structural evaluator: 11/11 fixtures and 13/13 probes passed with
  zero network attempts;
- evaluator protocol `v1.3` reports `release_readiness=BLOCKED` and cannot return
  overall PASS until the external process and signed persistence gate exist.
- durable BLOCK report: `docs/evals/runs/t4-blocked/latest.json`, SHA-256
  `0daddef39fad4749589a787fcd3cad6bdd2d03371edb0fafef5654918c074963`;
  11/11 fixtures and 13/13 structural probes passed, while both external
  authority implementation gates remain `false`.

The earlier `docs/evals/runs/t4/latest.json` PASS report is retained only as
historical structural benchmark evidence. It is superseded for release-readiness
claims by the `v1.3` BLOCK artifact under `docs/evals/runs/t4-blocked/`.

## Required Remediation

Implement the design in
`docs/reviews/t4-external-release-authority-design-2026-08-09.md`:

1. move final release replay/decision into a separately isolated process;
2. bind source, T3, T4, run, policy, and verifier build digests into a signed or
   MAC-authenticated receipt;
3. give only a receipt-verifying persistence gateway permission to publish
   factual runs;
4. enforce nonce uniqueness, expiry, anti-rollback, exact digest equality, and
   atomic receipt-plus-run persistence;
5. route production API/worker publication through that boundary.

## Residual Risks

- T5 and production API/worker flows do not yet use an external release service.
- No key lifecycle, receipt schema, persistence ACL, replay database, or
  failover/rotation protocol is implemented.
- Evaluation remains synthetic and does not establish precision, recall,
  calibration, legal admissibility, or real noisy-ASR quality.
- Live Git state is a development provenance signal, not a signed deployment
  identity.
