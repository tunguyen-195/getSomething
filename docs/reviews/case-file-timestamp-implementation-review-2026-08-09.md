# Case and File Timestamp Implementation Review

Date: 2026-08-09
Scope: creation time of a case and upload time of an audio file only.

## Decision

PASS for the requested timestamp scope.

- `Case.created_at` is the persisted case creation time.
- `AudioFile.created_at` is the single persisted upload time; `uploaded_at` is an API/model alias and does not create a duplicate database column.
- Creation/upload metadata is displayed for users but is excluded from transcript, summary, analysis, and model `source_metadata`.
- Legacy naive values are normalized from `Asia/Bangkok` to timezone-aware UTC by a fail-closed migration.

## Implemented Surface

- Database contract and indexes: `src/database/models/models.py`.
- Migration: `src/database/migrations/versions/e6f7a8b9c2_normalize_case_audio_created_at.py`.
- Canonical UTC serializer: `src/core/time.py`.
- API serialization and batch metadata query: `src/api/endpoints/cases.py`, `src/api/endpoints/audio.py`, `src/api/endpoints/audio_v2.py`.
- UI formatting and rendering: `frontend/src/utils/dateTime.ts`, `frontend/src/components/DateTimeText.tsx`, case sidebar/header, file table/card, and task list.
- Repeatable harness: `tests/test_timestamps.py`.
- Design record: `docs/research/case-file-timestamp-design.md`.

## Live Database Evidence

- Pre-migration backup: `E:\SpeechToInfomation-backups\speech_to_info-before-e6-20260809-013207.dump`.
- Backup size: `1,864,603` bytes.
- Backup SHA-256: `93429D5CBBE8A07BA47AA541F76B5440F535B79C73834907F8B168E1C6AA987B`.
- `pg_restore --list` parsed the archive and reported 311 entries.
- Alembic revision moved from `b1cbd9b60b5b` to `e6f7a8b9c2`.
- Counts remained 2,924 cases and 1,673 audio files; both timestamp columns had zero null values.
- Both columns are `timestamp with time zone`, `NOT NULL`, with `CURRENT_TIMESTAMP` defaults.
- Added indexes: `idx_case_archived_created_at` and `idx_audio_case_archived_created_at`.

## Verification Evidence

- Fresh disposable database migration to `e6f7a8b9c2`: PASS.
- Disposable clone of live data, including legacy revision reconciliation: PASS.
- `python -m compileall src tests -q`: PASS.
- `git diff --check`: PASS.
- `npm run build` in `frontend/`: PASS; Vite reports only the existing large-chunk advisory.
- `pytest tests/test_timestamps.py`: 6 passed.
- Combined timestamp, runtime-performance, security, and database-safety harness: 35 passed.
- Authenticated Playwright snapshot confirmed `Ngay tao` in case sidebar/header and `Tai len` in the file table.
- Local visual evidence: `output/playwright/case-file-timestamps-authenticated-2026-08-09.png`.
- Browser console during the authenticated timestamp check: zero errors and zero warnings.

The screenshot remains a local verification artifact because it contains current case/file labels and should not be published to the remote repository.

## Dependency Reproducibility Finding

The running native API currently uses global Python packages (`fastapi 0.109.1`, `starlette 0.35.1`, `httpx 0.28.1`) while `requirements.txt` declares `fastapi 0.104.1` and `httpx 0.25.1`. The global combination breaks `Starlette TestClient` at collection time. Validation therefore ran in an isolated temporary environment using the repository-declared FastAPI/Starlette/httpx versions. This is an environment drift finding, not a timestamp regression, and must be addressed by the production/offline environment packaging work.

## Residual Risks

- PostgreSQL reports a collation-version mismatch on the maintenance database; timestamp migration/data checks still passed, but database maintenance remains required.
- The frontend bundle is larger than Vite's 500 kB advisory threshold; this is a performance backlog item outside the timestamp scope.
- The native runtime is not dependency-isolated. A locked, offline-reproducible Python environment remains a release gate for production deployment.
