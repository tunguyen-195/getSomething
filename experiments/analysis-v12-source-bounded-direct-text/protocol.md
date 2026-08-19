# Analysis V12 Source-Bounded Direct-Text Protocol

Status: confirmatory candidate, locked before round-10 replay
Date: 2026-08-14

## Change From V11

V11 proved that direct text removes parser and repair failures, but its sparse
task output inferred two speakers, familiarity, dissatisfaction, conflict and
anger from a 47-word noisy fragment. The generic scenario guidance encouraged
the model to complete a story when the source did not contain one.

V12 keeps the same one-call direct-text architecture and changes only the
source-bound prompt:

- generic scenario guidance no longer asks the model to reconstruct people,
  relationships or a narrative;
- transcripts under 80 words receive a strict sparse-source instruction that
  requires an explicit context limitation and forbids inferred speakers,
  relationship, emotion, conflict, motive and behavior;
- longer transcripts require beginning/middle/end coverage and explicit
  separation of standing duties, plans, requests, decisions, commitments and
  completed events;
- no JSON schema, parser, critic, semantic gate, repair or retry is added.

## Promotion Gates

The V11 automated direct-text gates remain mandatory. Manual promotion requires
zero material factual error on all four locked real tasks, with particular
attention to the sparse task and actor/modality/quantity preservation.
