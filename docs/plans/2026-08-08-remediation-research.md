# Remediation Research - SpeechToInfomation

**Ngay:** 2026-08-08  
**Input:** `docs/reviews/2026-08-08-full-repo-review.md`  
**Muc tieu:** Xac dinh cach sua cac finding theo thu tu an toan, co the kiem chung va khong lam mat du lieu.  
**Trang thai:** Research complete; ready for implementation planning.

## Research frame

### Cau hoi

Lam the nao de sua cac defect security, database, concurrency, AI va release engineering ma:

1. Khong chay test vao DB that.
2. Khong xoa nham du lieu dang tron.
3. Khong mo anonymous admin path.
4. Khong che giau engine/model fallback.
5. Co test va negative gate cho tung requirement.

### Falsification conditions

Plan bi coi la khong dat neu mot trong cac dieu sau van dung sau implementation:

- `pytest` co the ket noi DB khong mang ten `_test`.
- Default deploy cho phep auth bypass.
- Member PATCH duoc `created_by`/`is_archived`/`id`.
- Valid JSON context response khong parse thanh schema.
- `user_prompt` khong den prompt thuc su cua model.
- `TRANSCRIPTION_ENGINE=cherry` tu dong fallback ma khong fail/report.
- `alembic current` khong bang head.
- Cung mot SQLAlchemy Session duoc share qua thread/task.
- High-risk LLM field duoc release ma khong co evidence span va eval gate.

## Local evidence synthesis

| Claim | Evidence | Ket luan research |
|---|---|---|
| SQLite khong phai test replacement tuong duong | Schema/migration dung PostgreSQL regex constraint `~` va JSON/index behavior | Dung dedicated PostgreSQL test DB, khong doi sang SQLite |
| Test helper mo nhieu Session va commit | `tests/test_security.py:60-183` | Can DB co lap + cleanup strategy; dependency override mot minh chua du |
| Live security tables da ton tai | Inspector output cho `auth_sessions`, `security_audit_logs` | Khong chay c4 migration truc tiep |
| Live Alembic revision cham 2 buoc | current `b1cbd9b60b5b`, head `d5e6f7a8b9c1` | Reconcile/stamp c4 chi sau schema comparison va backup |
| d5 backfill hien khong co row can sua | 0/1,672 audio rows co prefix `storage/audio/` | Sau c4 reconciliation, d5 upgrade co rui ro data thap hon, van phai test tren clone |
| Root Node tree khong co scripts | root `package.json` chi co dependencies | Can xac nhan runtime usage, sau do consolidate/remove de giam audit surface |
| Cherry path fail ngay luc import | `CherryTranscriberService()` -> `ModuleNotFoundError: core` | Import smoke test la gate toi thieu truoc model benchmark |

## Primary sources

Tat ca URL duoi day duoc kiem tra truy cap ngay 2026-08-08.

### SQLAlchemy - Session concurrency

- Source: [SQLAlchemy Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#is-the-session-thread-safe-is-asyncsession-safe-to-share-in-concurrent-tasks)
- Guidance: concurrency model la **Session per thread, AsyncSession per task**; Session la mutable, stateful va khong an toan de share.
- Ap dung: moi ThreadPool worker/Celery task phai tu mo va dong Session trong local context manager.

### FastAPI - Test dependency overrides

- Source: [Testing Dependencies with Overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/)
- Guidance: dung `app.dependency_overrides` de thay dependency trong test.
- Ap dung: override `get_db` sang test session factory, dong thoi set `DATABASE_URL` truoc khi import application modules.

### FastAPI/Pydantic - Partial updates

- Source: [Body - Updates](https://fastapi.tiangolo.com/tutorial/body-updates/)
- Guidance: PATCH model dung `model_dump(exclude_unset=True)` va copy/update tren allowlisted Pydantic schema.
- Ap dung: tao `CaseUpdate`, `extra='forbid'`, khong expose owner/archive/identity fields.

### OWASP - Authorization

- Source: [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
- Guidance: least privilege, deny by default, validate permission on every request, khong cho ID/lookup field bi tamper.
- Ap dung: auth default true; dev bypass explicit va loopback-only; resource ownership khong duoc cap nhat qua generic PATCH.

### Alembic - Revision stamping

- Source: [Alembic Commands](https://alembic.sqlalchemy.org/en/latest/api/commands.html#alembic.command.stamp)
- Installed Alembic `stamp` docstring: stamp revision table ma **khong chay migrations**.
- Ap dung: chi stamp `c4f1a2b3c9d0` neu schema clone/live duoc chung minh tuong duong migration c4; khong dung stamp de bo qua schema mismatch.

### Python - JSON decoding

- Source: [Python `json` documentation](https://docs.python.org/3/library/json.html)
- Guidance: decode JSON bang parser chuan; regex greedy khong phai structured parser.
- Ap dung: `json.loads` direct response, optional fence stripping, `JSONDecoder.raw_decode` neu provider tra text bao quanh, sau do Pydantic validation.

### NIST - Generative AI risk management

- Source: [NIST AI 600-1, Generative AI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)
- Guidance ap dung: measure/manage confabulation va harmful high-impact output, document limits, monitor va giu human oversight.
- Ap dung: high-risk forensic fields khong duoc coi la fact; phai co evidence spans, abstention va release threshold.

## Technical decisions

### D-001 - Dedicated PostgreSQL test database

**Decision**

- Tao `docker-compose.test.yml` hoac test service profile voi database `speech_to_info_test`, port rieng neu chay local.
- `tests/conftest.py` set `DATABASE_URL` truoc moi import `src.*`.
- Fail-fast neu parsed database name khong ket thuc `_test`, tru khi co explicit one-time override cho migration lab.
- Override `get_db` bang `app.dependency_overrides`.
- Function-scoped reset dung `TRUNCATE ... RESTART IDENTITY CASCADE` tren dedicated test DB, sau do seed lookup data; khong truncate live DB.

**Alternative rejected**

- SQLite in-memory: khong tuong duong PostgreSQL constraints/types.
- Chi dung unique UUID: tranh collision nhung van de lai du lieu va van co the tro nham live DB.
- Global transaction rollback duy nhat: kho bao phu cac Session doc lap va background paths hien tai.

### D-002 - Cleanup du lieu test la operation rieng, co approval

**Decision**

- Dau tien tao report read-only liet ke candidate IDs, foreign-key fanout, min/max timestamps va counts.
- Backup DB truoc cleanup.
- Cleanup script phai co `--dry-run` default, explicit `--apply`, database name confirmation va transaction.
- Khong dua cleanup vao test fixture hoac startup.

### D-003 - Authentication fail closed

**Decision**

- `AUTH_ENABLED=true` tren config, `.env.example`, compose va tracked startup scripts.
- Neu can dev bypass: them explicit `DEV_AUTH_BYPASS=false`; chi chap nhan khi `ENVIRONMENT=development`, `DEBUG=true`, host loopback, va `DEV_USER_ID` duoc chi dinh.
- Khong fallback implicit sang `admin`/first user.
- Startup fail neu production-like mode ma auth bi tat.

### D-004 - Typed CaseUpdate allowlist

**Decision**

Cho phep PATCH cac business fields sau neu validation thanh cong:

- `title`
- `description`
- `status_id`
- `priority_id`

`case_code`, `created_by`, `is_archived`, `id`, timestamps va relationship fields khong nam trong schema. Archive giu endpoint/action rieng.

### D-005 - Session ownership ro rang

**Decision**

- HTTP request Session chi dung authorize/list.
- Moi thread wrapper goi `with SessionLocal() as db:` roi `process_task(...)`.
- Moi Celery task mo Session trong `try/finally` hoac context manager.
- Khong truyen Session qua Celery payload/thread boundary.
- Sau sua ngan han, can danh gia chuyen batch endpoint sang Celery fan-out de bo threadpool trong web process.

### D-006 - Reconcile Alembic truoc khi bo create_all

**Decision sequence**

1. Backup/clone `speech_to_info`.
2. So sanh columns, nullability, PK/FK, unique constraints va indexes cua hai bang security voi c4.
3. Neu exact-enough: `alembic stamp c4f1a2b3c9d0` tren clone, sau do `alembic upgrade d5e6f7a8b9c1`.
4. Neu mismatch: tao reconciliation migration/data repair; khong stamp.
5. Verify app/tests tren clone.
6. Lap lai tren live trong maintenance window.
7. Bo `create_all()` khoi normal startup; chi migrations thay doi schema.

### D-007 - Structured context contract

**Decision**

- Tao Pydantic schema cho context response.
- Parse direct JSON; strip Markdown fence neu co; neu response co prefix/suffix, dung `JSONDecoder.raw_decode` tu vi tri object dau tien.
- Parse failure tra structured error/status, khong gia vo valid context bang raw summary.
- `user_prompt` duoc truyen explicit den mot parameter duoc test; bo dead `base_prompt` construction.
- Log provider/model/prompt version, khong log raw sensitive transcript theo default.

### D-008 - Explicit transcription engine contract

**Decision**

Them `TRANSCRIPTION_ENGINE=legacy|cherry|auto`:

- `legacy`: chi legacy.
- `cherry`: import/execution fail -> task fail ro rang, khong fallback.
- `auto`: fallback duoc phep, nhung result bat buoc co `requested_engine`, `engine_used`, `fallback_reason`.

Sua tracked imports thanh `src.cherry_core...`; import smoke tests khong duoc tai model/network.

### D-009 - High-risk LLM outputs bi gate

**Decision**

- Moi claim `deceptive`, crime/risk hoac surveillance phai co transcript evidence span va `model_generated=true`.
- UI hien thi nhu hypothesis, khong phai fact.
- Neu chua dat eval threshold, disable cac field nay tren default profile.
- Eval set chi dung synthetic/de-identified Vietnamese transcripts.

**Release thresholds de xuat**

- JSON schema validity: 100%.
- Evidence span ton tai cho high-risk claim: 100%.
- Benign-set false positive cho crime/deception/surveillance: 0%; neu khong dat, feature tiep tuc disabled.
- Missing/uncertain evidence phai abstain thay vi suy doan.

### D-010 - Reproducible release gates

**Decision**

- Them ESLint config phu hop ESLint 8 + TypeScript/React.
- Them CI cho compile, isolated pytest, frontend lint/build, compose config, `pip check`, dependency audit va Alembic head check.
- Pin `gevent` trong dependency manifest thay vi install luc startup.
- Phan tach base/dev/optional audio adapter dependencies hoac bo installed extras khong duoc repo support.
- Xac nhan root Node tree khong duoc runtime dung; neu khong, remove root package/lock va chi giu `frontend/` tree.
- `git rm` tracked runtime dumps; giu sanitized fixtures trong `tests/fixtures/` neu can.

## AI evaluation protocol

| Thanh phan | Quy dinh |
|---|---|
| Target | `LLMManager.analyze_context` va V2 context service |
| Prompt version | Luu version/hash trong output manifest |
| Model config | Model ID, runtime/provider, temperature, max tokens, date |
| Eval data | Synthetic/de-identified Vietnamese benign + suspicious + ambiguous cases |
| Baseline | Current prompt/parser truoc fix |
| Ablation A | Parser fix, prompt giu nguyen |
| Ablation B | Evidence-span + abstention prompt |
| Primary metrics | Schema validity, evidence support, benign false-positive rate |
| Secondary metrics | Entity precision/recall, latency, token/cost neu API |
| Safety gate | High-risk fields disabled neu bat ky release threshold nao fail |

## Open questions khong chan plan

- Retention policy cho 3,605 users/2,160 cases test cu; can user approval truoc cleanup.
- Co can giu dev no-auth mode hay chuyen hoan toan sang normal login.
- LLM provider/model production thuc te nao se dung cho benchmark.
- Untracked Cherry adapters nao se duoc promote vao tracked release surface.

