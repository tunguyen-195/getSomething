# T4 Verification, Reconciliation, and Contradiction Design

**Date:** 2026-08-09

**Status:** Locked implementation design; no production quality claim

**Parent:** `docs/plans/2026-08-09-adaptive-investigative-intelligence-plan.md`

**Evaluation protocol:** `docs/evals/t4-verification-protocol-2026-08-09.md`

## 1. Objective

Turn a replay-verified T3 discovery batch into an immutable T4 artifact that can
propose canonical claims without allowing a model, API caller, or mutable JSON
payload to mint factual release authority.

T4 is accepted only if the implementation binds each proposed claim to the
exact candidate semantics and source evidence, preserves attribution and
modality, refuses unsafe merges, records contradictions, and retains every
secondary-checker disagreement as a review signal.

This task does not release an `InvestigationRun`, does not generate Summary or
Analysis prose, and does not promote any local verifier model.

## 2. Current blockers reproduced on the committed snapshot

The current contracts accept all of the following adversarial constructions:

1. A canonical claim whose statement is unrelated to the candidate and quote.
2. A claim whose polarity differs from its candidate.
3. Reported speech promoted to an affirmed fact.
4. Affirmed and negated candidates merged into one canonical claim.
5. Arbitrary candidate, verification, and claim IDs.
6. A qualified release authorized only by
   `requires_human_verification=true`, without a completed review attestation.

The root cause is that T1 validates graph shape and trusted registry hashes but
does not bind the candidate semantic object into the verification subject hash.
T2 and T3 correctly replay source bytes and selectors; they do not and must not
make semantic release decisions.

## 3. Falsifiable requirements

| ID | Requirement | Falsification condition |
|---|---|---|
| V1 | Public T4 entrypoints accept only `VerifiedDiscoveryBatch` plus its exact `SourceRevision`. | A raw/detached batch or cross-revision batch is accepted. |
| V2 | Every projectable decision resolves a T2 selector and binds candidate, evidence, semantic frame, decision, and canonical claim hashes. | Any bound field changes after verification without failure. |
| V3 | Server-owned IDs are canonical and versioned. | ID-only rename or semantic mutation with a stale ID validates. |
| V4 | Compound candidates are split for diagnosis; the composite is never projected. | A multi-proposition composite becomes one factual claim. |
| V5 | Exact values, owner cues, units, time, polarity, modality, and attribution cannot be added, removed, or reassigned silently. | `15` becomes `50`, owner changes, unit disappears, or reported/conditional content becomes affirmed. |
| V6 | A canonical factual statement is an exact evidence-bound source assertion, not an unverified model paraphrase. | Model-only text appears in a projectable claim. |
| V7 | Hard merge requires identical semantic blocking keys and evidence identity. | Different person, value, event, time, polarity, modality, or evidence span is collapsed. |
| V8 | Entity hard merge is limited to exact normalized identifier/type/evidence equivalence. | Same-name mentions at different spans are asserted to be one person. |
| V9 | Opposite compatible assertions remain separate source assertions and create a contradiction record. | Contradiction is collapsed or either source assertion is deleted. |
| V10 | Checker/NLI output is non-authoritative. | A checker promotes missing/unresolved evidence or disagreement is discarded. |
| V11 | Human review is a hashed attestation, not a boolean. | Partial/contradicted/high-risk content becomes release-eligible without a matching completed attestation. |
| V12 | Output is offline-replayable with manifest, policy, source-module, config, and optional model digests. | Network is required or the exact decision cannot be reproduced. |

## 4. Locked epistemic policy

### 4.1 Source assertions versus world truth

A transcript-grounded assertion means that a named speaker/source said the
quoted content. It does not prove that the content is true in the world. T4
therefore preserves `affirmed`, `negated`, `uncertain`, `reported`,
`quoted_instruction`, conditional, question, and explicit-unknown states.

`absent`, `unknown`, `negated`, and `unverifiable` are different states and must
never be normalized into one placeholder.

### 4.2 Atomicity

T4 may identify deterministic atomic units for diagnosis. It must not invent a
new proposition. If a candidate contains multiple independently verifiable
clauses, the composite is withheld and returned to a later extraction/retry
boundary. A child claim is allowed only when its text is an exact contiguous
source span and its transformation record is canonical and reviewable.

### 4.3 Verification disposition

- `supported`: all released semantic bindings are present in the exact source
  assertion and deterministic checks pass.
- `partially_supported`: some bound content is supported, but the whole proposed
  semantics are not; withheld unless a future human-review policy explicitly
  authorizes a qualified, non-factual projection.
- `contradicted`: the proposed semantics conflict with the source; withheld.
- `unverifiable`: evidence, attribution, or required binding is missing; withheld.

Two separately sourced assertions that contradict one another may each be
`supported` as source assertions. Their conflict belongs in a separate
`ContradictionRecord`; it does not erase either provenance chain.

## 5. Target architecture

```text
VerifiedDiscoveryBatch + exact SourceRevision
  -> selector replay
  -> SemanticClaimFrame
  -> deterministic atomic/value/owner/unit/polarity/modality checks
  -> optional non-authoritative VerifierSignal
  -> CandidateVerificationRecord
  -> conservative claim/entity reconciliation
  -> ContradictionRecord
  -> immutable VerifiedVerificationBatch
  -> trusted T4 adapter (future InvestigationRun release context)
```

### 5.1 Module boundary

- `verification_contracts.py`: immutable T4 records, manifests, canonical IDs,
  batch sealing, and replay wrapper.
- `claim_semantics.py`: deterministic frame extraction, atomicity, exact-value,
  attribution, modality, polarity, owner, unit, and time checks.
- `canonicalization.py`: provenance-preserving hard dedupe and conservative
  entity grouping; soft links never authorize merges.
- `contradictions.py`: polarity-aware contradiction keys and conflict records.
- `verification.py`: orchestration from verified T3 input to T4 output.
- `verifier_adapters/`: optional offline signal ports. Adapters cannot create IDs,
  dispositions, eligibility, claims, or release authority.
- `human_review_contracts.py`: future completed-review attestation bound to exact
  semantic subject and policy hashes.

### 5.2 Canonical identity

IDs use SHA-256 over versioned canonical JSON. Set-like references are sorted
before hashing. Provenance-specific candidate IDs remain unchanged. Claim/entity
cluster IDs include scope, exact sorted member refs, semantic policy version, and
evidence identity so a new merge decision creates a new version instead of
mutating an old object.

## 6. Local checker research decision

Deterministic verification remains the only initial authority. The first
offline NLI baseline for a later ablation is:

- `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`
- revision `8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c`
- MIT license
- official `model.safetensors`: 557,652,046 bytes
- official quantized ONNX: 338,679,133 bytes
- model card reports Vietnamese XNLI accuracy around 0.795

This accuracy is far below the proposed released-critical-precision gate and is
not evidence of robustness to Vietnamese investigative dialogue or noisy ASR.
Use ONNX Runtime CPU INT8 first to avoid competing with ASR/LLM VRAM; record its
signal only.

`lytang/MiniCheck-Flan-T5-Large` revision
`96eafd01cee2d16cf81aaa2fb226b14f422a37b3` is an English factuality
challenger, not a Vietnamese release gate. Its official PyTorch weight is
3,132,786,242 bytes. `amazon-science/RefChecker` is useful as a claim-triplet
design reference but its official repository is archived, so runtime code must
not depend on it.

For soft duplicate retrieval, `sentence-transformers/paraphrase-multilingual-
MiniLM-L12-v2` revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`
is the smallest preferred research baseline. Embedding similarity may propose a
review pair only; it cannot merge claims or entities.

## 7. Primary sources

- FActScore: https://aclanthology.org/2023.emnlp-main.741/
- MiniCheck: https://aclanthology.org/2024.emnlp-main.499/
- RefChecker: https://arxiv.org/abs/2405.14486
- VERISCORE: https://aclanthology.org/2024.findings-emnlp.552/
- XNLI: https://aclanthology.org/D18-1269/
- mDeBERTa XNLI model: https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli
- MiniCheck model: https://huggingface.co/lytang/MiniCheck-Flan-T5-Large
- Multilingual MiniLM: https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
- RefChecker repository: https://github.com/amazon-science/RefChecker

Model/repository identifiers were refreshed from official APIs on 2026-08-09.

## 8. Implementation sequence

1. Add immutable semantic/verification/reconciliation contracts and canonical
   ID helpers.
2. Add deterministic frame and atomicity checks with Vietnamese modality,
   negation, attribution, exact-value, and unit policies.
3. Add T3-to-T4 orchestration that replays selectors and strips untrusted model
   authority fields.
4. Add conservative merge/entity grouping and contradiction preservation.
5. Add a signal-only checker port and deterministic fake adapter for tests; do
   not download or promote a model in this task.
6. Harden `run_contracts.py` so released semantics are bound to the exact T4
   candidate/claim subject and contradictions cannot enter factual buckets.
7. Run the locked adversarial/property/performance harness, then a sequential
   regression suite because the repository test DB reset fixture is not safe for
   parallel pytest processes.

## 9. Residual uncertainty

- No locked, human-labelled Vietnamese investigative corpus exists yet, so the
  numeric quality thresholds remain release gates rather than achieved claims.
- Exact transcript grounding does not prove audio truth; ASR and diarization
  errors still require evidence-to-audio review.
- Vietnamese conditionals, ellipsis, dialect, code-switching, and implicit
  coreference need labelled slices before semantic models or soft merges can be
  promoted.
- A deterministic-only verifier may abstain often. Low coverage is preferable
  to unsupported factual release until calibrated Vietnamese evidence exists.
