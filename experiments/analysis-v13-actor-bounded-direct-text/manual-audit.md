# Analysis V13 Manual Replay Audit

Date: 2026-08-14
Artifact: `output/analysis-v2-eval/20260814-v13-round11/round11-replay.json`
Verdict: PASS for prompt promotion; runtime and release remain blocked by
integration, security, long-context and portability gates.

## Locked Tasks

| Task | Manual verdict | Evidence |
|---|---|---|
| `84c115af-c025-4d0e-b0ef-cf2d4b099cc6` | PASS | Explicitly states insufficient context and only quotes the heard fragment; no inferred speaker count, relationship, emotion, conflict, motive or behavior. |
| `d59205bd-7955-4143-a721-3cb40ca4ba7c` | PASS | Preserves Nguyễn Thị Quyên, 2 rooms, 4 people, 2 male/2 female, 1 night, 15-16 February, 3 million per room/night, 6 million total, hotel-required deposit, customer-selected transfer and future hotel email. |
| `cd6f85d0-ac0a-438d-86b1-a1df43d0767d` | PASS | Treats the content as standing organizational responsibilities, covers finance/banking, industry, internal political security, advisory work, field presence, state-secret protection and public-security outreach; creates no bounded incident. |
| `c5923a81-3c7a-4e9c-aa06-29ef2c8dd887` | PASS | Preserves 15 March 2026, 07:00-19:00, polling station 7, Nạm Đíp/Nạm Trá, three ballot types and the voting instructions; adds no unsupported district level. |

## Architecture Checks

- One complete-transcript prompt and one generation call per task.
- Plain-text provider mode, temperature 0.0.
- Direct `analysis_text` persistence; no JSON schema, parser, semantic gate,
  critic, repair or retry.
- All four persisted task fingerprints remained unchanged during replay.
- Automated replay verdict: 4/4 PASS.

## Claim Boundary

This promotes the prompt contract only. The text remains model-generated and
requires transcript/audio review. It does not establish legal admissibility,
speaker identity, external truth or investigative conclusions.
