# Investigative Bulletin and Diarization Evidence Audit

**Ngày audit:** 2026-08-09

**Workspace:** `E:\research\STT`

**Scope:** documentation, research plan, repeatable readiness harness, Pyannote migration/config evidence, and negative tamper tests. This gate does not claim product summary or diarization quality is acceptable.

## Verdict

| Gate | Verdict | Evidence |
|---|---|---|
| Documentation/evidence harness | **PASS** | Independent dev-team audit found no remaining false-PASS path. |
| Workspace migration of legacy Pyannote cache | **PASS_NO_ADDITIONAL_LOSS** | Exactly 9 source, 9 destination, and 9 material rows; 25,179 bytes; current E cache matches path/size/SHA-256. |
| Product summary readiness | **BLOCKED** | Typed nested summary evidence, per-claim release coverage, shared request contract, fail-closed sync path, and Vietnamese quality benchmark remain unfinished. |
| Product diarization readiness | **BLOCKED** | Community-1 snapshot/runtime/API compatibility and verified speaker-state contract remain unfinished. |

## Closed False-PASS Findings

1. Official-source evidence now comes from one sealed seven-source capture with exact URL, status, raw Base64 content, byte count, SHA-256, parsed semantics, harness hash, and source hash.
2. Migration audit cross-binds the exact capture path, artifact SHA-256, capture ID, timestamp, and three Pyannote source bindings. A digest from a different observation is rejected.
3. Migration PASS requires exactly 9 source/destination/material rows and equal path/length sets.
4. Current `models/pyannote_cache` must match destination/material evidence for every path, size, and SHA-256; an empty, truncated, renamed, resized, or rehashed cache is rejected.
5. Readiness replay compares `official_sources` and all recomputed local state, so a self-asserted PASS cannot override observed blockers.

## Frozen Evidence

- Primary capture ID: `123282666facaa1ed6e0499a2703153a90b45e89f67c7d44bed8f251cf771861`.
- Primary capture artifact SHA-256: `1a317e5f7f9bba48d0318f9eb3ba0757a12fc28accd0c52ba551f5aa2c1b4cd8`.
- Static readiness SHA-256: `bd10cc6cc7c0c72708d3921f7532437ee267d0ce7919bde42f7575ba4ef71d99`.
- Live readiness SHA-256: `10be73ea2d18d598e2951b664f99a5475d7bb1939ffd8e16c653d3e03dd92ee0`.
- Manifest SHA-256: `928d8f6c311287fa45fdb5964c9e306ad3cde185ec4a0e12352c876cb37a9103`.
- Frozen readiness timestamp: `2026-08-09T10:27:31.208290+00:00`.
- Static blockers: 54; live blockers: 56.
- Manifest: 114 rows, 65 hashed, 49 expected missing, 0 duplicate/mismatch/error.
- Static replay: byte-identical.

## Validation

```text
tests/test_summary_diarization_audit_harness.py: 14 passed
tests/test_transcription_engines.py + tests/test_model_runtime.py: 23 passed
frontend build: PASS
backend health: HTTP 200
frontend runtime: HTTP 200
Celery: pong
git diff --check: PASS
```

Negative coverage includes fabricated URL/digest/byte count, raw capture tamper, a digest from another capture, missing capture reference, self-asserted PASS, truncated material rows, and empty current E cache.

Frontend build retains the existing advisory for the 724.43 kB JavaScript chunk; it is not a blocker for this evidence-only package.

## Exact Commit Allowlist

Only the following paths belong to this documentation/evidence package:

```text
docs/plans/2026-08-09-investigative-bulletin-diarization-plan.md
docs/research/2026-08-09-investigative-bulletin-diarization-evidence-refresh.md
docs/reviews/2026-08-09-investigative-bulletin-diarization-audit.md
docs/reviews/2026-08-09-pyannote-migration-config-audit.md
docs/reviews/artifacts/2026-08-09-diarization-primary-source-verification.json
docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json
docs/reviews/artifacts/2026-08-09-summary-diarization-readiness-static.json
docs/reviews/artifacts/2026-08-09-summary-diarization-readiness.json
docs/reviews/artifacts/2026-08-09-summary-diarization-readiness.sha256
scripts/audit_pyannote_migration_config.py
scripts/audit_summary_diarization_readiness.py
scripts/capture_diarization_primary_sources.py
tests/test_summary_diarization_audit_harness.py
```

`output/audits/summary-diarization-readiness.json` is a rerunnable local live snapshot and is not part of the commit allowlist.

## Residual Blockers and Next Task

No Community-1 model was downloaded or loaded. Product diarization remains blocked by the missing full snapshot, incompatible shared stack, legacy API usage, and missing verified/degraded speaker provenance.

No production summary remediation was implemented in this package. The locked next sequence remains P0A test-database isolation, then S1 typed nested evidence and evidence-bound summary sentence drafts, followed by S2 per-claim narrative release coverage.
