# Case and Audio Creation Timestamp Design

Date: 2026-08-09

## Objective and scope

Provide creation-time metadata that users can see and sort without allowing the
metadata to influence transcription, summary, analysis, prompts, or model
source metadata.

The persisted scope is deliberately narrow:

- `cases.created_at`: canonical case creation time.
- `audio_files.created_at`: canonical audio upload record time.
- `uploaded_at`: API alias of `audio_files.created_at`; it is not a duplicate DB
  column.

`Task` timestamps, `updated_at`, `processed_at`, transcript content, and model
inputs are outside this migration.

## Current-state evidence

Read-only inspection of the live PostgreSQL database found:

| Surface | Live observation |
| --- | --- |
| Server timezone | `Asia/Bangkok` |
| Alembic version | `b1cbd9b60b5b` |
| `cases.created_at` | `timestamp without time zone`, nullable, default `now()` |
| `audio_files.created_at` | `timestamp without time zone`, nullable, default `now()` |
| Case rows | 2,924; zero null `created_at` |
| Audio rows | 1,673; zero null `created_at` |

The application write paths do not explicitly set either creation field. Both
are produced by the PostgreSQL `now()` default, so the legacy naive values are
interpreted explicitly as `Asia/Bangkok`. The migration does not depend on the
session timezone.

The live revision is behind the repository migration head while the schema has
signs of `init_db`/`create_all` drift. Therefore the migration must be rehearsed
on a disposable clone; it must not be applied directly to the live DB first.

## Storage and API contract

PostgreSQL columns become `timestamp with time zone` (`timestamptz`), `NOT NULL`,
with `CURRENT_TIMESTAMP` defaults. PostgreSQL stores an absolute instant;
session timezone only affects raw presentation.

The API serializer in `src/core/time.py` always converts to UTC and emits an
ISO-8601 value with an explicit `+00:00` offset. A UI may localize this value for
`Asia/Saigon` or the user's browser locale.

Case responses expose:

```json
{
  "created_at": "2026-08-09T03:00:00+00:00"
}
```

Audio responses expose the same instant under both compatible names:

```json
{
  "created_at": "2026-08-09T03:00:00+00:00",
  "uploaded_at": "2026-08-09T03:00:00+00:00"
}
```

No creation timestamp is added to LLM prompts, investigation knowledge,
transcript payloads, or summary/analysis `source_metadata`.

## Query design

The case sidebar filters by `is_archived`, orders by `created_at`, and paginates.
Case files filter by `case_id` and `is_archived`, then order by `created_at`.
Deterministic `id` tie-breakers prevent unstable pagination when timestamps are
equal.

The migration adds:

- `idx_case_archived_created_at (is_archived, created_at, id)`
- `idx_audio_case_archived_created_at (case_id, is_archived, created_at, id)`

Live `EXPLAIN` evidence before migration showed the latest-cases query scanning
about 2,672 active rows plus a top-N sort in about 0.48 ms, while per-case audio
queries already used `idx_audio_case` and sorted a small result. These indexes
are scale-read optimizations for the production query shape, not a claim of a
measurable speedup at the current data size. PostgreSQL can scan the ascending
B-tree backward for the all-descending order.

The case-file API eager-loads the related task once. The timestamp regression
test captures SQL and rejects per-file `FROM tasks` queries.

## Migration protocol

Migration:

`src/database/migrations/versions/e6f7a8b9c2_normalize_case_audio_created_at.py`

Transformation:

```sql
created_at AT TIME ZONE 'Asia/Bangkok'
```

This converts the legacy wall-clock value into the correct absolute instant.
The migration fails closed if either column contains a null. It does not invent
a creation/upload instant from migration time and never uses `updated_at` as a
fallback. The discrepancy must be investigated and repaired from authoritative
evidence before retrying the migration.

Required rollout sequence:

1. Stop application writes or place the service in maintenance mode.
2. Take and verify a PostgreSQL backup.
3. Run the isolated tests below.
4. Run the existing disposable-clone reconciliation harness.
5. Review the clone report, column types, row counts, null counts, and ordering.
6. Apply `alembic upgrade head` to staging and run API smoke tests.
7. Only then schedule the production migration.

Rerunnable validation:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_timestamps.py -q
.\venv\Scripts\python.exe scripts\verify_alembic_reconciliation.py
```

The clone verifier uses `pg_dump`/`pg_restore`, upgrades fresh and cloned
disposable databases, and deletes both in `finally`. It never migrates the
source database.

Verified on 2026-08-09:

- Timestamp harness: `5 passed`.
- Timestamp + runtime performance + security regression set: `32 passed`.
- Fresh disposable DB: revision `e6f7a8b9c2`, 22 public tables.
- Disposable live clone: `b1cbd9b60b5b` / `MATCH_C4` upgraded to
  `e6f7a8b9c2`.
- Source live database revision remained unchanged.

## Completion gates

- Case and audio creation columns are timezone-aware, non-null, and defaulted.
- API creation values parse as UTC ISO-8601 with an explicit offset.
- `uploaded_at` equals `created_at` for every audio response.
- Case file listing has no per-file task query.
- Summary `source_metadata` excludes `created_at`, `uploaded_at`, and
  `updated_at`.
- Fresh and cloned migration rehearsals reach revision `e6f7a8b9c2`.
- The live database remains untouched during development verification.

## Residual risk

- The conversion assumes the audited write path and server timezone are valid
  for all historical case/audio creation rows. No conflicting explicit writer
  was found in the repository, but external/manual SQL writes cannot be proven
  from source code alone.
- A newly discovered null blocks migration because the historical instant cannot
  be reconstructed safely. Preflight null counts must remain a rollout gate.
- The current live Alembic drift must be reconciled on a clone before production.
