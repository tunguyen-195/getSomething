# Analysis Prompt v4 Experiment Protocol

## Hypothesis

A shorter output contract with two concrete, domain-neutral examples will make
the configured 8B local model more reliable than adding more prose rules. It
will preserve one-call generation and tolerate absent optional categories.

## Change under test

- Make `overview` the normal non-empty response for every non-empty source.
- Tell the model to preserve independently stated counts/durations/amounts and
  never calculate or substitute one for another.
- Show one quantity/action example and one noisy-ASR example.
- Require direct evidence for specialized `event` and `action` rows.
- Use temperature `0.0` for reproducible analysis.

## Predictions

- `84c...`: useful neutral overview or uncertainty, no people/event/action.
- `d592...`: exactly `2 rooms`, `4 people`, `1 night`, `6 million total`; no
  information-delivery event; transfer intent and account request retain their
  distinct modalities.
- `cd6...`: duties remain overview/key points only.
- `c592...`: the election occurrence may be an event; instructions may be
  actions; the act of announcing is not an event.

## Rejection gate

Reject on an empty non-failed result, arithmetic invention, invented
participant/relationship, speech-act event, standing-duty event/action, source
mutation, or more than one LLM generation call.
