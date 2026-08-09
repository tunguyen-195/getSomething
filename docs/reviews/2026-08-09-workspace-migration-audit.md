# Workspace Migration Audit - D to E

**Ngay audit:** 2026-08-09

**Nguon rollback:** `D:\Workspace\SpeechToInfomation`

**Workspace canonical:** `E:\research\STT`

**Evidence:** `E:\research\_STT_migration_evidence\2026-08-09-d-to-e`

**Branch:** `feature/architecture-refactor`

**Base implementation HEAD tai snapshot migration:**
`674ca91d40d3b64d929ade41653fa45f5cc7aef0`

## Verdict

| Pham vi | Verdict | Ket luan |
|---|---|---|
| Di chuyen du lieu va Git D -> E | **PASS** | Inventory, material hash, Git object database, Git LFS va DB backup deu dat gate |
| Cutover runtime sang E | **PASS** | Frontend, backend va Celery chay tu E; khong con app process chay tu D |
| Tinh portable cua venv sau khi copy | **PASS SAU REPAIR** | Da sua 94 launcher/script con nhung duong dan D; hien con 0 tham chieu cu trong `venv\Scripts` |
| Product/offline release readiness | **BLOCKED** | Day la blocker san pham doc lap voi migration; offline bundle hien dat `0/16` role |

Ket luan tren chi xac nhan workspace E da duoc di chuyen va cutover an toan. No
khong co nghia he thong da san sang production hoac hoat dong doc lap 100% offline.

## Migration Evidence

`result.json` ghi nhan:

| Gate | Ket qua |
|---|---:|
| File nguon | 198,979 |
| File dich | 198,979 |
| Byte nguon | 27,130,995,607 |
| Byte dich | 27,130,995,607 |
| File material duoc doi chieu SHA-256 | 108,493 |
| Inventory mismatch | 0 |
| Hash mismatch | 0 |
| Robocopy exit code | 1 - copy thanh cong, co file duoc copy |
| Source D duoc giu lai | true |

Independent audit da nap lai hai inventory CSV va dung `Compare-Object`; ket qua
khong co sai khac tai snapshot migration. `git fsck --full` exit 0, chi co 260
dangling blob; `git lfs fsck` tra `Git LFS fsck OK`. Dangling blob khong phai
Git corruption va khong bi xoa trong dot audit nay.

## Database Safety

- Backup: `speech_to_info-before-migration.dump`, 1,876,619 byte.
- SHA-256: `a5d444b71b70e2183f775e531779c6b26f42e6253e98a7edd8d36d1ebd6c1920`.
- `pg_restore --list` PASS; archive co 301 TOC entries.
- Ket noi tu workspace E va `SELECT 1` PASS.
- Collation cua database ung dung `speech_to_info` khop OS: `1541.2,1541.2`.
- Database bao tri `postgres` con warning collation `1540.3` so voi OS `1541.2`.
  Warning nay khong do migration va khong chan app, nhung can maintenance rieng;
  khong tu y chay `ALTER DATABASE ... REFRESH COLLATION VERSION` khi chua danh
  gia/rebuild cac object phu thuoc.

Khong co row nao bi xoa, khong co schema migration nao duoc chay trong qua trinh
di chuyen.

## Venv Relocation Repair

Audit sau cutover phat hien Windows console launcher va mot so text script trong
`venv\Scripts` van nhung `D:\Workspace\SpeechToInfomation`. Service dang chay
khong bi anh huong vi entrypoint dung
`E:\research\STT\venv\Scripts\python.exe -m ...`, nhung launcher se hong neu
repo D bi xoa.

Da xu ly bang harness:

```powershell
.\venv\Scripts\python.exe scripts\repair_moved_venv_launchers.py `
  --venv E:\research\STT\venv `
  --old-root D:\Workspace\SpeechToInfomation `
  --apply --json
```

Ket qua:

- 94 file co duong dan cu truoc repair.
- 82 console launcher duoc tao lai bang interpreter E.
- 12 text script duoc sua duong dan.
- 0 file con duong dan cu sau repair.
- Backup truoc repair va manifest hash nam tai
  `venv-launchers-before-repair` trong thu muc evidence.
- `pip.exe`, `celery.exe`, `pytest.exe`, `alembic.exe` va `uvicorn.exe` smoke PASS.
- `pytest.exe -q tests\test_model_runtime.py`: 13 passed.

Ba E2E helper cung da doi tu duong dan D hardcode sang `Path` tuong doi theo repo:

- `scripts/e2e_test.py`
- `scripts/e2e_full_test.py`
- `scripts/trigger_upload.py`

## Runtime Cutover

Trang thai duoc kiem tra tu workspace E:

| Thanh phan | Ket qua |
|---|---|
| Frontend | `http://127.0.0.1:3000`, HTTP 200, 1,026 byte |
| Backend health | `GET /api/v1/health`, HTTP 200, `{"status":"ok"}` |
| OpenAPI live khong auth | HTTP 401 dung security contract |
| OpenAPI TestClient schema reachability | HTTP 200, 36,710 byte |
| Celery | 1 logical node, `pong`, active task rong |
| PostgreSQL | listener 5432, `SELECT 1` PASS |
| Redis | listener 6379 |
| App process tu D | 0 |

Uvicorn reload co parent/child process; Celery Windows venv cung co redirector
parent va base-Python child. `celery inspect` chi nhan 1 logical worker, khong
phai hai worker nghiep vu doc lap.

## Model And Application Gates

- FastAPI `0.104.1`, Celery `5.3.4`, PyTorch `2.1.1+cu121`; CUDA available.
- llama.cpp `b10331`, commit label `7ba604f1c`, 11 file/1,767,834,013 byte,
  version va RTX 4070 SUPER probe PASS.
- Qwen3-8B Q4_K_M: 5,027,802,879 byte, repository-local model verification PASS.
- Runtime/model tests: **45 passed**, 13 warnings.
- Context/investigation/GPU tests: **48 passed**, 13 warnings.
- Frontend `tsc && vite build`: **PASS**; con advisory chunk 724.43 kB.

Day la targeted validation, khong phai full regression suite. Khong chay toan bo
`pytest tests` tren live database; P0 yeu cau test database co ten ket thuc `_test`
phai duoc hoan tat va dung cho full suite.

## Product Blockers Khong Thuoc Migration

1. Offline release bundle dang **BLOCKED, 0/16 role**.
2. Cherry ASR thieu `large-v2.pt` o cac duong dan adapter dang tim; live transcript
   fallback sang faster-whisper large-v3.
3. Pyannote local snapshot khong day du `config.yaml`/model tree; diarization live
   co the degraded thanh 1 speaker.
4. Effective LLM provider hien van co the la Ollama ngoai repo. Vendored
   llama.cpp + Qwen3 da verify nhung chua duoc active startup profile chon va
   khoi dong end-to-end.
5. Offline bundle verifier dang reject Qwen nested tree do `.cache` metadata va
   reject runtime manifest do commit chi co short hash, khong phai full 40-hex.
6. Model quality cho tieng Viet dieu tra chua duoc chung minh bang corpus gan nhan
   va benchmark tren may dich.

## Git And Change Safety

Tai snapshot truoc khi commit artifact handoff:

- Branch ahead upstream 1 commit, behind 0.
- Worktree co 32 tracked changes va 40,370 untracked file khi dung
  `--untracked-files=all`.
- Snapshot D va E trung nhau tai gate migration. Sau cutover, E co cac repair co
  chu dich neu tren; D duoc giu nguyen lam rollback snapshot.
- Khong commit/push toan bo dirty tree. Artifact audit/handoff va repair harness
  co the duoc commit theo allowlist rieng; implementation chi duoc commit sau khi
  tung goi dat gate tuong ung.

## Evidence Provenance Caveat

Inventory snapshot ghi `scripts\migrate_workspace.ps1` tai luc copy co SHA-256
`323c6845458f58084f514a798aea750bda5083c681b65134bcedc51da5d1dd19`
va 9,917 byte. File harness sau do duoc cap nhat thanh 10,029 byte, SHA-256
`1170395b540dde53639982f45620685f53305dd7087e1256f9a11dcbf1d91b9f`;
`result.json` ghi hash phien ban moi. Vi khong luu immutable copy cua exact
executed harness, field nay khong the chung minh bit-for-bit script da thuc thi.
Inventory/hash/data/Git/DB evidence van doc lap va dat gate, nhung dot migration
sau phai snapshot harness truoc khi chay va tao signed/hash manifest cho toan bo
evidence bundle.

Key evidence hashes tai khi lap bao cao:

| Artifact | SHA-256 |
|---|---|
| `result.json` | `f6c9f8afddd3c3314cc5c712ff952f88b010772ea9fb699dc5b468a11bd94533` |
| `cutover.json` | `8c959f5dafe8cfe90abf05c52a61f50154dcd1bd6ae861ed344cc10616874f6b` |
| `venv-launcher-repair.json` | `0d015ab4aecaeae7fbc5525b35700b195875fd2e29621f8a20138bb7b0003236` |
| `handoff-llm-runtime-tests.txt` | `b2f3ea47524a2a6fa5bb866ebed5d8bf5a356d8253f1c8c886da289f56cb4f1f` |
| `handoff-context-investigation-tests.txt` | `327849c6f50a09bdaf94f8b0f036f6e9098f560e47b5b2181e7d9a0bf8b0034d` |
| `handoff-frontend-build.txt` | `805ae2aa4d7640da6e3f58616cb6e5d13285f8c19612f1ad2fdfb4311cab3f2c` |

Evidence directory hien la sibling ngoai Git va van mutable. Khong xem cac hash
tren la chu ky release; day la audit snapshot de doi chieu.

## Rerun Protocol

```powershell
Set-Location E:\research\STT

Get-Content E:\research\_STT_migration_evidence\2026-08-09-d-to-e\result.json
Get-Content E:\research\_STT_migration_evidence\2026-08-09-d-to-e\cutover.json

git status --short --branch
git rev-parse HEAD
git fsck --full
git lfs fsck

.\venv\Scripts\python.exe scripts\repair_moved_venv_launchers.py `
  --venv E:\research\STT\venv `
  --old-root D:\Workspace\SpeechToInfomation `
  --json

Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/health
.\venv\Scripts\celery.exe -A src.worker.worker inspect ping --timeout 10
```

## Rollback Rule

Khong xoa `D:\Workspace\SpeechToInfomation` cho den khi nguoi dung mo phien moi
tai E, chay smoke/E2E can thiet va xac nhan workspace E on dinh. Neu can rollback,
dung D nhu snapshot; khong dong bo nguoc tu E ve D mot cach co hoc.
