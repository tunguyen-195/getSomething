# Analysis V9 Quote-Backed Core Protocol

Status: confirmatory candidate, locked before round-7 replay
Date: 2026-08-14

## Hypothesis

Using the LLM for a concise source-attributed overview while requiring key
points and unresolved actions to be contiguous verbatim transcript spans will
eliminate number/unit drift, actor/object paraphrase and fabricated evidence
without adding a critic, repair pass or second model call.

## Provider Schema

- `overview`: one to three source-faithful sentences.
- `key_points`: contiguous verbatim transcript strings.
- `actions`: contiguous verbatim transcript strings for unresolved work only.
- `uncertainties`: at most the genuinely ambiguous source spans.

The normalizer only maps each returned quote string to the existing public item
shape and drops quote strings that are not present in the transcript. It does
not rewrite or add semantic content.

## New Automated Gates

- Every key-point/action evidence quote is a contiguous source substring.
- Action kind/status, when present for legacy compatibility, belongs to the
  controlled enum.
- Existing single-call, useful-output, schema, placeholder, hedging and
  read-only task fingerprint gates remain mandatory.

## Locked Manual Gates

- Sparse transcript: neutral fixed caveat; no people, relation, conflict,
  attitude, motive or behavior inference.
- Booking: preserve `2 phòng` rather than `2 đêm`; retain the future email send
  commitment only as unresolved source text; no answered question or deposit
  actor reversal.
- Organizational description: retain corrupted ASR phrases verbatim instead of
  repairing them into stronger meanings.
- Election announcement: add no district level, no answered follow-up and no
  model-inferred commitment/status.
- Zero material semantic error is required for promotion.
