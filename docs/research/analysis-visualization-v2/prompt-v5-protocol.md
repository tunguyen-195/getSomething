# Analysis v5 Minimal Source Guard Protocol

## Hypothesis

One compact prompt plus deterministic validation of the same returned payload
can remove demonstrable source contradictions without another LLM call or a
semantic repair pipeline.

## Locked input

Prompt v4 replay: `output/analysis-v2-eval/20260814-023054-prompt-v4-round1/`.

Observed defects on `d592...`: `2 rooms / 1 night` became `2 nights`; the
pronoun `Em` became a participant; information delivery became an event;
transfer intent became a request; and answered questions became follow-ups.

## Minimal guard

The normalizer may only remove a field or row when the same response and its
cited source prove one of these local violations:

1. a number-unit pair is absent from the evidence quote/source;
2. a participant is only a generic pronoun or form of address;
3. an event describes asking, answering, informing, explaining, thanking, or
   another speech act rather than the described occurrence;
4. an action says `request` but its evidence contains no request/obligation cue;
5. a follow-up reason explicitly states that the answer was known.

The guard does not generate or reconstruct content, call a model, or reject an
otherwise useful partial response.

## Gates

- exactly one LLM generation;
- all four persisted tasks produce useful content;
- no invented participant/relationship on `84c...`;
- no `2 nights`, pronoun participant, speech-act event, false request, or
  answered follow-up on `d592...`;
- standing duties stay outside events/actions on `cd6...`;
- election information remains available on `c592...`;
- source task fingerprints remain unchanged.
