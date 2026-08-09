# T4 Verification Protocol

**Protocol status:** Pre-implementation lock

**Date locked:** 2026-08-09

**Execution rule:** Run sequentially; repository database fixtures are not safe
for concurrent pytest processes.

## Hypothesis

A deterministic-first T4 layer that binds candidate semantics to replayed source
evidence, uses conservative merge keys, and treats model checkers as signal-only
will block the six currently accepted semantic forgeries without weakening the
T2/T3 provenance boundary.

## Confirmatory test families

1. **Input authority**
   - raw `DiscoveryBatch` rejected;
   - forged `VerifiedDiscoveryBatch` construction rejected;
   - cross-case/file/source/revision replay rejected.
2. **Canonical identity**
   - ID-only rename rejected;
   - semantic mutation with stale ID rejected;
   - deterministic replay yields byte-identical batch JSON/hash.
3. **Semantic binding**
   - unrelated statement/quote rejected or withheld;
   - type, polarity, modality, attribution, value, owner, unit, and time mutation
     rejected;
   - reported speech and quoted instructions cannot become affirmed facts.
4. **Atomicity**
   - sentence/semicolon/independent-clause composite withheld;
   - punctuation inside money, date, identifier, abbreviation, or entity surface
     does not create a false split;
   - atomic units are exact contiguous source substrings.
5. **Exact values**
   - money/date/time/phone/account/identity/vehicle/quantity/code values remain
     exact;
   - `15` versus `50`, `triệu` versus `tỷ`, and owner swaps fail;
   - ambiguous detector mention remains a mention and does not gain ownership.
6. **Merge and entity policy**
   - exact duplicate candidate/evidence dedupes deterministically;
   - same surface at different spans remains separate by default;
   - different person/value/event/time/polarity/modality never hard-merges;
   - candidate ordering does not change cluster IDs.
7. **Contradiction preservation**
   - affirmed/negated compatible propositions create a contradiction record;
   - both source assertions retain separate evidence;
   - absence, unknown, negated, and unverifiable remain distinct;
   - premise and counterevidence sets are disjoint.
8. **Checker boundary**
   - checker cannot promote unresolved evidence;
   - checker disagreement is retained and forces review/withholding;
   - checker error/timeout has deterministic abstention behavior;
   - no socket/network call occurs in deterministic-only execution.
9. **Release boundary**
   - boolean human-review requirement is not a completed attestation;
   - stale/mismatched review subject hash is rejected;
   - contradicted/unverifiable candidate cannot enter factual projection;
   - unsupported high-risk release count is zero.
10. **Performance**
    - reconciliation uses hash-map blocks rather than global all-pairs matching;
    - 1,000 synthetic candidates complete within the locked local budget;
    - memory and latency are recorded, not inferred.

## Locked pre-implementation probes

All six probes below are known to be accepted by the pre-T4 contract snapshot
and must be rejected after implementation:

| Probe | Pre-T4 result | Required post-T4 result |
|---|---|---|
| Unrelated claim statement versus candidate/evidence | Accepted | Rejected/withheld |
| Candidate/claim polarity mismatch | Accepted | Rejected |
| Reported speech promoted to affirmed fact | Accepted | Rejected |
| Affirmed and negated candidates merged | Accepted | Separate + contradiction |
| Arbitrary candidate/verification/claim IDs | Accepted | Rejected |
| Qualified release with boolean only | Accepted | Rejected pending attestation |

The pre-T4 probes are exploratory evidence discovered during contract audit.
All post-lock executions are confirmatory unless explicitly labelled otherwise.

## Metrics and gates

Structural gates for this task:

- semantic-forgery probe rejection: `6/6`;
- resolvable evidence for projectable decisions: `100%`;
- duplicate candidate/decision/claim/evidence IDs: `0`;
- contradictory hard merges: `0`;
- checker disagreements silently converted to supported: `0`;
- unsupported high-risk release: `0`;
- deterministic replay mismatch: `0`;
- network calls in deterministic profile: `0`.

Release-quality gates remain locked but cannot be claimed from synthetic unit
tests:

- released critical precision >= `0.98`;
- exact numeric/value accuracy >= `0.99`;
- severe hallucination count = `0`;
- contradiction and absence-versus-unknown labelled slices pass;
- calibration reports ECE, Brier score, risk/coverage, and abstention behavior.

## Planned ablations for the future labelled corpus

1. deterministic only;
2. deterministic + mDeBERTa XNLI signal;
3. deterministic + local LLM verifier signal;
4. calibrated ensemble with abstention;
5. soft duplicate retrieval on/off;
6. ONNX FP32 versus INT8;
7. local LLM Q4 versus Q5 where applicable.

No model is promoted by the T4 implementation task. Model download, checksum,
license bundle, network-denied replay, Vietnamese/noisy-ASR calibration, and
hardware benchmark belong to the later model-selection gate.

## Rerunnable commands

```powershell
python -m pytest tests/test_investigation_verification.py -q
python -m pytest tests/test_investigation_canonicalization.py -q
python scripts/evaluate_investigation_verification.py --manifest tests/eval/investigation_verification_cases.jsonl
python -m pytest tests/test_adaptive_summary_contracts.py tests/test_investigation_evidence_selectors.py tests/test_investigation_discovery.py tests/test_investigation_verification.py tests/test_investigation_canonicalization.py -q
python -m compileall src tests scripts -q
```
