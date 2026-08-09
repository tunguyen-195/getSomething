# New Workspace Handoff - SpeechToInfomation

**Ngay handoff:** 2026-08-09

**Workspace canonical:** `E:\research\STT`

**Rollback snapshot:** `D:\Workspace\SpeechToInfomation`

**Migration audit:** `docs/reviews/2026-08-09-workspace-migration-audit.md`

**Evidence:** `E:\research\_STT_migration_evidence\2026-08-09-d-to-e`

## Bat Dau Phien Moi

```powershell
Set-Location E:\research\STT

Get-Content docs\handoffs\2026-08-09-new-workspace-handoff.md
Get-Content docs\reviews\2026-08-09-workspace-migration-audit.md
Get-Content E:\research\_STT_migration_evidence\2026-08-09-d-to-e\result.json
Get-Content E:\research\_STT_migration_evidence\2026-08-09-d-to-e\cutover.json

git status --short --branch
git log --oneline --decorate -6
```

Khong tiep tuc lam viec tai D. Khong xoa repo D cho den khi nguoi dung xac nhan
phien moi tai E va cac E2E quan trong deu on dinh.

File `context_handoff.md` o root la handoff cu ngay 2026-01-18 va da stale. Dung
file nay trong `docs/handoffs` lam source of truth cho phien moi.

## Active Goal

**Goal ID:** `019fe1f4-71d2-7fd3-82c0-ef9f59a16d4f`

**Objective:** Implement the full SpeechToInfomation remediation plan P0-P8,
continuously review and research design decisions, and deliver a secure,
evidence-backed audio intelligence system that extracts traceable knowledge for
criminal investigations without presenting unsupported LLM inferences as facts.

Goal tong van **active**, khong duoc mark complete. Neu phien moi khong ke thua
goal state, tao lai goal voi nguyen objective tren; khong thu hep thanh viec sua
mot endpoint hoac mot model rieng le.

## Canonical Git State Snapshot

Bang sau la snapshot truoc commit artifact handoff. Phien moi phai dung
`git status`/`git log` de lay trang thai live sau push.

| Truong | Gia tri |
|---|---|
| Branch | `feature/architecture-refactor` |
| Base implementation HEAD | `674ca91d40d3b64d929ade41653fa45f5cc7aef0` |
| Upstream | `origin/feature/architecture-refactor` |
| Ahead / behind | `1 / 0` |
| Tracked changes | 32 |
| Untracked files | 40,370 voi `--untracked-files=all` |

Worktree rat dirty va chua phai release candidate. Khong stage/commit toan bo.
Moi commit phai dung allowlist file cua task, audit diff va chay gate lien quan
truoc khi push. Commit ahead hien tai la:

```text
674ca91d research(reuse): lock reference port register
```

## Migration And Runtime Status

Migration D -> E da PASS sau khi repair tinh portable cua venv:

- 198,979/198,979 file va 27,130,995,607 byte doi chieu.
- 108,493 material file SHA-256 match; 0 inventory mismatch, 0 hash mismatch.
- Git fsck/LFS pass; DB backup va `pg_restore --list` pass.
- 94 stale venv launcher/script da duoc repair; hien con 0 duong dan D trong
  `venv\Scripts`.
- Ba E2E helper da dung audio path tuong doi theo repo.
- Khong co app process chay tu D.

Service dang chay tu E tai thoi diem handoff:

| Service | Dia chi/trang thai |
|---|---|
| Frontend | `http://127.0.0.1:3000`, HTTP 200 |
| Backend | port 8000; `GET /api/v1/health` HTTP 200 |
| OpenAPI | live khong auth tra 401 theo dung security contract |
| Celery | 1 logical worker, `pong`, 0 active task |
| PostgreSQL | port 5432, app DB `SELECT 1` PASS |
| Redis | port 6379 |

Logs cutover: `logs/migration-cutover`. Neu service da dung o phien moi, khoi dong
lai bang entrypoint cua repo E; khong chay batch/script tu D.

## Da Hoan Thanh Hoac Da Co Gate

1. Case/file timestamp da co implementation review; timestamp chi la metadata UI,
   khong dua vao prompt/model reasoning.
2. Analysis blank-page va Analysis/Visualization convergence da co audit/artifact;
   visualization duoc dinh huong la projection tu grounded knowledge, khong phai
   mot LLM authority thu hai.
3. Evidence-first investigation domain, canonicalization, contradiction,
   verification va release adapter da co code/test artifacts trong dirty tree.
4. Legacy forensic provider da bi disable fail-closed; khong fallback sang
   `forensic_report.j2` hoac generic free-text summary.
5. Investigation summary fail-closed neu context loi hoac khong co grounded
   evidence; single-pass khong fallback sang secondary unconstrained LLM call.
6. OpenAI-compatible local client da co loopback/no-proxy/no-redirect guard,
   model alias/path/hash binding va strict SSE/output checks.
7. Core GPU quarantine da co persistent marker, sleep verification va negative
   test; multi-summary reject `available=false`.
8. Qwen3-8B Q4_K_M va llama.cpp Windows CUDA da nam trong repo E va artifact
   verification PASS.
9. Validation gan nhat: 45 runtime/model tests pass, 48
   context/investigation/GPU tests pass, frontend build pass.

Day la gate muc tieu, khong phai full P0-P8 completion va khong phai bang chung
chat luong nghiep vu tren corpus tieng Viet that.

## Task Dang Lam Va Phat Hien Chua Dong

### 1. LLM Investigation Contract - Uu Tien Cao Nhat

Top-level structured schema da `extra="forbid"`, nhung nested payload van dung
`dict[str, Any]` o nhieu truong. Can:

1. Doi `key_points`, entities, facts, events, relationships va hypotheses thanh
   typed nested models.
2. Bat buoc evidence quote/reference va `additionalProperties=false` o moi cap.
3. Khong chi kiem tra ledger co it nhat mot evidence span; tung cau/claim duoc
   release trong overview/summary phai lien ket den claim/evidence cu the.
4. Them `summary_type` enum/allowlist o API va service; input la phai 422, khong
   ngam roi vao detailed.
5. Doi `min_length` thanh advisory cho transcript it evidence; chi hard-enforce
   `max_length` va factual/evidence bounds.
6. Them negative tests cho unknown nested fields, missing evidence, unsupported
   summary sentence, invalid summary type va short-evidence transcript.

Files chinh:

- `src/services/summarization/models/context_analysis.py`
- `src/services/investigation/contracts.py`
- `src/services/summarization/summary_service_v2.py`
- `src/api/endpoints/audio_v2.py`
- `tests/test_context_analysis.py`
- `tests/test_local_llm_optimization.py`

### 2. Synchronous Summary Va GPU Handoff

Async Celery worker da reject `available=false`, nhung synchronous path van co
the ghi `summarized` sai. Can:

1. Sua `audio_v2.py` va legacy `audio.py`: khong persist/return `summarized` khi
   `result.available` false.
2. Dua GPU handoff/quarantine xuong shared runtime context hoac service layer de
   bao ve moi direct caller, khong chi Celery task.
3. Khong nuot unload/sleep failure trong cleanup.
4. Fail-closed chieu audio -> LLM khi transcription cleanup/release khong an toan.
5. Them recovery CLI + runbook: chi clear quarantine khi live
   `/props.is_sleeping=true`.
6. Them subprocess/cross-process test va live llama-server sleep/wake/VRAM gate.

Files chinh:

- `src/api/endpoints/audio_v2.py`
- `src/api/endpoints/audio.py`
- `src/services/summarization/summary_service_v2.py`
- `src/services/transcription/transcribe_service_v2.py`
- `src/services/model_runtime/gpu_lease.py`
- `src/worker/tasks/summarize_task.py`

### 3. Frontend Runtime Profile Va Model Provenance

Frontend van hardcode `llama3.2:3b` va `gemma2:9b` trong dialog/multi/case summary.
Can:

1. API expose runtime profile/model alias da verify tu manifest.
2. UI chi hien alias kha dung cua active profile; `auto` map den canonical alias,
   khong map thanh model cu ngoai repo.
3. Multi-summary va case-summary dung cung profile thay vi hardcode Gemma.
4. UI hien model/runtime/provenance va degraded/fail-closed state ro rang.

Files chinh:

- `frontend/src/components/SummarizeDialog.tsx`
- `frontend/src/components/TaskList.tsx`
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- runtime-profile endpoint/backend config tuong ung

### 4. Offline Runtime Activation Va Release Bundle

Artifact llama.cpp/Qwen3 da verify nhung effective provider van co the la Ollama
ngoai repo. Can:

1. Cho startup profile chinh thuc khoi dong `scripts/start_llama_server.ps1` va
   fail neu alias/path/hash/profile khong khop.
2. Chuyen effective provider sang repository-local llama-server trong profile
   offline; ghi runtime/model config/eval metadata.
3. Sua runtime manifest thanh full 40-hex commit.
4. Quyet dinh/canonicalize HF `.cache` metadata de nested model verification
   khong fail nhung van chan unexpected artifact.
5. Dong goi va verify du 16 role: source, runtimes, models, Python wheelhouse,
   Node cache/runtime, DB/queue, FFmpeg, licenses, prompts/schema, startup va OS
   prerequisites.
6. Network-denied clean-machine test; khong duoc tao cache ngoai release root.

Source research/audit:

- `docs/research/local-ai-stack-2026-08-09.md`
- `docs/reviews/local-llm-runtime-independent-audit-2026-08-09.md`
- `docs/reviews/offline-release-bundle-independent-audit-2026-08-09.md`

### 5. ASR Va Diarization Offline Completeness

Live transcript tai E da success qua fallback faster-whisper, nhung day chua phai
full target stack:

1. Cherry adapter dang thieu `large-v2.pt`; chon mot canonical model layout va
   khong silent fallback khi profile yeu cau Cherry.
2. Pyannote local snapshot hien khong du `config.yaml`/model tree; live output co
   the degraded 1 speaker.
3. Pin revision/hash/license cho Whisper/PhoWhisper/Pyannote nhu Qwen3.
4. Test offline loader voi outbound network bi chan.
5. UI phai hien `engine_requested`, `engine_used`, `fallback_reason`, diarization
   degraded state va speaker provenance.

### 6. Summary/Analysis Product Design

Tiep tuc original product objective, khong quay lai template dien field:

1. Overview ngan gon nhung bao phu nguoi, doi tuong, su kien, thoi gian, dia diem,
   so tien, so dien thoai/tai khoan/bien so va cac dinh luong thuc su co trong
   hoi thoai.
2. Khong tao truong `null`/"khong co" neu transcript khong co thong tin.
3. Detail theo chu de khong lap overview; moi item co evidence/time/speaker/file.
4. Analysis la mot tab duy nhat; visualization la deterministic projection cua
   released claims, khong tao them su that.
5. Trong case nhieu file, moi tab Transcript/Diarization/Summary/Analysis phai co
   file identity ro rang; diarization co collapse theo file/speaker turn.
6. Human-review state cho entity linking, speaker mapping, hypotheses va withheld
   high-risk claims.

Source architecture:

- `docs/reviews/summary-analysis-architecture-audit-2026-08-09.md`
- `docs/reviews/analysis-visualization-convergence-audit-2026-08-09.md`
- `docs/research/evidence-preserving-adaptive-investigative-summary-2026-08-09.md`

### 7. Vietnamese Evaluation And Model Promotion

Khong claim model "manh nhat" chi dua vao model card. Can corpus Viet du an va
repeatable benchmark:

1. ASR: CER/WER, critical-entity recall/F1, hallucinated span, timestamp MAE,
   RTF, RAM/VRAM.
2. Diarization: DER/JER, speaker-count accuracy, overlap recall, SA-WER.
3. Summary: fact coverage, entity/amount/time recall, contradiction/unsupported
   rate, compression, latency.
4. Analysis: schema-valid, evidence-grounding, unsupported high-risk claim,
   withheld count, prompt-injection pass, human usefulness.
5. Ghi model ID, revision/hash, quantization, runtime build, decoding params,
   hardware, corpus revision va raw result JSONL.
6. Qwen3.5-9B chi la challenger; khong promote truoc A/B voi Qwen3-8B baseline.

### 8. P0-P8 Release Closure

Original plan van o:

- `docs/plans/2026-08-08-remediation-plan.md`
- `docs/plans/2026-08-08-remediation-research.md`

Can tiep tuc/kiem tra day du:

1. PostgreSQL `_test` isolation va negative guard truoc full pytest.
2. Auth/case authorization va typed PATCH.
3. Alembic clone-first reconciliation; khong stamp/live migrate tuy tien.
4. Session lifecycle/concurrency.
5. Cherry explicit engine/fallback contract.
6. Forensic/evidence eval gate.
7. CI/dependency/privacy hygiene.
8. Full verification, browser E2E, release manifest va handoff.

## Thu Tu De Xuat Cho Phien Moi

1. Re-audit diff/status tai E va khoa file ownership cho task dau.
2. Implement typed nested evidence schema + per-claim summary support gate.
3. Sua sync summary fail-closed + shared GPU handoff/recovery CLI.
4. Chay targeted negative tests va independent audit; chi commit allowlist neu PASS.
5. Hoi tu frontend ve verified runtime profile/model alias.
6. Active llama-server/Qwen3 repository-local va chay live sleep/wake/VRAM test.
7. Hoan thien Cherry/Pyannote artifact tree va offline loader.
8. Tiep tuc Vietnamese benchmark, product UX va P0-P8 release closure.

## Validation Commands Hien Co

```powershell
Set-Location E:\research\STT

.\venv\Scripts\python.exe -m pytest -q `
  tests\test_openai_compatible_llm.py `
  tests\test_summary_runtime_benchmark.py `
  tests\test_model_runtime.py `
  tests\test_llama_runtime_bundle.py

.\venv\Scripts\python.exe -m pytest -q `
  tests\test_context_analysis.py `
  tests\test_investigation_knowledge.py `
  tests\test_local_llm_optimization.py

npm --prefix frontend run build
.\venv\Scripts\python.exe scripts\verify_llama_runtime.py --probe --json
.\venv\Scripts\python.exe scripts\model_store.py verify --json
```

Khong chay full `pytest tests` neu `DATABASE_URL` van tro den `speech_to_info`.
Phai dung dedicated `_test` database va negative guard theo P0.

## Commit, Push Va Rollback Policy

- Khong commit/push goi dirty LLM/GPU. Artifact audit/handoff va migration repair
  harness duoc phep commit theo allowlist rieng.
- Truoc commit: `git diff --check`, targeted tests, independent audit va exact
  allowlist.
- Khong include model weights/generated logs/user artifacts vao commit neu khong
  co manifest/LFS/release policy ro rang.
- Push chi sau khi commit tuong ung dat gate; khong dung `git add -A`.
- Khong xoa D cho den user approval sau phien moi tai E.

## Prompt Goi Y Cho Phien Moi

```text
Lam viec duy nhat tai E:\research\STT. Doc
docs/handoffs/2026-08-09-new-workspace-handoff.md va
docs/reviews/2026-08-09-workspace-migration-audit.md, tiep tuc goal P0-P8
019fe1f4-71d2-7fd3-82c0-ef9f59a16d4f. Bat dau bang audit current diff,
sau do implement typed nested evidence schema va per-claim summary support gate;
review/research khi can, chay negative tests, audit doc, commit/push chi theo
allowlist khi gate PASS. Khong xoa repo D.
```
