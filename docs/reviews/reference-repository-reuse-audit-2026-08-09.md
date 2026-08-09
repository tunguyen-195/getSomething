# Reference Repository Reuse Audit

Date: 2026-08-09
Target: `D:\Workspace\SpeechToInfomation` at `5f7f2ac92598`
References: `SpeechToInfomation-pr` at `9a2e5387f786`; `cherry_core` at `1dbb880c0ca0`

## Findings

### Critical 1 - Do not clone or merge either repository wholesale

`SpeechToInfomation-pr` uses the same remote as the target but has a different
root commit. Git reports no merge base. The two checkouts share 192 hashed paths,
only 67 are exact and 125 differ. A mechanical merge would mix older security,
DB, prompt and runtime designs into the hardened branch.

`cherry_core` is a separate repository and its current checkout is heavily dirty:
242 tracked files plus 27,949 non-ignored untracked paths. Much of the strongest
PhoGuard/SAGE work is research state rather than a clean release boundary.

Decision: port bounded techniques and artifact facts with source commit/file
provenance. Never replace `src`, `frontend`, `models` or database migrations as a
directory.

### Critical 2 - No checkout currently proves a reproducible air-gapped release

- All three repository roots lack `LICENSE`, `NOTICE` or `COPYING`.
- The target has a strict model-manifest implementation but only an example
  manifest. `scripts/model_store.py preflight` returns
  `FAIL: no deployed model manifests matched the selection`.
- The target physically contains about 14.85 GiB logical model data, the Lite
  checkout about 3.76 GiB and Cherry about 82.25 GiB. Physical presence does not
  prove revision/license/dependency closure, and cache layouts can duplicate data.
- The static model-tree inventory finds only five license/notice filenames in
  the target and none in the Lite/Cherry model trees; this is not license closure
  for the listed model families.
- `SpeechToInfomation-pr/scripts/precache_lite_models.py:53-74` still downloads
  from Hugging Face during setup; its Docker model-sync path invokes that script.
- `SpeechToInfomation-pr/docs/MODEL_SETUP.md` explicitly describes manual copying,
  missing full-offline artifacts and a summary path that needs an LLM provider.

Decision: independently reverify artifact metadata hints, not the deployment
policy. Build a signed internal
release bundle with model/runtime/tokenizer/config hashes, licenses, wheelhouse,
native binaries, prompt/schema hashes and a network-denial test.

### Critical 3 - Legacy “forensic” prompts are unsafe as factual analysis

The target's imported Cherry prompt at
`src/cherry_core/prompts/templates/forensic_report.j2`:

- hard-codes slang-to-drug mappings as truth;
- requires a danger level and crime indicators;
- asks the model to infer deception, hidden meaning, relationships, intent and
  surveillance targets;
- forces identity/finance/time sections even when the conversation lacks them.

`src/cherry_core/services/analysis_service.py` returns one cleaned free-form
response without evidence validation or typed epistemic separation. The PR has
the same fixed-form failure in
`src/services/summarization/summary_service_v2.py:145-177` and a monolithic
analysis prompt in `src/services/summarization/models/llm_manager.py:331-392`.

Decision: reject these prompts for production. Keep selected slang/forced-field
examples only as adversarial evaluation fixtures. Use open-schema discovery,
source verification, bounded reasoning and evidence-preserving synthesis.

### Critical 4 - PR evidence lifecycle contains authorization and preservation regressions

- `SpeechToInfomation-pr/src/core/auth.py:330-348` can authorize a task through a
  linked audio row after the task's direct case authorization fails.
- `SpeechToInfomation-pr/src/api/endpoints/audio.py:705-755` unlinks the source
  file and then labels the row “archived”.
- `SpeechToInfomation-pr/src/database/init_db.py:31-34` uses
  `Base.metadata.create_all` despite an Alembic history.
- `SpeechToInfomation-pr/src/services/audio_service.py:46-91` stores original
  filename metadata but does not establish a source-audio hash chain.
- `SpeechToInfomation-pr/src/services/audit_service.py:29-41` can silently skip an
  audit event when its activity type is unavailable.

Decision: reject these implementations. The target's source SHA-256 and direct
task authorization are stronger; extend them with legal hold, append-only audit,
UTC revisions and Alembic-only production migration.

### Critical 5 - The new investigative contracts are not the production pipeline

The target contains strong T1-T4 code for immutable source revisions, evidence
selectors, adaptive discovery and verification. Search outside tests and the
investigation module finds no production API/worker/summary service invoking
`build_discovery_batch` or `build_verification_batch`.

T4 also remains blocked by independent audit: legacy release context can bypass
T4, contradictions are not bound into T5 authority, reported speech is currently
factual-release eligible, actor/object reversal can pass alignment and replay
does not independently measure its source-module hashes.

Decision: do not present the contracts as product-ready and do not wire T5/UI
around the current T4 wrapper. Fix the single release adapter first.

### Critical 6 - Cherry's web runner can deadlock and its tests mask the real implementation

`cherry_core/application/services/web_job_manager.py:93-103` holds a
non-reentrant `threading.Lock` while calling `_set_status()`, which attempts to
acquire the same lock again at `:230-240`. Enqueuing a second stage such as
diarization, correction or intelligence summary can therefore block the job
runner indefinitely. `cherry_core/tests/test_webapp_api.py:118` substitutes a
`FakeJobManager`, so the API test path does not exercise this failure.

Decision: reuse only the serialized single-GPU execution requirement. Reject the
lock/job implementation; build a persistent worker with atomic DB transitions,
idempotency, cancellation, watchdog recovery and a real concurrency/deadlock test.

### High 1 - ASR and speaker uncertainty are currently misrepresented

- `src/services/transcription/transcribe_service_v2.py:187` labels
  `avg_logprob` as confidence.
- `src/services/transcription/transcribe_service_v2.py:271` emits overall
  confidence `1.0`.
- `src/cherry_core/adapters/asr/phowhisper_adapter.py:238` and `:266-279`
  construct estimated uniform word timestamps.
- `src/services/transcription/cherry_transcription_service.py:107-134` chooses a
  single speaker after an overlap threshold and discards ambiguity/overlap.

Decision: introduce an uncertainty artifact before Summary/Analysis. Adapt the
Cherry PhoGuard/SAGE selective-review technique, but never copy its thresholds or
call a rule score a calibrated probability.

### High 2 - PR UI/data patterns explain browser jank and must be selectively ported

The PR's metadata-only list is enabled only for Lite/single-job mode at
`src/api/endpoints/audio.py:48-66`; full mode can return transcript, segments,
summary and graph data in list responses. Runtime profile is polled every five
seconds by `frontend/src/App.tsx:275`.

Decision: adopt metadata-only paginated lists and separate detail endpoints for
all profiles. Cache runtime health or push changes; never perform heavy health
work on a five-second poll. Keep one Analysis workspace and one run.

### High 3 - Cherry PhoGuard/SAGE is useful methodology, not a drop-in production gate

Strong reusable elements include:

- explicit `selected_text`, `review_text`, `abstain_flag`, reason codes and risk
  signal in `research/phoguard_asr/decision_schema.py:10-31`;
- transparent non-probabilistic risk ranking and abstention in
  `research/phoguard_asr/gate.py:28-115`;
- environment and dataset-manifest capture in
  `research/phoguard_asr/artifacts.py:56-121`;
- evidence modes separating proxy, decoded and manual-final data in
  `research/sage_asr/evidence.py:7-104`;
- calibrated logistic scoring and source-balanced training in
  `research/sage_asr/calibrator.py:10-103`;
- conformal false-accept risk control in
  `research/sage_asr/conformal.py:7-80`.

However `application/services/sage_asr_service.py:11-48` embeds a calibrator and
threshold from the research checkout. Those values are not established for this
target's Vietnamese/noisy investigative distribution.

The evidence is also exploratory rather than a production baseline. SAGE's
promotion tool explicitly records `human_rated=False` at
`tools/sage_promote_auto_labels.py:91`; its 1,020 labelled rows are policy-derived
proxy labels. The source-stratified CRC artifact reduces aggregate false-accept
risk but still reports 13.33% on `internal-hard`, rejects all B20 examples and
keeps only 2.5% MUSAN coverage at
`annotations/sage_stratified_crc_evidence_v1.json:249-283`. PhoGuard's CUDA
ablation reports no WER improvement and roughly doubles RTF at
`docs/paper_pack/PHOGUARD_ASR_CUDA_INTERNAL_AB_RESULTS_2026-05-03.md:49-61`.
P6/P7 are negative-result experiments; P8 is compatibility/metadata-only; P10
and P11 explicitly remain retrospective/exploratory.

Decision: ADAPT the decision schema, features, evidence discipline and calibration
protocol. Retrain/recalibrate on a frozen target corpus and preserve coverage.

### High 4 - Model stores are research caches, not organized release inventories

Cherry contains multiple copies/formats of Whisper/PhoWhisper weights, including
PyTorch, safetensors, TensorFlow and Flax representations. The target also mixes
Hugging Face cache layouts, standalone CTranslate2 files, Ollama/GGUF and legacy
models. None is selected by a complete production manifest.

Cherry's setup downloads an unpinned Hugging Face revision at
`scripts/setup_models.py:55`, fetches floating `master.zip` for Silero at `:28`,
and its inventory primarily checks `path.exists()` at
`application/services/model_inventory_service.py:142`. A model file being present
does not establish its source revision, license, runtime compatibility or loadability.

Decision: deduplicate release artifacts by runtime profile. Keep original upstream
hash/provenance plus only the converted format required by the selected runtime;
archive research alternatives outside the production bundle.

### High 5 - Cherry correction and timeline transforms break evidence replay

Cherry's correction port accepts and returns only `str` at
`core/ports/correction_port.py:3`. ProtonX truncates to 100 words and concatenates
the remainder at `infrastructure/adapters/correction/protonx_adapter.py:57-86`,
while the pipeline overwrites `corrected.txt` and later prefers it for Summary at
`application/services/stt_web_pipeline.py:211` and `:528`. Speaker refinement
mutates `speaker_id` at `infrastructure/adapters/correction/contextual_refiner.py:82`.
Silero VAD can emit a time map, but the pipeline does not pass one at
`application/services/stt_web_pipeline.py:272`, so downstream timestamps can refer
to a compressed speech-only timeline instead of the original audio.

Decision: correction, inferred speaker roles and VAD-compacted audio must create
new immutable revisions with input/output hashes, span/time mappings, model/config
identity and explicit epistemic class. Raw transcript and original-audio
coordinates remain the only evidence authority.

## Repository decision matrix

### `SpeechToInfomation-pr`

| ID | Decision | Reusable item | Evidence | Target action |
|---|---|---|---|---|
| `PR-MODEL-ARTIFACT-FACTS` | ADAPT / PENDING_LICENSE | Pinned faster-whisper and pyannote artifact facts | `docs/model_artifacts.required.json:35-205` | Reverify and convert to strict target manifests; add runtime/tokenizer/license/dependency closure. |
| `PR-EVIDENCE-REF-CONTRACT` | ADAPT / PENDING_LICENSE | Evidence refs with source hash/span/time/speaker | `src/services/analysis_intelligence/schemas.py:72-91`, `:121-158` | Reimplement with audio hash, source revision, modality, polarity and semantic roles after ownership/license approval. |
| `PR-HUMAN-REVIEW` | ADAPT / PENDING_LICENSE | Review states and correction API | `src/api/endpoints/audio_v2.py:636-730` | Replace mutable patch with immutable signed human attestation. |
| `PR-ROW-LOCK-REVISION` | ADAPT / PENDING_LICENSE | Row lock and expected revision | `src/services/analysis_intelligence/storage.py:45-68`, `:85-243` | Reimplement the concurrency pattern in normalized run/review tables. |
| `PR-METADATA-DETAIL-API` | ADAPT / PENDING_LICENSE | Metadata list/detail split and no-store helpers | `src/api/endpoints/audio.py:48-66`; `src/api/endpoints/audio_v2.py:316-471` | Enable for every profile with ETag and pagination. |
| `PR-GPU-LEASE` | ADAPT / PENDING_LICENSE | Single-GPU DB lease | `src/services/lite_runtime.py:73-218` | Use a persistent worker/process, watchdog, cancellation and progress; no daemon job thread. |
| `PR-RUNTIME-PROFILE` | ADAPT / PENDING_LICENSE | Runtime profile UI | `src/api/endpoints/system.py:16-55` | Back with cached manifest/preflight state; replace five-second heavy polling. |
| `PR-REJECT-AUTH-FALLBACK` | REJECT | Task authorization fallback | `src/core/auth.py:330-348` | Preserve direct case authorization and add DB consistency constraints. |
| `PR-REJECT-PHYSICAL-ARCHIVE` | REJECT | Physical delete labelled archive | `src/api/endpoints/audio.py:705-755` | Legal hold + soft archive; controlled secure purge only by policy. |
| `PR-REJECT-CREATE-ALL` | REJECT | `create_all` production init | `src/database/init_db.py:31-34` | Alembic upgrade/head check only. |
| `PR-REJECT-JSON-MONOLITH` | REJECT | JSON-monolith analysis graph | `src/services/analysis_intelligence/storage.py:17-42` | Normalize runs/items/evidence/review events; Task stores pointers/status. |
| `PR-REJECT-FIXED-PROMPT` | REJECT | Fixed police summary and monolithic crime/deception prompt | `summary_service_v2.py:145-177`; `llm_manager.py:331-392` | Replace with the new prompt/technique specification. |
| `PR-REJECT-NETWORK-DEFAULT` | REJECT | Internet-dependent default/provider drift | `docker-compose.yml:83-90`; `src/core/config.py:109-123` | Offline strict allowlist, network denial and fail-closed startup. |

### `cherry_core`

| ID | Decision | Reusable item | Evidence | Target action |
|---|---|---|---|---|
| `CH-ARTIFACT-DISCIPLINE` | ADAPT / PENDING_LICENSE | Research artifact/environment/evidence discipline | `research/phoguard_asr/artifacts.py`; `research/sage_asr/evidence.py` | Recreate the methodology in target-owned code; do not copy dirty/unlicensed implementation. |
| `CH-SELECTIVE-ASR` | ADAPT / PENDING_LICENSE | Selective ASR risk, abstention and conformal control | `research/phoguard_asr/gate.py`; `research/sage_asr/calibrator.py`; `research/sage_asr/conformal.py` | Implement provider-neutral uncertainty service; train target calibrator and report coverage. |
| `CH-PORTS-ADAPTERS` | ADAPT / PENDING_LICENSE | Ports/adapters separation | `core/ports/*`; `infrastructure/adapters/*` | Recreate bounded target ports and remove direct runtime imports from business services. |
| `CH-GPU-QUEUE` | ADAPT / PENDING_LICENSE | Serialized single-GPU execution | `application/services/web_job_manager.py:34` | Keep one-GPU scheduling semantics, but replace the deadlocking in-process lock/runner. |
| `CH-STAGE-ARTIFACTS` | ADAPT / PENDING_LICENSE | Raw/stage artifact separation | `application/services/stt_web_pipeline.py:168-362` | Make each stage immutable and content-addressed with original-audio coordinate mappings. |
| `CH-RESEARCH-CHALLENGERS` | RESEARCH_CHALLENGER / PENDING_LICENSE | Whisper head/intervention, AudioSAE, Stable-TS, PhoWhisper.cpp experiments | `research/phoguard_asr/*`; `scripts/run_whisper_*`; `docs/paper_pack/*` | Retain protocols as benchmark arms only; require independent reproducibility and quality ablation. |
| `CH-MANUAL-AUDIT` | ADAPT / PENDING_LICENSE | Manual audit, evidence registry and claim ladder | `docs/paper_pack/EVIDENCE_REGISTRY.md`; manual-audit protocols and scripts | Recreate methodology for Tier B/C labelling and source-backed claims. |
| `CH-REJECT-SAGE-THRESHOLD` | REJECT | Embedded SAGE calibrator/threshold | `application/services/sage_asr_service.py:11-48` | Never port numeric policy without target calibration and signed artifact. |
| `CH-REJECT-JOB-MANAGER` | REJECT | Deadlocking web job manager | `application/services/web_job_manager.py:93-103`, `:230-240` | Do not port; test the real worker instead of `FakeJobManager`. |
| `CH-REJECT-MUTATION` | REJECT | Destructive correction/speaker mutation | `application/services/stt_web_pipeline.py:211`, `:420`, `:528` | Preserve raw data and create mapped correction/role hypothesis revisions. |
| `CH-REJECT-VLLM` | REJECT | Current vLLM adapter | `infrastructure/adapters/llm/vllm_adapter.py:19-79` | Benchmark a real HF/AWQ/GPTQ Linux sidecar only if concurrency requires it. |
| `CH-REJECT-FIXED-PROMPT` | REJECT | Fixed scenario/slang forensic prompt | `prompts/`, `application/services/analysis_service.py` | Treat dictionaries as contextual candidates/adversarial tests, never fact/risk rules. |
| `CH-REJECT-MODEL-INVENTORY` | REJECT | Wholesale model directory and path-only inventory | `models/` logical inventory ~82.25 GiB; `application/services/model_inventory_service.py:142` | Select exact artifacts by winning runtime profile; manifest and deduplicate. |
| `CH-REJECT-DIRTY-RELEASE` | REJECT | Unlicensed dirty working tree as release source | root has no license; current dirty/untracked state | Port only from content-addressed source evidence after owner approval. |

## Exact source identity

`docs/research/reference-repo-audit/source-evidence-spec.json` maps every matrix ID
to exact source files. The audit harness writes byte size, SHA-256, worktree Git
blob, HEAD blob, tracked state and source commit into
`docs/research/reference-repo-audit/evidence.json`. This is essential for Cherry:
many PhoGuard/SAGE/P6-P11 sources are modified or untracked, so commit
`1dbb880c0ca0` alone does not identify the reviewed content.

These hashes make the review replayable; they do not resolve ownership or license.
Every reusable row remains `PENDING_LICENSE` until R0 records authorization.

## What should be implemented first

1. Fix all T4 release-boundary blockers in the already-active target work before
   exposing T5, Summary, Analysis or UI reasoning.
2. Convert the PR's verified faster-whisper medium/small and pyannote artifact
   facts into the target manifest schema, add licenses/runtime binaries and make
   target preflight pass without Internet.
3. Add `UncertainTranscriptSegment`; correct confidence/timestamp/speaker semantics
   and preserve original-audio coordinates through VAD/alignment.
4. Add immutable correction revisions with diff/span mapping before any corrected
   text can feed discovery, Summary or Analysis.
5. Adapt PhoGuard/SAGE selective review behind a target-calibrated, versioned
   policy and audio-review UI.
6. Implement discovery critic, bounded reasoner and Summary/Analysis projections
   from one run.
7. Add normalized append-only DB/review/audit surfaces, a deadlock-safe persistent
   job runner and one Analysis workspace.
8. Select model/runtime/quantization only after the locked Vietnamese benchmark.

Detailed tasks, dependencies and gates are in
`docs/plans/2026-08-09-reference-reuse-offline-cand-plan.md`.

## Verification evidence

- Static audit harness:
  `scripts/audit_reference_repos.py` ->
  `docs/research/reference-repo-audit/evidence.json`.
- Source identity input:
  `docs/research/reference-repo-audit/source-evidence-spec.json`.
- Locked development hardware:
  `docs/research/reference-repo-audit/hardware-profile.json`.
- Harness unit tests: 6 passed, including modified/untracked source identity.
- PR readiness/runtime slice reported by independent audit: 49 passed.
- Wider PR slice: 92 passed, 30 failed because the checkout environment uses
  `httpx 0.28.1` while its requirements pin `0.25.1`; this is not product proof.
- Target model-runtime tests previously pass, but live production preflight fails
  closed because no deployable manifest exists.
- Runtime observed at 2026-08-09T02:52Z: backend health 200 on `/api/v1/health`,
  frontend 200 on port 3000, PostgreSQL/Redis/Ollama listening locally.

## Public standards and legal boundary

- NIST SP 800-86 and RFC 3227 support evidence preservation, hashes, UTC records
  and continuous custody documentation.
- Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 was issued 2025-06-26 and is effective
  2026-01-01 according to the official Government document page.
- The system must implement purpose limitation, need-to-know access, retention,
  legal hold, controlled deletion and auditability. Exact applicability and any
  lawful public-security exceptions require authorized legal review.
- Public sources do not establish internal/classified CAND operational rules.

## Residual uncertainty

- The Cherry review covers implemented and current research artifacts, but its
  dirty/untracked state is not a signed release snapshot.
- No root repository license is present; ownership authorization remains a gate.
- No human-labelled Vietnamese investigative corpus currently proves model or
  prompt quality.
- Cherry's strongest PhoGuard/SAGE/P6-P11 artifacts are dirty research state;
  proxy labels, viewed holdouts and negative results cannot authorize production
  thresholds or accuracy claims.
- Model logical byte totals can double-count cache representations and are not a
  storage-deduplication benchmark.
