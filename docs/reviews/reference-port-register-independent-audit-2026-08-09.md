# Independent Audit - Reference Port Register

Date: 2026-08-09
Target branch: `feature/architecture-refactor`
Target baseline: `b2c90910`
Scope: `scripts/reference_port_register.py`, the generated register, its locked
artifact validator integration, and negative tests.

## Requirements

1. Every reuse decision must resolve to content-addressed source evidence.
2. No reference code may be copied while ownership or license remains open.
3. Dirty and untracked reference sources must remain visibly distinguished.
4. A standalone register verification must fail closed on stale, incomplete,
   duplicate, malformed, or permissive evidence.
5. Verification must be repeatable without Internet or an optional YAML parser.

## Initial Finding

### Medium - standalone verification trusted source evidence too broadly

The aggregate artifact validator checked source-spec hashes, record counts and
source identities, but `reference_port_register.py verify` did not independently
enforce those invariants. A caller using only the dedicated register command
could therefore accept a coordinated register/evidence rewrite that omitted a
source while another record still covered the same recommendation ID.

Resolution:

- require the exact source-spec SHA-256 recorded by the evidence bundle;
- require a one-to-one source-spec/evidence record set;
- reject duplicate or non-object records;
- validate SHA-256, source identity, byte count, tracked state, commit and blob IDs;
- add negative tests for a missing source record and forged source identity.

## Verified State

- 27/27 reuse recommendation IDs are present exactly once.
- Every non-rejected item remains `blocked_pending_license` and
  `copy_code_allowed=false`.
- Every source has a content hash and explicit clean/modified/untracked state.
- The register is canonical JSON encoded as valid YAML 1.2, so verification has
  no PyYAML dependency.
- Standalone and aggregate verification both pass after fail-closed hardening.

## Harness And Results

Commands:

```text
python scripts/reference_port_register.py verify
python scripts/validate_reference_reuse_artifacts.py
python -m py_compile scripts/reference_port_register.py scripts/validate_reference_reuse_artifacts.py tests/test_audit_reference_repos.py
git diff --check -- scripts/reference_port_register.py docs/provenance/reference-port-register.yaml scripts/validate_reference_reuse_artifacts.py tests/test_audit_reference_repos.py
```

Results:

- standalone register verification: valid, zero failures;
- locked artifact validator: 105/105 checks pass;
- negative harness: missing record rejected; forged source identity rejected;
- syntax and whitespace gates pass.

## Verdict: PASS

The register is suitable as the R0 provenance gate for selecting techniques
from the two reference repositories. It does not authorize code copying or
production promotion. Those remain blocked on owner/license approval, target-
owned reimplementation, human-labelled Vietnamese evaluation, and the later
air-gapped release gates.

## Residual Risk

The register is content-addressed but not yet signed. A signed release manifest,
third-party notices, SBOM, and authorized license decisions remain required
before any reference-derived component can enter a production bundle.
