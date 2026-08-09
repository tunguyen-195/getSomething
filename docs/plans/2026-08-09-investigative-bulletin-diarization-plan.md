# Investigative Bulletin and Diarization Implementation Plan

**Date:** 2026-08-09

**Status:** Active; implementation gated task by task

**Canonical workspace:** `E:\research\STT`
**Research input:** `docs/research/2026-08-09-investigative-bulletin-diarization-evidence-refresh.md`

## 1. Objective

Deliver an offline, evidence-backed audio intelligence workflow whose bulletin lets an authorized user understand the whole audio, critical and sensitive values, speaker-aware events, bounded insights, uncertainties, and verification needs without presenting unsupported LLM output or degraded diarization as fact.

This plan refines the active P0-P8 remediation goal. It does not replace the broader remediation, offline-release, ASR, security, or authorization gates.

## 2. Locked product rules

1. Summary and Analysis are projections of one canonical source revision and claim ledger.
2. Every factual sentence has semantic support, claim refs, and resolvable evidence refs.
3. Every released critical claim appears in the overview or a critical-detail sentence; every other released claim appears in exactly one primary theme.
4. Exact names, phones, accounts, IDs, money, quantities, times, places, vehicles, objects, documents, actions, decisions, and relations cannot be silently normalized away.
5. Hypotheses and verification actions never enter factual prose.
6. Diarization failure, degraded output, verified one-speaker output, overlap, and unresolved speaker state are distinct.
7. Speaker cluster IDs are anonymous evidence labels. Human identity/role mapping is a separate append-only review assertion.
8. A short complete bulletin passes below advisory minimum length; maximum length and factual/evidence bounds remain hard.
9. Unknown summary type/model alias/diarization method fails at every entry point before GPU/model use.
10. Runtime/profile UI reports live alias/path/hash/server binding, not artifact presence alone.
11. Performance benchmarks include the real direct/Celery path, cleanup, GPU handoff, cold/warm/wake state, and long-audio chunking.
12. DB-backed pytest runs are serialized until P0 test isolation is repaired.

## 3. Dependency order

```text
P0 test isolation
  -> S1 strict summary/evidence contract
  -> S2 semantic sentence and coverage release gate
  -> S3 shared type/length contract
  -> S4 synchronous fail-closed
  -> G1 shared GPU handoff/recovery
  -> F1a verified runtime profile/model alias
  -> Q1 whole-audio discovery and source-coverage integration
  -> C1 append-only run and grounded multi-file orchestration
  -> D1 offline diarization artifact/profile
  -> D2 speaker-turn uncertainty and alignment
  -> X1 speaker-aware claim release
  -> F1b file-aware evidence UX
  -> E1A corpus/scorer/baseline lock
  -> E1 Vietnamese quality-performance promotion
```

The order preserves the handoff priority: S1, S2, S3, S4, G1, and F1a remain the first product packages after test safety. Q1 and C1 are inserted before promotion because per-claim correctness cannot prove that the system found the important content across a long or multi-file source.

### 3.1 Exact package allowlists

No task may expand its allowlist during implementation without first updating its task manifest and obtaining a new independent audit. Generated model weights, user audio, DB dumps, caches, and unrelated dirty hunks are always excluded.

| Package | Exact initial production/config paths | Exact initial test, harness, and evidence paths |
|---|---|---|
| P0A | `tests/conftest.py` | `tests/test_test_database_isolation.py`; `scripts/verify_test_database_isolation.py`; `docs/reviews/artifacts/p0-test-isolation.json` |
| S1 | `docs/plans/2026-08-09-investigative-bulletin-diarization-plan.md`; `scripts/audit_summary_diarization_readiness.py`; `src/services/summarization/models/context_analysis.py`; `src/services/summarization/models/investigation_knowledge.py`; `src/services/summarization/models/llm_manager.py`; `src/services/summarization/context_service.py`; `src/services/summarization/legacy_context_adapter.py`; `src/services/audio_service.py`; `src/summarization/summarizer.py`; `src/web_interface/app.py` | `scripts/evaluate_context_analysis.py`; `tests/test_summary_diarization_audit_harness.py`; `tests/test_context_analysis.py`; `tests/test_investigation_knowledge.py`; `tests/test_context_eval_harness.py`; `docs/reviews/artifacts/s1-summary-schema.json` |
| S2 | `src/services/investigation/contracts.py`; `src/services/investigation/run_contracts.py`; `src/services/investigation/narrative_attestation.py`; `src/services/investigation/release_adapter.py`; `src/services/summarization/summary_service_v2.py` | `tests/test_adaptive_summary_contracts.py`; `tests/test_investigation_release_adapter.py`; `tests/test_local_llm_optimization.py`; `docs/reviews/artifacts/s2-narrative-release.json` |
| S3 | `src/services/summarization/contracts.py`; `src/services/summarization/summary_service_v2.py`; `src/api/endpoints/audio_v2.py`; `src/api/endpoints/audio.py`; `src/api/endpoints/summary.py`; `src/worker/tasks/summarize_task.py`; `frontend/src/api/client.ts`; `frontend/src/components/SummarizeDialog.tsx` | `tests/test_summary_request_contract.py`; `tests/test_local_llm_optimization.py`; `docs/reviews/artifacts/s3-summary-request-contract.json` |
| S4 | `src/api/endpoints/audio_v2.py`; `src/api/endpoints/audio.py`; `src/worker/tasks/summarize_task.py`; `src/services/task_service.py` | `tests/test_summary_fail_closed.py`; `docs/reviews/artifacts/s4-summary-state-transitions.json` |
| G1 | `src/services/model_runtime/gpu_lease.py`; `src/services/model_runtime/__init__.py`; `src/services/summarization/models/openai_compatible_client.py`; `src/services/summarization/summary_service_v2.py`; `src/services/transcription/transcribe_service_v2.py`; `src/worker/tasks/summarize_task.py`; `src/worker/tasks/transcribe_task.py`; `scripts/recover_gpu_quarantine.py`; `scripts/start_llama_server.ps1`; `docs/runbooks/gpu-quarantine-recovery.md` | `tests/test_model_runtime.py`; `tests/test_openai_compatible_llm.py`; `tests/test_gpu_quarantine_subprocess.py`; `docs/reviews/artifacts/gpu-handoff-live.json` |
| F1a | `src/api/endpoints/system.py`; `src/main.py`; `src/core/config.py`; `frontend/src/api/client.ts`; `frontend/src/App.tsx`; `frontend/src/components/SummarizeDialog.tsx`; `frontend/src/components/TaskList.tsx` | `tests/test_startup_runtime_profile.py`; `frontend/src/__tests__/runtimeProfile.test.tsx`; `docs/reviews/artifacts/runtime-profile-contract-tests.json` |
| Q1 | `src/services/investigation/chunk_planner.py`; `src/services/investigation/exact_detectors.py`; `src/services/investigation/discovery.py`; `src/services/investigation/discovery_contracts.py`; `src/services/investigation/source_revision.py` | `tests/test_investigation_discovery.py`; `tests/test_investigation_evidence_selectors.py`; `tests/eval/whole_audio_coverage_cases.jsonl`; `docs/reviews/artifacts/q1-source-coverage.json` |
| C1 | `src/database/models/models.py`; `src/services/investigation/run_store.py`; `src/services/investigation/orchestrator.py`; `src/api/endpoints/summary.py`; `src/worker/tasks/summarize_task.py` | `scripts/rehearse_intelligence_run_migration.py`; `tests/test_intelligence_run_persistence.py`; `docs/reviews/artifacts/c1-intelligence-run.json`; the exact new Alembic version path recorded by the C1 preflight before editing |
| D1 | `models/manifests/pyannote-speaker-diarization-community-1.json`; `src/services/model_runtime/local_artifacts.py`; `src/services/transcription/models/pyannote_manager.py`; `src/cherry_core/adapters/diarization/pyannote_adapter.py`; `src/core/config.py`; `requirements.txt`; `requirements-torch-cu121.txt`; `scripts/acquire_pyannote_community1.py`; `scripts/verify_pyannote_offline.py`; `docs/runbooks/pyannote-offline.md` | `tests/test_transcription_engines.py`; `docs/reviews/artifacts/pyannote-community-1-acquisition.json`; `docs/reviews/artifacts/pyannote-community-1-network-denied-loader.json` |
| D2 | `src/services/transcription/contracts.py`; `src/services/transcription/transcribe_service_v2.py`; `src/services/transcription/models/pyannote_manager.py`; `src/cherry_core/ports/diarization_port.py`; `src/cherry_core/adapters/diarization/pyannote_adapter.py` | `tests/test_transcription_engines.py`; `tests/test_diarization_alignment.py`; `docs/reviews/artifacts/diarization-contract-tests.json` |
| X1 | `src/services/investigation/contracts.py`; `src/services/investigation/run_contracts.py`; `src/services/investigation/source_revision.py`; `src/services/investigation/release_adapter.py` | `tests/test_adaptive_summary_contracts.py`; `tests/test_investigation_release_adapter.py`; `tests/test_speaker_aware_claim_release.py`; `docs/reviews/artifacts/x1-speaker-claim-release.json` |
| F1b | `frontend/src/App.tsx`; `frontend/src/api/client.ts`; `frontend/src/components/TranscriptPanel.tsx`; `frontend/src/components/DiarizationPanel.tsx`; `frontend/src/components/SummaryPanel.tsx`; `frontend/src/components/AnalysisPanel.tsx`; `frontend/src/components/InvestigationSummaryCard.tsx` | `frontend/src/__tests__/fileAwareEvidence.test.tsx`; `tests/test_case_evidence_authorization.py`; `docs/reviews/artifacts/f1b-file-aware-evidence.json` |
| E1A | `scripts/evaluate_summary_diarization.py`; `tests/eval/summary_diarization_corpus_manifest.json`; `tests/eval/summary-diarization-scoring-v1.json`; `tests/eval/summary_diarization_cases.jsonl` | `tests/test_summary_diarization_evaluator.py`; `docs/evals/runs/summary-diarization-baseline-v1.json`; `docs/reviews/artifacts/e1a-baseline-lock.json` |
| E1 | `scripts/evaluate_summary_diarization.py`; `docs/evals/runs/summary-diarization-candidate-v1.json` | `docs/reviews/artifacts/e1-promotion-audit.json` |

## 4. Task sequence

### P0A - Serialize and isolate test execution

**Deliverables**

- Add a lock or per-worker database/schema strategy so concurrent pytest processes cannot race `drop_all/create_all`.
- Add a negative guard proving the application database `speech_to_info` is never targeted.
- Remove historical D source paths from regenerated test bytecode/evidence output without touching the D repo.

**Gate**

- Two intentionally concurrent test invocations do not deadlock or mutate each other's schema.
- Non-`_test` URL fails before DDL.
- App DB `SELECT 1` remains healthy before and after the harness.

**Commit boundary:** test infrastructure only.

### S1 - Typed nested evidence and canonical output separation

**Owned surface**

- `src/services/summarization/models/context_analysis.py`
- `src/services/summarization/models/investigation_knowledge.py`
- `src/services/summarization/models/llm_manager.py`
- `src/services/summarization/context_service.py`
- focused tests

**Implementation**

- Add canonical `summary_sentences: list[EvidenceBoundSummarySentenceDraft]` with required `draft_id`, `text`, `sentence_role`, and non-empty `evidence_quotes`. Keep top-level `summary` only as a legacy compatibility projection and prohibit release code from treating it as authority.
- Remove the canonical legacy key-point string upgrader; keep compatibility in an explicit versioned legacy adapter only.
- Make knowledge nested models strict and type timeline/safety/attributes envelopes where they affect release.
- Resolve every sentence/item quote against the immutable source revision. Ungrounded items produce machine-readable gate failures and cannot remain in the released/raw product payload.
- Preserve a rendered `summary` string only as a compatibility projection; store typed narrative separately.

**Negative tests**

- Unknown nested field, missing evidence, missing required entity value, unresolvable quote, duplicate ID, raw unsupported item leakage, and legacy string in canonical validator.

**Gate**

- JSON Schema uses `additionalProperties=false` at every closed safety/provenance level.
- Released payload contains no item absent from grounded knowledge.
- No model/network call in contract tests.

**Commit boundary:** one atomic S1 schema/grounding commit using only the S1 allowlist, followed by an independent S1 audit. S2 is never staged in the same commit.

### S2 - Per-sentence semantic attestation and critical coverage

**Owned surface**

- `src/services/investigation/contracts.py`
- `src/services/investigation/run_contracts.py`
- `src/services/investigation/narrative_attestation.py` as the T5 narrative-stage authority, not a Transformer T5 model dependency
- `src/services/summarization/summary_service_v2.py`
- contract and release tests

**Implementation**

- Extend `NarrativeSentence` with required `sentence_id`, derived non-empty `evidence_refs`, `content_sha256`, and `semantic_attestation_ref`.
- Add `narrated_claim_refs` coverage: every released claim appears in narrative; every critical claim appears in overview or a critical-detail sentence.
- Add typed salience/category metadata needed to gate important and sensitive omission without closing the business ontology.
- Reject new names/numbers/exact values not present in referenced claims/evidence.
- Define `NarrativeAttestationArtifact` with schema version, producer ID, source revision, exact sentence hash, exact claim/evidence hashes, renderer/prompt/model digest, decision, and replay verifier result. The producer is either the deterministic renderer or a pinned verifier executed inside the trusted run context; caller-supplied JSON is never an authority.
- First safe vertical slice uses a deterministic renderer over released claims to keep one LLM call. An LLM narrative challenger may be added only with atomic sentence re-verification and fail-closed `needs_review`.
- Keep evidence-backed insights factual only when all premise claims are released and the derivation is attested.

**Negative tests**

- Fabricated confession with valid claim ref, hallucinated phone/account/amount/time, released claim omitted from narrative, critical claim omitted from overview/detail, dangling evidence, hypothesis leakage, and duplicate primary theme.

**Gate**

- Factual sentence semantic support and evidence resolution: 100% in contract fixtures.
- Released-claim narrative coverage: 100%.
- Critical-claim required placement: 100%.
- Severe hallucination and hypothesis leakage: 0.

**Commit boundary:** one atomic S2 narrative release commit using only the S2 allowlist, followed by an independent S2 audit.

### S3 - Shared summary type and length contract

**Implementation**

- Create one shared `SummaryType`/request contract imported by v2 API, legacy API, service, Celery, multi-summary, and frontend types.
- Reject unknown values with 422 at HTTP and typed failure before GPU/model at direct/worker boundaries.
- Keep `max_length`, non-empty output, evidence bounds, and coverage as hard gates.
- Make `min_length` advisory and return `minimum_satisfied=false` without failing a complete short transcript.
- Remove fixed 80-220 wording from the context prompt; pass one coherent target/maximum contract.

**Gate**

- Invalid type never reaches model/GPU.
- Short evidence fixture passes; over-maximum fixture fails.
- Direct, API, Celery, and multi-summary behavior is identical.

**Commit boundary:** shared contract + all callers + negative tests.

### S4 - Synchronous summary fail-closed

**Implementation**

- Apply the v2 `available=true`, non-empty, evidence/release gate to legacy and synchronous paths.
- Never persist or return `summarized` when the service is unavailable, cleanup/handoff is unsafe, or release gates fail.
- Return explicit non-2xx error with stable code; persist `failed`/`needs_review` and diagnostics without sensitive transcript content.

**Gate**

- Legacy, v2, direct, and Celery negative cases never write false success.
- Successful and failed state transitions are idempotent.

**Commit boundary:** endpoints/state transition tests + independent S4 audit.

### Q1 - Whole-audio discovery and source-coverage integration

**Scheduling note:** this specification is adjacent to the summary tasks for readability, but execution is deferred until G1 and F1a PASS, exactly as locked in the dependency order.

**Implementation**

- Wire the existing T3 `chunk_planner`, deterministic exact-value detectors, and open-schema discovery into the canonical investigation path instead of leaving them as isolated contracts/tests.
- Persist a `SourceCoverageManifest` for every file and chunk: source revision, segment/turn range, beginning/middle/end stratum, overlap with adjacent chunks, detector channels run, model call ID, candidates emitted, empty reason, and retry state.
- Require all authorized case files and all eligible transcript segments to be covered exactly once as a primary chunk, with bounded overlap only for context. A missing/failed chunk blocks completion or creates explicit `needs_review`; it cannot silently reduce the bulletin.
- Measure candidate-level critical recall before T4 verification. Released-claim coverage is reported separately so a verifier cannot hide extractor omissions.
- Preserve exact values with owner/role/unit binding and position-balanced retrieval. User focus changes ranking only; it cannot remove critical categories or source strata.

**Negative tests**

- Lost-middle multi-needle cases, critical value only in first/last chunk, repeated value with different owners, multi-file case with one skipped file, detector/LLM disagreement, prompt injection, empty chunk, and retry/idempotency replay.

**Gate**

- Authorized source segment and file coverage: 100% in fixtures.
- Missing chunk/file and unexplained empty emission: 0.
- Critical candidate recall is no worse than the locked fixed-form baseline in any category; no quality claim is made until E1 locks the corpus and scorer hashes.
- One-call deterministic S2 path remains available; Q1 records LLM call count, tokens, chunk count, p50/p95 latency, RAM/VRAM, and cache behavior.

**Commit boundary:** one atomic Q1 discovery/orchestration commit + immutable source-coverage JSON + independent Q1 audit.

### C1 - Append-only run and grounded multi-file orchestration

**Implementation**

- Create versioned append-only `intelligence_runs` ownership with run ID, authorized case/file scope, source and diarization revisions, status, supersession, ledger, narrative, quality report, release state, model/config/schema/prompt hashes, Git/source hashes, and retention/legal-hold metadata.
- Use one idempotency key over source revisions + diarization revisions + pipeline/config digests. Direct API, Celery, multi-summary, Analysis, and visualization read projections from the same run and cannot create competing mutable truth stores.
- Replaying against a different file set, case/user authorization scope, source revision, diarization revision, or config digest fails closed.
- Preserve backward reads from legacy `Task.result`, but label them `legacy_unverified`; never backfill them as verified without replay.

**Gate**

- Fresh DB and production-clone migration rehearsal pass; no live stamp or ad-hoc migration.
- Duplicate request creates at most one canonical run; failed/retried worker transitions are idempotent.
- Cross-user, cross-case, removed-file, changed-transcript, changed-diarization, legal-hold, retention, and supersession negative tests pass.
- A multi-file bulletin proves every sentence against a source in the authorized run manifest.

**Commit boundary:** migration/model/store/orchestrator tests as one C1 package only after the exact Alembic path is locked in the C1 preflight artifact.

### G1 - Shared GPU quarantine, handoff, and recovery

**Implementation**

- Move cleanup verification and quarantine into a shared runtime/service boundary used by all providers and direct/Celery callers.
- Cleanup false/exception creates persistent quarantine and blocks the next stage.
- Add a module-local random `process_instance_id` at process start and bind every lease/quarantine snapshot to lease ID, PID, process instance, owner, and stage. Same owner/stage from another process cannot reuse quarantine authority; old markers without the new binding fail closed.
- Parse llama-server `props.is_sleeping` as a real JSON boolean and accept only identity-equal `True`; string/number truthiness is rejected.
- Add recovery CLI and runbook; clear only after provider-specific live proof.
- Audio cleanup failure prevents LLM acquisition and records post-cleanup GPU evidence.
- `scripts/start_llama_server.ps1` must acquire and honor the shared lease/quarantine state machine before runtime verification or process launch. Active Ollama or another GPU provider requires provider-specific unload plus live process/VRAM proof; absent proof blocks repository-local startup and is reported explicitly.
- Emit `rtk-evidence-v1` live evidence bound to current source/test/harness hashes, command, exit code, runtime/model hashes, hardware identity, observed time, sleep/wake response, and pre/post VRAM.

**Gate**

- Same-owner cross-process retry cannot bypass quarantine.
- String `"false"` is rejected.
- Direct/Celery parity and subprocess tests pass.
- Live sleep/wake/VRAM gate passes before release promotion.
- Cleanup false/exception, stale marker, provider mismatch, server crash, and recovery without live `/props.is_sleeping=true` all retain quarantine.

**Commit boundary:** GPU runtime package only; do not mix with summary schema hunks.

### F1a - Verified runtime profile and model alias

**Implementation**

- Add `GET /api/v1/system/runtime-profile` with active/degraded/blocked status, canonical alias, available aliases, provider/runtime/model provenance, live server binding, model path/SHA-256, manifest status, and release eligibility.
- Remove hardcoded `llama3.2:3b` and `gemma2:9b` selections. `auto` resolves server-side only to an alias whose provider/path/hash/server response all match the active profile.
- Unknown alias, provider mismatch, server-down state, model-path/hash mismatch, or artifact-only state returns 422/503 and a blocked profile; no legacy fallback.
- Preserve `legacy_unverified` for historical results whose runtime cannot be reconstructed.
- Produce `rtk-evidence-v1` contract evidence bound to backend/frontend/test hashes.

**Gate**

- Endpoint, direct service, Celery request, multi-summary, and frontend expose the same available alias set.
- Active alias/path/hash/server mismatch never reaches model generation.
- Frontend renders blocked/degraded/unverified truthfully and contains no hardcoded legacy model ID.

**Commit boundary:** backend runtime profile + frontend alias consumption only; file-aware evidence UX remains F1b.

### D1 - Offline diarization artifact and runtime profile

**Implementation**

- Treat the current 9-file `models/pyannote_cache` tree as legacy metadata only. Migration evidence proves it was copied without loss, but it is not a 3.1 or Community-1 runtime snapshot and must never be promoted by changing only the search path.
- Before changing the shared environment, run a compatibility preflight comparing an isolated repository-local diarization runtime with a coordinated shared-stack upgrade. Record correctness, startup/IPC overhead, GPU handoff, VRAM, ASR regression, packaging size, and clean-install reproducibility; update the D1 task manifest and allowlist before adding any new runtime/lock file selected by that decision.
- After authorized gated-model acceptance, package Community-1 at revision `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee`. Record model ID, exact resolved snapshot path/ref, authorization event, CC-BY-4.0 acceptance/attribution, source-metadata response hash, every file path/size/SHA-256, acquisition harness hash, and immutable acquisition evidence.
- Pin and verify a compatible Pyannote/Torch/Torchaudio/TorchCodec/FFmpeg stack. Community-1/pyannote.audio 4.x must use the `token` API, unwrap regular/exclusive diarization from the output object, and must not be declared compatible with the current 3.1.1/Torch 2.1.1 stack without a passing probe.
- Use one absolute canonical model root in both manager and Cherry adapter. Require `config.yaml`, embedding weights, PLDA assets, segmentation weights, package/runtime versions, FFmpeg/TorchCodec prerequisites, and network-denied loading before returning artifact availability.
- Expose `requested_method`, `method_used`, model/revision/hash, artifact verification, live-load status, and degraded reasons.
- Strict profile fails if the required artifact is missing. A degraded profile may continue transcription only with explicit `diarization_status=unavailable|degraded`.

**Gate**

- No runtime download or external cache creation; before/after external-cache inventory is identical.
- Missing/tampered artifact fails before audio processing.
- Clean install reproduces the pinned runtime, and the selected isolation/shared-stack design passes ASR regression plus GPU handoff gates.
- Community-1 regular/exclusive output is consumed through the pinned API contract; legacy `use_auth_token` and direct-output assumptions fail negative tests.
- Verified one-speaker result is distinguishable from unavailable/degraded fallback.
- Model manifest, acquisition evidence, resolved snapshot, loader evidence, runtime versions, and current disk hashes all replay against each other.

**Commit boundary:** model manifest/verifier/loader/runbook; model weights follow release/LFS policy and are not blindly committed.

### D2 - Speaker-turn uncertainty and safe alignment

**Implementation**

- Define typed diarization run/turn contracts with source file/revision, anonymous cluster, start/end, overlap, ambiguity, confidence provenance, assignment method, and human mapping state.
- Add one shared `DiarizationMethod` allowlist imported by API, service, worker, Cherry adapter, and frontend. Unknown methods fail before ASR/diarization model use.
- Retain ASR word objects and label each timestamp `actual`, `model_estimated`, or `segment_interpolated`. PhoWhisper/other estimated timing cannot be presented as measured word timing.
- Replace whole-segment winner-take-all mapping with word/turn-aware split alignment only when timing provenance meets the locked error gate; otherwise use turn/segment alignment with explicit exclusive/overlap/unresolved states.
- Guard zero-duration/tie/unmapped cases.
- Convert unsupported audio into a unique temporary directory; never overwrite/delete a sibling user file.
- Preserve per-file speaker namespaces; no cross-file `SPEAKER_00` merge.

**Gate**

- Unit fixtures cover invalid method, overlap, tie, zero duration, repeated labels across files, conversion collision, unmapped turns, actual versus estimated timestamps, and timestamp-error fallback.
- No inferred human identity mutates raw cluster IDs.
- Timestamp MAE and speaker-attributed WER are reported separately by timestamp provenance; estimated-timestamp slices cannot unlock word-level alignment promotion.

**Commit boundary:** diarization domain/adapter/alignment + tests + independent D2 audit.

### X1 - Speaker-aware claim and bulletin release

**Implementation**

- Bind every evidence span and speaker-dependent claim to diarization revision/status.
- When speaker assignment is unresolved/degraded, withhold or qualify owner/role claims; do not silently transfer the value to a named speaker.
- Separate transcript-grounded statements from audio/speaker-grounded statements in the bulletin and evidence drawer.
- Human speaker mapping creates a new review assertion and never rewrites raw diarization.

**Gate**

- Wrong-speaker sensitive-value release: 0 on adversarial fixtures.
- Speaker-dependent claim precision and withholding accuracy meet locked thresholds.
- Replaying a summary against a different diarization revision fails.

**Commit boundary:** cross-stage provenance and release tests.

### F1b - File-aware evidence and investigation UX

**Implementation**

- Preserve runtime and summary provenance through list/detail API and frontend types.
- Render adaptive overview/themes, facts, insights, hypotheses, and verification actions separately.
- Keep file identity visible across Transcript/Diarization/Summary/Analysis.
- Group diarization `file -> speaker -> turns`; show degraded state, method/model provenance, overlap/unresolved state, and evidence playback.

**Gate**

- Legacy result shows `unverified` provenance.
- Two files with `SPEAKER_00` never merge.
- No empty placeholder tabs/cards; mobile/keyboard/evidence playback E2E passes.
- Evidence playback and sensitive reveal require current user/case/file authorization; cross-case and removed-file references return 403/404 without leaking existence.
- Sensitive transcript/claim content is absent from browser console, analytics, server diagnostics, and non-authorized list payloads.

**Commit boundary:** file-aware evidence UX only, after F1a runtime-profile PASS.

### E1A - Corpus, scorer, and baseline lock

**Implementation**

- Freeze the de-identified Vietnamese corpus manifest, annotation/adjudication state, blind-review protocol, scorer contract, seeds, metric definitions, and same-hardware baseline before tuning or promotion.
- Run the current fixed-form/legacy summary and diarization baseline through the exact direct/Celery, human/ASR, gold/predicted diarization, cold/warm/wake/cached, short/long, and file-count slices that candidates will use.
- Record sample-size/power analysis, missing-output policy, denominator checks, runtime/model/prompt/schema/config hashes, and immutable per-item results.

**Gate**

- Corpus/source/scorer hashes are frozen and train/tune/test leakage checks pass.
- Tampered scorer/corpus/source/runtime inputs fail replay.
- Baseline contains confidence intervals and absolute values for every promotion metric; unavailable/degraded output is scored as failure, not omitted.
- Independent methodology and privacy audit PASS before E1 candidate execution.

**Commit boundary:** E1A evaluator/corpus/scorer/baseline package only; candidate promotion results are excluded.

### E1 - Vietnamese quality-performance benchmark and promotion

**Dataset**

- Tier A synthetic/minimal pairs for exact values, negation, contradiction, prompt injection, overlap, and speaker ambiguity.
- Tier B scripted/de-identified realistic 5-30 minute calls.
- Tier C paired human/ASR transcript and gold/predicted diarization for 30-90 minute noisy audio.
- Freeze `tests/eval/summary_diarization_corpus_manifest.json` with corpus revision, de-identification/consent basis, file/source hashes, split, duration/noise/language/speaker/overlap slices, label schema, annotator IDs, adjudication state, and exclusion reason. No test case may enter prompts or tuning.

**Metrics**

- Summary: atomic precision/recall, weighted salience, exact-value owner binding, sentence support, released-claim coverage, human usefulness/consistency, duplication, reading time.
- Diarization primary: DER/JER with zero collar and overlap scored; diagnostic: 0.25 s collar with overlap excluded. Record both policies explicitly.
- Speaker-aware ASR: MeetEval-compatible `cpWER` and `tcpWER`; add `MIMO-WER` for multi-channel/meeting-compatible slices only. Never report an unspecified generic “speaker WER”.
- Operational: cold/warm/wake/cached p50/p95, TTFT, tokens/s, RTF, retries, lease wait, RAM/VRAM, cleanup and post-sleep evidence.

**Promotion gate**

- Severe hallucination, unsupported high-risk release, unknown refs, and wrong-speaker sensitive-value release: 0.
- Critical atomic precision >= 0.98; macro recall >= 0.95 and no group < 0.90.
- Exact released numeric/value accuracy >= 0.99.
- Factual sentence and released-claim narrative coverage >= 0.99.
- Human preference lower-bound 95% bootstrap CI > 0.50 versus baseline.
- E1A first locks the baseline artifact, scorer version/hash, seeds, repetition count, hardware/runtime/model manifests, and per-slice confidence intervals. Numeric quality/latency thresholds below are proposed until E1A PASS; zero-tolerance safety gates are locked now.
- Diarization candidate must beat absolute pilot floors established by E1A and must not regress the locked baseline in DER/JER/speaker-count/overlap/cpWER/tcpWER slices. A degraded or unavailable baseline cannot unlock promotion through non-regression alone.
- Deterministic one-call summary path p95 increase <= 5%; a two-stage narrative challenger may use <= 1.25x p95 only if weighted coverage improves >= 10 percentage points and all hard safety gates pass.
- Blind human review uses randomized model-hidden pairs, at least three independent reviewers per item or the sample size chosen by a documented power calculation, adjudication for material disagreement, and a stratified 10,000-resample bootstrap with a fixed seed recorded in the scorer protocol.

**Executable scorer contract**

- `tests/eval/summary-diarization-scoring-v1.json` pins metric definitions, denominators, critical-category weights, hallucination severity, DER collar/overlap rules, MeetEval metric variants, bootstrap seed/count, missing-output handling, and promotion logic.
- `scripts/evaluate_summary_diarization.py` writes immutable per-item JSONL plus aggregate JSON and hashes its own source imports, corpus manifest, prompts/schema, model/runtime config, hardware, and Git dirty inputs.
- Tampered fixtures must cause failure for omitted middle chunks, unsupported sentence, wrong-speaker value, invalid reference, duplicated theme, false one-speaker success, stale source/diarization revision, and scorer denominator drift.

**Commit boundary:** evaluator + immutable raw results + audit; no model promotion from a model card or smoke fixture.

## 5. Per-task audit protocol

Each task must publish:

1. Requirement-to-evidence map.
2. Exact file/hunk allowlist and interface impact.
3. Negative, targeted, sequential DB tests, build, and runtime commands/results.
4. Model/prompt/schema/config/dataset/hardware hashes when applicable.
5. Security/privacy/authorization and sensitive-log review.
6. Performance evidence for runtime behavior.
7. Residual uncertainty and rollback trigger.
8. Clean staged-snapshot validation.
9. Atomic commit hash and push confirmation.
10. Machine evidence uses `rtk-evidence-v1`: observed time, command, exit code, harness path/hash, exact source/test hashes, environment/model/runtime hashes, and named checks. Independent audit must inspect semantics; a self-asserted PASS boolean is never sufficient.

## 6. Immediate next package

Start with **P0A**, then one atomic **S1** package. Begin S2 only after the P0A and S1 independent audits both PASS:

- typed evidence-bound `summary_sentences` drafts;
- removal of canonical legacy coercion;
- strict nested grounding and raw unsupported-item rejection;
- negative fixtures for unknown fields, missing/unresolvable evidence, duplicate IDs, and canonical legacy strings.

S2 then adds semantic sentence attestation and released/critical claim narrative coverage in its own commit. Do not mix S1, S2, GPU, diarization, frontend alias, or legacy endpoint changes in one staged snapshot.

## 7. Completion boundary

This plan is complete only when the reader-facing bulletin, speaker state, evidence playback, runtime provenance, and quality-performance benchmark all pass on current canonical artifacts. Parser/unit tests or fluent output alone are insufficient.
