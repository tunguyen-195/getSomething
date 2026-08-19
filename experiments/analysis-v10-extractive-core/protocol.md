# Analysis V10 Extractive Core Protocol

Status: confirmatory candidate, locked before round-8 replay
Date: 2026-08-14

## Objective

Return useful investigative reading aids from one complete-transcript LLM call
without allowing the model to introduce facts, actors, events, actions,
relationships, conclusions or follow-up questions.

## Falsifiable Hypothesis

If the provider schema contains only verbatim `key_points` and verbatim
`uncertainties`, and the normalizer releases only contiguous source spans, the
four locked real-task replays will contain zero material model-inferred facts
while still surfacing the main source passages.

## Locked Provider Contract

- Exactly one LLM generation call over the complete transcript.
- `key_points`: 3-12 contiguous transcript quotations selected for importance.
- `uncertainties`: at most three contiguous transcript quotations that require
  audio or context review.
- No provider fields for overview, participants, events, actions, entities,
  relationships, contradictions or follow-ups.
- The normalizer ignores every field and row outside this contract. It restores
  the exact source case and whitespace for accepted spans and never rewrites
  their meaning.
- Public compatibility collections remain present and empty.
- Transcripts shorter than 80 words receive a fixed neutral overview written by
  the application, not by the model.

## Automated Gates

- Prompt contains the complete transcript and identifies V10.
- Provider JSON schema exposes only `key_points` and `uncertainties`.
- Runtime generation count is exactly one.
- Every released model string maps to a contiguous exact source span.
- Object rows, non-source strings, unsupported fields and duplicates are
  ignored without retry or semantic repair.
- No replay changes the persisted task fingerprint.
- Every non-failed replay exposes at least one useful source quote or the fixed
  sparse-transcript caveat.

## Locked Manual Gates

- Sparse transcript: no inferred people, interaction, conflict, attitude,
  motive or behavior.
- Booking transcript: preserve exact amounts, room/night quantities, names and
  modality; no answered questions promoted as work items.
- Organizational transcript: preserve noisy ASR verbatim; do not repair it into
  a stronger institutional fact.
- Election transcript: preserve the stated administrative levels and dates;
  add no district-level interpretation or inferred obligation.
- Each long transcript must include passages from its main material threads,
  not only the opening segment.

## Promotion Rule

Promotion requires all automated gates plus manual review with zero material
semantic error. A fluent but low-coverage result is not sufficient.
