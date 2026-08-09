# Reference Reuse and Offline CAND Implementation Plan

Date: 2026-08-09
Status: proposed; independent audit required before execution
Goal: extend the active P0-P8 remediation goal without bypassing blocked T4

## 1. Outcome

Deliver one Vietnamese-first, fully offline audio-intelligence pipeline that:

- preserves immutable audio/transcript provenance and ASR/speaker uncertainty;
- extracts open-schema candidates without fixed-template padding;
- verifies attributed source assertions, values, roles, modality and contradictions
  before release, with world findings requiring independent corroboration;
- derives insights, hypotheses and verification actions from one canonical ledger;
- projects Summary and Analysis from the same run;
- packages models, runtimes, dependencies, prompts, schemas and licenses for an
  air-gapped deployment;
- passes a locked Vietnamese/noisy-ASR benchmark and security/privacy gates.

## 2. Reuse policy

Do not clone, overwrite, merge unrelated histories or cherry-pick a directory
wholesale.

- `SpeechToInfomation-pr` shares the same remote but has a different root commit
  and no merge base with the target. Port bounded facts/patterns by source commit
  and tests.
- `cherry_core` is a separate, heavily dirty research checkout. Treat its
  untracked experiments as research evidence, not a distributable release.
- No reference repository has a root license file. Internal code reuse requires
  recorded owner authorization; redistribution requires explicit license closure.

## 3. Dependency graph

```text
R0 provenance/license/baseline -> R1 deployable offline artifact bundle
R1 -> R2 transcript/correction uncertainty + selective ASR review
R1 -> R3 diarization uncertainty + evidence playback
R0 -> R4 T4 release-boundary hardening
R4 -> R5 adaptive discovery + omission critic -> R6 bounded reasoner
R2 + R3 + R6 -> R7 append-only DB/API + human attestation
R7 -> R8 Analysis UX convergence -> R9 blind benchmark/air-gap release
R1 ---------------------------------------------------------------> R9
```

R4 does not depend on R1/R2/R3. Because T4 code is already active and independently
blocked, its release adapter is the next implementation block after this audit
commit. R1 and R4 can progress independently; R2/R3 start after R1, but R6-R8
cannot expose new factual output until R4 passes.

### Locked evaluation hardware profile

The current benchmark host is recorded as `cand-dev-win4070s-12g-v1` in
`docs/research/reference-repo-audit/hardware-profile.json`: Windows 11 Pro
10.0.26200 x64, RTX 4070 SUPER 12,282 MiB, NVIDIA driver 591.86/CUDA API 13.1,
Ryzen 7 9800X3D 8C/16T, 64 GiB physical RAM (about 61.6 GiB OS-visible). This is
a development/evaluation profile, not an assumed production target. The D:
workspace volume has only about
4.0 GiB free at capture time and cannot hold a promoted offline bundle.

Production promotion requires a separately signed target profile with exact OS,
CPU, RAM, GPU/VRAM, driver/CUDA/runtime, storage, concurrency, latency and thermal
constraints. Benchmark results do not transfer automatically between profiles.

## 4. Phase R0 - provenance, license and baseline lock

### Reuse

- Adapt the RTK-like evidence/artifact discipline documented by `cherry_core`
  research in target-owned code; do not copy dirty/unlicensed implementation.
- Treat pinned artifact facts from `SpeechToInfomation-pr` as source hints, then
  independently reverify them in the target `model_runtime` schema.

### Tasks

1. Record source commits, dirty-state snapshots and ownership/license decisions
   for every ported file or algorithm.
2. Create `THIRD_PARTY_NOTICES`, SBOM, dependency license inventory and a policy
   for internal/manual artifacts.
3. Freeze current end-to-end baseline outputs for transcript, diarization,
   Summary and Analysis on a de-identified/synthetic fixture set.
4. Lock prompt/schema/model/runtime/config hashes and current failure examples.
5. Classify test data; remove or quarantine production-derived data from Git and
   define retention/legal-hold handling.
6. Record evidence class (`human_final`, `decoded`, `proxy`, `synthetic`) and
   holdout-view history so research artifacts cannot silently promote themselves.
7. Freeze corpus governance and annotation/adjudication protocol before training:
   Tier A/B/C definitions, annotator roles, access controls, de-identification,
   source-stratified train/calibration/validation splits and a sealed release holdout.
8. Hash every split manifest and record who has viewed the sealed holdout; R2/R3
   may use only train/calibration/validation, never the release holdout.

### Artifacts

- `docs/provenance/reference-port-register.yaml`;
- `config/models/*.manifest.json` source register;
- `docs/evals/baselines/current-pipeline/`;
- `docs/evals/corpus-governance/` with split manifests and sealed-holdout registry;
- `THIRD_PARTY_NOTICES.md`, SBOM and license bundle manifest.

### Gate

- No unknown source revision/license for a release component.
- Baseline is reproducible offline from exact inputs.
- No real sensitive audio/transcript is committed to the evaluation set.
- R2/R3 calibration data exists under an approved annotation protocol and the
  release holdout remains sealed.

## 5. Phase R1 - benchmark-candidate offline artifact closure

### Reuse

- Adapt `SpeechToInfomation-pr/docs/model_artifacts.required.json` artifact facts
  for faster-whisper medium/small and pyannote Community-1.
- Keep the target's stricter `src/services/model_runtime` parser/store.
- Reuse the reference profile/health idea, not its Internet-dependent startup.

### Tasks

1. Generate candidate manifests for every benchmark ASR, diarization, LLM,
   tokenizer, prompt template and native runtime artifact; do not mark a winner.
2. Package pinned `llama-server`/CUDA runtime, optional NeMo-Speech.cpp challenger,
   FFmpeg, Python wheelhouse, Node packages and OS prerequisites.
3. Add `OFFLINE_STRICT=true`; allow only loopback/local IPC providers.
4. Disable runtime Hugging Face/Ollama/GitHub downloads and undeclared user caches.
5. Build a staging-only fetch/sign script and a verify-only candidate startup.
6. Add model lease/health cache so API health never loads a heavyweight model.
7. Replace in-process daemon/lock job execution with a persistent single-GPU
   worker, atomic DB state transitions, idempotency keys, cancellation and watchdog.

### Tests

- manifest path traversal, duplicate ID, floating revision, size/hash tamper;
- missing tokenizer/config/license/runtime binary;
- cold start with OS/container outbound network denied;
- no writes outside declared model/cache roots;
- last-known-good rollback bundle.
- enqueue/multi-stage/deadlock/crash-recovery tests against the real worker, not a fake.

### Gate

`scripts/model_store.py preflight --profile benchmark-candidate` finds every
declared candidate manifest and passes. Candidate startup performs zero public
network attempts. No candidate is labelled production-promoted before R9.

## 6. Phase R2 - transcript uncertainty and selective ASR review

### Reuse

- Adapt the `cherry_core` PhoGuard/SAGE idea: transparent risk features,
  abstention, calibration, evidence modes and conformal risk control.
- Do not copy embedded thresholds/calibrators or treat rule scores as
  probabilities.

### Tasks

1. Implement `UncertainTranscriptSegment` with raw/normalized text, timestamp
   provenance, full Whisper metrics, word probabilities, alternatives and flags.
2. Rename current `confidence=avg_logprob`; preserve the raw metric instead of a
   false calibrated label. Remove overall confidence `1.0` defaults.
3. Label PhoWhisper uniform word times as `estimated` and keep segment-level
   source timing.
4. Introduce immutable `TranscriptCorrectionRevision`: input/output hash, model
   and config revision, ordered edit spans, raw-to-corrected mapping, reviewer and
   abstention state. Corrected text never overwrites raw text.
5. Require VAD/chunk/alignment transforms to map every timestamp back to the
   original audio revision; compressed speech timelines are never evidence coordinates.
6. Port a provider-neutral feature extractor and decision schema from PhoGuard/
   SAGE; train a target calibrator only on labelled target-domain data.
7. Implement `accept/needs_review/abstain`, with critical identifier audio review.
8. Store raw, accepted and review text; never silently delete a suspicious span.

### Tests and benchmark

- low-speech hallucination, repetition, decoder disagreement, code-switch and
  short valid Vietnamese controls;
- calibration split, source-stratified evaluation and conformal false-accept bound;
- human transcript versus ASR transcript downstream delta;
- raw versus corrected transcript downstream delta and edit-span replay;
- CER/WER, critical entity F1, hallucinated-span rate, coverage, RTF/RAM/VRAM.

### Gate

- No uncalibrated number is called probability/confidence.
- Severe accepted hallucination is zero on the release set.
- Coverage and false-accept risk are reported together; abstention is visible.
- No corrected token or transformed timestamp can be released without replay to
  raw transcript and original audio.

## 7. Phase R3 - diarization uncertainty and audio evidence

### Reuse

- Adapt the local pinned pyannote package flow from `SpeechToInfomation-pr`.
- Reuse ports/adapters, but upgrade the domain contract beyond one speaker label.
- Keep VBx/Sortformer/alternative adapters as benchmark challengers only.

### Tasks

1. Add speaker candidates, overlap, ambiguity, confidence provenance and human
   mapping to diarization records.
2. Replace winner-take-all `overlap > 0.3` alignment with split/exclusive mapping
   and explicit unresolved/overlap states.
3. Package pyannote Community-1 locally after authorized terms acceptance; store
   revision, files, license/attribution and network-denial evidence.
4. Add audio clip playback bound to exact source file hash and time span.
5. Preserve anonymous speaker cluster IDs; never infer real identity from voice
   or conversation content without an authorized separate process.
6. Store inferred speaker role/name separately as a reviewable hypothesis; never
   mutate the diarization cluster ID or raw speaker assignment.

### Gate

- DER/JER, speaker-count accuracy, overlap recall and speaker-attributed WER are
  measured on Vietnamese/noisy slices.
- UI never hides ambiguous/overlapping/unknown speaker state.

## 8. Phase R4 - harden T4 release boundary

### Blocking findings to fix

1. Legacy caller-built trusted registries can bypass T4.
2. Contradictions live outside the ledger and can be lost before T5.
3. Reported speech is factual-release eligible.
4. Subject/object reversal passes token-set alignment.
5. A forged `VerifiedVerificationBatch` wrapper can be resealed without trusted replay.
6. Replay trusts caller-supplied source-module hashes.
7. Risk artifact identity excludes its subject digest.
8. Opposite-polarity contradiction output can grow as `m x n`.

### Tasks

1. Create one release adapter accepting exact T3/T4/source artifacts and replaying
   them internally.
2. Require T4 `status=success`, zero unresolved release-blocking contradictions
   and exact ledger hash/equality binding.
3. Derive release registries inside the adapter; remove production access to raw
   trusted context builders.
4. Add a separate reported/hearsay projection class; block it from factual refs.
5. Add semantic-role actor/action/object/recipient checks and adversarial tests.
6. Recompute source-module hashes and Git revision inside the trusted boundary.
7. Bind risk IDs to `subject_sha256`.
8. Bound contradiction generation by canonical key, dedupe, cap and review summary.

### Gate

- Legacy/raw context cannot authorize success.
- T5 must replay T4 and cannot trust wrapper type alone.
- Reported speech never enters facts.
- Contradiction and semantic-role adversarial tests pass.
- Performance matrix covers N=100/500/1000/2000, collision-heavy and unique cases.

## 9. Phase R5 - adaptive discovery and omission critic

### Reuse

- Keep the target's T2/T3 evidence selector, chunk planner, deterministic detector
  and strict materializer.
- Reject fixed scenario dictionaries and mandatory forms from old Cherry/PR
  prompts as production truth; retain them only as labelled adversarial fixtures.

### Tasks

1. Version the P1 discovery prompt and P2 omission-critic prompt from the prompt
   specification.
2. Add source role/modality to candidates and typed exact-value check records.
3. Build position-balanced coverage maps and multi-needle long-context tests.
4. Ensure overlap context cannot become an output source.
5. Add candidate-only multilingual entity challenger and optional soft duplicate
   retrieval without merge authority.

### Gate

- No required placeholder/null output.
- Candidate/relation IDs are host-owned and scope-bound.
- Critic provides measured recall gain without violating released precision.
- Prompt injection inside transcript is treated as data.

## 10. Phase R6 - bounded reasoner and shared projections

### Tasks

1. Implement the reasoning service for `EvidenceBackedInsight`, `Hypothesis` and
   `VerificationAction`; current objects are contracts only.
2. Require complete released premises, explicit alternatives/counterevidence and
   answerable verification criteria.
3. Implement adaptive theme planning from the verified graph.
4. Implement one evidence-preserving synthesizer for Summary and Analysis.
5. Remove old independent Summary/Analysis/visualization LLM generation paths.
6. Keep deterministic post-checks for claim refs, exact values, duplicate themes
   and hypothesis leakage.

### Gate

- Every released sentence maps to claim IDs and preserves source-assertion,
  corroborated-finding or derived-insight class without de-attribution.
- Insight premise resolution is 100%.
- Hypothesis-to-fact leakage and unsupported high-risk claims are zero.
- Summary/Analysis share one source revision and run ID.

## 11. Phase R7 - append-only persistence and human attestation

### Reuse

- Reimplement the `SpeechToInfomation-pr` row-lock and expected-revision patterns
  in target-owned code after ownership/license review.
- Adapt review states and metadata/detail API split.
- Reject its `Task.result` JSON monolith, `create_all` deployment and physical
  deletion called archive.

### Tasks

1. Add normalized `investigation_runs`, source revisions, claims, evidence refs,
   contradictions, reasoning records, projections and review events.
2. Keep Task as orchestration/status pointer only.
3. Implement `HumanReviewAttestation` with reviewer, policy, exact subject hash,
   decision, reason, before/after refs, UTC time and signature/audit hash.
4. Use Alembic-only production migrations and UTC timezone-aware columns.
5. Add legal hold, retention and approved secure-purge workflows. Archive is
   non-destructive by default.
6. Implement append-only/audit-outbox controls and immutable evidence export.
7. Enforce case/file/run authorization and no cross-case reference.

### Gate

- Concurrent update conflict and idempotency tests pass.
- No source evidence is physically deleted by an archive action.
- Every human decision is attributable, immutable and replayable.
- Production startup refuses schema drift and never calls `create_all`.

## 12. Phase R8 - Analysis workspace and UX convergence

### Reuse

- Adapt the reference Analysis panel's evidence list, review status and file
  selector concepts.
- Do not reuse the deterministic hotel/booking extractor or legacy graph ontology.

### Tasks

1. Keep one top-level Analysis tab; remove duplicate visualization task/tab.
2. Show active case, file name, upload time, source hash short form and run revision
   persistently across Transcript/Diarization/Summary/Analysis.
3. Provide Overview, Evidence, Entities/Events/Relations, Timeline, Contradictions,
   Insights, Hypotheses and Verification Actions as views of one run.
4. Make diarization collapsible per file/speaker and link every important item to
   exact audio playback.
5. Use metadata-only paginated lists and separate detail endpoints with ETag/no-store.
6. Add copy buttons for overview and bounded sections without copying hidden data.

### Gate

- No blank page on partial/invalid payload; error boundary shows run/task evidence.
- No duplicate Analysis/visualization requests for one user action.
- Long case payload does not block the browser main thread or poll heavy runtime
  health every five seconds.

## 13. Phase R9 - blind benchmark and air-gapped release

### Tasks

1. Open the R0 fresh, unseen sealed release holdout under recorded authorization
   only after all model, threshold, prompt and runtime choices are frozen.
2. Require genuinely human-rated release labels; proxy labels, viewed holdouts and
   synthetic-only slices cannot satisfy the product gate.
3. Run required model/runtime/quantization/prompt ablations on the locked hardware
   profile and select the promoted profile from measured quality/resource tradeoffs.
4. Generate production manifests only for the winning artifacts and exact target
   hardware/runtime profile; keep challengers outside the production bundle.
5. Execute security, prompt-injection, cross-case, privacy, retention and export tests.
6. Run cold-start, long-file soak, queue backpressure, crash recovery and rollback.
7. Generate a signed release manifest and immutable validation report.
8. Deploy shadow -> opt-in canary -> controlled production after stakeholder signoff.

### Product release gates

- schema 100%; source/hash/reference 100%; severe hallucination 0;
- critical precision >=0.98, macro recall >=0.95, exact-value accuracy >=0.99;
- insight premises 100%; hypothesis leakage 0;
- zero public network attempts; all dependencies/models/licenses present;
- no cross-case evidence or unauthorized export;
- signed legal/security/privacy/operational acceptance by authorized stakeholders.

## 14. Commit strategy

Use small, auditable commits and push only after each phase audit passes:

1. `research(reuse): audit reference repositories`
2. `fix(ai): enforce T4 release boundary`
3. `chore(models): lock benchmark-candidate offline artifacts`
4. `feat(asr): preserve uncertainty and selective review`
5. `feat(diarization): preserve speaker uncertainty`
6. `feat(ai): add omission-aware discovery`
7. `feat(ai): add bounded reasoning and projections`
8. `feat(data): add append-only investigation runs`
9. `feat(ui): converge analysis workspace`
10. `release(offline): verify air-gapped CAND profile`

Never mix unrelated user changes or blocked T4 code into the research-plan commit.

## 15. Residual risks

- Reference repositories contain valuable research but no root license closure.
- Local model stores are large and partly duplicated; physical presence does not
  prove complete, licensed or reproducible packaging.
- The target currently has model files but no selected production manifests, so
  offline preflight correctly fails.
- A human-labelled Vietnamese investigative corpus remains the main evidence gap.
- Cherry's current calibrators and intervention experiments cannot be promoted:
  key labels are proxy-derived, several arms are negative/scaffold-only and the
  research checkout is not a committed reproducible release snapshot.
- Public sources cannot validate classified CAND procedures or accreditation.
