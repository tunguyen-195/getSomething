# Investigative Bulletin and Diarization Evidence Refresh

**Date:** 2026-08-09

**Canonical workspace:** `E:\research\STT`

**Goal:** P0-P8 remediation goal restored in this session
**Scope:** repository review, local runtime evidence, primary-source refresh, and implementation requirements; no production code change

## 1. Research question

How should SpeechToInfomation turn Vietnamese audio into a readable investigative bulletin that preserves critical and sensitive information, exposes useful but bounded insights, attributes every factual statement to source evidence and speaker state, and remains practical on the repository-local single-GPU runtime?

The answer must treat ASR, diarization, evidence extraction, reasoning, narrative synthesis, runtime provenance, and UI presentation as one traceable system. A fluent summary cannot compensate for missing speakers, wrong speaker ownership, lost exact values, or unsupported inferences.

## 2. Falsifiable requirements

| ID | Requirement | Failure condition |
|---|---|---|
| R1 | A reader can understand the purpose, sequence, outcome, participants, events, and critical exact values in the audio without reading the full transcript. | Human review or weighted salience coverage does not improve over the locked baseline. |
| R2 | Every factual bulletin sentence resolves to supported claim IDs and exact evidence spans. | A sentence has no claim/evidence map, references a dangling item, or adds semantics not attested by its claims. |
| R3 | Critical people, roles, time, place, money, phone/account/ID, quantity, vehicle, object, document, action, decision, and relation are retained when present. | Macro critical recall is below the locked threshold or any category regresses materially. |
| R4 | Unsupported high-risk interpretation never appears as fact. | Crime, deception, hidden relationship, surveillance, or risk leaks into factual overview/themes. |
| R5 | Diarization state is explicit and file-aware. | Failure, verified one-speaker audio, and degraded one-speaker fallback are indistinguishable. |
| R6 | Speaker ownership is not overstated. | A whole ASR segment is assigned to one speaker despite overlap/ambiguity, or an inferred identity replaces the anonymous cluster. |
| R7 | Offline runtime and model provenance are truthful. | UI shows a verified/active alias when only an artifact is present, the server is down, or the alias/path/hash binding is unverified. |
| R8 | Short evidence remains releasable when complete. | A valid short bulletin fails only because it is below a requested minimum length. |
| R9 | Performance is measured end to end. | Benchmark excludes model cleanup, GPU lease/quarantine, Celery, wake/sleep, or long-audio chunking. |
| R10 | Summary quality is not claimed from parser tests or model cards. | Production promotion occurs without a human-labelled Vietnamese corpus, baselines, ablations, and blind review. |

## 3. Current local evidence

### 3.1 Workspace and runtime

- Live branch/HEAD: `feature/architecture-refactor` at `a87b2319caefd64ff3e09f87f9345cc184d7b309`, upstream `0/0`.
- Pre-artifact worktree baseline: 32 tracked changes and 40,367 untracked files. Generated readiness artifacts are excluded separately by the v2 harness so rerunning it does not rewrite the baseline. Every future commit must use an exact allowlist and hunk review.
- Frontend `3000` and backend `8000` listener provenance resolves to E. PostgreSQL `5432` and Redis `6379` are reachable, and one logical Celery node answers `pong`; the readiness probe does not claim E process-origin provenance for PostgreSQL, Redis, or the logical Celery node. Llama-server `8088` is not live.
- No application process was found executing from `D:\Workspace\SpeechToInfomation`. The D repo remains a rollback snapshot and was not modified.

### 3.2 Summary and evidence contract

- `ContextAnalysisPayload` now has strict typed nested models and `extra="forbid"`; the current v2 schema walk finds 17 object definitions with `additionalProperties=false`.
- The top-level `summary` remains a compatibility free string and there is no typed `summary_sentences` draft contract. The live service only checks that the knowledge ledger contains at least one grounded item, then releases the entire string.
- An independent negative probe accepted a fabricated confession sentence against an unrelated meeting transcript because the ledger had some evidence.
- The canonical `InvestigationRun` validates reference existence and claim status, but currently accepts arbitrary sentence text with a valid claim reference and does not require every released claim to appear in narrative text.
- The raw parsed context can retain unsupported nested items even when the grounding builder silently omits them from `investigation_knowledge`.
- `summary_type` is typed only at the v2 FastAPI boundary; direct service, legacy API, worker, and multi-summary paths still accept arbitrary strings and can fall through to detailed mode.
- `min_length` is a hard release gate, which contradicts the required short-evidence behavior.

Read-only database aggregation found 494 task results with non-empty `summary`, but only 6 with a context key, 1 with grounded investigation knowledge, and 1 with `summary_runtime`. The database includes legacy/test artifacts, so these counts prove deployment-shape scarcity, not production-quality prevalence.

### 3.3 Diarization

- `OFFLINE_STRICT=true`; current configured transcription engine is `legacy`.
- `models/pyannote` contains zero files. Both Community-1 and 3.1 local snapshot resolvers return `None`.
- Migration evidence stored on E proves source and destination both contained only 9 Pyannote cache metadata files/25,179 bytes with matching SHA-256. The cache describes the older 2.1 pipeline and contains no model payload, so migration did not create the loss.
- Installed runtime is `pyannote.audio 3.1.1`, Torch/Torchaudio `2.1.1+cu121`, with no TorchCodec. Official Pyannote 4.0.0 metadata requires Torch/Torchaudio >=2.8.0 and TorchCodec >=0.6.0; current Community-1 compatibility is therefore false/unproven.
- Current manager/adapter still use the legacy `use_auth_token` keyword and consume the pipeline result as a direct `Annotation`; Community-1/4.x documents the `token` keyword and an output object containing regular and exclusive diarization.
- The latest task carrying persisted engine provenance used `legacy`, fell back because Cherry lacked `large-v2.pt`, and persisted `has_diarization=false`, `num_speakers=1`, `diarization_time=0`. The requested engine was not persisted at this boundary and is therefore not claimed.
- In the 100 most recent tasks, only one row carried the current diarization contract and none had `has_diarization=true`.
- Across all stored task results, 6 rows carry `has_diarization`, 2 say `true`, 4 say one speaker, and 2 say two speakers. These historical/test-shaped counts do not contradict the latest-100 slice and do not prove current quality.
- Legacy alignment assigns a whole ASR segment to the single speaker with the greatest overlap above `0.3`; overlap and ambiguity are discarded.
- `has_diarization` is defined as `num_speakers > 1`, so successful one-speaker diarization and diarization failure collapse into the same state.
- Unsupported audio conversion uses a sibling `.wav` path and later deletes it, which risks colliding with an existing repository/user file.
- The active frontend flattens segments across files and groups only by speaker/time, so identical `SPEAKER_00` labels can be merged across different files.

### 3.4 Test infrastructure observation

Targeted suites use a shared PostgreSQL database ending in `_test` and perform `drop_all/create_all` for every test. Concurrent pytest processes caused DDL deadlocks and schema races. The application database remained `speech_to_info`; the failing test processes targeted the derived `_test` database. All DB-backed validation must be serialized until P0 provides per-worker schemas/databases or a session-scoped isolation strategy.

Copied bytecode still embeds historical D source filenames in traceback metadata. Current source and process paths were verified in E; this is stale `.pyc` metadata, not evidence that tests executed from D.

### 3.5 Claim-to-evidence map

The durable readiness JSON records each local observation at the following JSON pointers. A claim is not considered current if its pointer is absent or its input hash differs from the manifest.

| Claim | Readiness JSON pointer or primary artifact |
|---|---|
| Canonical workspace, branch, HEAD, dirty counts | `/canonical_workspace`, `/git` |
| Exact hashes for every source/config/test/artifact input consumed by the readiness gate | `/source_input_sha256` |
| Nested schema strictness and missing typed summary sentences | `/summary_contract/all_objects_forbid_additional_properties`, `/summary_contract/summary_sentence_contract_present` |
| Raw free-text release, legacy coercion, hard minimum, untyped callers | `/summary_contract` |
| Missing full Pyannote tree, manifest, license/revision proof and offline-load evidence | `/model_state` |
| Winner-take-all alignment, collapsed one-speaker state, missing overlap/timestamp provenance, sibling-WAV collision | `/diarization_contract` |
| GPU quarantine, cleanup, sleep verifier, recovery CLI and startup gaps | `/gpu_contract` |
| Hardcoded/unverified frontend runtime state | `/frontend_contract` |
| Presence of chunk planner/exact detectors, plus missing integration evidence, append-only run and evaluation manifests | `/architecture_and_evaluation`, `/package_evidence/q1`, `/package_evidence/c1` |
| Live HTTP/Celery/process origin/GPU/Ollama/llama-server state | observed-live JSON `/runtime` only |
| Read-only database aggregates, latest persisted engine provenance and latest-100 slice | observed-live JSON `/database_read_only` only |

## 4. Research synthesis

The existing source-backed design remains correct: use an evidence-first `extract -> verify -> synthesize` pipeline, not a larger fixed form. The refresh adds one non-negotiable dependency: diarization uncertainty must flow into claim verification and narrative release.

Recommended system:

1. Seal audio, transcript, segments, word-timestamp provenance, speaker turns, hashes, model revisions, file identity, authorization scope, and pipeline version into an immutable source revision and append-only run.
2. Plan position-balanced, turn-aware chunks and record a source-coverage manifest so the beginning, middle, end, and every file in a case are accounted for.
3. Run deterministic high-recall exact-value detectors and open-schema LLM discovery over those chunks. Candidate omission is measured before verification; released-claim coverage alone cannot prove whole-audio coverage.
4. Resolve every candidate to exact evidence; preserve polarity, reported speech, contradiction, owner/unit binding, ASR uncertainty, actual-versus-estimated timestamps, and speaker-assignment state.
5. Release only supported facts into one canonical claim ledger. Speaker-dependent claims remain withheld or qualified when diarization is unresolved.
6. Build a concise Vietnamese overview plus adaptive themes from released claims. Each sentence needs claim refs, derived evidence refs, a content hash, and a replayable semantic-attestation artifact produced by the trusted T5 narrative authority.
7. Keep evidence-backed insight, hypothesis, and verification action as separate typed products. Only supported facts and attested insights can enter factual prose.
8. Persist one idempotent, versioned run for direct API, Celery, multi-file Summary, Analysis, and visualization projections; no caller may create a competing mutable truth store.
9. Render file-aware transcript/diarization/summary/analysis views with source playback, cross-case authorization checks, sensitive-data controls, and truthful runtime/degraded provenance.
10. Promote only on a quality-performance Pareto frontier measured on the same hardware, artifacts, corpus, scorer, and runtime state.

## 5. Primary-source refresh

Summary/attribution decisions continue to rely on the audited primary-source set in:

- `docs/research/evidence-preserving-adaptive-investigative-summary-2026-08-09.md`
- `docs/reviews/adaptive-summary-research-source-audit-2026-08-09.md`

Key supported mechanisms are atomic fact evaluation (FActScore), sentence/source attribution (AIS/ALCE/LongCite), extract-before-generate for long dialogue (QMSum/DYLE), effective-context stress testing (Lost in the Middle/RULER), and strict structure without factuality overclaim (JSON Schema/GCD/Ollama structured output).

Additional diarization sources checked on 2026-08-09:

- Bredin et al., “pyannote.audio: neural building blocks for speaker diarization,” arXiv:1911.01255. https://arxiv.org/abs/1911.01255
- Ryant et al., “The Second DIHARD Diarization Challenge: Dataset, task, and baselines,” arXiv:1906.07839. https://arxiv.org/abs/1906.07839
- von Neumann et al., “MeetEval: A Toolkit for Computation of Word Error Rates for Meeting Transcription Systems,” arXiv:2307.11394. https://arxiv.org/abs/2307.11394
- Official `pyannote.audio` repository and Community-1 instructions. https://github.com/pyannote/pyannote-audio
- Official Hugging Face model metadata for `pyannote/speaker-diarization-community-1`, revision `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee`, gated access, CC-BY-4.0, and a tree containing `config.yaml`, embedding, PLDA, and segmentation artifacts. https://huggingface.co/api/models/pyannote/speaker-diarization-community-1
- Official PyPI metadata for `pyannote.audio==4.0.0`, including Torch/Torchaudio/TorchCodec requirements. https://pypi.org/pypi/pyannote.audio/4.0.0/json
- Official Pyannote 4.0.0 release notes for Community-1 output, offline local loading, TorchCodec I/O, and breaking API changes. https://api.github.com/repos/pyannote/pyannote-audio/releases/tags/4.0.0

Live source verification in this session returned HTTP 200 for all three arXiv records and reproduced their exact titles. The Hugging Face API returned `sha=3533c8cf8e369892e6b79ff1bf80f7b0286a54ee`, `gated=auto`, `license=cc-by-4.0`, plus `config.yaml`, `embedding/pytorch_model.bin`, `plda/plda.npz`, `plda/xvec_transform.npz`, and `segmentation/pytorch_model.bin`. URL, observed time, status, parsed metadata, response byte count, and UTF-8 content SHA-256 are stored in `docs/reviews/artifacts/2026-08-09-diarization-primary-source-verification.json`. This metadata is a packaging requirement, not evidence that the absent local snapshot can load or performs well on Vietnamese audio.

These sources support diarization capability, artifact requirements, DER/JER-style evaluation, and speaker-aware transcription metrics. They do not prove Community-1 is best for Vietnamese/noisy investigative audio; local comparison remains mandatory.

The migration/config/runtime compatibility chain is independently replayable through `scripts/audit_pyannote_migration_config.py`; its report is `docs/reviews/2026-08-09-pyannote-migration-config-audit.md` and its current machine artifact is `docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json`.

## 6. Locked evaluation dimensions

### Summary and intelligence

- Schema validity, evidence resolution, unknown refs, severe hallucination, high-risk leakage.
- Atomic-claim precision/recall/F1 and weighted salience coverage.
- Critical exact-value accuracy with owner/role/unit binding.
- Factual sentence-to-claim semantic support and released-claim narrative coverage.
- Contradiction/negation preservation, primary-theme overlap, duplication, reading time, and human usefulness.

### Diarization and speaker-aware ASR

- DER, JER, speaker-count exact accuracy, overlap recall, unresolved mapping rate.
- Speaker-attributed/cpWER metrics through a pinned MeetEval-compatible protocol.
- File-bound turn accuracy, anonymous cluster stability, and human speaker-map auditability.
- RTF, p50/p95 latency, RAM/VRAM, model load/unload, and GPU handoff evidence.

### Cross-stage

- Speaker-dependent claim precision and withholding accuracy under degraded diarization.
- Human transcript versus ASR transcript and gold diarization versus predicted diarization ablations.
- Direct API versus Celery parity; cold, warm, sleeping-wake, and cached runs.

## 7. Residual uncertainty

1. No approved human-labelled Vietnamese investigative corpus exists yet.
2. Most automatic factuality and diarization research is not calibrated on Vietnamese noisy ASR.
3. Pyannote Community-1 is gated; authorized acceptance, license attribution, immutable download evidence, and offline packaging are still required.
4. Exact transcript evidence does not establish audio truth when ASR or speaker assignment is wrong.
5. Multi-stage quality gains can increase latency; thresholds must be locked after a valid end-to-end baseline on the RTX 4070 SUPER host.

## 8. Rerunnable evidence

```powershell
Set-Location E:\research\STT

# Refresh one sealed official-metadata capture; this does not download gated models.
.\venv\Scripts\python.exe -B scripts\capture_diarization_primary_sources.py `
  --output docs\reviews\artifacts\2026-08-09-diarization-primary-source-verification.json

# Replay migration/config evidence against that exact capture without network access.
.\venv\Scripts\python.exe -B scripts\audit_pyannote_migration_config.py `
  --no-network `
  --output docs\reviews\artifacts\2026-08-09-pyannote-migration-config-audit.json

.\venv\Scripts\python.exe -B scripts\audit_summary_diarization_readiness.py `
  --database --runtime `
  --output output\audits\summary-diarization-readiness.json

# Deterministic contract/artifact snapshot: no live ports, processes, DB, or queue.
.\venv\Scripts\python.exe -B scripts\audit_summary_diarization_readiness.py `
  --generated-at <ISO-8601-observed-at> `
  --output docs\reviews\artifacts\2026-08-09-summary-diarization-readiness-static.json

# Immutable observed-live snapshot plus a manifest that also binds the static snapshot.
.\venv\Scripts\python.exe -B scripts\audit_summary_diarization_readiness.py `
  --database --runtime `
  --generated-at <ISO-8601-observed-at> `
  --output docs\reviews\artifacts\2026-08-09-summary-diarization-readiness.json `
  --manifest docs\reviews\artifacts\2026-08-09-summary-diarization-readiness.sha256 `
  --manifest-extra docs\reviews\artifacts\2026-08-09-summary-diarization-readiness-static.json

# DB-backed pytest suites must run sequentially until P0 isolation is fixed.
.\venv\Scripts\python.exe -m pytest -q tests\test_context_analysis.py
.\venv\Scripts\python.exe -m pytest -q tests\test_transcription_engines.py
```

Durable documentation-gate artifacts:

- `docs/reviews/artifacts/2026-08-09-diarization-primary-source-verification.json`
- `docs/reviews/artifacts/2026-08-09-pyannote-migration-config-audit.json`
- `docs/reviews/artifacts/2026-08-09-summary-diarization-readiness-static.json` for deterministic source/schema/artifact checks
- `docs/reviews/artifacts/2026-08-09-summary-diarization-readiness.json`
- `docs/reviews/artifacts/2026-08-09-summary-diarization-readiness.sha256`
- `output/audits/summary-diarization-readiness.json` as the rerunnable live snapshot

The static JSON is deterministic for a fixed source tree and supplied timestamp. The observed-live JSON freezes one point-in-time runtime/DB observation and is not claimed deterministic across external state changes. Both carry consumed input hashes; the separate manifest binds both JSON files and records absent expected inputs as `MISSING`. Hashes are not copied into this research file because changing the research input would invalidate that same manifest.

**Boundary:** this refresh establishes a source-backed plan and current-state evidence. It does not claim the current summary or diarization quality is acceptable.
