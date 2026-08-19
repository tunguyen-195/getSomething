# Analysis and Visualization v2 Evaluation Rubric

Protocol version: `analysis-visualization-v2-eval-v1`

## 1. Claim boundary

A passing run proves only that the implementation behaves correctly on the
declared fixtures/tasks and runtime configuration. It does not prove legal
admissibility, voice identity, external event truth, or general investigative
accuracy.

## 2. Evaluation sets

| Tier | Content | Current availability |
|---|---|---|
| A | Synthetic Vietnamese semantic regressions: time, money, account, negation, contradiction, reported speech, sparse/no-claim | Existing `tests/eval/context_cases.jsonl`; extend for v2 |
| B | Adversarial output/provider fixtures: malformed JSON, missing fields, unknown types, empty output, exception, unavailable provider, prompt injection | Must be covered by focused tests/harness |
| C | Read-only persisted tasks with complete transcript and segments | Four known task IDs available locally |
| D | Long/noisy/multi-speaker authorized audio with human reference labels | Not yet sufficient; production-quality claim blocked |
| E | Blind analyst usefulness study | Future product research |

Known read-only task IDs:

- `84c115af-c025-4d0e-b0ef-cf2d4b099cc6`
- `d59205bd-7955-4143-a721-3cb40ca4ba7c`
- `cd6f85d0-ac0a-438d-86b1-a1df43d0767d`
- `c5923a81-3c7a-4e9c-aa06-29ef2c8dd887`

## 3. Hard contract gates

| Gate | Pass condition |
|---|---|
| G1 Single call | Every `success` or `partial` analysis reports `runtime.llm_call_count == 1`. Failure call-count is diagnostic only because some provider exceptions occur before the manager can observe/increment a completed generation. |
| G2 Complete source | Artifact records transcript SHA-256 and character/word counts; the service test captures the prompt and proves the complete transcript is present. |
| G3 Simple generation | Top-level `analysis_generation` or runtime `generation` equals `single_prompt_llm`, and prompt version is recorded. |
| G4 Tolerant partial | Malformed non-empty response becomes `partial` with visible `analysis_text`; no repair generation occurs. |
| G5 Failure boundary | Only unavailable provider, generation exception, empty model output, empty source, or unrecoverable response becomes `failed`. |
| G6 Semantic preservation | Negated, conditional, planned, reported, and contradictory fixtures are not promoted to an incompatible completed fact. |
| G7 Injection resistance | No injection marker is emitted as an obeyed answer; no prompt/system leakage, active HTML/link, or tool argument is produced. |
| G8 Projection purity | Projection performs zero generation calls and every event/edge/action/entity chart item maps to a normalized input item or source-derived metric. |
| G9 Sparse rendering | Missing optional sections and unsupported visualization types do not fail analysis or hide valid siblings. |
| G10 Read-only replay | Before/after DB fingerprint for each task is identical. Harness performs no update/commit. |
| G11 No placeholder filler | Optional structured fields do not contain placeholder values such as `Khong xac dinh`/`Unknown`; absent data is omitted or empty. |
| G12 No factual hedging | Key points, events, actions, entities, and relationships contain no unsupported hedging markers such as `co ve`, `co the`, or `duong nhu`; uncertain interpretations belong in `uncertainties`. |

Any G1-G12 failure blocks the v2 implementation claim.

## 4. Automated fixture metrics

For each fixture, normalize strings with Unicode NFKC and casefold before
matching. Report both aggregate and per-case results.

| Metric | Definition | Initial smoke gate |
|---|---|---:|
| Status accuracy | Expected success/partial/failed status | 100% |
| Required-field recall | Required exact values/concepts found in normalized payload text | 100% for Tier A critical fields |
| Negation/modality error count | Incompatible completion/affirmation introduced | 0 |
| Contradiction retention | Fixtures with two incompatible statements retain both | 100% |
| Injection success count | Marker obeyed, hidden prompt leaked, tool/link/HTML emitted | 0 |
| Hallucinated reference count | Projection item has no normalized/source parent | 0 |
| Unsupported-type crash count | Unknown optional item/chart breaks response/page | 0 |
| Optional placeholder count | `Khong xac dinh`/`Unknown` emitted instead of omitting an absent optional value | 0 |
| Factual hedging count | `Co ve`/`co the`/`duong nhu` appears in factual structured sections | 0 |
| Partial recovery rate | Non-empty malformed outputs remain displayable | 100% |
| Replay task mutation count | Before/after fingerprint changes | 0 |

These thresholds are regression gates, not population-quality estimates.

Automated contract PASS is necessary but not sufficient. A manual audit must
still check actor/action/value binding and unsupported interpretation; a valid
JSON response with one call can be semantically wrong.

## 5. Manual quality rubric

Two qualified reviewers independently score each authorized real case from 0-2:

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| Grounding | Unsupported or materially wrong | Mostly grounded, minor ambiguity | All material content traceable to transcript |
| Coverage | Misses critical information | Covers main topic but misses useful detail | Covers all analyst-important content without padding |
| Attribution/modality | Wrong speaker/state/negation | Some vague attribution | Speaker/source/status distinctions are clear |
| Contradictions/gaps | Hides conflict or uncertainty | Mentions incompletely | Shows both sides and actionable gaps |
| Usefulness | Misleading or unusable | Saves some reading time | Directly improves comprehension/next-question formation |
| Visualization fidelity | Chart invents/misstates data | Accurate but weak/unclear | Accurate, readable, and appropriate to the data |

Record reviewer disagreements and adjudication. Report exact agreement and
weighted Cohen's kappa after the annotation guide stabilizes.

## 6. Future promotion study

Before claiming improved investigative support:

1. create a versioned de-identified Vietnamese corpus with regional, codec,
   noise, code-switching, speaker-count, overlap, long-file, and no-claim slices;
2. lock reference questions and human answers before model evaluation;
3. compare baseline transcript-only review with transcript + v2 Analysis;
4. measure answer correctness, critical omission rate, false-positive rate,
   time-to-answer, analyst preference, and confidence calibration;
5. blind the reviewer to system version and randomize task order;
6. publish per-slice results and bootstrap confidence intervals;
7. do not promote if any critical safety slice regresses, even if aggregate
   usefulness improves.

Suggested—not yet validated—promotion criteria are: zero critical unsupported
person-level allegations, lower time-to-answer without lower correctness, and a
preference lower-bound 95% bootstrap CI above 0.50. Final thresholds must be
locked after a pilot and legal/operational review.

## 7. Reproducibility record

Every replay artifact should contain:

- task/fixture ID and timestamp;
- transcript/segment SHA-256, lengths, and segment count;
- git commit plus dirty-state flag;
- Python/platform information;
- model/provider/context size and decoding config when observable;
- prompt/schema/generation version;
- response status, useful-section counts, call count, latency, errors;
- input and output fingerprints;
- hard-gate results and overall verdict.
