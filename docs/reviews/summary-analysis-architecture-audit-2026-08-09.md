# Summary/Analysis Architecture Audit

**Date:** 2026-08-09

**Repository:** `D:\Workspace\SpeechToInfomation`

**Branch:** `feature/architecture-refactor`

**Decision:** **PRODUCTION BLOCK**

**Review mode:** RTK evidence-first, read-only architecture audit

## 1. RTK objective

Đánh giá liệu Summary và Analysis hiện tại đã trở thành một pipeline tri thức
điều tra evidence-grounded, khai thác khả năng discovery, reasoning và synthesis
của LLM thay vì chỉ điền một biểu mẫu cố định hay chưa.

Kết quả chỉ được coi là đạt khi đồng thời chứng minh được các yêu cầu có thể
kiểm chứng sau:

1. Discovery tạo claim, concept, event, relationship và theme theo nội dung thực
   tế, không bị giới hạn bởi một ontology/form bắt buộc.
2. Candidate phải được xác minh với source revision và evidence span trước khi
   trở thành released claim.
3. Summary, Analysis và Visualization chỉ là các projection của cùng một
   versioned canonical ledger; không endpoint nào tự tái tạo factual content.
4. Mọi factual sentence phải truy ngược được tới claim `supported` và evidence
   thực sự resolve trên source bytes hiện hành.
5. Fact, inference, hypothesis và recommended verification action phải được phân
   biệt; inference/hypothesis không được trình bày như fact.
6. Concept không xuất hiện phải được bỏ hẳn, không sinh `null`, collection rỗng,
   card/tab rỗng, `Không có thông tin` hoặc `Cần xác minh thêm` để lấp form.
7. Hard-gate failure phải tạo trạng thái không phát hành như `needs_review`, thay
   vì trả một summary có vẻ hoàn chỉnh.

## 2. Scope

Audit bao phủ:

- Canonical T1 contract tại `src/services/investigation/contracts.py`.
- Legacy/live Context Analysis, grounding và Summary generation.
- Summary worker, API re-analysis và Visualization service.
- UI projection trong `InvestigationSummaryCard.tsx`.
- Target architecture và quality gates trong research/implementation plan.

Audit này không thay đổi code, không đánh giá chất lượng một model cụ thể và
không tuyên bố T0 offline/replay gate đã đạt.

## 3. Authoritative evidence

### 3.1 Local source artifacts

- `src/services/investigation/contracts.py`
- `src/services/summarization/models/context_analysis.py`
- `src/services/summarization/models/investigation_knowledge.py`
- `src/services/summarization/models/llm_manager.py`
- `src/services/summarization/summary_service_v2.py`
- `src/services/visualization_service.py`
- `src/api/endpoints/summary.py`
- `src/worker/tasks/summarize_task.py`
- `frontend/src/components/InvestigationSummaryCard.tsx`
- `tests/test_adaptive_summary_contracts.py`
- `docs/plans/2026-08-09-adaptive-investigative-intelligence-plan.md`
- `docs/research/evidence-preserving-adaptive-investigative-summary-2026-08-09.md`
- `docs/reviews/adaptive-contract-t1-review-2026-08-09.md`

### 3.2 Repeatable audit harness

Production integration was located with:

```powershell
rg --files src/services/investigation
rg -n "AdaptiveSummaryAnalysisContract|AdaptiveSummaryContract|AdaptiveAnalysisContract|adaptive_contract" src frontend tests
```

The result shows that `src/services/investigation/` currently contains only
`__init__.py` and `contracts.py`; canonical contract references outside this
module are confined to tests/evaluation code. The live worker, API, service and
frontend paths do not consume it.

Contract negative checks were executed in memory by loading the canonical
fixture from `tests/test_adaptive_summary_contracts.py`, mutating one invariant
per case, and calling
`AdaptiveSummaryAnalysisContract.model_validate(payload)`. No network or model
call was made.

## 4. Findings

### CRITICAL-1: Live outputs are competing generations, not one-ledger projections

The live Summary flow first runs Context Analysis
(`src/services/summarization/summary_service_v2.py:128`), then independently
generates narrative Summary (`src/services/summarization/summary_service_v2.py:140`),
and then runs another LLM extraction from the model-generated summary for the
Analysis tab (`src/services/summarization/summary_service_v2.py:284`). The third
generation explicitly uses `{summary}` as its source
(`src/services/summarization/summary_service_v2.py:313`).

The `/summary/analyze` endpoint invokes Context Analysis again from the task
transcript and overwrites `context_analysis` inside `Task.result`
(`src/api/endpoints/summary.py:130`, `src/api/endpoints/summary.py:148`). The UI
automatically calls this endpoint when a visualization tab is first opened
(`frontend/src/components/InvestigationSummaryCard.tsx:83`).

`generate_visualization` provides another independent Ollama/fallback analysis
path (`src/services/visualization_service.py:259`,
`src/services/visualization_service.py:272`) and persists its own visualization
payload (`src/services/visualization_service.py:311`). The Summary worker also
mutates `Task.result` directly rather than storing a canonical versioned run
(`src/worker/tasks/summarize_task.py:92`,
`src/worker/tasks/summarize_task.py:113`).

The aliases at `src/services/investigation/contracts.py:577` only establish that
two Python names resolve to one Pydantic class. They do not establish one runtime
artifact, append-only ownership, idempotency or shared projection behavior.

**Impact:** Summary, Analysis and Visualization can disagree, duplicate costly
LLM work, overwrite one another and expose different factual interpretations of
the same transcript.

### HIGH-1: Production discovery remains fixed-form slot filling

Context Analysis requires a large predetermined JSON form beginning at
`src/services/summarization/models/llm_manager.py:271`. It enumerates people,
locations, time, contacts, financial information, relationships, events,
sentiment, anomaly, crime indicator and investigation-note fields through
`src/services/summarization/models/llm_manager.py:353`. It explicitly instructs
the model to fill absent fields with `[]`, `""`, `{}` or `null`
(`src/services/summarization/models/llm_manager.py:366`).

The investigation narrative is another fixed twelve-section form
(`src/services/summarization/summary_service_v2.py:163`) and instructs the model
to write `Không có thông tin` or `Cần xác minh thêm` for absent sections
(`src/services/summarization/summary_service_v2.py:248`).

The T1 contract correctly leaves `claim_type` and sparse `attributes` open
(`src/services/investigation/contracts.py:275`), but no live discovery extractor,
turn-aware chunk planner, exact-value candidate detector or adaptive theme
formation currently targets that contract.

**Impact:** LLM capacity is spent completing a form instead of discovering
content-specific claims, cross-turn dependencies, emerging themes and novel
relationships.

### HIGH-2: Evidence references are internally consistent but not source-resolved

The legacy grounding builder normalizes quotes and performs case-insensitive
substring matching (`src/services/summarization/models/investigation_knowledge.py:235`).
For whole-transcript fallback it uses the first `str.find` occurrence
(`src/services/summarization/models/investigation_knowledge.py:260`). It does not
disambiguate repeated quotes with segment ID plus prefix/suffix, nor verify a
source revision before release.

The canonical contract shape-validates evidence offsets and SHA-256 strings
(`src/services/investigation/contracts.py:226`) and checks graph references
(`src/services/investigation/contracts.py:506`), but it does not recompute hashes
or resolve selectors against source bytes. The current mapper also consumes only
a finite subset of legacy fixed-form fields
(`src/services/summarization/models/investigation_knowledge.py:297`,
`src/services/summarization/models/investigation_knowledge.py:417`).

The negative payload harness confirmed that syntactically valid but intentionally
incorrect `quote_sha256` and `source_sha256` values are accepted by T1.

**Impact:** A contract-valid claim can still point to stale, ambiguous or
non-matching evidence. T2 selector resolution must pass before live integration.

### HIGH-3: Fact, inference and hypothesis are not safely separated

`GroundedClaim` protects only claims marked `risk_tier="high_risk"`
(`src/services/investigation/contracts.py:299`). A factual narrative may cite
both `supported` and `partially_supported` claims
(`src/services/investigation/contracts.py:565`). It rejects hypotheses only when
they are high-risk (`src/services/investigation/contracts.py:571`).

`GroundedRelationship` has no epistemic status, disposition, risk tier,
premise-claim references or human-verification flag
(`src/services/investigation/contracts.py:311`). Therefore an inferred or hidden
relationship can be represented as a fact-like graph edge.

The UI maps `knowledge.facts` to both key points and insight
(`frontend/src/components/InvestigationSummaryCard.tsx:143`,
`frontend/src/components/InvestigationSummaryCard.tsx:152`) and renders them again
under `Insight nghiệp vụ`
(`frontend/src/components/InvestigationSummaryCard.tsx:473`). It does not provide
fact/inference/hypothesis/verification-action badges.

The negative payload harness confirmed that both a `partially_supported` claim
and an ordinary-risk `epistemic_status="hypothesis"` claim are currently accepted
inside a factual narrative sentence.

**Impact:** Useful analytical intelligence cannot be retained safely without a
risk of being visually or narratively conflated with transcript-supported fact.

### HIGH-4: Release lifecycle and projection completeness are missing

The canonical run status is limited to `success` and
`no_extractable_claims` (`src/services/investigation/contracts.py:434`). The
research design requires hard-gate failure to return `needs_review`, not a
plausible-looking completed summary
(`docs/research/evidence-preserving-adaptive-investigative-summary-2026-08-09.md:226`).

For `success`, the contract requires claims and evidence but not themes or
narrative (`src/services/investigation/contracts.py:475`). Primary-theme
validation prevents overlap but does not require every released claim to have a
primary theme (`src/services/investigation/contracts.py:535`). Narrative
validation checks references only for sentences that happen to exist
(`src/services/investigation/contracts.py:547`).

There is no separate candidate ledger, verification report, machine-readable
quality failure, release state or deterministic projection envelope.

**Impact:** A run can report `success` while being incomplete and cannot express
a non-releasable but diagnostically useful partial result.

### MEDIUM-1: Omission semantics are not end-to-end

T1's `StrictEnvelope` correctly rejects null, blank, empty and filler values
(`src/services/investigation/contracts.py:185`). This is an important positive
foundation.

However, the legacy `ContextAnalysisPayload` requires `summary`, `key_points`,
`entities` and `risk_assessment`
(`src/services/summarization/models/context_analysis.py:14`). The live prompt
requires placeholder values, while the UI always renders six fixed tabs
(`frontend/src/components/InvestigationSummaryCard.tsx:228`) and multiple
`Không rõ`/`Không có` fallbacks, including overview
(`frontend/src/components/InvestigationSummaryCard.tsx:245`), time
(`frontend/src/components/InvestigationSummaryCard.tsx:261`), location
(`frontend/src/components/InvestigationSummaryCard.tsx:271`), status
(`frontend/src/components/InvestigationSummaryCard.tsx:281`) and topic
(`frontend/src/components/InvestigationSummaryCard.tsx:291`).

**Impact:** Absent concepts still produce UI noise and preserve the fixed-form
mental model even if a future backend payload becomes sparse.

### POSITIVE-1: Creation/upload timestamps remain outside model reasoning

The Summary worker passes only task/audio integrity metadata into model-side
source metadata (`src/worker/tasks/summarize_task.py:48`). The canonical source
provenance contains source/audio/transcript/model identifiers, not case creation
or file-upload timestamps (`src/services/investigation/contracts.py:364`).

This matches the product rule that those timestamps are user-facing metadata,
not investigative evidence or model input.

## 5. In-memory negative payload results

| Mutated invariant | Current result | Required production behavior |
|---|---:|---|
| `success` without themes or narrative | Accepted | Reject or mark non-releasable |
| Released claim not assigned to theme/narrative | Accepted | Reject incomplete projection |
| `partially_supported` claim in factual narrative | Accepted | Only supported atomic subclaim may be factual |
| Ordinary hypothesis in factual narrative | Accepted | Hypothesis must remain non-factual |
| Shape-valid but incorrect evidence hashes | Accepted | T2 selector resolution must fail closed |
| `run_status="needs_review"` | Rejected | Accept as explicit non-release state |

These checks do not claim that T1 should resolve source bytes by itself. They
demonstrate that T1 cannot currently be treated as a complete release contract
without T1.1/T2 enforcement.

## 6. Stage verdict

| Pipeline stage | Contract support | Live implementation | Missing invariant | Verdict |
|---|---|---|---|---|
| Source sealing and chunk plan | Partial provenance/hash shape | No stable source-revision builder or chunk manifest in live Summary | Duplicate quote, normalized/raw offsets, revision mismatch, position coverage | **BLOCK T2** |
| Adaptive discovery | Open claim/concept/relationship names | Fixed-form Context Analysis and twelve-section Summary | Candidate ledger, turn-aware chunks, deterministic exact-value candidates, open discovery prompt | **BLOCK T3** |
| Claim verification | Evidence refs and disposition labels | Substring grounding from selected legacy fields | Atomic splitting, exact-value checks, selector resolution, verifier report | **BLOCK T4** |
| Canonical ledger | Final claim collection only | Multiple mutable `Task.result` writers | Candidate history, verification decisions, append-only run ownership, release state | **BLOCK T6** |
| Adaptive themes and narrative | Optional theme/narrative shapes | Independent narrative generation from raw transcript | Mandatory released-claim coverage, coverage request, no-new-claim synthesis | **BLOCK T5** |
| Summary/Analysis projections | Same Pydantic alias | Independent generation and re-analysis | One run ID, deterministic projections, no competing ontology/persistence | **BLOCK T6/T7** |
| Post-generation release gates | Partial high-risk guard | No unified release gate | `needs_review`, gate failures, exact-value/narrative coverage, epistemic separation | **BLOCK** |

## 7. Explicit architecture answers

**Is discovery open and adaptive?**

Only the isolated T1 vocabulary is open. Production behavior remains constrained
by fixed forms and predetermined sections.

**Can absent concepts be omitted without placeholders?**

T1 can represent sparse output correctly. The live prompt, legacy payload and UI
still force or display placeholders.

**Does every released statement resolve to source evidence?**

No. References can be graph-consistent while selectors/hashes remain unresolved
against the authoritative source revision.

**Can useful insight and hypotheses be preserved without releasing them as fact?**

Only partially for high-risk claims. Ordinary inference/hypothesis and all
relationships lack sufficient release constraints.

**Are Summary and Analysis truly projections of one ledger?**

No. A shared type alias exists, but live services generate and persist competing
outputs.

## 8. Recommended atomic task: T1.1 lifecycle/release contract hardening

Complete one contract-only task before T2 production integration.

### Exclusive ownership

- `src/services/investigation/contracts.py`
- `tests/test_adaptive_summary_contracts.py`
- One T1.1 review artifact after verification

Do not modify live worker/API/UI behavior in this atomic task.

### Required design

1. Introduce a canonical `InvestigationRun` owner instead of treating one final
   Summary/Analysis-shaped object as both ledger and projection.
2. Define separate typed envelopes for discovery candidate, verification
   decision, canonical ledger and released projections.
3. Represent at least `fact`, `inference`, `hypothesis` and
   `verification_action`; relationships must carry equivalent epistemic and
   verification state.
4. Permit factual narrative references only to atomic claims with
   `epistemic_status="fact"` and `disposition="supported"`.
5. Preserve contradicted, unverifiable and rejected candidates in the ledger but
   exclude them from factual projection.
6. Add `needs_review` and `failed` plus machine-readable gate failures.
7. Require every released claim to have exactly one primary theme and every
   factual sentence to map to one or more released claim IDs.
8. Retain explicit inference/hypothesis premises and human-verification state so
   analytical value is preserved without fact conflation.

### T1.1 quality gates

- The first four unsafe accepted rows in the negative table must fail release
  validation.
- An ordinary evidence-backed hypothesis remains storable but cannot enter
  factual narrative.
- A relationship inference remains storable with premise/evidence references and
  mandatory human-verification state.
- `needs_review` accepts diagnostic ledger/gate failures but cannot contain a
  released factual projection.
- Released-claim primary-theme coverage is 100%; overlap is zero.
- Existing sparse-value, ID/reference, high-risk and schema-hash tests remain
  green.
- Tests make no network or model call; schema hash is stable across processes.
- Compile, formatter/linter, targeted tests and `git diff --check` pass before an
  atomic commit/push.

After T1.1, continue in order with T2 robust evidence selectors, T3 adaptive
discovery, T4 verification/merge, T5 grounded projections, T6 append-only
persistence/orchestration and T7 adaptive UI.

## 9. Production decision

**Summary/Analysis architecture is BLOCKED from production promotion.**

T1 may remain as a non-integrated foundation, but passing its current unit tests
does not prove adaptive discovery, evidence resolution, one-ledger ownership,
projection completeness or investigative quality. Live Summary, Analysis or
Visualization must not be advertised as a verified evidence-grounded
intelligence pipeline until the stage gates above pass against the real runtime.

## 10. Residual risks

- The T0 Vietnamese human-labelled evaluation set and valid fixed-form baseline
  remain incomplete, so no model-quality improvement can be claimed.
- Evidence exactness is transcript-grounded only; ASR and diarization errors still
  require audio playback and human review.
- The production offline bundle, network-denied replay and complete model/runtime
  manifests remain separate blocking work.
- Multi-stage reasoning increases latency and GPU pressure; model assignment must
  be chosen by ablation and hardware-specific Pareto evaluation.
- Exact evidence quotes and analytical hypotheses are sensitive law-enforcement
  data and still require authorization, retention, legal-hold and redaction
  controls.
