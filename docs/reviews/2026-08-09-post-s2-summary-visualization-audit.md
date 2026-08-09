# Post-S2 Summary And Visualization Audit

**Ngay audit:** 2026-08-09

**Workspace canonical:** `E:\research\STT`

**Branch:** `feature/architecture-refactor`

**Base HEAD:** `fe5fe6d77a962b405d65758e5b5d7f19788520c5`

**Evidence artifact:** `docs/reviews/artifacts/post-s2-summary-visualization.json`

## Verdict

**PASS** cho defect package post-S2: UI khong con in raw fact metadata thanh
noi dung, khong lap `key_point` vao `Insight nghiep vu`, summary khong con tao
visualization, va visualization chi duoc doc nhu deterministic projection cua
mot `InvestigationRun` da duoc release authority seal.

Verdict nay khong dong nghia C1 persistence da hoan tat. Stored JSON hien khong
duoc phep tu rehydrate thanh release authority; POST visualization tu stored run
vi vay co chu dich tra `409 VISUALIZATION_RELEASED_RUN_REQUIRED` cho den khi co
trusted persistence/rehydration gateway.

## Root Cause

Loi UI trong payload mau co hai nguon doc lap:

1. `InvestigationSummaryCard` lay toan bo `investigation_knowledge.facts` cho ca
   `Cac diem mau chot` va `Insight nghiep vu`, sau do render object qua generic
   formatter. Vi vay `fact_id`, `category`, `evidence_ids`, `model_generated` va
   `verification_status` bi lo thanh prose, dong thoi cung mot fact xuat hien hai
   lan.
2. Summary service thuc hien mot LLM call thu hai de trich xuat graph/timeline
   tu summary. Worker lai ghi ca result object, nen summary co the tro thanh mot
   truth authority thu hai va co the ghi de visualization da release.

## Contract Da Khoa

- `Cac diem mau chot` chi chon `category=key_point`, render duy nhat `statement`,
  deduplicate statement trung nhau, gom evidence reference, an fact `rejected`,
  va hien trang thai xac minh bang chip thay vi raw metadata.
- `Insight nghiep vu` khong duoc suy ra tu facts. Tab insight bi an neu chua co
  reasoning-release authority; hypotheses khong duoc promote thanh risk/fact.
- Legacy `TaskList` va `TaskListItem` sanitize `context_analysis` truoc khi truyen
  vao component, chan payload cu bypass projection.
- `FileCard`, `FileTable`, `App`, `AnalysisPanel` va `VisualizationDialog` chi doc
  artifact qua strict frontend validator. UI khong con nut Generate/Re-generate
  va khong POST visualization de tao them su that.
- Summary service khong con LLM/regex visualization extraction. Summary worker
  chi gui partial summary patch; task service deep-merge de giu nguyen bytes cua
  visualization doc lap va clear context stale khi summary khong co context moi.
- Backend artifact bind `run_id`, `source_revision_id`,
  `release_subject_sha256` va `content_hash`; reversed time bounds, dangling
  graph edges, extra metadata, hash tamper, stale/standalone artifact deu bi
  reject.
- Release authority la one-shot seal. `model_construct`, model copy, deepcopy va
  mutation sau release khong the tao authority hop le.
- v1 list/detail va v2 status chi expose visualization khop active released run.
  Neu artifact bi an, status `visualized` duoc ha ve `summarized`, `transcribed`
  hoac `uploaded` theo du lieu thuc con lai.
- Legacy/v2 visualization endpoints va Celery worker fail closed neu khong co
  trusted released run, khong ghi `visualizing`, `visualized` hoac `failed` gia.

## RTK Harness Va Evidence

Snapshot commit duoc xuat truc tiep tu Git index bang `git write-tree`, sau do
kiem thu trong detached worktree rieng. Cach nay loai anh huong cua delta S3/S4/G1
dang giu lai ngoai index.

| Gate | Ket qua |
|---|---|
| Working-tree broad backend | `240 passed`, 13 warnings, 108.35 s |
| Cached-index backend | `225 passed`, 13 warnings, 104.00 s |
| Cached-index frontend semantic | `9/9 passed` |
| Cached-index TypeScript/Vite build | PASS, 12,066 modules, bundle 694.58 kB, gzip 212.66 kB |
| `git diff --check` | PASS |
| Frontend runtime | HTTP 200 |
| Backend health | HTTP 200, `{"status":"ok"}` |
| Celery | 1 node, `pong` |
| PostgreSQL / Redis | ports 5432 / 6379 listening |
| Browser smoke | Login shell rendered; unauthenticated `/auth/me` 401 is expected |

Backend-validated index tree: `40398d44da15914e18a9b7f94f322434f8f8936e`.
Final frontend-validated index tree: `98d1643b6031de97273aebe9852e99bf664bceca`.
Ephemeral cached commits: `db085de9156738bf0621447391a2a47e8e35d251`
and `fd43ec06ad763fe70a6e67dd337c9b258b772a39`.

Browser evidence:

- `output/playwright/ui-viz-final-smoke.png`
- SHA-256 `72eb9e72a763608da0ea4c895243a384a98e45bda930194786a46c950b331d3f`

## Independent Review

- UI audit: **PASS**, khong co blocking finding. Auditor xac nhan payload mau chi
  con hai statement xuat hien mot lan, `insights=[]`, component wiring read-only,
  va 27/27 staged source hash khop cached snapshot. One-sided evidence timestamp
  gap duoc dong sau audit bang negative test frontend.
- Backend audit: **PASS**, khong co blocking finding. Auditor xac nhan genuine
  release seal, hash/provenance binding, stale-state downgrade, summary separation,
  endpoint/worker no-mutation fail-closed va staged snapshot khong tron S3/S4/G1.

## Commit Boundary

Git index chi chua defect package post-S2. Cac thay doi sau van duoc giu nguyen
ngoai index de xu ly theo task rieng:

- S3: shared `summary_type` allowlist va length-bound contract.
- S4: synchronous summary fail-closed va state transition contract.
- G1: shared GPU lease/quarantine, handoff va recovery CLI.
- Frontend runtime profile/model alias, case pagination va diarization/model delta.

## Residual Risk Va Blocker

1. **C1 trusted persistence/rehydration:** he thong chua co gateway co tham quyen
   de nap stored released run ma van bao toan seal. Day la ly do POST visualization
   tu stored JSON tra 409; khong duoc sua bang public `model_validate`.
2. Browser smoke chi xac nhan auth shell vi khong dung tai khoan/fixture san pham
   trong audit nay. Semantic fixture va component wiring tests bao phu defect cu
   the; authenticated E2E voi case that van la release gate sau.
3. Frontend con advisory chunk >500 kB; khong phai correctness blocker cua package.
4. Frontend validator kiem tra dinh dang `content_hash` nhung khong tu tinh lai
   canonical SHA-256 dong bo. Backend `InvestigationVisualization` bat buoc tinh
   lai hash truoc khi artifact duoc expose, nen day la defense-in-depth gap muc
   thap, khong phai authority gap.
5. Offline/product blockers, Pyannote artifact completeness va Vietnamese corpus
   quality van giu nguyen theo workspace handoff; package nay khong claim da giai
   quyet cac blocker do.

## Next Task

Tiep tuc S3 va S4 tren delta da giu lai: shared summary request contract truoc,
sau do synchronous summary fail-closed. Khong tron GPU G1 vao cung commit.
