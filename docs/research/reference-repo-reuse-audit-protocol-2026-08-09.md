# Reference Repository Reuse Audit Protocol

Date: 2026-08-09
Status: locked before reuse decisions
Method: RTK static evidence audit plus independent repository review

## 1. Objective

Determine which implemented techniques, research methods, runtime components,
and packaging practices from these repositories can be adopted safely by the
offline CAND audio-intelligence system:

- `D:\Workspace\SpeechToInfomation` (target);
- `D:\Workspace\SpeechToInfomation-pr` (Lite/reference branch checkout);
- `E:\research\Cherry2\cherry_core` (research/reference checkout).

The audit must distinguish source facts from repository documentation and must
not treat a paper, proposal, model card, or passing unit test as evidence that a
component is integrated into the production request path.

## 2. Falsifiable requirements

| ID | Requirement | Failure condition |
|---|---|---|
| R1 | Every reuse recommendation names an exact source revision and file evidence. | A recommendation is based only on a repo name, memory, or prose claim. |
| R2 | `implemented`, `tested`, `integrated`, and `production-ready` are separate states. | A code artifact or document is described as a working product path without entrypoint evidence. |
| R3 | Reused code has an explicit ownership/license decision and dependency/model license closure. | Code or weights are copied while root/component licensing remains unknown. |
| R4 | Offline candidates have pinned source revisions, local artifacts, checksums, licenses, runtime dependencies, and a network-denial test. | A runtime downloads a model/tokenizer/config or writes into an undeclared user cache. |
| R5 | Investigative outputs preserve audio/transcript provenance and epistemic class. | Reported speech, hypothesis, model inference, or contradiction becomes an unqualified fact. |
| R6 | Model or quantization promotion uses the same Vietnamese noisy-ASR corpus and locked metrics. | A model is selected only from model-card scores, size, or subjective examples. |
| R7 | Repository copying does not overwrite target-specific hardening or user changes. | Wholesale directory replacement, mechanical merge, or unrelated-history merge is recommended. |
| R8 | The target remains operable on the declared air-gapped Windows/GPU profile. | A mandatory component requires public Internet, an unbundled service, or an unsupported host runtime. |
| R9 | Multi-stage execution is deadlock-safe, persistent and replayable. | A fake runner masks the real queue, a lock can self-deadlock, or process exit loses work state. |
| R10 | Correction, VAD and speaker refinement preserve immutable source mappings. | Raw text/speaker IDs are overwritten or timestamps cannot map to original audio. |

## 3. Evidence harness

Run from the target repository:

```powershell
.\venv\Scripts\python.exe scripts\audit_reference_repos.py `
  --repo main=D:\Workspace\SpeechToInfomation `
  --repo lite=D:\Workspace\SpeechToInfomation-pr `
  --repo cherry=E:\research\Cherry2\cherry_core `
  --source-evidence-spec docs\research\reference-repo-audit\source-evidence-spec.json `
  --output docs\research\reference-repo-audit\evidence.json
```

The harness records:

- Git commit, branch, remote and dirty state;
- tracked and selected non-ignored research/source files;
- dependency, container and package manifests with SHA-256;
- root license presence;
- prompt, evaluation, ASR, diarization, summary, analysis and forensic surfaces;
- local-only, runtime-download, external-API and `trust_remote_code` indicators;
- repository-local model-store sizes and weight inventory;
- exact and changed files sharing the same relative path across repositories.
- content-addressed source records for every recommendation ID, including byte
  size, SHA-256, Git worktree blob, HEAD blob, tracked state and source commit.

Large model weights are inventoried by path and size in this first pass. They
are not hashed by this audit command; deployable artifacts must instead be
covered by the target model-manifest preflight.

## 4. Decision classes

| Decision | Meaning | Minimum gate |
|---|---|---|
| `ADOPT` | Port the design and implementation with small target adapters. | Source, license, tests, integration boundary and offline closure are known. |
| `ADAPT` | Reuse the technique, test method, or bounded code after redesign. | Value is demonstrated, but architecture, semantics, provenance or packaging differs. |
| `RESEARCH_CHALLENGER` | Preserve as a benchmark arm, not a production default. | Reproducible protocol exists but local CAND/Vietnamese release gates are not met. |
| `REJECT` | Do not copy into the production path. | Duplicates weaker code, violates evidence policy, lacks provenance, or creates unsupported operational risk. |

`PENDING_LICENSE` is a blocking qualifier, not a weaker gate. It permits review
of a fact, pattern or protocol but forbids copying code/model content until owner
authorization and component license closure are recorded in R0.

## 5. Investigative and forensic gates

- Source audio remains immutable and is bound by SHA-256 to every derived run.
- Raw transcript, normalized transcript, diarization, prompts, schemas, model
  manifests and outputs have independent revisions and hashes.
- Case/file creation and upload timestamps remain operator metadata; they are
  not injected as conversational event time.
- Direct assertions, reported assertions, verified source facts, insights,
  hypotheses, contradictions and verification actions remain distinct.
- Human acceptance creates an append-only attestation; it does not rewrite the
  original model output.
- The application must preserve exact source spans and an audio playback path
  for critical names, identifiers, quantities, times and locations.

## 6. Offline release gates

The current evaluation profile is captured by
`scripts/capture_offline_hardware_profile.ps1` in
`docs/research/reference-repo-audit/hardware-profile.json`. It is benchmark
evidence only. A separately signed production target profile is required before
model/runtime promotion.

An offline component passes only when all of these artifacts are present in the
release tree or internal artifact bundle:

1. immutable upstream revision and source URL;
2. model/runtime/tokenizer/config files and SHA-256 manifest;
3. model, code and dataset licenses plus notices;
4. locked Python/Node/native dependency bundle;
5. prompt, schema, normalization and evaluation revisions;
6. cold-start smoke with outbound networking denied;
7. no fallback to public API or public cache;
8. rollback artifact and last-known-good manifest.

R1 creates verify-only benchmark-candidate bundles. The production bundle is
selected and signed only after the sealed R9 holdout and hardware/resource
ablation; a physically present model is never implicitly production-selected.

## 7. Completion gates

- The evidence JSON is reproducible and parses successfully.
- Every recommendation ID resolves to at least one exact source record; dirty or
  untracked evidence is identified by current SHA-256 rather than HEAD alone.
- Each repo has an independent `ADOPT/ADAPT/REJECT` review with file evidence.
- The final reuse matrix identifies destination modules, prerequisite tasks,
  tests, ownership and release gates.
- Real-worker deadlock/crash tests and raw-to-derived provenance replay are
  mandatory before a runtime implementation is described as integrated.
- The phased plan is independently audited before code is ported.
- No quality claim is made without a shared Vietnamese/noisy-ASR baseline or an
  explicit statement that the required benchmark remains outstanding.

## 8. Known limits

- Both reference checkouts may contain large untracked research artifacts. The
  harness records their count but excludes virtual environments, caches,
  outputs, model weights and other generated directories from source hashing.
- Static evidence cannot prove runtime accuracy, throughput or memory use.
- Public legal and technical sources cannot define classified/internal CAND
  operational requirements. Data classification, authorization, retention,
  evidentiary acceptance and deployment accreditation require authorized human
  stakeholders.
