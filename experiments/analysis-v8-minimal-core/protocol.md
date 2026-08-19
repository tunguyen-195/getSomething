# Analysis V8 Minimal-Core Protocol

Status: confirmatory schema ablation, locked before round-6 replay
Date: 2026-08-14

## Hypothesis

The local 8B model over-populates risky optional fields even when the prompt
says they may be empty. Removing participants, events, relationships and
follow-ups from the provider schema will prevent those classes of hallucination
while retaining a useful overview, evidence-backed key points, unresolved
actions and source uncertainty in exactly one generation call.

## Provider Contract

- `overview`: concise source-attributed narrative.
- `key_points`: important statements with direct `evidence_quote`.
- `actions`: only unresolved requests, instructions, decisions, commitments or
  next steps, with `kind`, non-completed `status`, actor/object when supported,
  and direct evidence.
- `uncertainties`: only source ambiguity requiring audio/context verification.

The public compatibility payload still exposes the legacy collections as empty
arrays so current UI and API consumers do not break. No semantic post-processing
or second LLM call is added.

## Locked Gates

- All four locked replay tasks use exactly one generation call.
- Database fingerprints remain unchanged.
- Automated contract gates pass.
- Sparse task contains no inferred interaction, participant or follow-up.
- Booking task has no answered breakfast/special-request follow-up, no future
  send commitment phrased as completed, and no wrong deposit actor.
- Noisy organizational task preserves the corrupted phrase without semantic
  strengthening.
- Election task adds no district level and no answered follow-up.
- Manual promotion requires zero material semantic errors.
