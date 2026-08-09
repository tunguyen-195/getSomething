# Independent Audit - Reference Repository Reuse Plan

Date: 2026-08-09
Target branch: `feature/architecture-refactor`
Target baseline: `5f7f2ac92598a30ba796b7a4ae793251ac7d5eea`
Reference baselines: `SpeechToInfomation-pr@9a2e5387f786`,
`cherry_core@1dbb880c0ca0`

## Scope

Independent read-only review of the protocol, source evidence, prompt/technique
specification, reuse findings and phased plan for a Vietnamese-first CAND audio
intelligence system that must run without Internet.

## Initial verdict: BLOCK

1. Dirty/untracked Cherry sources were described by HEAD only; the reviewed
   PhoGuard/SAGE content was not uniquely identified.
2. A verified transcript proposition could lose speaker attribution and become
   an unsupported world fact.
3. R2/R3 required labelled calibration data before corpus governance was defined
   in R9.
4. `ADOPT` rows contradicted the protocol because ownership/license was unknown.
5. R1 promoted production bundles before model/runtime/hardware ablation in R9.

## Resolutions

| Finding | Resolution | Direct evidence |
|---|---|---|
| Source identity | Source-evidence v2 records exact bytes, SHA-256, worktree/HEAD blobs, tracked state and recommendation IDs. | `docs/research/reference-repo-audit/source-evidence-spec.json`; `docs/research/reference-repo-audit/evidence.json` |
| Epistemic boundary | `verified_source_assertion` remains attributed; only a `corroborated world finding` with independent evidence may be released as world truth. | `docs/research/cand-audio-intelligence-prompt-technique-spec-2026-08-09.md` |
| Corpus dependency | Corpus governance, annotation/adjudication and split sealing moved to R0; the sealed release holdout stays closed until R9. | `docs/plans/2026-08-09-reference-reuse-offline-cand-plan.md` |
| License gate | Every reusable code/method row is `ADAPT / PENDING_LICENSE`; code copying remains forbidden before R0 authorization. | `docs/reviews/reference-repository-reuse-audit-2026-08-09.md` |
| Promotion order | R1 produces benchmark-candidate bundles; R9 selects and signs production artifacts for an exact hardware profile. | `docs/plans/2026-08-09-reference-reuse-offline-cand-plan.md`; `docs/research/reference-repo-audit/hardware-profile.json` |

## Final verification

- 41/41 selected source files resolve with no evidence-harness error.
- All 27 recommendation IDs map to content-addressed source records.
- Modified and untracked Cherry sources are distinguished from clean HEAD files.
- The prompt contract includes a zero source-assertion-to-world-fact leakage gate.
- The corpus, candidate-bundle and hardware promotion dependencies are acyclic.
- The locked artifact validator and harness tests pass after the corrections.

## Verdict: PASS

The review and plan now answer the reuse question without treating either
reference repository as a merge source or production authority. Remaining model,
prompt and runtime quality claims are explicitly blocked on ownership/license,
human-labelled Vietnamese evaluation, sealed holdout results and exact offline
target-hardware verification.

This PASS applies to the research/reuse plan only. T4 remains a separate
implementation `BLOCK` until its trusted release adapter and adversarial tests pass.
