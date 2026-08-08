# Adaptive Intelligence Evaluation Protocol v3

## 1. Objective and claim boundary

This protocol defines the T0 offline scorer pilot for the canonical contract shared by Summary and Analysis. It answers a narrow, falsifiable question: given versioned Vietnamese synthetic fixtures and canonical prediction JSON, does the scorer reliably detect coverage, exact-value, provenance, hallucination, sparse-output, theme, no-claim, and split-leakage failures?

The status `PILOT_PASS` means only that the deterministic scorer and supplied synthetic predictions passed these contract gates. It is **not human evidence of Vietnamese summary quality**, does not establish investigative correctness, does not rank models, and does not authorize AI output to be treated as verified evidence.

No model, network service, audio decoder, database, Ollama, vLLM, or cloud API is invoked by this pilot.

## 2. Versioned inputs

- Scorer: `scripts/evaluate_adaptive_contract.py`
- Canonical output contract: `src/services/investigation/contracts.py`
- Fixture corpus: `tests/eval/adaptive_contract_cases.jsonl`
- Dataset version: `adaptive-intelligence-pilot-v1.0`
- Protocol version: `adaptive-intelligence-eval-v3-pilot`
- Frozen split SHA-256: `2e9f7dd7d2bada9d07fb7813345899b5eee68cfae5e844b77688ea133dd50b54`

The pilot has four synthetic cases: a financial transfer with exact identifiers, a negated/conflicting report, Vietnamese-English code-switching, and a valid `no_extractable_claims` conversation. It is intentionally small; it validates the evaluator, not production quality.

Every fixture row contains:

1. `dataset_version`, stable `id`, frozen `split` (`train`, `dev`, or `blind`), and deterministic `source_revision_id`.
2. Exact transcript and stable source segments.
3. `allow_no_claims`, which permits the empty gold state only for an intentionally non-factual conversation.
4. `gold_claims` with open `claim_type`, polarity, salience, explicit nested `attributes`, and a unique exact `evidence_quote` resolved against source segments.

Every prediction JSONL row contains:

1. `case_id`.
2. `prompt_example_case_ids`, used only for leakage auditing.
3. `prediction`, validated as `AdaptiveSummaryAnalysisContract`.

Prediction and model-generated claim IDs are never matching keys.

## 3. Frozen split and leakage policy

The published case-to-split mapping is hashed with canonical UTF-8 JSON. Changing any case split requires a new dataset version and a new published fingerprint; silently rewriting the v1 split is an input error.

Prompt examples obey both rules:

- Only `train` cases may be prompt examples.
- A case may not use itself as an example.

`dev` is available for threshold and prompt development but cannot be used as an in-context example by this protocol. `blind` cannot be used for prompt construction, few-shot examples, model selection, threshold tuning, or error-driven prompt edits. Any unknown, self, dev, or blind prompt-example reference fails the leakage gate.

The synthetic blind rows are stored in Git, so “blind” here is a workflow contract rather than secrecy against a person reading the repository. The later human corpus must keep blind labels and annotations access-controlled until the prompt/model/config is frozen.

## 4. Metric definitions

### 4.1 Atomic claim match

A gold claim and prediction match only when all of the following are equal after NFKC, whitespace, and case normalization:

1. Open `claim_type`.
2. `polarity`.
3. Every explicit scalar path/value in gold `attributes` exists with the same value in prediction `attributes`.

Claim IDs, evidence IDs, model IDs, statement wording, and array order do not determine a match. Pairing is one-to-one. Duplicate gold signatures are rejected by the fixture loader.

### 4.2 Adaptive discovery versus slot filling

The evaluator does not publish a closed enum of business claim types. Fixture claim types such as verification conditions, reported records, backup identifiers, and newly introduced domain concepts are matched as open strings plus evidence-bound attributes.

Salience weights prioritize evidence-backed people/roles, events/actions, time, place, amounts, accounts, codes, and other exact identifiers when they are actually present. These are recall priorities, not mandatory output slots: a concept absent from the transcript must be omitted rather than emitted as an empty row.

The adaptive discovery gate requires complete atomic-claim recall, complete critical recall, exact-value accuracy `1.0`, zero optional filler emission, and zero legacy fixed top-level slots. A prediction that preserves familiar person/time/money fields but omits an unexpected verification action or relation fails this gate. Top-level form keys such as `people`, `time`, `location`, `financial_info`, `risk_assessment`, and `timeline` are rejected; sparse concepts belong in evidence-backed claims/attributes and absent concepts are omitted.

This does not require extractive copying. The prediction statement may paraphrase, but claim identity/value binding and an exact source evidence quote must remain verifiable. A template shell with copied values but missing discovered atomic claims cannot pass weighted coverage or the adaptive discovery gate.

### 4.3 Salience coverage

Weights are fixed before evaluation:

| Salience | Weight |
|---|---:|
| `critical` | 5 |
| `important` | 2 |
| `optional` | 1 |

`weighted_salience_coverage = sum(weights of matched gold claims) / sum(weights of all gold claims)`.

The empty-gold denominator is defined as `1.0` only for a valid `no_extractable_claims` case.

### 4.4 Critical precision and recall

- `critical_recall = exactly matched critical gold claims / all critical gold claims`.
- A critical prediction candidate is a prediction sharing open `claim_type + polarity` with a critical gold claim.
- `critical_precision = exactly matched critical prediction candidates / all critical prediction candidates`.
- If no critical gold/candidate exists, the corresponding metric is `1.0`; a missing critical prediction still produces recall `0` because its gold denominator is non-zero.

Predicted claims outside all critical type/polarity keys are still included in unsupported-claim and hallucination gates.

### 4.5 Exact-value accuracy

Every scalar leaf in gold `attributes` is an exact-value cell. The scorer pairs same-type/polarity claims by maximum explicit attribute agreement without reusing a prediction.

`exact_value_accuracy = correctly retained normalized cells / all gold normalized cells`.

This checks values and their attribute binding, not mere occurrence somewhere in the output. It covers money, account, time, location, person/role, code, and other open attributes declared by a fixture.

### 4.6 Evidence resolution

For every emitted evidence span:

1. `segment_id` must resolve to the fixture segment.
2. `quote_exact` must occur exactly in that segment.
3. `quote_sha256` must match the exact UTF-8 quote.
4. `source_sha256` must match the exact UTF-8 segment text.
5. If raw offsets are emitted, the transcript slice must equal `quote_exact`.
6. An exactly matched claim must cite every gold segment/quote pair assigned to it.

All checks must pass. A valid `no_extractable_claims` case is the only case allowed to emit zero evidence spans.

### 4.7 Source revision and provenance

Each fixture locks `source_revision_id` to the exact string `fixture:<dataset_version>:<case_id>`. Revision IDs must be unique; changing source text under the same revision is forbidden.

Prediction provenance must satisfy all four exact checks:

1. `source_revision_id` equals the fixture value.
2. `raw_transcript_sha256` equals SHA-256 of the fixture transcript's exact UTF-8 bytes.
3. `normalized_transcript_sha256` equals SHA-256 after NFKC normalization, whitespace collapse, and case folding.
4. `segment_count` equals the number of fixture source segments.

These checks are independent of schema validity. An arbitrary non-empty revision string or syntactically valid but wrong 64-character hash fails the provenance gate.

### 4.8 Unsupported claims and hallucinated numbers

Any predicted claim not matched one-to-one to a gold claim is unsupported for this fixture. Numeric tokens are extracted only from factual claim statements/attributes and narrative, not manifests or evidence metadata.

A predicted numeric token is hallucinated when it appears in neither the transcript nor an explicit gold normalized attribute. This whitelist allows a supported normalization such as `50 triệu` to `50000000` while still catching a fabricated value such as `70000000`.

Each hallucinated number is a severe hallucination. An unmatched high-risk hypothesis also counts as severe. The pilot release gate requires zero severe hallucinations and zero unsupported claims.

### 4.9 Empty optional emission

The numerator counts optional properties or collection rows explicitly emitted as any of:

- `null`;
- blank string;
- empty object/list;
- normalized placeholder `Không có thông tin`, `Cần xác minh thêm`, `Không rõ`, `N/A`, or `null`.

The denominator is the number of optional properties plus collection rows actually emitted. If no optional property or row is emitted, the rate is defined as `0.0`, not undefined or perfect-by-omission. The required sentinel `claims=[]` in a valid `no_extractable_claims` payload is not an empty optional row.

Both the count and rate are reported. The hard gate uses the absolute count `0`.

### 4.10 Primary themes and no-claim state

A claim may appear in at most one primary theme. Each repeated `claim_ref` across themes adds one duplicate assignment and fails the gate.

Gold `no_extractable_claims` requires prediction status `no_extractable_claims`, `claims=[]`, and omission of evidence, concepts, relationships, themes, and narrative. Any populated optional business surface fails closed.

## 5. Pilot gates

Every case must satisfy all applicable conditions:

1. Canonical schema valid.
2. Run status matches gold and no-claim state is valid.
3. Weighted salience coverage `1.0`.
4. Critical precision and recall `1.0`.
5. Exact-value accuracy `1.0`.
6. Unsupported claim count `0`.
7. Severe hallucination count `0`.
8. Empty optional emission count `0`.
9. Duplicate primary-theme assignment count `0`.
10. Legacy fixed-slot artifact count `0` and adaptive discovery gate passes.
11. Evidence and gold-evidence alignment gates pass.
12. Source revision, raw/normalized transcript hashes, and segment count all match.
13. Global prompt-example leakage count `0`.

These strict values are appropriate for four deterministic synthetic scorer fixtures. Production thresholds must be locked separately using human labels and confidence intervals.

## 6. Determinism and integrity report

The report contains no generation timestamp, runtime latency, transcript, gold text, or prediction text. Keys and case ordering are deterministic.

It records:

- SHA-256 of exact fixture and prediction files.
- SHA-256 of the scorer and canonical contract source bytes.
- SHA-256 of the canonical evaluation payload.
- SHA-256 of the report payload before inserting that self-reference field.
- Git revision, tracked dirty state, untracked state, and status for relevant scorer/contract/input paths.
- Dataset version, frozen split fingerprint, metric contract, aggregate, and per-case metrics.

The report file itself can additionally be hashed with `Get-FileHash`; that external file hash is intentionally not embedded recursively in the file.

## 7. Required tamper tests

`tests/test_adaptive_eval_harness.py` must prove that the scorer catches:

1. Missing critical claim.
2. Fabricated normalized number.
3. Unsupported quote, quote hash, source hash, or raw offset.
4. Null or placeholder optional value.
5. Duplicate primary theme.
6. Invalid `no_extractable_claims` payload.
7. Dev/blind/self prompt-example leakage.
8. Frozen split mutation.
9. Non-semantic model claim-ID changes do not change matching.
10. Two identical CLI runs produce byte-identical reports.
11. A familiar identifier-only/template output still fails when it omits a discovered claim.
12. Legacy top-level slot shells are rejected rather than treated as intelligence synthesis.
13. Source revision ID, raw/normalized transcript hash, and segment-count tampering all fail.

## 8. Human-labeled corpus protocol for the next task

The T0 synthetic pilot must not be expanded ad hoc into a quality claim. A human corpus requires a new version and the following pre-registered process.

### 8.1 Annotation and qualification

- Annotators must be native or professionally proficient Vietnamese readers trained on atomic claims, polarity/modality, evidence spans, salience, exact-value binding, contradiction, and `absent` versus `unknown`.
- Investigative salience guidelines must be approved by a qualified domain reviewer; annotators must not infer guilt or legal conclusions.
- Before production annotation, each annotator completes a calibration set and must reach at least 0.90 critical-claim recall, 0.95 exact-value accuracy, and 0.85 span token F1 against adjudicated calibration labels.
- Real sensitive data must not be committed to Git. Dataset manifests store legal/privacy status, de-identification method, access scope, and cryptographic hashes.

### 8.2 Independent annotation, IAA, and adjudication

- Every blind-test case receives two independent annotations before either annotator sees the other result.
- Report Cohen's kappa for claim category and polarity, weighted kappa for salience, and token/span F1 or IoU for evidence.
- Pilot acceptance thresholds are category/polarity kappa at least 0.80, salience weighted kappa at least 0.70, and span token F1 at least 0.85.
- If a threshold fails, revise the guideline and re-annotate a new calibration sample; do not adjudicate disagreement away and call the unreliable labels valid.
- A third qualified adjudicator resolves final gold labels and records the reason for each material disagreement.

### 8.3 Frozen splits and leakage control

- Assign case IDs and train/dev/blind splits before prompt/model tuning; publish a split fingerprint and dataset manifest hash.
- Train may supply prompt examples. Dev may tune prompts, thresholds, and model selection but may not be copied as few-shot examples into scored runs. Blind remains inaccessible until all configs and gates are frozen.
- Record prompt-example IDs, model digest, prompt/schema/source hashes, decoding parameters, seed, and Git state for every run.

### 8.4 Power plan

- Begin with a double-annotated 30-case annotation pilot to estimate per-slice prevalence, disagreement, paired win variance, and critical-claim frequency.
- Before collecting the blind set, run a documented paired-power simulation for the primary endpoint: human preference over the fixed `investigation-v1` baseline, two-sided alpha `0.05`, power at least `0.80`, and minimum detectable absolute preference lift `0.10` above `0.50`.
- Use the larger of the simulated sample size, 100 paired blind cases, or the size needed to provide at least 30 cases for each pre-registered critical slice. Expand rare slices deliberately and report macro as well as micro metrics.
- Promotion still requires the lower bound of a paired 95% bootstrap confidence interval above `0.50`, zero severe hallucinations, and no critical slice below its locked recall gate.

## 9. Rerun command

Given a canonical prediction JSONL:

```powershell
python scripts/evaluate_adaptive_contract.py `
  --fixtures tests/eval/adaptive_contract_cases.jsonl `
  --predictions path/to/predictions.jsonl `
  --output path/to/adaptive-eval-report.json
```

Exit codes:

- `0`: all pilot gates pass;
- `1`: inputs are valid but one or more evaluation gates fail;
- `2`: fixture/prediction protocol input is invalid.
