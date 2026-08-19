# Full Repository Review - SpeechToInfomation

**Ngay review:** 2026-08-08  
**Branch:** `feature/architecture-refactor`  
**Commit:** `da4b8a3d`  
**Pham vi:** backend FastAPI/SQLAlchemy, Celery, transcription/summarization, Cherry Core, frontend React/Vite, PostgreSQL/Redis/Docker, startup scripts, migrations, dependencies, tests va tracked runtime artifacts.  
**Phuong phap:** RTK evidence-first review + code maturity assessment 9 nhom.  
**Trang thai:** Review hoan tat; chua sua source code va chua xoa du lieu.

## Ket luan dieu hanh

Repo build duoc va test hien tai pass trong virtual environment cua repo, nhung chua dat nguong an toan de coi la production-ready. Bon van de can xu ly truoc tien la:

1. Test suite ghi truc tiep vao PostgreSQL local that.
2. Default deploy tat authentication va fallback thanh admin.
3. Case PATCH cho phep mass assignment va leo thang quyen.
4. V2 context analysis khong parse JSON binh thuong va bo qua `user_prompt`.

Ngoai ra, Cherry Core dang fallback ngam, live schema lech Alembic hai revision, SQLAlchemy Session bi dung sai trong thread/Celery, va release gate con thieu CI/lint/dependency validation.

## Canh bao du lieu

Khong chay lai `pytest` tren cau hinh hien tai cho den khi test database duoc co lap.

`tests/conftest.py:4-10` chi dat cac flag test, khong override `DATABASE_URL`. `src/database/config/database.py:8-25` nap `.env` va tao engine den PostgreSQL local. Cac helper trong `tests/test_security.py` commit du lieu vinh vien.

Snapshot read-only sau review tren `localhost:5432/speech_to_info`:

| Mau du lieu test | So ban ghi |
|---|---:|
| `users.username LIKE 'user_%'` | 3,605 |
| `cases.title LIKE 'case_%'` | 2,160 |
| task co `filename IN ('restricted.wav', 'orphan.wav')` | 1,761 |
| audio co ten UUID, `file_size=10`, `duration=1.0` | 1,235 |
| summary noi dung test dac trung | 246 |

Test run trong review da them ban ghi. Khong duoc bulk-delete theo prefix neu chua backup va doi chieu vi du lieu test cu co the dang tron voi du lieu nguoi dung.

## Findings

### R-001 - Critical - Test suite ghi vao database that

**Evidence**

- `tests/conftest.py:4-10`: khong set `DATABASE_URL` rieng cho test.
- `src/database/config/database.py:8`: `load_dotenv()` nap cau hinh local.
- `src/database/config/database.py:19-25`: engine dung `DATABASE_URL` hoac fallback `speech_to_info`.
- `tests/test_security.py:80`, `:102`, `:122`, `:142`, `:164`, `:180`: helper commit user/case/task/audio/summary.

**Impact**

- Lam ban DB phat trien/van hanh.
- Test khong idempotent va khong co rollback tin cay.
- Cleanup tu dong co nguy co xoa nham du lieu that.

**Gate sua loi**

- Test phai fail-fast neu DB name khong ket thuc bang `_test`.
- Truoc/sau full test, row counts cua `speech_to_info` phai khong thay doi.

### R-002 - Critical - Default authentication fail-open

**Evidence**

- `.env.example:3`: `AUTH_ENABLED=false`.
- `src/core/config.py:14`: default `AUTH_ENABLED=False`.
- `docker-compose.yml:18`: compose default false.
- `START_ALL_SERVICES.bat:16`: startup script default false.
- `src/core/auth.py:221-222`: middleware bo qua authentication.
- `src/core/auth.py:245-250`: dependency tra ve `admin` hoac user dau tien.
- Backend bind `0.0.0.0` trong `docker-compose.yml:14` va `START_ALL_SERVICES.bat:93`.

**Runtime evidence**

Voi `AUTH_ENABLED=false`, harness read-only tra ve fallback user `admin/admin` va admin path nhin thay 2,923 case rows. `.env` cuc bo hien tai dang bat auth; defect nam o committed defaults va bypass contract.

**Impact**

- May cung LAN/container port co the bi truy cap nhu admin ma khong can credential.
- Toan bo authorization phia sau `get_current_user` mat y nghia khi deploy theo default.

**Gate sua loi**

- Auth default true o moi tracked startup/config surface.
- Dev bypass chi duoc phep khi explicit opt-in, development mode va bind loopback.

### R-003 - High - Case PATCH mass assignment va privilege escalation

**Evidence**

- `src/api/endpoints/cases.py:149`: body la `Dict[str, Any]`.
- `src/api/endpoints/cases.py:157-159`: moi attribute ton tai deu duoc `setattr`.
- `src/core/auth.py:272-273`: `created_by` quyet dinh owner.
- `src/core/auth.py:297`: member co quyen `write`.

**Impact**

Member co the PATCH `created_by` thanh ID cua minh de tro thanh owner, hoac thay doi `id`, `case_code`, `is_archived`, relationship/state ngoai business contract.

**Gate sua loi**

- Dung `CaseUpdate` allowlist voi `extra='forbid'`.
- `id`, `created_by`, `is_archived` va relationship fields phai bi reject voi 422/403.

### R-004 - High - V2 context analysis hong JSON contract va bo qua user prompt

**Evidence**

- `src/services/summarization/models/llm_manager.py:300`: regex `r'\{{.*\}}'` chi match double braces.
- `src/services/summarization/models/llm_manager.py:305-307`: valid JSON binh thuong roi vao raw summary fallback.
- `src/services/summarization/context_service.py:38-53`: tao `base_prompt` co `user_prompt`.
- `src/services/summarization/context_service.py:56`: chi gui `transcript` cho model.

**Runtime evidence**

- Fake model tra valid JSON `{...}` -> ket qua tro thanh chuoi raw trong `summary`, `key_points=[]`.
- `user_prompt='SPECIAL-INSTRUCTION'` -> fake model chi nhan `TRANSCRIPT`.

**Impact**

Context extraction V2 mat structured fields va khong ton trong yeu cau nguoi dung.

### R-005 - High - Cherry Core enforced path khong khoi tao duoc va fallback ngam

**Evidence**

- `src/cherry_core/ports/diarization_port.py:3`: import `core.domain.entities`, trong repo khong co top-level package `core`.
- `src/cherry_core/adapters/diarization/pyannote_adapter.py:10`: import port bi loi.
- `src/services/transcription/cherry_transcription_service.py:18`: service load Pyannote adapter.
- `src/services/transcription/transcribe_service_v2.py:61`: ghi `USE_CHERRY_CORE = True`.
- `src/services/transcription/transcribe_service_v2.py:102-107`: catch moi import/execution error va fallback legacy.

**Runtime evidence**

`CherryTranscriberService()` fail voi `ModuleNotFoundError: No module named 'core'`.

**Scope note**

Finding nay chi dua tren tracked port, Pyannote adapter va service. Cac adapter enhanced/resemblyzer/speechbrain dang untracked khong duoc tinh la release surface.

### R-006 - High - Live schema va Alembic history bi drift

**Evidence**

- Repository head: `d5e6f7a8b9c1`.
- Live `alembic_version`: `b1cbd9b60b5b`.
- `src/database/init_db.py:31-34`: startup dung `Base.metadata.create_all()`.
- `src/database/migrations/versions/c4f1a2b3c9d0_add_auth_session_and_security_audit.py:17-59`: pending migration tao `auth_sessions` va `security_audit_logs`.
- Live DB da co ca hai bang va cac index chinh.
- Pending `d5e6f7a8b9c1` backfill path; live DB hien co 0 row mang prefix `storage/audio/`.

**Impact**

Chay `alembic upgrade head` truc tiep co kha nang collide voi bang da ton tai. `create_all()` tiep tuc che giau migration drift.

### R-007 - High - SQLAlchemy Session dung sai trong concurrency va bi leak

**Evidence**

- `src/api/endpoints/audio.py:682`: request tao mot Session.
- `src/api/endpoints/audio.py:704-705`: cung Session duoc gui vao nhieu `ThreadPoolExecutor` workers.
- `src/services/audio_service.py:93-190`: worker query va commit bang Session nhan vao.
- `src/worker/tasks.py:10-12`: `next(get_db())` khong close generator/session.

**Impact**

Co the gay transaction contamination, connection state error, intermittent failure va connection pool exhaustion.

### R-008 - High - Forensic LLM claims khong co evaluation/evidence gate

**Evidence**

- `src/services/summarization/models/llm_manager.py:242`: `honesty_assessment`.
- `src/services/summarization/models/llm_manager.py:260-263`: risk va crime indicators.
- `src/services/summarization/models/llm_manager.py:271`: surveillance targets.
- Khong co test nao tham chieu cac field tren; test surface chi gom `test_security.py` va `test_system.py`.

**Impact**

He thong co the hien thi nhan dinh deceptive/criminal/surveillance ma khong co evidence span, calibration, false-positive benchmark hoac human confirmation.

### R-009 - Medium - Release gates khong day du

**Evidence**

- `frontend/package.json:8`: co lint script, nhung repo khong co ESLint config.
- `npm run lint`: fail `ESLint couldn't find a configuration file`.
- Khong co `.github/workflows`.
- `requirements.txt:17-20`: co Celery, khong co `gevent`.
- `START_ALL_SERVICES.bat:103`: pip install `gevent` moi lan startup.
- `pip check`: thieu metadata dependencies cho optional `resemblyzer` va `simple-diarizer` installs.
- Frontend production audit: 1 moderate (`yaml`).
- Root Node tree: 2 high (`nanoid`, `postcss`) va 2 moderate (`styled-components`, `yaml`).

### R-010 - Medium - Tracked runtime dumps chua identifiers va filename

**Evidence**

- `cases.json:5-6`, `cases.txt:5-6`: case IDs, UUID case codes, creator IDs.
- `tasks.json:5`: task UUID va audio filename that-looking.
- `.gitignore` da ignore root `/*.json` va `/*.txt`, nhung ba file tren da duoc track tu truoc.

**Impact**

Metadata van hanh bi luu trong source history va co the tiep tuc duoc cap nhat/phan phoi nham.

## Validation da chay

| Gate | Ket qua | Ghi chu |
|---|---|---|
| Repo venv pytest | PASS | 25 passed, 13 warnings; test khong isolated nen khong duoc chay lai truoc R-001 fix |
| Security subset | PASS | 17 passed |
| `python -m compileall src tests scripts -q` | PASS | Khong co syntax error |
| `npm run build` | PASS | Main chunk 709.88 kB minified, co size warning |
| `npm run lint` | FAIL | Khong co ESLint config |
| `docker compose --env-file .env.example config --quiet` | PASS | Compose parse thanh cong |
| `pip check` | FAIL | 3 missing dependency declarations trong installed environment |
| `alembic current` | FAIL gate | Live o `b1cbd9b60b5b`, head la `d5e6f7a8b9c1` |
| Python vulnerability audit | NOT RUN | `pip-audit` chua duoc cai |

## Code maturity scorecard

| Nhom | Rating | Ly do chinh |
|---|---:|---|
| Arithmetic | Weak - 1/4 | Signal-processing heuristic khong co boundary/property tests |
| Auditing | Moderate - 2/4 | Co audit tables/logs; thieu monitoring va incident response |
| Authentication/access | Weak - 1/4 | Fail-open defaults va mass assignment |
| Complexity | Weak - 1/4 | Module lon, legacy/V2 duplication, broad silent fallbacks |
| Decentralization | N/A | Day la centrally operated web application |
| Documentation | Weak - 1/4 | Co setup docs, nhung tracked architecture/risk contract chua day du |
| Transaction ordering | N/A | Khong co blockchain transaction surface |
| Low-level manipulation | Satisfactory - 3/4 | Khong tim thay unsafe deserialization hoac `shell=True` tren request path |
| Testing/verification | Weak - 1/4 | Test pass nhung destructive, hep va khong co CI |

**Tong diem tren cac nhom ap dung:** 1.4/4 - Weak.

## Residual uncertainty

- Chua the phan loai an toan tung row test va row that trong live DB neu khong co backup/retention decision.
- Chua chay end-to-end audio/model benchmark vi day la review, va mot so model tai nguyen lon/ngoai repo.
- Cac untracked Cherry Core adapters va report scripts co the thay doi ket qua khi duoc dua vao release; review nay khong coi chung la tracked implementation.
- Dependency vulnerability severity la output audit hien tai; exploitability can danh gia theo duong build/deploy thuc te.

## Artifacts lien quan

- `docs/plans/2026-08-08-remediation-research.md`
- `docs/plans/2026-08-08-remediation-plan.md`

