# T4 External Release Authority And Persistence Gate Design

Date: 2026-08-09
Status: DESIGN ONLY - IMPLEMENTATION REQUIRED
Decision owner: independent T4 audit

## Objective

Prevent arbitrary Python code in the application, worker, plugin, or test process
from publishing an `InvestigationRun` as factual. A successful release must be
authorized by a separately isolated verifier and enforced again at persistence.

The existing same-process adapter remains useful for deterministic replay and
diagnostics, but it is not a security boundary. Python closure inspection,
monkeypatching, frame inspection, or process-memory access is inside its trust
domain.

## Threat Model

Untrusted for release authorization:

- API, Celery worker, model runtime, plugins, and arbitrary Python code in those
  processes;
- caller-provided T3, T4, source revision, proposed run, manifest, and receipt;
- direct imports, reflection, monkeypatching, closure inspection, and forged
  Pydantic validation context;
- replayed, expired, duplicated, reordered, or partially persisted requests;
- direct database writes using ordinary application credentials.

Trusted components:

- a minimal release-authority process running a pinned, verify-only build;
- its private signing key or MAC key, held outside application processes;
- a persistence gateway with exclusive factual-publication database rights;
- the operating-system identity and key-store controls separating these services.

Out of scope for the first implementation: host administrator compromise,
kernel compromise, signing-key extraction from the release service, and factual
accuracy beyond the locked verification policy.

## Minimal Architecture

```text
API / worker / model process
        |
        | canonical release request over authenticated local IPC
        v
Release-authority process (verify-only, no plugins, no model execution)
        |
        | signed RELEASE or BLOCK receipt
        v
Persistence gateway (receipt verifier + exclusive DB role)
        |
        | one transaction: receipt + immutable run + projections
        v
Published investigation tables
```

### 1. Canonical release request

The caller sends immutable bytes or content-addressed references for:

- source revision;
- raw T3 discovery artifact;
- raw T4 verification artifact;
- proposed `InvestigationRun`;
- policy bundle and verifier build identifiers;
- a caller-generated request ID and nonce.

The release service parses canonical JSON, rejects duplicate keys and invalid
UTF-8, recomputes every artifact digest, replays T3/T4, and performs the final
run validation. It does not accept a caller-built validation context or verified
wrapper.

### 2. Process isolation

The release authority runs under a dedicated OS identity. Its executable,
policy bundle, and Python environment are read-only to the application identity.
The service exposes only a narrow local named-pipe or Unix-domain-socket API and
does not load application plugins, model adapters, user paths, or dynamic code.

The application process cannot read the release private key and cannot use the
release service database role.

### 3. Signed release receipt

Preferred production mechanism: Ed25519 signatures. The release service holds
the private key; persistence holds only pinned public keys. HMAC-SHA-256 is
acceptable only when both the release service and persistence gateway are
separate from the application and exclusively hold the MAC key.

Canonical receipt fields:

```json
{
  "receipt_version": "investigation-release-receipt-v1",
  "decision": "RELEASE",
  "request_id": "...",
  "nonce": "...",
  "sequence": 1,
  "issued_at": "...",
  "expires_at": "...",
  "source_revision_sha256": "...",
  "t3_sha256": "...",
  "t4_sha256": "...",
  "investigation_run_sha256": "...",
  "model_manifest_sha256": "...",
  "policy_bundle_sha256": "...",
  "verifier_build_sha256": "...",
  "repository_bundle_sha256": "...",
  "key_id": "release-key-2026-01",
  "failure_codes": [],
  "signature": "base64url-ed25519-signature"
}
```

The signature covers every field except `signature` using the locked canonical
JSON algorithm. A `BLOCK` receipt records failure codes but never grants write
authority.

### 4. Persistence enforcement

The normal application DB role must not have `INSERT` or `UPDATE` privileges on
factual release tables. Only the persistence gateway role may publish them.

Before writing, the gateway must:

1. verify the signature and pinned `key_id`;
2. require `decision=RELEASE` and an unexpired receipt;
3. recompute all persisted artifact and run digests;
4. require exact digest equality with the receipt;
5. enforce unique `(request_id, nonce)` and receipt signature constraints;
6. enforce monotonic sequence or an equivalent anti-rollback policy;
7. insert the receipt, immutable run, and projections in one transaction.

Any missing verifier, unavailable key, unknown policy/build digest, duplicate
nonce, stale receipt, digest mismatch, or partial transaction fails closed.

## Required Repository Impact

- Add a dedicated release-service entrypoint and locked dependency/build
  manifest; do not import the application runtime entrypoint.
- Add canonical request/receipt contracts with byte-level test vectors.
- Add key provisioning and rotation runbooks; private keys must not exist in
  application environment variables or repository files.
- Add a persistence-gateway service or stored-procedure boundary with a distinct
  DB credential and explicit grants.
- Change API/worker publication paths to persist factual runs only through the
  gateway. Same-process `release_adapter` results remain diagnostic until a valid
  receipt is returned.
- Add migrations for receipts, nonce uniqueness, immutable digests, key IDs,
  decision state, and transaction linkage.

## Completion Gates

Release readiness remains BLOCKED until all gates pass:

1. An application-process exploit can inspect every Python closure and still
   cannot obtain the release private key or factual-publication DB role.
2. Forged, modified, expired, replayed, and wrong-key receipts are rejected by
   the persistence gateway.
3. Direct application DB writes to factual tables fail at the database privilege
   layer.
4. Kill/restart tests prove no partial run can exist without its valid receipt.
5. Key rotation accepts the new key, rejects retired keys after the overlap
   window, and preserves verification of historical receipts.
6. End-to-end tests bind source, T3, T4, run, policy bundle, verifier build, and
   persisted bytes to the exact signed digests.
7. A deployment manifest identifies service build hashes, public keys, policy
   hashes, DB grants, and rollback procedure.

## Residual Risk After Implementation

The external boundary prevents a compromised application process from granting
itself release authority. It does not prove source truth, eliminate model error,
or defend against compromise of the release host, persistence gateway, private
key, or database administrator. Those risks require operational hardening,
human review policy, and labelled quality evaluation.
