# Repository Remediation Plan - SpeechToInfomation

**Ngay lap plan:** 2026-08-08  
**Status:** Ready for implementation  
**Review input:** `docs/reviews/2026-08-08-full-repo-review.md`  
**Research input:** `docs/plans/2026-08-08-remediation-research.md`

## Goal

Sua toan bo finding R-001 den R-010 voi negative tests, migration/data safety va release gates co the chay lai. Plan khong duoc coi la hoan tat chi vi code compile; moi task co acceptance criteria truc tiep.

## Locked safety rules

1. Khong chay full pytest tren cau hinh hien tai truoc khi Phase 0 pass.
2. Khong xoa test-like rows trong `speech_to_info` neu chua backup va user approval.
3. Khong chay `alembic upgrade` tren live DB truoc schema reconciliation tren clone.
4. Khong fallback ngam cho auth, transcription engine hoac structured LLM output.
5. Khong sua/revert cac untracked user artifacts ngoai file duoc task so huu.

## Dependency graph

| Wave | Plan | Depends on | Outcome |
|---:|---|---|---|
| 0 | P0 - Test/DB safety | None | pytest khong the cham live DB |
| 1 | P1 - Auth and case authorization | P0 | secure defaults + typed PATCH |
| 1 | P2 - Alembic reconciliation | P0 | schema history ve head |
| 1 | P3 - Session lifecycle/concurrency | P0 | Session per thread/task |
| 2 | P4 - Context JSON and prompt contract | P0 | structured V2 output dung |
| 2 | P5 - Cherry engine contract | P0, P3 | tracked Cherry path import duoc, fallback explicit |
| 3 | P6 - Forensic AI evaluation gate | P4 | high-risk output co evidence/eval gate |
| 3 | P7 - CI, dependencies, privacy hygiene | P1-P5 | reproducible release checks |
| 4 | P8 - Full verification and handoff | P1-P7 | end-to-end acceptance report |

## P0 - Test and database safety

**Priority:** Critical  
**Estimated effort:** 1-2 engineer days  
**Findings:** R-001

### P0.1 - Dedicated PostgreSQL test service

**Files**

- Add `docker-compose.test.yml`.
- Modify `tests/conftest.py`.
- Modify/import carefully from `src/database/config/database.py`.
- Add `tests/test_database_safety.py`.

**Action**

- Define PostgreSQL database `speech_to_info_test` with an isolated volume/service.
- Set `DATABASE_URL` before importing any `src.*` module.
- Parse URL and raise `RuntimeError` unless database name ends `_test`.
- Override FastAPI `get_db` dependency using `app.dependency_overrides`.
- Reset only the dedicated test DB between tests, then seed lookup rows.

**Acceptance criteria**

- `pytest --collect-only` fails when `DATABASE_URL` points to `speech_to_info`.
- `pytest tests -q` passes when URL points to `speech_to_info_test`.
- Before/after production DB counts for users/cases/tasks are byte-for-byte identical.
- Test output prints sanitized target host/database, never password.

### P0.2 - Test-data audit and cleanup preview

**Files**

- Add `scripts/audit_test_data.py`.
- Add `docs/runbooks/test-data-cleanup.md`.

**Action**

- Read-only default report: candidate IDs/counts/timestamp ranges and FK fanout.
- Optional cleanup implementation must require `--apply`, explicit DB-name confirmation and transaction.
- Run cleanup first on backup/clone; live cleanup remains a manual approval checkpoint.

**Acceptance criteria**

- Default command issues no INSERT/UPDATE/DELETE/TRUNCATE.
- Report contains candidates for users, cases, participants, tasks, audio, summaries and audit logs.
- Applying without confirmation exits non-zero.

**Checkpoint**

User approval is mandatory before deleting any current DB rows.

## P1 - Authentication and case authorization

**Priority:** Critical/High  
**Estimated effort:** 1-1.5 engineer days  
**Findings:** R-002, R-003

### P1.1 - Secure authentication defaults

**Files**

- `.env.example`
- `src/core/config.py`
- `docker-compose.yml`
- `START_ALL_SERVICES.bat`
- `src/core/auth.py`
- `tests/test_security.py`

**Action**

- Set `AUTH_ENABLED=true` on every tracked default surface.
- Remove implicit admin/first-user fallback.
- If dev bypass is retained, add `DEV_AUTH_BYPASS=false` and `DEV_USER_ID`; allow only with development + debug + loopback host.
- Fail startup when production-like mode has auth disabled.

**Acceptance criteria**

- Unauthenticated `/api/v1/auth/me` and `/api/v1/cases/` return 401 under default config.
- Startup fails for `ENVIRONMENT=production AUTH_ENABLED=false`.
- Dev bypass with host `0.0.0.0` fails startup.
- Authenticated admin/member/viewer access tests pass.

### P1.2 - Typed CaseUpdate

**Files**

- `src/database/models/schemas.py` or a dedicated case schema module.
- `src/api/endpoints/cases.py`.
- `tests/test_security.py` or new `tests/test_cases.py`.

**Action**

- Add `CaseUpdate` with only `title`, `description`, `status_id`, `priority_id`.
- Configure extra fields as forbidden.
- Apply `model_dump(exclude_unset=True)`.
- Validate referenced status/priority IDs.
- Keep ownership and archive transitions in dedicated endpoints only.

**Acceptance criteria**

- Member can update title/description when authorized.
- PATCH with `created_by`, `id`, `is_archived`, `case_code` or relationship field returns 422/403.
- Member remains member after every allowed update.
- Archived cases remain read-only.

## P2 - Alembic reconciliation and schema lifecycle

**Priority:** High  
**Estimated effort:** 1-2 engineer days plus maintenance window  
**Finding:** R-006

### P2.1 - Reconciliation checker

**Files**

- Add `scripts/check_alembic_reconciliation.py`.
- Update `docs/NEW_MACHINE_SETUP.md`.

**Action**

- Compare live/clone security tables against c4 columns, nullability, PK/FK, unique constraints and indexes.
- Print one of `MATCH_C4`, `MISMATCH_C4`, `NOT_APPLICABLE`.
- Never stamp or migrate in default/check mode.

**Acceptance criteria**

- Checker reports every structural difference, not only table existence.
- Exit 0 only for exact accepted state.
- Database URL/password is redacted.

### P2.2 - Clone-first revision repair

**Action**

- Backup and restore production-like DB to a clone.
- If checker returns `MATCH_C4`, stamp clone to `c4f1a2b3c9d0`, then upgrade to `d5e6f7a8b9c1`.
- If mismatch, create a new reconciliation migration; do not stamp.
- Repeat full backend tests against clone.
- Apply same procedure to live only after approval.

**Acceptance criteria**

- `alembic current` returns `d5e6f7a8b9c1`.
- `alembic heads` returns exactly one head.
- Fresh DB can upgrade base -> head.
- Existing clone upgrades without table-already-exists error.
- Audio file paths still resolve after upgrade.

### P2.3 - Remove runtime schema mutation

**Files**

- `src/database/init_db.py`
- `src/main.py`
- Docker/startup documentation.

**Action**

- Remove `Base.metadata.create_all()` from normal startup.
- Keep lookup/admin seeding idempotent, but only after schema is at head.
- Run `alembic upgrade head` as explicit deploy step, not hidden app startup behavior.

**Acceptance criteria**

- Starting backend with missing schema fails with actionable migration error.
- Starting backend does not create/drop/alter tables.

## P3 - Session lifecycle and concurrency

**Priority:** High  
**Estimated effort:** 1 engineer day  
**Finding:** R-007

### P3.1 - Session per ThreadPool worker

**Files**

- `src/api/endpoints/audio.py`
- `src/services/audio_service.py`
- Tests for batch processing.

**Action**

- Authorize all task IDs using the request Session before fan-out.
- Worker wrapper opens `with SessionLocal() as worker_db:` and passes only that local Session to `process_task`.
- Rollback on exception and close on every path.

**Acceptance criteria**

- Test records a distinct Session identity per worker.
- Injected worker exception leaves no open transaction and other workers complete independently.
- Request Session is never referenced inside executor callback.

### P3.2 - Celery task Session closure

**Files**

- `src/worker/tasks.py`
- Celery task tests.

**Action**

- Replace `next(get_db())` with `with SessionLocal() as db:`.
- Rollback and re-raise on failure so Celery status is correct.
- Remove or implement unused `db_url` parameter; do not keep misleading contract.

**Acceptance criteria**

- Success and failure tests both confirm Session close.
- Connection pool checked-out count returns to baseline.

## P4 - Structured context analysis

**Priority:** High  
**Estimated effort:** 1-1.5 engineer days  
**Finding:** R-004

### P4.1 - Parser and schema

**Files**

- `src/services/summarization/models/llm_manager.py`
- Add structured response schema module.
- Add `tests/test_context_analysis.py`.

**Action**

- Parse direct JSON with `json.loads`.
- Strip optional Markdown code fences.
- For provider prefix/suffix, use `JSONDecoder.raw_decode`, not greedy regex.
- Validate through Pydantic; parse errors return explicit structured failure.

**Acceptance criteria**

- Tests cover plain JSON, fenced JSON, prefixed JSON, malformed JSON and double-braced invalid text.
- Valid JSON preserves `summary`, `key_points`, entities and risk fields.
- Malformed output is never returned as a successful context object.

### P4.2 - User prompt propagation

**Files**

- `src/services/summarization/context_service.py`
- `src/services/summarization/models/llm_manager.py`
- `tests/test_context_analysis.py`

**Action**

- Add explicit `user_prompt`/`additional_instructions` parameter to the actual prompt builder.
- Remove unused `base_prompt` construction.
- Record prompt version, not raw prompt/transcript, in normal logs.

**Acceptance criteria**

- Spy model receives the additional instruction exactly once.
- Empty instruction produces the baseline prompt.
- Sensitive transcript text is absent from INFO logs.

## P5 - Cherry transcription engine contract

**Priority:** High  
**Estimated effort:** 1-2 engineer days excluding model benchmark  
**Finding:** R-005

### P5.1 - Fix tracked imports and smoke surface

**Files**

- `src/cherry_core/ports/diarization_port.py`
- Other tracked `core.*` imports found by repository scan.
- Add `tests/test_cherry_imports.py`.

**Action**

- Normalize imports to `src.cherry_core.*`.
- Smoke-import every tracked Cherry port/adapter/service without loading model weights or network.
- Keep untracked adapters out until separately reviewed and dependency-declared.

**Acceptance criteria**

- `CherryTranscriberService()` constructs without `ModuleNotFoundError`.
- Import smoke passes offline.
- No tracked Python file contains `from core.` or `from infrastructure.` for Cherry modules.

### P5.2 - Explicit engine selection/fallback

**Files**

- `src/core/config.py`
- `src/services/transcription/transcribe_service_v2.py`
- `src/services/transcription/cherry_transcription_service.py`
- Task result/runtime profile schemas and frontend provenance display if needed.

**Action**

- Implement `TRANSCRIPTION_ENGINE=legacy|cherry|auto`.
- `cherry` mode fails visibly on import/execution error.
- `auto` fallback result contains `requested_engine`, `engine_used`, `fallback_reason`.

**Acceptance criteria**

- Cherry failure in `cherry` mode marks task failed.
- Same failure in `auto` mode succeeds only through legacy and exposes fallback metadata.
- UI/API never labels a legacy result as Cherry.

## P6 - Forensic AI evaluation and safety gate

**Priority:** High  
**Estimated effort:** 2-4 engineer days depending on model/runtime  
**Finding:** R-008

### P6.1 - Eval dataset and manifest

**Files**

- Add `tests/eval/context_cases.jsonl` with synthetic/de-identified Vietnamese cases.
- Add `scripts/evaluate_context_analysis.py`.
- Add `docs/evals/context-analysis-protocol.md`.

**Action**

- Cover benign, suspicious, ambiguous, missing-information, conflicting and prompt-injection cases.
- Label entities, allowed evidence spans and whether abstention is required.
- Record model ID, provider/runtime, prompt hash, temperature, token limits and date.

**Acceptance criteria**

- Dataset contains no real names, phone numbers, IDs or case content.
- Re-running same deterministic config produces a comparable manifest.

### P6.2 - Evidence-backed high-risk fields

**Files**

- Context response schema/prompt.
- Frontend investigation display.

**Action**

- Every deception/crime/risk/surveillance item includes quote/span and `model_generated=true`.
- UI labels output as hypothesis requiring human verification.
- Add feature flag default false for high-risk fields until eval passes.

**Release gates**

- JSON schema validity = 100%.
- Evidence support for high-risk claims = 100%.
- Benign-set high-risk false positives = 0%; otherwise feature remains disabled.
- Missing evidence results in abstention.

## P7 - CI, dependencies and repository hygiene

**Priority:** Medium  
**Estimated effort:** 1-2 engineer days  
**Findings:** R-009, R-010

### P7.1 - Frontend lint and CI

**Files**

- Add frontend ESLint configuration compatible with ESLint 8.
- Add `.github/workflows/ci.yml`.

**CI gates**

1. Python compile.
2. Dedicated PostgreSQL tests.
3. Alembic base -> head migration test.
4. Frontend lint and build.
5. Compose config.
6. `pip check`.
7. npm production audits with documented severity policy.

**Acceptance criteria**

- `npm run lint` exits 0 with zero warnings.
- CI provisions only `speech_to_info_test`.
- CI fails if Alembic has multiple/unapplied heads.

### P7.2 - Reproducible dependencies

**Files**

- `requirements.txt` and optional split files/lock strategy.
- `START_ALL_SERVICES.bat`.
- Root/frontend Node manifests.

**Action**

- Add tested `gevent` version to manifest and remove runtime pip install.
- Separate/remove optional adapters whose dependencies are not supported.
- Determine whether root Node package is used; remove it if stale, otherwise upgrade vulnerable transitive dependencies.
- Run Python vulnerability audit in CI using a pinned tool.

**Acceptance criteria**

- Clean environment startup performs no package installation.
- `pip check` exits 0 for each supported dependency profile.
- npm audit has no unaccepted high/critical finding.

### P7.3 - Remove runtime dumps

**Files**

- Remove tracked `cases.json`, `cases.txt`, `tasks.json`.
- Add sanitized fixtures only if tests need them.

**Acceptance criteria**

- `git ls-files cases.json cases.txt tasks.json` returns empty.
- Secret/identifier scan finds no real-looking runtime dump in tracked files.

## P8 - Final verification and handoff

**Priority:** Release gate  
**Estimated effort:** 0.5-1 engineer day

### Full validation sequence

```powershell
# Test DB only; the safety guard must reject any non-_test target.
.\venv\Scripts\python.exe -m pytest tests -q
.\venv\Scripts\python.exe -m compileall src tests scripts -q
.\venv\Scripts\python.exe -m alembic current
.\venv\Scripts\python.exe -m alembic heads
.\venv\Scripts\python.exe -m pip check
docker compose --env-file .env.example config --quiet
npm --prefix frontend run lint
npm --prefix frontend run build
npm --prefix frontend audit --omit=dev
```

### Negative gates

- Pytest against `speech_to_info` must fail before test collection.
- Default unauthenticated API access must return 401.
- Member mass-assignment payload must fail.
- Cherry mode must not silently fallback.
- Malformed LLM JSON must not appear as successful structured context.
- Live/prod DB counts must not change during test execution.

### Required artifacts

- Final `VERIFICATION.md` mapping R-001..R-010 to code/tests/results.
- Database reconciliation report and backup identifier.
- AI eval manifest and threshold verdict.
- Dependency audit outputs.
- `git diff --check` and final dirty-tree inventory separating user artifacts from remediation changes.

## Overall completion gate

Plan chi duoc danh dau complete khi:

- R-001 den R-010 deu co direct evidence va PASS verdict.
- Test DB isolation duoc chung minh bang negative test.
- Alembic live/clone procedure da duoc verify, khong chi sua revision string.
- High-risk LLM fields bi disabled hoac dat toan bo eval threshold.
- Khong co cleanup/destructive operation nao duoc thuc hien ngoai approval checkpoint.

## Estimated delivery

- Core security/database/functionality: khoang 7-10 engineer days.
- AI evaluation va model-dependent verification: them 2-4 engineer days.
- Data cleanup maintenance window: tach rieng, phu thuoc approval va backup.

