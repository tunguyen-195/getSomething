# T2 Immutable Source Revision And Evidence Selector Audit

Date: 2026-08-09

## 1. RTK objective

Implement and falsify the isolated T2 foundation required by
`docs/plans/2026-08-09-adaptive-investigative-intelligence-plan.md`:

- seal an immutable transcript revision with exact source, normalized source,
  stable segments, speaker/time metadata, optional audio hash, and scope;
- resolve exact transcript evidence deterministically across repeated quotes,
  Unicode normalization, whitespace normalization, and overlapping matches;
- reject cross-case, cross-file, cross-source, stale-revision, and resealed
  tampering;
- allow only replayed evidence artifacts to enter the production T1 trusted
  context adapter;
- remain offline and make no database, network, model, or runtime service call;
- exclude case/file creation and upload timestamps from model input artifacts.

This task does not implement T3 LLM discovery, T4 verification, T5 narrative
reasoning, T6 persistence, or T7 UI integration. It therefore makes no claim
that the live Summary or Analysis product is already improved.

## 2. Owned surface

- `src/services/investigation/source_revision.py`
- `src/services/investigation/evidence_selector.py`
- minimal integration in `src/services/investigation/run_contracts.py`
- lazy exports in `src/services/investigation/__init__.py`
- `tests/test_investigation_evidence_selectors.py`

The repository contained many unrelated tracked and untracked changes. This T2
task did not revert, stage, commit, push, or modify those surfaces.

## 3. Implemented invariants

### 3.1 Source revision

- Exact raw transcript bytes are represented by `raw_transcript_sha256`.
- Normalized transcript uses NFKC, Unicode casefold, and collapsed Unicode
  whitespace, matching the locked T0 evaluation provenance policy.
- `unicodedata.unidata_version` is sealed into the canonical revision and a
  runtime-table mismatch fails closed.
- Offsets explicitly use Python/Unicode code points through
  `offset_unit="unicode_code_point"`; consumers must not silently interpret them
  as JavaScript UTF-16 code units.
- Segment identity binds scope, order, exact text hash, raw and normalized
  offsets, speaker, and time.
- Revision identity binds scope, normalization policy, Unicode table version,
  offset unit, raw/normalized hashes, optional audio hash, and all segments.
- Pydantic `model_copy()` products are serialized and revalidated at every
  source boundary because `model_copy()` itself does not execute validators.

### 3.2 Evidence selector

- A selector stores the exact and normalized quote, raw and normalized offsets,
  a fixed 32-code-point prefix/suffix, global overlapping occurrence index,
  segment/speaker/time, scope, segment hash, transcript hashes, and revision
  hash.
- Repeated quotes require segment, context, or occurrence disambiguation.
- Quotes crossing segment boundaries fail closed.
- `EvidenceSpan.source_sha256` remains the exact segment-text SHA-256 required by
  the existing T0/T1 evaluator; whole-transcript and revision hashes remain
  separate selector fields.
- Artifacts carry audio hash and segment count so production run provenance can
  be compared with the replayed source, not merely trusted by shape.
- Build and replay normalize the full source once and cache occurrence indexes
  per unique quote.
- Compatibility characters whose NFKD form begins with a combining mark are
  grouped with their predecessor. The previous quadratic prefix-normalization
  fallback was removed; an unknown boundary now fails closed.

### 3.3 Trust adapter

- `VerifiedEvidenceSelectorArtifact` can only be created by successful replay.
- The wrapper stores sealed validated JSON, revalidates on access, and rejects
  reassignment.
- The production public context builder accepts only verified wrappers and
  separates verification and relationship registries.
- Run provenance is compared with attested source revision ID, raw hash,
  normalized hash, optional audio hash, and segment count before `success`.
- The resulting trusted context is write-once and uses mapping proxies.
- The old private T1 fixture adapter remains only for regression compatibility;
  it is not the public production T2 path.

## 4. Falsification coverage

The focused harness covers:

- exact immutable roundtrip and timestamp-field exclusion;
- NFKC, casefold expansion, Unicode whitespace, decomposed Vietnamese text,
  compatibility ligatures, Hangul, halfwidth voiced Katakana, and non-BMP
  offset units;
- raw-normalized mapping idempotence and aligned range roundtrip;
- duplicate, repeated, overlapping, context-disambiguated, and occurrence-
  disambiguated quotes;
- cross-scope, cross-revision, cross-segment, hash, quote, offset, context,
  occurrence, segment, speaker, time, audio, and segment-count tampering;
- canonical order and duplicate evidence IDs;
- verification and relationship registry kind/key enforcement;
- `model_copy()` bypass attempts against source revision, scope, segment draft,
  selector request, and selector artifact;
- post-replay wrapper/context mutation attempts;
- deterministic hashes across four `PYTHONHASHSEED` values;
- seeded generative normalization/selector properties.

## 5. Repeatable gates and current evidence

Focused T2:

```powershell
venv\Scripts\python.exe -m pytest --noconftest tests/test_investigation_evidence_selectors.py -q
```

Result: `39 passed`.

Extended T0/T1/context regression:

```powershell
venv\Scripts\python.exe -m pytest tests/test_adaptive_summary_contracts.py tests/test_adaptive_eval_harness.py tests/test_context_analysis.py tests/test_investigation_knowledge.py tests/test_context_eval_harness.py -q
```

Final serial result: `148 passed, 13 pre-existing warnings`. The suite was run
serially because concurrent agents share the same PostgreSQL test database.

Static gates:

```powershell
venv\Scripts\python.exe -m black --check <owned Python files>
venv\Scripts\python.exe -m flake8 --max-line-length=88 --extend-ignore=E203 <owned Python files>
venv\Scripts\python.exe -m mypy --check-untyped-defs <owned source/test files>
venv\Scripts\python.exe -m compileall -q <owned Python files>
```

Final result: Black, Flake8, MyPy, and compileall passed.

Additional property harnesses:

- 5,000 seeded mixed-Unicode strings matched the independent
  `NFKC -> casefold -> whitespace collapse` oracle.
- All 917 code points in Unicode 14.0 whose NFKD form begins with a combining
  code point matched the oracle across four representative bases.
- Import order passed in three fresh-process module orders.
- Four `PYTHONHASHSEED` values (`1`, `2`, `123`, and `random`) produced the same
  revision hash `ea001178...320fb` and selector artifact hash
  `80cd2a5c...1dde4`.
- Source and selector schemas contain none of `created_at`, `creation_time`,
  `uploaded_at`, or `upload_time`.
- Owned-file `git diff --check` and trailing-whitespace scans passed.

Diagnostic performance observation on the current Windows/Python environment:

- halfwidth voiced Katakana normalization at 400/800/1600/3200/6400 pairs:
  `0.00085/0.00154/0.00376/0.00597/0.01286` seconds;
- combining-mark normalization at the same sizes:
  `0.00029/0.00052/0.00105/0.00210/0.00448` seconds;
- Independent final cardinality run at 6,400 items: source revision `0.604s`,
  selector build `1.092s`, and replay verification `1.002s`.

These timings are diagnostic observations, not a production SLA.

## 6. Independent audit remediation log

The independent read-only audit initially reproduced four material findings:

1. An artifact produced by `model_copy(update={...})` could skip canonical model
   validation when passed as an already-instantiated object.
2. A verified wrapper's artifact reference could be replaced after replay.
3. A copied source revision with changed raw text and stale hashes could reach
   selector build/replay if the selected quote was unaffected.
4. Halfwidth voiced Katakana could trigger a quadratic full-prefix NFKC fallback.

Remediation:

- serialize and revalidate all immutable Pydantic inputs at trust boundaries;
- store sealed JSON in a write-once verified wrapper and freeze trusted context;
- add negative regression attacks for copied instances;
- replace the prefix fallback with compatibility-aware normalization units and
  fail closed on an unsupported boundary.

The post-remediation audit then reported and closed two additional findings:

- `SCR-001`: substantive text could remain outside declared segments. The
  builder now permits only whitespace in segment gaps, while replay rejects a
  forged legacy revision containing uncovered substantive text.
- `SCR-002`: normalized range mapping and repeated-occurrence selection still
  contained cardinality scans. Bisect-backed indexes and direct occurrence
  lookup removed the identified quadratic behavior.

Final independent verdict: **PASS - no remaining blocking findings.**

## 7. Artifact hashes

Hashes of the final audited code and focused harness:

```text
source_revision.py   8FD6A4D7C0EBDC699169368683CC747CC754C09D2EEEC958900FB050EC06C5B6
evidence_selector.py E33B7E6988066455B5F7B68F1F38F3868864A1A4B5B74C026C010F5844E817B1
run_contracts.py     6F39E4B5397A807C7A4528B8DCCA91D92B11CB643014059C8CBE258E5B3CA505
__init__.py          0E954CC37F600D41BA07086D58277B2D1235F1D6C24D88491F2B0C247553460A
test harness         B7A7593F4E6206B090379CC3114644468B65711522E96636B9E1B0B6C103E5CC
```

## 8. Residual risks and explicit non-claims

1. Transcript selectors prove exact transcript attribution, not truth in the
   audio. `grounding_basis="transcript_only"` and `audio_grounded=false` are
   deliberate even when an audio hash and time range exist.
2. T2 trusts the caller-supplied audio SHA-256. The upstream storage boundary
   must compute it from exact audio bytes and preserve chain of custody.
3. Python object opacity is not a cryptographic or hostile-code security
   boundary. T6 should add persisted signatures/MACs or process isolation if
   artifacts cross a hostile trust boundary.
4. T1 `EvidenceSpan` does not itself carry `offset_unit`; consumers must resolve
   the T2 source revision/artifact. T6/T7 must not expose bare offsets without
   this metadata, especially to JavaScript clients.
5. The full live Summary/Analysis pipeline does not consume T2 yet. Production
   promotion remains blocked on T3-T7 and the offline model/runtime gates.
6. The 13 regression warnings are pre-existing deprecations outside the atomic
   T2 ownership surface.
