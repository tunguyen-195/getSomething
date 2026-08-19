# Test Data Cleanup Runbook

This runbook separates evidence collection from deletion. The default workflow is read-only.

## 1. Stop new test writes

Do not run pytest until `tests/conftest.py` confirms the target database name ends in `_test`.

## 2. Generate a read-only inventory

```powershell
.\venv\Scripts\python.exe scripts\audit_test_data.py `
  --output artifacts\test-data-audit.json
```

The report contains pattern-matched counts, timestamp ranges and foreign-key relationships. A match is not proof that a record can be deleted.

## 3. Back up and clone

Create a PostgreSQL backup and restore it to a disposable clone. Record:

- backup path or backup-system identifier;
- backup timestamp and hash where available;
- source database name;
- clone database name;
- operator and approval reference.

## 4. Review candidate identity

Compare candidate rows with known production cases, user accounts, audio paths, task results, audit logs and retention requirements. Exclude every ambiguous row.

## 5. Approval checkpoint

`scripts/audit_test_data.py --apply` intentionally exits non-zero. Deletion must be implemented as a separate reviewed change after explicit user approval.

The approved cleanup must:

- default to dry-run;
- require the exact database name and backup identifier;
- delete in foreign-key-safe order inside one transaction;
- print before/after counts;
- abort on any unexpected row count;
- be tested against the clone before the live database.

