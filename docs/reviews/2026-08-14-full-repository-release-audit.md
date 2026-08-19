# Full Repository Release Audit

Date: 2026-08-14  
Repository: `E:\research\STT`  
Branch observed: `feature/architecture-refactor`  
Revision observed: `060f3d7a fix(summary): harden bounded recovery replay`  
Mode: read-only source/config audit; this document is the only audit output

## 1. Objective and release verdict

This audit tests the falsifiable claim that the current product can be committed,
pushed, cloned on another Windows machine, installed from repository artifacts,
and run through the active audio-to-investigation workflow.

Current verdict: **BLOCKED FOR PUSH AS A REPRODUCIBLE RELEASE**.

The local workspace passes selected backend and frontend gates, but tracked
runtime files import release-critical files that are still untracked. The
canonical new-machine instructions also call untracked installer, preflight,
runtime, and manifest assets. A commit made from the current index or from only
the already tracked modifications would therefore not reproduce the working
local application.

This is a release-packaging and source-of-truth failure, not evidence that every
local implementation is incorrect. The immediate goal is to make the exact
tested runtime closure explicit and reproducible before refactoring further.

## 2. Scope and trust boundaries

Reviewed surfaces:

- FastAPI startup, middleware, routers, uploads, task APIs, analysis and
  visualization endpoints.
- SQLAlchemy models/session creation, Alembic chain, schema bootstrap and seed.
- Celery application, legacy and modular tasks, transcription, summary, analysis,
  visualization, GPU lease and model runtime imports.
- React/Vite entrypoint, API client, investigation panels and build/test config.
- Python/npm dependencies, Dockerfiles, Compose, Windows launchers and canonical
  new-machine runbook.
- Git tracked, staged, unstaged, untracked and ignored boundaries without reading
  secret values from `.env`.

Primary trust boundaries are HTTP input and cookies, uploaded audio, database
records, Celery messages, environment configuration, model/runtime artifacts,
and LLM output rendered by the frontend.

## 3. Runtime inventory

### Active application path

```text
frontend/src/main.tsx
  -> frontend/src/App.tsx
  -> frontend/src/api/client.ts
  -> /api/v1
  -> src/main.py
  -> src/api/router.py
  -> v1 audio/tasks/cases/summaries + v2 audio workflow
  -> PostgreSQL task/audio/case records
  -> Celery src.worker.worker
  -> transcribe / summarize / visualize tasks
  -> local ASR + llama-server/Ollama adapters
```

FastAPI mounts both generations of API at the same time: v1 routers are included
at `src/api/router.py:9` through `src/api/router.py:14`, while the modular v2
workflow is included at `src/api/router.py:16` and `src/api/router.py:17`.

Celery also loads both generations. The package initializer dynamically loads
the legacy `src/worker/tasks.py` at `src/worker/tasks/__init__.py:10` through
`src/worker/tasks/__init__.py:16`, while the worker imports modular tasks at
`src/worker/worker.py:67` through `src/worker/worker.py:71`.

### Duplicate and legacy surfaces still tracked

- `frontend/src/App_v2.tsx`
- `frontend/src/components/FileCard_old.tsx`
- `frontend/src/components/FileCard_backup.tsx`
- `src/speech_to_text/transcriber.py.backup`
- `src/web_interface/app.py`
- `src/services/summary_service.py` plus `src/services/summarization/`
- `src/services/transcribe_service.py` plus `src/services/transcription/`
- `src/worker/tasks.py` plus `src/worker/tasks/`
- `START_PROJECT.bat.backup`

These paths are not automatically defects, but they enlarge the release and test
surface and allow behavior to diverge silently. The legacy v1 resummarization
endpoint still executes `ollama list` and selects `gemma2:9b` at
`src/api/endpoints/audio.py:878` through `src/api/endpoints/audio.py:885`, which
conflicts with the documented pinned llama-server product path.

## 4. Findings

### RA-001 - Tracked backend and worker import untracked runtime modules

- Severity: **P0 / Critical release blocker**
- Type: correctness, packaging, clean-clone portability
- Status: open

Evidence:

- `src/worker/worker.py:13` and `src/worker/worker.py:70` require the untracked
  `src/worker/tasks/runtime_contract_task.py`.
- `src/worker/tasks/summarize_task.py:11` requires untracked
  `src/services/model_runtime/gpu_lease.py`.
- `src/worker/tasks/summarize_task.py:24` requires untracked
  `src/services/summarization/investigation_scenarios.py`.
- `src/api/endpoints/summary.py:13` and `src/api/endpoints/summary.py:20` require
  untracked investigation preview and model-runtime modules.
- `src/api/endpoints/audio.py:52`, `src/api/endpoints/audio.py:56`,
  `src/api/endpoints/audio_v2.py:26`, `src/api/endpoints/audio_v2.py:30`, and
  `src/api/endpoints/audio_v2.py:35` require untracked preview, scenario and
  public-projection modules.
- `src/services/summarization/summary_service_v2.py:13`,
  `src/services/summarization/summary_service_v2.py:38`, and
  `src/services/summarization/summary_service_v2.py:45` require untracked runtime
  modules.
- `src/services/transcription/transcribe_service_v2.py:18` requires the untracked
  model-runtime package.

Impact: local import and tests succeed only because the missing Git objects exist
in this working directory. A clean clone of the committed tree can fail during
FastAPI import, Celery registration, transcription or summarization.

Reproduction gate:

```powershell
git ls-files --error-unmatch src/services/model_runtime/__init__.py
git ls-files --error-unmatch src/worker/tasks/runtime_contract_task.py
git ls-files --error-unmatch src/services/summarization/investigation_scenarios.py
```

Each command currently fails even though tracked runtime code imports the file.

Required remediation: generate a release file manifest, classify every imported
local module, add the complete intended runtime closure deliberately, then test
from a clean index-derived clone. Do not solve this with a broad `git add .`.

### RA-002 - Tracked frontend imports untracked utilities

- Severity: **P0 / Critical release blocker**
- Type: frontend build, packaging, clean-clone portability
- Status: open

Evidence:

- `frontend/src/App.tsx:25` imports untracked `utils/transcriptText.ts`.
- `frontend/src/App.tsx:26` imports untracked `utils/summaryDisplay.ts`.
- `frontend/src/components/AnalysisPanel.tsx:34` and
  `frontend/src/components/AnalysisPanel.tsx:35` import untracked summary and
  analysis utilities.
- `frontend/src/components/VisualizationDialog.tsx:31` imports untracked
  `utils/investigationAnalysis.ts`.

Impact: `npm run build` passes in the local workspace but is not evidence that the
committed tree builds. A clone without these files fails TypeScript/Vite module
resolution.

Reproduction gate:

```powershell
git ls-files --error-unmatch frontend/src/utils/transcriptText.ts
git ls-files --error-unmatch frontend/src/utils/summaryDisplay.ts
git ls-files --error-unmatch frontend/src/utils/investigationAnalysis.ts
```

Required remediation: add the product utilities and their intended tests to the
release manifest, or remove the imports and feature wiring. Run `npm ci`, tests,
and production build in an index-derived clean clone.

### RA-003 - Canonical clean-machine runbook calls untracked assets

- Severity: **P0 / Critical release blocker**
- Type: onboarding, artifact acquisition, model/runtime identity
- Status: open

Evidence:

- `README.md:17` calls untracked `scripts/install_local_llm_staging.ps1`.
- `README.md:20` calls untracked `scripts/preflight_new_machine.ps1`.
- `README.md:28` calls untracked `scripts/install_audio_models_staging.py`.
- `docs/NEW_MACHINE_SETUP.md:245` calls the same untracked preflight.
- `docs/NEW_MACHINE_SETUP.md:277` calls untracked
  `scripts/start_llama_server.ps1`.
- The required `config/models/`, `config/runtimes/`, and `config/release/`
  manifests exist locally but are untracked.

Impact: another machine following the declared canonical path cannot acquire or
verify the pinned LLM, ASR and diarization artifacts from Git. The product can be
working locally while the published instructions are unusable.

Required remediation: treat installer scripts, model/runtime manifests, verifier,
license/terms documentation and preflight tests as first-class release assets.
Run the runbook from a clean clone with no undeclared files inherited from this
workspace.

### RA-004 - Dirty tree is too large and partially staged for a safe release

- Severity: **P1 / High**
- Type: change ownership, commit integrity, generated artifact contamination
- Status: open

Observed inventory at audit time:

- 393 tracked files.
- 77 files with unstaged changes.
- 9 files with staged changes.
- 41,050 untracked files.
- 164 untracked release-relevant source/config/test/doc files.
- 40,820 untracked generated or working artifacts dominated by
  `.playwright-cli`, `.planning`, and `output`.
- 8 paths are partially staged (`MM`), including LLM/context implementation and
  tests.

Impact: broad staging can accidentally commit browser state, experiments, real
replay artifacts, or stale reports. Partial staging can also publish a code/test
combination that was never executed together.

Required remediation: create a path-by-path manifest with owner and disposition;
review both index and worktree versions of every `MM` path; use explicit path
lists for staging; verify the exact staged tree independently.

### RA-005 - Python dependency declaration is incomplete and current environment is inconsistent

- Severity: **P1 / High**
- Type: dependency resolution, portability, Docker parity
- Status: open

Evidence:

- The canonical runbook admits that packages are loose or absent from
  `requirements.txt` at `docs/NEW_MACHINE_SETUP.md:87` and installs additional
  packages at `docs/NEW_MACHINE_SETUP.md:91` through
  `docs/NEW_MACHINE_SETUP.md:100`.
- Source imports include `pyannote`, `huggingface_hub`, `requests`, `jinja2`,
  `yaml`, `sklearn`, `speechbrain`, `resemblyzer`, and `llama_cpp`, not all of
  which have a complete pinned repository declaration.
- `Dockerfile.backend:23` through `Dockerfile.backend:28` installs only the two
  requirements files and therefore does not reproduce the documented manual
  install sequence.
- `pip check` currently reports missing requirements for Resemblyzer and
  simple-diarizer: `typing`, `webrtcvad`, and `ipython`.
- The documented clean-machine path uses Python 3.11 at
  `docs/NEW_MACHINE_SETUP.md:79`, but `Dockerfile.backend:11` installs Python 3.10.

Impact: clean installs and containers can resolve different package graphs or
fail at import/runtime. Local success depends on an environment that is not fully
described by Git.

Required remediation: choose supported runtime profiles, pin a resolver-complete
lock/constraints surface per profile, make Docker and Windows use the same Python
minor and critical package versions, and require `pip check` to pass after a fresh
install.

### RA-006 - Docker and launcher paths do not represent the product runtime

- Severity: **P1 / High**
- Type: startup reliability, deployment configuration
- Status: open

Evidence:

- `Dockerfile.backend:40` starts Uvicorn with `--reload`.
- Compose bind-mounts the whole checkout into backend and worker at
  `docker-compose.yml:8` through `docker-compose.yml:12` and
  `docker-compose.yml:75` through `docker-compose.yml:79`.
- Compose defaults to development/debug/schema seeding at
  `docker-compose.yml:16` through `docker-compose.yml:22`.
- Compose has no llama-server service and `.dockerignore:23` excludes models.
- The repository explicitly states that Compose is not a substitute for artifact
  acquisition/preflight at `README.md:35` through `README.md:37`.
- `entrypoint.bat` starts Celery, FastAPI and frontend, but not PostgreSQL, Redis
  or llama-server.
- `docs/NEW_MACHINE_SETUP.md:263` through `docs/NEW_MACHINE_SETUP.md:272` defines a
  different mandatory order and warns against `START_ALL_SERVICES.bat`.

Impact: there is no single launcher whose behavior matches the verified product
contract. Users can start a superficially healthy UI/backend while analysis or
summary fails because the pinned LLM runtime is absent.

Required remediation: name exactly one development launcher and one staging
launcher, make each run a preflight, use fail-fast dependency health checks, and
label Docker explicitly as development-only until it includes or securely binds
the verified model/runtime artifacts.

### RA-007 - Frontend API environment contract is dead or misnamed

- Severity: **P1 / High**
- Type: deployment configuration, frontend portability
- Status: open

Evidence:

- `docker-compose.yml:51` assigns `VITE_API_URL` from `FRONTEND_URL`.
- `.env.example:34` defines `FRONTEND_URL` as the frontend origin.
- `frontend/src/api/client.ts:37` ignores `VITE_API_URL` and uses only
  `window.API_BASE_URL` or a relative URL.

Impact: Compose/Nginx relative proxying masks the problem locally, but operators
cannot reliably configure an external backend using the documented environment
surface. The same variable name represents incompatible concepts.

Required remediation: define separate public frontend origin and API base URL
contracts, consume one canonical API setting at build/runtime, and test same-origin
proxy plus split-origin deployment.

### RA-008 - Legacy paths can bypass the pinned LLM product contract

- Severity: **P1 / High**
- Type: correctness, model provenance, duplicated architecture
- Status: open

Evidence:

- Both v1 and v2 API surfaces remain mounted at `src/api/router.py:9` through
  `src/api/router.py:17`.
- Both legacy and modular Celery tasks are loaded at
  `src/worker/tasks/__init__.py:10` through `src/worker/tasks/__init__.py:16` and
  `src/worker/worker.py:64` through `src/worker/worker.py:71`.
- The v1 resummarize path probes local Ollama and selects `gemma2:9b` at
  `src/api/endpoints/audio.py:878` through `src/api/endpoints/audio.py:885`.
- The declared staged product path is Qwen3 through pinned llama-server at
  `README.md:12` through `README.md:18`.

Impact: the same user action through different UI/API paths can use different
models, prompt stacks, task semantics and persistence shapes. This weakens replay,
supportability and investigation provenance.

Required remediation: map every frontend action to one backend endpoint and
worker task; either remove legacy routes from the release or place them behind an
explicit compatibility profile with contract tests and truthful model metadata.

### RA-009 - Production offline bundle remains intentionally blocked

- Severity: **P1 / High release limitation**
- Type: offline deployment, artifact completeness
- Status: acknowledged but unresolved

Evidence: `README.md:39` through `README.md:44` states that the clone-only offline
bundle is blocked because runtime/cache/artifact components are absent and the
verifier must return `release_ready=false`.

Impact: the project must not be advertised or tagged as a portable production
offline release yet. An online staging installer is not a production substitute.

Required remediation: close runtime, Python wheelhouse, Node runtime/cache,
FFmpeg, database/queue, ASR/diarization/LLM artifact, checksum, license and
network-denied verification requirements before changing this verdict.

### RA-010 - Validation error details and frontend source maps need release policy

- Severity: **P2 / Medium**
- Type: information disclosure, deployment hardening
- Status: open

Evidence:

- `src/main.py:50` through `src/main.py:55` returns `str(exc)` for request
  validation errors.
- `frontend/vite.config.ts:24` enables production source maps.
- `frontend/nginx.conf` sets basic legacy headers but has no explicit CSP, HSTS,
  Referrer-Policy or Permissions-Policy.

Impact: detailed schema information and source structure can be exposed in a
production deployment. This is not the current P0 cause, but it should be decided
before an operational release.

Required remediation: return a stable validation envelope, retain detailed
diagnostics only in protected logs, decide whether source maps are private
artifacts, and define proxy/TLS/security-header ownership.

### RA-011 - Frontend build is large and ships duplicate configuration surfaces

- Severity: **P2 / Medium**
- Type: performance, maintainability
- Status: open

Evidence:

- Production build emits a roughly 714 kB minified JavaScript chunk and Vite
  warns about chunks larger than 500 kB.
- Both `frontend/vite.config.ts` and generated-looking
  `frontend/vite.config.js` are tracked.
- `frontend/Dockerfile:11` runs `npm install` even though the canonical runbook
  requires reproducible `npm ci` at `docs/NEW_MACHINE_SETUP.md:140` through
  `docs/NEW_MACHINE_SETUP.md:146`.

Required remediation: keep one authored Vite config, use `npm ci` in the image,
add lazy loading/manual chunks for heavyweight visualization surfaces, and record
a bundle-size budget.

## 5. Positive controls observed

The audit did not identify a high-confidence unauthenticated P0 vulnerability in
the reviewed active path. Existing controls include:

- `.env` is ignored by `.gitignore:46`; its values were not read during audit.
- Production/auth-enabled startup rejects weak secrets and insecure cookies in
  `src/core/config.py:151` through `src/core/config.py:201`.
- Authentication uses JWT session identifiers backed by database session state,
  CSRF checks, bcrypt passwords and Redis rate limiting in `src/core/auth.py`.
- Case, audio and task authorization helpers exist at
  `src/core/auth.py:274` through `src/core/auth.py:358` and are applied broadly by
  API endpoints.
- Upload handling validates filename boundaries, extension, maximum size,
  ffprobe audio content and storage-root containment in
  `src/services/audio_storage.py:48` through `src/services/audio_storage.py:215`.
- The public filename audio endpoint is disabled at
  `src/api/endpoints/audio.py:1115` through `src/api/endpoints/audio.py:1117`.
- Alembic has one linear head and the current database is at that head.
- Normal application startup seeds lookup/admin data but does not call
  `create_all` unless explicitly requested at `src/database/init_db.py:31`
  through `src/database/init_db.py:34`.

These controls reduce immediate security risk but do not resolve clean-clone or
release reproducibility.

## 6. Executed gates and evidence

All commands below ran against the current dirty workspace, so passing results
must not be interpreted as clean-clone proof.

| Gate | Result | Important evidence |
| --- | --- | --- |
| `git diff --check` and cached equivalent | PASS with CRLF warnings | No whitespace error; line-ending normalization remains noisy. |
| `venv\Scripts\python.exe -m compileall src tests -q` | PASS | Current local source closure imports syntactically. |
| Selected backend release/security/onboarding/visualization suite | 73 PASS | `tests/test_security.py`, startup profile, new-machine onboarding, offline bundle, visualization and analysis projection. |
| `npm test` in `frontend` | 36 PASS | Analysis, summary, navigation and visualization contracts pass locally. |
| `npm run build` in `frontend` | PASS with size warning | Production build succeeds only because untracked frontend utilities exist. |
| `venv\Scripts\python.exe -m alembic heads` | `e6f7a8b9c2` | Exactly one repository head. |
| `venv\Scripts\python.exe -m alembic current` | `e6f7a8b9c2` | Current local database is at head. |
| `venv\Scripts\python.exe -m pip check` | FAIL | Missing Resemblyzer/simple-diarizer requirements. |

Selected backend command:

```powershell
venv\Scripts\python.exe -m pytest `
  tests/test_security.py `
  tests/test_startup_runtime_profile.py `
  tests/test_new_machine_onboarding.py `
  tests/test_offline_release_bundle.py `
  tests/test_investigation_visualization.py `
  tests/test_investigation_analysis_projection.py -q
```

## 7. Release-manifest classification strategy

Every changed or untracked path must receive one disposition before staging.
The manifest should be machine-readable, but a reviewed table is the authority.

| Class | Meaning | Default action | Examples |
| --- | --- | --- | --- |
| `RUNTIME_REQUIRED` | Imported or executed by active product path | Track and test in clean clone | `src/services/model_runtime/`, analysis projection, frontend utilities |
| `STARTUP_REQUIRED` | Installer, preflight, launcher, migration or health probe | Track with rerunnable smoke | staging installers, runtime verifier, Alembic scripts |
| `CONFIG_MANIFEST` | Version/hash/schema/license binding for runtime artifacts | Track; prohibit secrets and machine paths | `config/models/`, `config/runtimes/`, `config/release/` |
| `TEST_REQUIRED` | Protects active runtime and release contract | Track and map to requirement | new-machine, model-runtime, analysis/visualization tests |
| `DOC_REQUIRED` | Canonical setup, operations, threat/release boundary | Track after command validation | `README.md`, `docs/NEW_MACHINE_SETUP.md`, runbooks |
| `EVIDENCE_CURATED` | Small de-identified reproducibility artifact | Track only with provenance, privacy and size review | selected eval JSON and hashes |
| `LEGACY_COMPAT` | Intentionally supported older path | Track only with owner, sunset and tests | v1 routes/tasks, old summary/transcribe service |
| `LEGACY_REMOVE` | Backup or duplicate not part of release | Remove in an explicit reviewed change | old/backup UI and Python files |
| `GENERATED_LOCAL` | Rebuildable local output/cache | Ignore; never stage | `.playwright-cli`, `.planning`, `frontend/dist` |
| `SENSITIVE_LOCAL` | Case data, transcript/audio, token, credential or raw model response | Ignore, scan history, define retention | `.env`, uploads, storage, raw replay output |
| `RESEARCH_ONLY` | Non-runtime experiment or hypothesis | Keep outside release or clearly namespace | exploratory reports/scripts not used by startup |

Minimum manifest columns:

```text
path, class, owner, required_by, tracked_state, staged_state,
contains_case_data, contains_secret, machine_path_free,
license_status, validation_command, disposition, review_status
```

Manifest invariants:

1. Every local `src.*` or frontend relative import resolves to a tracked
   `RUNTIME_REQUIRED` file.
2. Every command in canonical documentation resolves to a tracked
   `STARTUP_REQUIRED` file.
3. No `GENERATED_LOCAL` or `SENSITIVE_LOCAL` item is staged.
4. Every `LEGACY_COMPAT` item has a supported entrypoint, owner, tests and sunset
   decision.
5. The staged tree, not the dirty working tree, is the exact input to final
   verification.

## 8. Remediation and audit order

### Task 1 - Freeze and classify the tree

1. Capture `git status --short`, tracked/untracked inventories and file hashes.
2. Review all 164 release-relevant untracked paths.
3. Review both index and worktree versions of every partially staged file.
4. Build the explicit release manifest; do not use `git add .`.

Completion gate: every changed/untracked path has owner, class and disposition;
zero unknown `MM` paths remain.

### Task 2 - Prove the clean-clone failure and close runtime source

1. Create a temporary clone/worktree from the intended staged/index tree.
2. Run `python -c "import src.main; import src.worker.worker"`.
3. Run frontend `npm ci` and `npm run build`.
4. Add only the manifest-approved missing runtime files and repeat.

Completion gate: backend and worker import, Celery task enumeration and frontend
build pass without copying any file from the dirty workspace.

### Task 3 - Make dependencies reproducible

1. Define Windows GPU, Windows CPU and Docker support profiles.
2. Produce complete pinned constraints/lock artifacts.
3. Align Python minor versions and package acquisition paths.
4. Run fresh install, `pip check`, import smoke and `npm ci`.

Completion gate: resolver-complete installs pass from an empty environment and
Docker uses the same declared dependency contract.

### Task 4 - Rehearse database and authentication

1. Start isolated PostgreSQL and Redis.
2. Run Alembic base-to-head on an empty database.
3. Seed lookup/admin data once, restart, and prove idempotence.
4. Test CSRF/login/logout, ownership, cross-user/cross-case 403/404, upload limits
   and audit logs.

Completion gate: fresh database reaches exactly `e6f7a8b9c2`, restart does not
mutate schema unexpectedly, and authorization negative tests pass.

### Task 5 - Normalize startup and model/runtime identity

1. Select canonical dev and staging launchers.
2. Track and validate acquisition, preflight and start scripts/manifests.
3. Verify llama-server alias, model path/hash, context size, no fallback and no
   runtime download.
4. Verify ASR and diarization artifacts before enabling full transcription.

Completion gate: missing service/artifact fails early with an actionable message;
healthy start follows one documented order and records model/runtime identity.

### Task 6 - Consolidate active product routing

1. Map each frontend action to endpoint, service, worker task and persistence key.
2. Remove or isolate legacy Ollama/Gradio/backup paths.
3. Decide v1 compatibility scope and add contract tests if retained.
4. Resolve frontend API base URL configuration.

Completion gate: one normal product action cannot silently select a different
model or pipeline through another route.

### Task 7 - Full product and security verification

1. Run all backend tests with documented exclusions only.
2. Run frontend tests, lint, type check, production build and bundle budget.
3. Run Compose config/build smoke for the profile it claims to support.
4. Run secret/history scan, dependency/SBOM scan, migration verifier and offline
   bundle verifier.
5. Run real upload -> transcription -> summary -> analysis -> visualization with
   persisted task evidence and a multi-speaker sample.

Completion gate: every explicit product requirement maps to a passing command or
artifact; remaining failures are documented blockers, not ignored warnings.

### Task 8 - Atomic commit, push and independent clone

1. Stage from the approved manifest with explicit paths.
2. Inspect `git diff --cached --check`, `git diff --cached --stat` and full staged
   diff.
3. Re-run release gates from the staged-tree clone.
4. Commit in reviewable boundaries, push, clone into a second path or machine,
   then execute the canonical runbook again.

Completion gate: the post-push independent clone reaches the same health,
registered tasks, migrations, model identity and end-to-end results without any
undeclared local files.

## 9. Release decision rules

Release may proceed only when all of the following are true:

- No tracked runtime import resolves only because of an untracked file.
- Canonical setup commands reference only tracked, reviewed assets.
- Fresh Python/npm installs pass dependency checks.
- Fresh DB migration and seed rehearsal pass.
- One canonical startup path proves DB, Redis, llama-server, backend, solo Celery
  and frontend health.
- Real persisted summary, analysis and visualization jobs pass on the intended
  model/runtime with no silent fallback.
- Secret/privacy scan confirms no credentials, raw case audio/transcript or
  sensitive replay artifacts are staged.
- The exact staged tree passes tests/build/audit; an independent clone reproduces
  the result.

Until then, the honest status is: local development workspace functional on the
tested machine, staging packaging incomplete, production offline bundle blocked.

## 10.1 Repeatable inventory harness

The read-only implementation is `scripts/audit_release_inventory.py`; its
regression suite is `tests/test_release_inventory_harness.py`, and operating
instructions are in `docs/runbooks/release-inventory-audit.md`. The canonical
evidence artifact is
`docs/reviews/artifacts/2026-08-14-release-inventory.json`.

This harness separates `HEAD`, index, and workspace content, reads Git blobs for
the first two snapshots, checks active Python and frontend import closure, and
classifies untracked paths. It reports secret filename risk without reading
sensitive contents. Its verdict is an inventory gate only; a clean-clone
install/start/end-to-end rehearsal remains mandatory before release.

## 10. Residual uncertainty

- A provisional exported tree received a fresh Python 3.11 venv and frontend
  install. Python dependency resolution failed before backend execution, so a
  complete fresh-clone runtime rehearsal is still unavailable.
- The selected backend suite is not the whole backend suite. It proves focused
  release/security/onboarding surfaces only.
- No secret values from `.env` were read. Git tracked names/history were checked,
  but a dedicated entropy/history scanner remains required before push.
- Current Alembic status proves the local database is at head, not that every
  historical production database upgrades cleanly.
- Model quality, ASR accuracy and investigative usefulness require separate
  benchmark evidence; this document audits release closure and runtime integrity.

## 11. Provisional candidate rehearsal update

The hardened inventory uses schema v2 and candidate rehearsal uses schema v3. Generated and
sensitive untracked filenames are aggregated rather than persisted, and the
candidate content scan never records matched secret or case-data values. The
candidate manifest is an explicit per-file allowlist with origin, class,
disposition and review status; research, curated evidence, legacy compatibility
and unclassified paths remain pending by default.

Current workspace inventory remains `BLOCKED`: 44 tracked-source dependency
edges resolve only to untracked files, the real index misses 11 dependency
edges, 8 paths are partially staged, and 256 release-relevant untracked paths
still need disposition. The real index fingerprint remained
`df1c149644a756a784d0db773fe26491b6f2c11a` throughout rehearsal.

An earlier provisional v2b exported tree was `53f02e332ec9ecc6cb5b490b2abb91a29d69e687`
with 480 selected paths. A separate Git repository reproduced that exact tree
only after force-adding 26 manifest-selected paths hidden by the repository's
root `/*.txt` ignore rule. This confirms why the release must stage from the
allowlist instead of `git add .`.

That candidate-local source inventory passed and 79 loaded `src.*` modules resolved
inside the candidate tree. Frontend `npm ci`, 36 tests and production build
passed; lint remained blocked because no ESLint configuration exists. The
canonical Python 3.11 fresh install failed after roughly 404 seconds with pip
`resolution-too-deep`, so backend fresh-venv tests and a true new-machine startup
remain blocked. Compose configuration renders, but Docker still uses Python
3.10, installs the same unresolved requirements, bind-mounts the dirty checkout,
starts Uvicorn with reload, and does not supply the pinned llama-server runtime.

The latest provisional v3 candidate tree is
`2db6566f07d580b17b64031aa1a035b1b24c0b8a`. Its manifest contains 480 entries: 375 tracked
and 105 untracked. It remains `BLOCKED` pending explicit review of 153 entries
(100 research, 37 unclassified, 13 curated evidence and 3 legacy compatibility).
It must not be treated as a final release candidate while Summary/Analysis source
is still changing.

## 12. Source-lock and release-test profile update

The current release rehearsal schema is v4. Candidate v4d was exported before
the source-content fingerprint and machine-readable test profile were added. It
therefore remains historical evidence only, even though its exact temporary Git
tree and independent local commit were reproducible:

- export: `E:\research\STT-release-candidate-allowlist-v4d-20260814`;
- tree OID: `701ce603bc89e6c496d489d34825fc6dfb1871f8`;
- independent commit: `ef78e864d330ff551344fa1fbcd1e2cc9e26d331`;
- candidate files: 324;
- manifest: `PASS`, zero pending review;
- local dependency closure: 674 edges, four added helpers, zero parse errors;
- rehearsal artifact SHA-256:
  `4D43AAB1469DC617B6CE104EC0CAF2111D1AD57FD1C792E330E92576F41DE586`.

Its full backend run is not an authoritative verdict for the current source. It
reported `1064 passed`, `1 skipped`, and `21 failed` in 517.68 seconds. The
failures included four wrapper tests that assumed a candidate-local venv,
historical/research evidence deliberately excluded from the runtime candidate,
operator-acquired Pyannote artifacts, an obsolete launcher assertion, stale
Summary/Analysis source, and one current portability failure in
`src/cherry_core/adapters/correction/contextual_refiner.py` importing
`core.domain.entities` instead of the repository package path.

The machine-readable profile is now
`config/release/backend-source-test-profile.v1.json`. Its rule is fail-safe: all
collected backend tests are release-blocking unless an exact node ID is declared
as non-release. Current collection contains 1,096 tests: 1,085 release-blocking
and 11 declared separately (nine historical evidence tests, one gated external
model test, and one non-canonical legacy-launcher test). All 11 node IDs were
found; no Summary/Analysis, API, replay-wrapper, timestamp, import, database,
worker, or security regression is excluded.

`scripts/verify_release_test_profile.py` now requires all of the following
before pytest can run:

1. The source workspace still matches the content fingerprint recorded at
   candidate export.
2. The exported candidate bytes match that same fingerprint.
3. Current release-policy selection and transitive local dependency closure add
   no path missing from the candidate manifest.
4. The candidate contains no unmanifested source/config/test/document path and
   no unmanifested sensitive path; sensitive filenames are counted and redacted.
5. Every declared non-release test node still exists in collection.
6. Pytest executes with a Python interpreter inside the candidate root, never
   with the development workspace venv.

Current harness validation is `20 passed`; flake8, compileall, JSON parsing and
`git diff --check` pass. Candidate v4d is correctly rejected because it predates
the required profile/fingerprint and is missing current release paths. No new
candidate may be exported until the Summary/Analysis owner explicitly locks the
V11 source set.

The real Git index changed outside this release harness during concurrent team
work. Its tree fingerprint moved from
`df1c149644a756a784d0db773fe26491b6f2c11a` to
`881bdbd10c0a008553de8afab6beb83b4461277e` at the observed index timestamp
2026-08-14 03:42:38 Asia/Saigon. The release harness did not stage, revert,
commit or push any file and did not attribute that change. Final staging and
candidate evidence must use the post-lock index/source state, not either older
fingerprint.
