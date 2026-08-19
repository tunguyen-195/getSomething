# Analysis V13 Actor-Bounded Direct-Text Protocol

Status: confirmatory candidate, locked before round-11 replay
Date: 2026-08-14

## Change From V12

V12 still inferred a two-person conversation and conflict from the sparse task,
and reversed the booking deposit actor by writing that the customer requested a
deposit when the hotel required the customer to place one.

V13 retains one plain-text model call and adds two falsifiable constraints:

- sparse sources must use a fixed two-part response pattern: explicit context
  limitation plus quoted heard fragments; no conversation, speaker-count,
  relationship, emotion or conflict characterization is permitted;
- every request, decision, deposit, payment, send/receive or commitment sentence
  must preserve actor-action-object direction. The prompt includes the booking
  deposit reversal as a negative example.

Temperature is locked to 0.0. No parser, critic, semantic gate, repair or retry
is introduced.

## Promotion Gate

All direct-text automated gates plus zero material factual error on the four
locked real tasks. Sparse-source inference and actor reversal are explicit
automatic manual-rejection conditions.
