# Analysis and Visualization v2 Experiment Log

## 2026-08-14 - Bootstrap and contract lock

### Objective

Replace the prior over-engineered analysis/visualization direction with one
complete-transcript LLM call, tolerant normalization, and deterministic charts.

### Evidence reviewed

- current repository analysis, visualization, summary, API, worker, frontend,
  persistence, and test surfaces;
- prior capability research and audit artifacts;
- RTK Research Harness and `autoresearch` workflow;
- 12 locally stored primary-source PDFs and their manifest hashes;
- live official/primary metadata for UNODC, CIA, NIST AI RMF, and QMSum;
- four existing persisted-task summary replay artifacts.

### Locked decision

- Analysis performs one LLM call and accepts sparse structured output.
- Malformed non-empty output becomes visible `partial` text; no repair call.
- Visualization performs no generation and cannot create facts.
- Speaker contribution is computed from segments and exposed through a public
  metrics whitelist.
- Unsupported/missing insight/chart types are skipped.

### Artifacts

- `requirements.md`
- `taxonomy.md`
- `prompt-protocol.md`
- `evaluation-rubric.md`
- `claim-evidence.md`
- `protocol.json`
- `scripts/evaluate_analysis_visualization_v2.py`
- `tests/test_analysis_visualization_v2_eval_harness.py`

### Continuity limitation

The `autoresearch` skill requests `/loop` or cron continuity, but neither control
is available in this Codex environment. Continuity is therefore preserved in
this durable protocol/log plus the parent team's goal/plan state.

## 2026-08-14 - Harness unit validation

Command:

```powershell
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_analysis_visualization_v2_eval_harness.py
```

Result: `7 passed`, with 13 existing deprecation/config warnings.  
Additional checks: Python compile PASS, protocol JSON parse PASS, and
`git diff --check` PASS for this scoped package.

## 2026-08-14 - Read-only four-task replay

Command:

```powershell
.\venv\Scripts\python.exe scripts\evaluate_analysis_visualization_v2.py `
  --all-known `
  --output output\analysis-visualization-v2-eval\four-task-replay.json
```

Runtime environment observed:

- git commit: `060f3d7aaef71a863d556c9fd79055e89abd2183`;
- branch: `feature/architecture-refactor`;
- dirty worktree: yes;
- deployed local analysis schema: `investigation-analysis-simple-v2`.

Contract results:

| Task | Transcript words | Status | LLM calls | Seconds | Task unchanged |
|---|---:|---|---:|---:|---|
| `84c115af-c025-4d0e-b0ef-cf2d4b099cc6` | 47 | success | 1 | 10.03 | PASS |
| `d59205bd-7955-4143-a721-3cb40ca4ba7c` | 838 | success | 1 | 14.52 | PASS |
| `cd6f85d0-ac0a-438d-86b1-a1df43d0767d` | 575 | success | 1 | 15.21 | PASS |
| `c5923a81-3c7a-4e9c-aa06-29ef2c8dd887` | 859 | success | 1 | 17.29 | PASS |

Artifact SHA-256:
`95a96a16a249e4889e562a5722b101493d39d5d5e22c8d99a369870cd61ec0e3`.

Protocol SHA-256:
`63a3a139dc840ebc79b7202d29d5b4da35cd01caa2094e0ff1ea6edcac23e87c`.

### Contract finding

All four tasks passed schema/status/single-call/collection-shape/read-only gates.
The task fingerprints before and after every replay were identical. This is
direct evidence that the harness did not mutate the persisted tasks.

### Manual semantic audit - BLOCK for quality promotion

Contract PASS did not imply reliable content quality. The replay exposed these
material defects:

1. Task `84c...` inferred that “mien Nam” and “mien Trung” were two participants,
   that they might know each other, and that there was conflict/anger. Those
   interpretations are not direct, stable facts in the noisy transcript.
2. Task `d592...` stated “tong 6 trieu cho 2 dem” although the source discussion
   concerns two rooms for one night; the same future account-email action was
   labelled as an event that already occurred while the action section labelled
   it not completed.
3. Task `cd6...` invented an event that the Economic Security Department “was
   established”; the transcript describes its role and duties, not its creation.
4. Several payloads emitted filler values such as “Khong xac dinh” and model
   interpretations such as “co the”, reducing precision and chart usefulness.

The implementation therefore passes the structural/replay gates but remains
blocked for an investigative-quality claim until prompt/normalization fixes and
a second manual replay close these errors.

### Next experiment

Strengthen the prompt and normalization around:

- direct-explicit-only participant/event rules;
- planned versus completed event/action state;
- quantity owner/unit binding (rooms versus nights);
- no invented lifecycle event (“duoc thanh lap”);
- omit unknown fields instead of returning “Khong xac dinh”;
- remove unsupported speculative wording.

Then replay the same four hashes and compare exact error counts. A successful
fix must preserve one call and read-only fingerprints while reducing the listed
material semantic errors to zero on this regression set.

## 2026-08-14 - Content-smoke gate and post-prompt replay

The harness was extended with two general, non-task-specific negative gates:

- optional placeholders such as `Khong xac dinh`, `Unknown`, and `N/A` are
  rejected; absent optional values must be omitted;
- hedging such as `co ve`, `co the`, `duong nhu`, `possibly`, or `appears` is
  rejected in overview/key points/events/actions/entities/relationships and is
  allowed only in the explicit uncertainty section.

Harness validation:

```powershell
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
  tests\test_analysis_visualization_v2_eval_harness.py
```

Result: `11 passed`, with the same 13 existing warnings.

Post-prompt replay command:

```powershell
.\venv\Scripts\python.exe scripts\evaluate_analysis_visualization_v2.py `
  --all-known `
  --output output\analysis-visualization-v2-eval\four-task-content-smoke-v2.json
```

Artifact SHA-256:
`1abf2e4c29176f89c6f18e01da5bb222f771d851a1b69054454b6f816223befc`.

Automated result: all four tasks PASS schema/status/one-call/no-placeholder/
no-factual-hedging/read-only gates. All before/after task fingerprints remain
identical.

Manual comparison:

- `d592...`: the previous room/night binding error was corrected; overview now
  says 2 rooms at 3 million each, total 6 million, and the future email action
  is described as an expected notification rather than a completed transfer.
- `cd6...`: the invented “department was established” event was removed.
- `c592...`: the election announcement remains materially grounded and events
  are attributed with `reported` status.
- `84c...`: still fails manual quality. It invents generic “Nguoi 1/Nguoi 2”
  mappings although the persisted diarization has one file-local speaker, and
  interprets “khong dong y/khong hai long”, “dau don”, and “nghi ngo” from a
  highly noisy 47-word transcript. These are not protected by the generic
  placeholder/hedging gates and require prompt/normalizer or human-quality
  correction rather than a task-specific phrase blacklist.

Current verdict:

- structural/simple-call/read-only contract: PASS;
- generic content-smoke gates: PASS;
- four-task manual semantic quality: BLOCKED by task `84c...`;
- production investigative-quality claim: BLOCKED pending the authorized
  Vietnamese corpus and human-labelled evaluation described in the rubric.

## 2026-08-14 - Manual semantic follow-up on evaluator-fixed replay

Artifact audited:
`output/analysis-v2-eval/20260814-015034/replay-evaluator-fixed.json`  
SHA-256:
`a618017b9e3e73c75eada1b1e1a22e0e6a07d34e205c80f0d7bff1d7fc8f8289`.

Method: compare every overview/key point/event/action/follow-up against the
persisted full transcript and top-level segments for all four tasks. No task or
production source was modified.

Automated contract result remained 4/4 PASS: each task returned `success`, one
LLM call, valid collection shapes, no placeholder/hedging hit, and an unchanged
task fingerprint. Manual semantic review found the following.

### Task `84c115af...` - PASS with low-information caveat

- The prior invented participants, emotions, and conflict were removed.
- The result conservatively exposes one exact heard passage and leaves events,
  actions, entities, relationships, and follow-ups empty.
- The source remains highly noisy and internally inconsistent: result metadata
  reports two speakers, while all six persisted segments are labelled
  `SPEAKER_01`. The conservative output is appropriate, but this file should be
  marked as requiring transcript/speaker review rather than interpreted.

### Task `d59205bd...` - MINOR FAIL

- Core booking facts, 2-room/1-night amount binding, deposit method, and future
  account-email action are now materially correct.
- The final event says the hotel “chuc mung va hen gap lai”. The source thanks
  the customer, says it is pleased to serve her, wishes her a good morning, and
  contains a likely appended “cam on cac ban...hen gap lai” outro. It never
  congratulates her. This is unsupported lexical strengthening.
- The action “yeu cau chuyen khoan dat coc” is labelled `planned`; more precise
  semantics are that the customer selected bank transfer as the intended
  payment method, while actual deposit completion remains unobserved.
- The follow-up asking whether she will use the fitness center is operationally
  weak: she says it suits her purpose but does not unambiguously book the
  service. It is not false, but usefulness scoring should penalize low-value or
  already substantially answered follow-ups.

### Task `cd6f85d0...` - MATERIAL FAIL

- The overview and key points correctly describe organizational roles and
  recurring duties.
- The same descriptions are incorrectly duplicated into `events`, even though
  most are standing functions or recurring activities rather than bounded
  occurrences. This would produce a misleading event timeline.
- Action statuses are unsupported: the standing duty to advise is labelled
  `completed`, report/plan/document preparation is labelled `planned`, and
  coordination is labelled `completed`. The source describes responsibilities
  and, for some passages, recurring work “trong nam qua”; it does not provide
  these item-level completion/planning states.
- The first follow-up asks how many divisions exist although the transcript does
  not state a count. This is a legitimate gap. The other follow-ups seek more
  specific counterpart/location detail and are reasonable, but should not imply
  that absent specificity is a contradiction or failure.

### Task `c5923a81...` - MATERIAL FAIL

- Exact election date, hours, location, ballot types, selection limits, and
  instructions are grounded.
- The overview asserts that the election “dien ra” on 15 March 2026. The audio is
  an announcement/instruction before or about the scheduled election; the safe
  formulation is that the recording states the election is scheduled for that
  date, not that it occurred.
- Event rows represent speech acts (announcement, explanation, listing,
  reminder), but attach the described election date and location to each speech
  act. This collapses audio occurrence time and described event time and can
  make a future announcement appear to have occurred at the polling location.
- Status vocabulary leaks uncontrolled values (`Nhac nho`, `Quy dinh`) outside
  the compact normalized vocabulary used elsewhere. These labels are useful as
  speech-act/category types, not temporal/action statuses.
- Follow-ups ask whether voters can see the candidate list, obtain guidance, or
  know the exact time/location even though the transcript explicitly provides
  the candidate list, assistance condition, time, and location. These are
  answered-question hallucinations and reduce analyst usefulness.

### Invariant recommendations

1. **Eventhood invariant:** create an event only for a bounded occurrence,
   state transition, explicit scheduled occurrence, or explicit speech act. A
   standing role, general responsibility, recurring practice, description, or
   rule remains a key point/entity relationship unless a concrete occurrence is
   stated.
2. **Speech-act/time invariant:** when representing an announcement or
   instruction as an event, its `time/location` describe the speech act only if
   explicitly known. Election/meeting dates mentioned in its content belong to
   a separate `described_event_time`, not the announcement's occurrence time.
3. **Status-evidence invariant:** `completed`, `planned`, `ongoing`, `denied`,
   and `conditional` require explicit source cues bound to the same action.
   Duties and policies must not receive inferred temporal status.
4. **Lexical entailment invariant:** factual paraphrases must not strengthen the
   source predicate (`cam on/chuc mot ngay tot lanh` must not become `chuc mung`).
   Add human fixtures for near-synonym strengthening rather than a phrase
   blacklist.
5. **Question-answer invariant:** a follow-up must target information not already
   supplied by the transcript. Deterministically flag a follow-up when its
   subject/value has an explicit answer in key points or evidence text; manual
   review remains necessary for paraphrases.
6. **Controlled-vocabulary invariant:** keep temporal/action status separate
   from speech-act/category labels and normalize unknown model values to a safe
   supported value or omit them.
7. **Source-quality invariant:** conflicting speaker-count/segment-label
   metadata or very noisy/sparse transcripts should produce a visible source
   quality warning and favor evidence-only output.

### Verdict

- Structural/simple-call/read-only contract: PASS.
- Manual semantic quality: BLOCKED (`cd6...` and `c592...` material; `d592...`
  minor).
- Promotion remains blocked until eventhood, described-time separation,
  evidence-bound status, lexical entailment, and answered-follow-up invariants
  pass on this set and on an untouched Vietnamese blind corpus.

## 2026-08-14 - Read-only replay round 3

Artifacts:

- `output/analysis-v2-eval/20260814-024838/round3-replay.json`
- `output/analysis-v2-eval/20260814-024838/round3-manual-semantic-verdict.json`
- `output/analysis-v2-eval/20260814-024838/manifest.sha256`

Runtime contract:

- all four tasks returned `success` with `runtime.llm_call_count == 1`;
- all four before/after task fingerprints were identical;
- prompt version observed: `investigation-analysis-simple-v5-minimal-source-guard`;
- harness tests: `13 passed`;
- automated replay verdict: `FAIL` only on G12 `no_factual_hedging` for task
  `cd6f85d0...`; every other automated gate passed.

Manual semantic verdict: **BLOCKED**.

- `84c115af...`: pass with source-quality caveat. No participants, events,
  actions or relationships are invented; sparse transcript and inconsistent
  speaker metadata are visibly warned.
- `d59205bd...`: minor fail. Core booking facts and modalities are faithful and
  the previous unsupported congratulation predicate is gone. Two uncertainty
  rows speculate about identifier/email validity without source evidence, and
  direct request/commitment items remain only in key points rather than the
  optional action view.
- `cd6f85d0...`: material fail. Standing duties are now correctly excluded from
  events/actions, but one noisy ASR span is silently repaired into a materially
  stronger statement about proposed command solutions and competent
  authorities. A possibility marker also remains in a factual key point,
  triggering G12.
- `c5923a81...`: pass with a minor coverage gap. The recording is correctly
  framed as a scheduled-election announcement; no speech-act time/location,
  uncontrolled status or answered follow-up is emitted. One ballot type's
  color/selection/count detail is omitted while the main content remains useful.

Round-3 event/action policy:

- empty `events`/`actions` is acceptable for standing duties, announcements and
  procedural instructions;
- event/action coverage is required only when the source contains a bounded
  event or direct action whose separation materially improves analyst utility;
- round 3 has zero material event/action false-positive errors, but promotion is
  still blocked by source strengthening and the lack of an independent second
  reviewer.

## 2026-08-14 - Locked V6 replay round 4

Artifacts:

- `output/analysis-v2-eval/20260814-030230/round4-replay.json`
- `output/analysis-v2-eval/20260814-030230/round4-manual-semantic-verdict.json`
- `output/analysis-v2-eval/20260814-030230/round4-vs-round3-comparison.json`
- `output/analysis-v2-eval/20260814-030230/manifest.sha256`

Candidate: `investigation-analysis-simple-v6-source-faithful-actions`.

Runtime and automated gates:

- focused contract/evaluation suite: `58 passed`;
- all four successful tasks report exactly one LLM call;
- all four before/after database fingerprints are identical;
- automated verdict remains `FAIL` because task `cd6f85d0...` still triggers
  G12 `no_factual_hedging`; all other automated gates pass.

Manual verdict: **BLOCKED**. Relative to round 3, V6 is **REGRESSED**.

- `84c115af...`: minor fail. Invented participant/event/action regressions do
  not return and source-quality warnings remain visible, but new uncertainty
  rows ask about relationship, motive and behavior that the noisy source does
  not support; the overview also adds an interaction-attitude interpretation.
- `d59205bd...`: material fail. V6 removes unsupported identifier/email validity
  speculation and exposes the direct account-detail request as an action.
  However, a generic address becomes a participant, several rows reverse the
  deposit requirement into a customer request, some confirmation rows cite
  unrelated evidence, the future sending commitment is not exposed as an
  action/commitment, and all three follow-ups are answered or not interrogative.
- `cd6f85d0...`: material fail unchanged. Standing duties remain correctly out
  of events/actions, but the noisy ASR passage is still silently normalized into
  a stronger command/authority statement and G12 hedging still fails.
- `c5923a81...`: material fail. Ballot coverage improves and speech-act event
  rows remain absent, but the overview adds an unsupported district-level
  election and promotes the scheduled announcement to an occurrence. Both
  follow-ups ask matters explicitly answered in the source.

Round-4 promotion gate: **BLOCK**. Prompt-only semantic generation must still
preserve actor/object binding, require unanswered interrogative follow-ups,
retain scheduled/announced modality, avoid adding unstated levels/categories,
and keep noisy ASR neutral rather than silently repairing it. A second
independent reviewer is also still required by the evaluation protocol.
