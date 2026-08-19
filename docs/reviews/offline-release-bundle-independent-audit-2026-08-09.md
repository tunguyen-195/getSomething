# Offline Release Bundle Independent Audit

Date: 2026-08-09
Scope: `src/services/model_runtime/offline_bundle.py`, its candidate manifest,
tests, schema, verifier CLI, and current local artifacts
Method: RTK static review plus isolated temporary-directory negative probes
Verdict: **BLOCK**

## What the hardening fixed

- The required-role gate is fixed by code and cannot be reduced by the bundle.
- Model roles are bound to required tasks.
- Nested model and runtime directories reject unlisted files.
- Runtime commits must have 40 hexadecimal characters.
- The current candidate remains non-release-authoritative by design.

The focused unit suite previously completed with `16 passed`.

## Blocking findings

### High: runtime roles are not bound to runtime identity or capability

`_ROLE_KIND_REQUIREMENTS` only requires every runtime role to use a
`runtime_manifest`. `_verify_runtime_manifest` verifies the caller-selected
`subject_id`, files, and metadata, but does not bind `database-runtime`,
`ffmpeg-runtime`, `llm-runtime`, `node-runtime`, `python-runtime`, or
`queue-runtime` to distinct runtime families or probes.

An isolated probe assigned a llama-like subject to `database-runtime` and the
component passed:

```text
runtime_role_spoof_component_valid= True
runtime_role_spoof_role= database-runtime
runtime_role_spoof_subject= llama.cpp.windows-cuda
```

Required fix: define a role-specific runtime contract, including an allowlisted
runtime family/capability, expected executable/probe semantics, target OS,
architecture, accelerator constraints, and immutable package identity.

### High: file-set roles validate names and hashes, not manifest semantics

For file-set roles, the verifier only requires certain paths and verifies their
bytes. It does not parse the app-source, frontend-cache, third-party-component,
OS-prerequisite, prompt/schema, wheelhouse, or startup-profile manifests.

An isolated complete-candidate probe wrote arbitrary text bytes under every
required filename. All components and the candidate passed:

```text
arbitrary_named_files_candidate_valid= True
arbitrary_named_files_status= PASS_CANDIDATE_COMPLETE
all_component_valid= True
```

This also means `THIRD_PARTY_NOTICES.md` and
`config/release/third-party-components.json` can be unrelated to the promoted
models and runtimes.

Required fix: add strict duplicate-key-safe schemas and semantic replay for
each file-set manifest. Cross-check source revision, package/file inventory,
license identifiers and local license bytes against every promoted component.

## Additional gaps

- `target_profile` is an identifier only; it is not resolved to a signed or
  checked profile and is not compared with runtime platform/architecture.
- Runtime `platform`, `architecture`, `accelerator`, `version`, and `probe`
  values are present but not fully type-checked or executed by this verifier.
- Model/runtime license metadata is URL-only and is not linked to a local
  license artifact in the license bundle.
- The report calculates the current bundle hash but does not compare it with an
  independently trusted digest or signature. This is acceptable for a local
  diagnostic, not for release or evidence authority.

## Current candidate evidence

Command:

```powershell
venv\Scripts\python.exe scripts\verify_offline_release_bundle.py `
  --json `
  --output docs/evals/runs/offline-bundle/latest.json
```

Observed exit code: `1`.

Current result is correctly `BLOCKED` with zero satisfied roles. Qwen is
blocked by five unlisted Hugging Face cache metadata files. llama.cpp is
blocked because its recorded commit is shortened rather than 40-hex. All 16
fixed roles remain missing.

## Gate result

The verifier is a useful fail-closed byte checker for declared artifacts, but
it cannot yet prove semantic offline bundle closure. Do not promote a candidate
or weaken the current artifact failures. Fix the two PASS paths above and add
negative tests before expanding the real bundle manifest.
