# Offline Benchmark-Candidate Bundle

Date: 2026-08-09
Status: implemented verifier; current candidate is BLOCKED

## Purpose

The bundle verifier proves byte-level closure for a benchmark candidate without
accessing public networks. It does not select a winning model and cannot grant a
production release. Production still requires the signed R9 release manifest,
the external T4 release authority, labelled Vietnamese quality evidence, and
authorized operational acceptance.

## Current command

```powershell
venv\Scripts\python.exe scripts\verify_offline_release_bundle.py `
  --json `
  --output docs/evals/runs/offline-bundle/latest.json
```

Expected current result: exit code `1`, `status=BLOCKED`.

The local candidate currently proves neither of its two declared roles:

- Qwen3-8B Q4_K_M is blocked because the model directory contains unlisted
  Hugging Face cache metadata files;
- llama.cpp b10331 Windows CUDA is blocked because its manifest records a
  shortened commit instead of an immutable lowercase 40-hex Git commit.

It intentionally remains blocked until all fixed v1 roles are closed:

- application source bundle;
- ASR model manifest;
- database runtime;
- diarization model manifest;
- FFmpeg runtime manifest;
- frontend package cache;
- third-party license bundle;
- LLM model manifest;
- LLM runtime manifest;
- Node.js runtime;
- operating-system prerequisites;
- prompt/schema bundle;
- Python runtime;
- Python wheelhouse;
- queue runtime;
- startup profile.

## Verification contract

The verifier:

1. rejects duplicate JSON keys, unknown fields, floating production claims,
   unsafe paths, drive prefixes and symlink escapes;
2. hashes every bundle-declared file and checks exact byte size;
3. re-parses and verifies nested model manifests and model artifacts;
4. re-parses and verifies nested native-runtime manifests and runtime artifacts;
5. enforces a fixed v1 role-to-component-kind mapping so an arbitrary text file
   cannot satisfy an ASR, diarization, LLM or runtime role;
6. binds model roles to allowed tasks and rejects subject-ID mismatches;
7. rejects unlisted files below model and runtime artifact roots, including
   case-insensitive collisions;
8. reports every missing role and exits non-zero;
9. always returns `release_ready=false` because v1 is candidate-only.

The verifier performs no downloads, package installation, model loading, GPU
probe or public network request.

## Adding a component

Do not add a component until its source revision, license, local files, byte
sizes and SHA-256 values are known. Model and native runtime roles must point to
their own strict nested manifest. File-set roles must enumerate every release
file; a directory name alone is not evidence of closure.

After editing the candidate manifest, rerun the command and inspect the nested
verification results. A zero exit code means only that all candidate artifact
roles are present and byte-valid. It is not a quality or production approval.

## Negative gates

The candidate must remain blocked when any of the following occurs:

- required role missing;
- manifest/file duplicate, path escape or symlink escape;
- missing file, size mismatch or checksum mismatch;
- nested subject ID mismatch;
- role/task mismatch, including an LLM relabelled as ASR or diarization;
- model without the `offline` profile;
- unlisted nested model or runtime files;
- runtime with missing license/source metadata or a non-40-hex commit;
- attempted `production` state in this unsigned v1 protocol.

## Next closure order

1. Generate manifests for the measured faster-whisper baseline and selected
   diarization candidate without relying on user caches.
2. Package and manifest FFmpeg.
3. Build a pinned wheelhouse and frontend package cache on a staging machine.
4. Freeze prompt/schema files and generate their byte manifest.
5. Generate `THIRD_PARTY_NOTICES` and a license-file bundle from exact promoted
   artifacts.
6. Run the verifier under outbound network denial on a clean deployment image.
