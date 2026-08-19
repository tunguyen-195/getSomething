# Analysis Prompt v3 Experiment Protocol

## Objective

Test whether a clearer single-prompt taxonomy can remove dialogue-act rows from
`events` while retaining useful transcript facts. The experiment must not add a
critic, repair generation, retry, or second model call.

## Locked baseline

- Artifact: `output/analysis-v2-eval/20260814-021856-current-round1/`
- Model path: configured local OpenAI-compatible model
- Generation calls: exactly one per task
- Temperature: `0.2`
- Prompt: `investigation-analysis-simple-v2`

The baseline is structurally usable for all four persisted tasks. Manual review
found one remaining material classification defect: task `d592...` places
asking, informing, thanking, and saying goodbye in `events`.

## Change under test

1. Prefer `overview` and `key_points`; keep specialized collections sparse.
2. Define an event by the occurrence described, not by the act of speaking.
3. Explicitly exclude asking, answering, informing, explaining, listing,
   thanking, greeting, and saying goodbye from `events`.
4. Prevent duplicate rows across `key_points`, `events`, and `actions`.
5. Allow participants only for explicit names or stable source labels; pronouns
   and forms of address alone are not participants.
6. Lower temperature from `0.2` to `0.1`.

## Predictions and gates

| Task | Prediction |
|---|---|
| `84c...` | No invented participants, relationships, events, or actions; only source ambiguity may appear as follow-up/uncertainty. |
| `d592...` | No generic pronoun participant and no speech-act events; retain booking dates, room count, people count, price, deposit, breakfast, transfer intent, and unresolved account/terms. |
| `cd6...` | Standing duties remain in overview/key points; events/actions stay empty. |
| `c592...` | Election facts remain; events do not represent the announcement itself; actions contain only explicit voting instructions. |

Global gates: complete transcript in one prompt, one generation call, non-empty
usable result, no source mutation, and no semantic critic/repair/retry chain.

## Falsification

Reject prompt v3 if any replay invents people/relationships, turns a speech act
or standing duty into an event, loses the material hotel facts, or uses more
than one generation call.

## Result

Rejected on `2026-08-14` after the first four-task replay.

- `84c...` returned an empty business payload, so the analysis was not useful.
- `d592...` reduced generic speech-act events but incorrectly changed `2 rooms,
  1 night` into `2 nights` and still classified service-information delivery as
  an event.
- `cd6...` and `c592...` met their predicted conservative classifications.

Artifact: `output/analysis-v2-eval/20260814-022410-prompt-v3-round1/`.
