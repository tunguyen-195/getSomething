# Release Inventory Audit

## Purpose

Use this read-only harness before staging a release. It compares three distinct
states:

- `HEAD`: the last commit;
- `index`: the exact staged tree that a commit would contain;
- `workspace`: tracked files as currently edited plus visible untracked files.

The audit detects tracked source that depends on untracked local modules, an
index whose local imports do not close, partially staged paths, untracked files
that require a release disposition, prohibited staged classes, and secret-like
filenames. It never reads `.env` or other files classified as sensitive.
Untracked generated/sensitive filenames are reported only as aggregate counts;
their path samples are redacted from durable JSON evidence.

## Canonical command

```powershell
.\venv\Scripts\python.exe scripts\audit_release_inventory.py `
  --output docs\reviews\artifacts\2026-08-14-release-inventory.json
```

Exit code `0` means the inventory gates pass. Exit code `2` means at least one
release blocker remains. Use `--no-fail` only to capture a blocked evidence
artifact; it does not make the tree releasable.

## Review order

1. Review `blockers` and the verdict.
2. Resolve `dependencies.workspace_tracked.missing_local_dependencies`.
3. Resolve index closure errors in `dependencies.index`.
4. Review both versions of every `partial_staged_paths` entry.
5. Assign an owner and disposition to every untracked release-relevant path.
6. Review secret filename risks without opening sensitive contents.
7. Review the exact index tree and approve an explicit staging manifest.

Never use `git add .` for this workspace. The harness does not authorize
staging, committing, pushing, or deleting any path.

## Candidate rehearsal

Export a candidate with a temporary index and temporary Git object database:

```powershell
.\venv\Scripts\python.exe scripts\rehearse_release_candidate.py `
  --export-root E:\research\STT-release-candidate-YYYYMMDD `
  --output docs\reviews\artifacts\release-candidate-rehearsal.json
```

The export directory must be empty. The report records the candidate tree and
proves the real index fingerprint is unchanged. Paths classified as generated
or sensitive are excluded from the candidate and redacted from the JSON; only
aggregate class counts are retained. Treat the candidate as provisional until
the current Summary/Analysis source is locked and every clean-install gate has
been rerun from a freshly exported tree.

The rehearsal also scans candidate UTF-8 text for private-key blocks, known
provider-token formats, high-entropy credential assignments, investigation
record identifiers, and structured transcript payloads. Findings record only
rule, severity, candidate path and line; matched values are never stored. Exit
code `2` means the content scan found a release-blocking risk. A clean scan is
still not a substitute for a dedicated secret-history scanner or human privacy
review of curated evidence.

`candidate_manifest.entries` is the exact per-file candidate allowlist. The
temporary index starts empty and only force-adds policy-selected paths, so
ignored files cannot silently disappear and historical tracked files cannot
silently enter the candidate. Each
entry records its tracked/untracked origin, release class, suggested disposition
and selection reason. Runtime, tests, canonical startup/config/docs, explicit
build assets and the documented v1 worker compatibility module are selected;
research documents, curated evidence, obsolete launchers and unclassified
utilities are excluded by default. Do not replace this manifest with `git add .`.
Script paths referenced by `README.md`, `docs/NEW_MACHINE_SETUP.md`, or selected
runbooks are discovered from their content and included even when their filename
does not match a startup heuristic. A missing referenced script blocks the CLI.
The harness then computes transitive local Python/frontend import closure from
the selected runtime, tests and scripts. Added helpers and their source edges are
recorded under `selection.dependency_closure`; parse errors block the CLI.
`candidate.workspace_content_fingerprint_sha256` binds the selected path list to
the current workspace bytes. Recompute a candidate after source lock; evidence
from an older fingerprint is stale even when its tests previously passed.

## Backend release-test profile

The machine-readable source gate is
`config/release/backend-source-test-profile.v1.json`. Its default is fail-safe:
every collected backend test is release-blocking unless an exact node ID is
listed under `selection.non_release_tests`. The only allowed exclusions are
historical/research evidence, operator-acquired external artifacts, and a
documented non-canonical legacy surface. Summary/Analysis behavior, replay
wrapper, timestamp, import, API, worker, database, and security regressions stay
in the release-blocking set.

Run the verifier from the source workspace after source lock. It resolves the
candidate export from the rehearsal report (or `--candidate-root`) and executes
pytest inside that candidate:

```powershell
venv\Scripts\python.exe scripts\verify_release_test_profile.py `
  --candidate-report E:\research\STT\docs\reviews\artifacts\release-candidate-rehearsal.json `
  --python venv\Scripts\python.exe `
  --execute `
  --output output\audits\backend-release-tests.json
```

Before invoking pytest, the verifier recomputes the candidate workspace-content
fingerprint against both the still-current source workspace and the exported
candidate bytes. This detects source edits after export as well as an incomplete
or modified candidate materialization. It also verifies manifest and privacy
verdicts, rejects missing documented scripts or dependency parse failures,
recomputes the current policy-selected release paths plus local dependency
closure, detects any path absent from the candidate manifest, collects all test
node IDs, and rejects a stale or misspelled exclusion. It also rejects files
inserted into the candidate after export. Dependency/cache trees such as
`venv/`, `node_modules/` and pytest caches are ignored; sensitive extra paths are
blocked and counted without serializing their filenames. The JSON stores hashes
and counts, not test output or matched source content. A passing backend source
profile is not an overall release verdict: the separately declared historical
evidence and external-model gates, frontend, Docker, migrations, security,
preflight, and real Summary/Analysis replay remain mandatory.

The pytest interpreter must be a file inside the candidate root. The default is
the candidate's `venv\Scripts\python.exe` on Windows. A workspace-global or
source-workspace venv is rejected so clean-clone success cannot inherit packages
from the development checkout.

## Validation

```powershell
.\venv\Scripts\python.exe -m py_compile scripts\audit_release_inventory.py
.\venv\Scripts\python.exe -m pytest tests\test_release_inventory_harness.py -q
.\venv\Scripts\python.exe -m pytest tests\test_release_candidate_rehearsal.py -q
.\venv\Scripts\python.exe -m pytest tests\test_release_test_profile.py -q
git diff --check -- scripts\audit_release_inventory.py `
  scripts\rehearse_release_candidate.py `
  scripts\verify_release_test_profile.py `
  tests\test_release_inventory_harness.py `
  tests\test_release_candidate_rehearsal.py `
  tests\test_release_test_profile.py `
  config\release\backend-source-test-profile.v1.json `
  docs\runbooks\release-inventory-audit.md
```

An inventory PASS is necessary but not sufficient. Final release verification
must export or clone the exact index-derived tree into an isolated directory,
install dependencies from the declared manifests, and run backend imports,
worker registration, migrations, frontend tests/build, startup preflight, and
the supported end-to-end smoke flow without copying local workspace files.
