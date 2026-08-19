# Research Roadmap for Lawful Investigative Product Capabilities

**Date:** 2026-08-14  
**Workspace:** `E:\research\STT`  
**Scope:** research and prioritization only; no source implementation in this task

## 1. Product objective and decision rule

Develop the audio-intelligence product into an assistive workspace that helps an
authorized analyst answer evidence questions faster, with fewer omissions and
without increasing unsupported person-level conclusions.

The primary outcome is **analyst time-to-correct-answer**, not the number of
models, extracted fields, charts, or generated words.

A capability is promoted only if a locked, blind comparison shows that it:

1. reduces time-to-answer or effort on representative Vietnamese cases;
2. preserves or improves answer correctness and critical evidence recall;
3. does not increase unsupported claims, wrong speaker/value ownership,
   unauthorized disclosure, or audit gaps;
4. works offline on the declared release hardware and artifacts;
5. exposes uncertainty and lets the analyst inspect and correct the evidence.

## 2. Research foundations

The official and primary sources support a restrained product direction:

- UNODC describes link, event, flow, activity, frequency, correlation,
  premise/inference, hypothesis, and intelligence-gap analysis. Charts organize
  information; they are not independent factual authorities.
- INTERPOL states that timely and accurate criminal intelligence analysis helps
  join data points and understand crime phenomena, while its INTERPOL/UNICRI AI
  Toolkit requires responsible use aligned with policing principles, human
  rights, ethical standards, practical governance, and lifecycle controls.
- NIST AI RMF requires scoped use, benchmarks, uncertainty measurement,
  repeatable TEVV, feedback, independent review, and human oversight.
- NIST OpenASR, SRE24, and DIHARD III provide evaluation patterns for ASR,
  speaker/person detection, and “who spoke when”; none authorizes treating a
  diarization label as identity proof.
- NIST IR 8387, SP 800-53, SP 800-92, and SP 800-207 support hashes,
  preservation, configurable security/privacy controls, robust log management,
  per-resource authentication/authorization, and no implicit trust from network
  location.

These sources do not establish Vietnamese product accuracy, legal
admissibility, surveillance authority, or a right to process data. Those require
local law, agency policy, purpose limitation, case authority, and human review.

## 3. Priority model

Each capability is scored from 1-5 on:

- **User impact:** expected reduction in analyst time/omissions;
- **Evidence safety:** ability to remain traceable and avoid fact creation;
- **Architecture fit:** reuse of the current transcript/segment/simple-analysis
  path without reintroducing repair chains;
- **Evaluation readiness:** availability of baselines, metrics, and corpus;
- **Delivery cost:** reverse-scored; 5 means a smaller, safer increment.

Priority score is the unweighted sum. Safety gates override score.

| Rank | Capability | Impact | Safety | Fit | Eval | Cost | Total | Decision |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1 | Evidence retrieval with audio seek | 5 | 5 | 5 | 4 | 4 | 23 | Build first |
| 2 | Analyst feedback, correction, and evaluation loop | 5 | 5 | 4 | 5 | 3 | 22 | Build with capability 1 |
| 3 | Exact-value provenance and explicit flows | 5 | 4 | 4 | 4 | 4 | Build next |
| 4 | Contradiction and change detection | 5 | 4 | 4 | 4 | 3 | Build after exact values |
| 5 | Vietnamese ASR/diarization calibration | 5 | 5 | 3 | 3 | 2 | Parallel enabling program |
| 6 | Cross-file timeline and uncertain entity linking | 5 | 3 | 3 | 2 | 2 | Research pilot only |
| 7 | Offline audit and access-control hardening | 5 | 5 | 3 | 4 | 2 | Mandatory release workstream |

The order separates navigation/evidence wins from high-risk cross-file inference.

## 4. Capability contracts

### C1. Query-driven evidence retrieval and audio seek

**Analyst question:** “Đoạn nào trong các file được phép đề cập đến người, số
tiền, tài khoản, cuộc gặp hoặc chủ đề này, và tôi nghe lại đúng vị trí nào?”

**Baseline:** manual browser search through transcripts, then manually scrub the
audio; current analysis cards have no guaranteed evidence-to-audio navigation.

**Candidate:** case-scoped hybrid retrieval over transcript segments using
lexical search plus optional local embeddings. Return exact file, anonymous
speaker label, start/end, quote, neighboring context, source hash/revision, and
one-click seek. Retrieval ranks candidates but does not answer the question or
generate a fact.

**Architecture fit:** index immutable transcript segments after transcription;
bind every index row to case/file/task/transcript/segment hashes. Analysis cards,
timeline, relations, exact values, contradictions, and free-text search use one
evidence drawer and seek API. The v2 analysis LLM remains one-call and separate.

**Corpus and baseline protocol:** at least 100 de-identified Vietnamese queries
over 30+ authorized files, including names, ASR variants, numbers, paraphrases,
negation, no-answer queries, long files, and middle-position evidence. Compare
manual transcript search, BM25/FTS baseline, semantic-only, and hybrid ranking.

**Metrics:** Recall@5/10, MRR, nDCG@10, no-answer false-positive rate, seek-start
absolute error, time-to-first-correct-evidence, total time-to-correct-answer,
clicks/seeks, and analyst preference with bootstrap confidence intervals.

**Falsification:** reject the candidate if the 95% CI does not show lower median
time-to-correct-evidence than lexical search, if critical Recall@10 regresses,
or if a result resolves to a stale/wrong case, file, segment, or audio interval.

**Safety/privacy boundary:** authorization is evaluated before search and before
audio fetch; no cross-case index lookup; query/result/access events are audited;
snippets are minimized and redacted by role; embeddings remain offline and
case-scoped; retrieved text is data, not an instruction to an LLM.

**Promotion gate:** zero cross-case disclosure and dangling/stale selectors;
100% seek target resolution on locked fixtures; critical Recall@10 at least
0.95; no-answer false-positive rate below the locked pilot threshold; lower
time-to-correct-answer without lower answer correctness.

### C2. Analyst feedback, correction, and evaluation loop

**Analyst question:** “Tôi sửa speaker, câu chữ, thực thể, sự kiện hoặc quan hệ
này như thế nào; ai sửa; phiên bản nào đang có hiệu lực; hệ thống có tốt lên
thật hay chỉ học lại lỗi?”

**Baseline:** mutable task JSON and informal bug reports; corrections are not a
versioned evaluation dataset and cannot reliably supersede prior output.

**Candidate:** append-only correction events for transcript spans, speaker maps,
analysis items, entity aliases, event/relationship state, and reject/confirm
labels. A reviewed correction creates a new revision; it never silently edits
source evidence. De-identified/adjudicated corrections feed a versioned eval
set, not direct online model learning.

**Architecture fit:** add a correction/annotation layer beside tasks rather than
embedding edits into LLM output. Reuse evidence selectors and task/source hashes.
Projection shows original, correction, reviewer, reason, revision, and
supersession. Training/evaluation export is a separate authorized workflow.

**Baseline and corpus:** seed with the current replay fixtures and a 30-case
double-annotation pilot. Expand only after the label guide stabilizes. Preserve
original model/prompt/config output for paired regression.

**Metrics:** correction completion time, correction reopen/reversal rate,
reviewer agreement, adjudication rate, stale-projection count, correction-to-eval
latency, regression recurrence rate, and post-fix error reduction by slice.

**Falsification:** reject if edits overwrite evidence, prior revisions cannot be
reconstructed, reviewer agreement remains below the locked pilot threshold, or
accepted corrections do not reduce recurrence on an untouched blind set.

**Safety/privacy boundary:** role-based correction/review permissions; reason and
identity audit; no automatic promotion of user edits to shared model truth; no
cross-case training export without purpose/authority, minimization, redaction,
retention, and approval.

**Promotion gate:** every displayed correction resolves to immutable source and
revision; zero silent overwrite; stale artifacts visibly withheld; 100% audit
event completeness; blinded regression set improves without new critical errors.

### C3. Exact-value provenance and explicit money/object flows

**Analyst question:** “Những số tiền, tài khoản, số điện thoại, biển số, mã,
ngày giờ, số lượng và tài liệu nào được nhắc đến; ai nói, ai sở hữu/gửi/nhận,
đơn vị là gì; luồng nào thực sự được nói rõ?”

**Baseline:** LLM lists and entity-frequency views that can omit duplicates,
lose owner/unit binding, or turn mention co-occurrence into a flow.

**Candidate:** deterministic detectors plus one-call LLM context extraction,
with every value stored as surface text, normalized form, type/unit, speaker,
file/time, owner/action/recipient when explicit, polarity/modality, evidence
quote, and ambiguity. Flow charts require explicit source, target, and object.

**Architecture fit:** detectors run on transcript segments and provide candidates;
the existing analysis payload displays verified/tolerant items. The projector
creates cards/tables and directed flows but never fills a missing endpoint.

**Corpus and baseline:** mutation pairs for digit/word forms, Vietnamese units,
currency, dates, accounts, phones, IDs, plates, negation, reported speech,
owner/recipient reversal, repeated values, and ASR errors; plus authorized real
audio with human transcript/reference spans.

**Metrics:** span precision/recall/F1; normalized-value accuracy; type/unit,
owner, sender, recipient, polarity, and modality accuracy; explicit-flow edge
precision/recall; critical omission rate; wrong-owner count.

**Falsification:** reject if improvement in value recall increases wrong owner,
unit, polarity, or fabricated flow edges; more detected numbers alone is not a
success.

**Safety/privacy boundary:** sensitive values are masked by default and revealed
only to authorized roles with logging; no external validation/network lookup;
values and relationships remain source statements, not verified ownership or
criminal findings.

**Promotion gate:** critical exact-value recall at least 0.95, precision at least
0.99, normalized-value/unit accuracy at least 0.99, wrong-owner/recipient count
zero, explicit-flow edge precision at least 0.98, zero revealed value without
authorization and audit.

### C4. Contradiction and change detection

**Analyst question:** “Lời khai/thông tin nào khác nhau theo file hoặc thời
điểm; khác ở giá trị, người, địa điểm, trạng thái hay phủ định; điều gì cần xác
minh tiếp?”

**Baseline:** analysts compare summaries/transcripts manually; current one-file
LLM may list a contradiction but has no durable canonical proposition or
cross-revision change ledger.

**Candidate:** canonicalize only conservative atomic source statements, compare
polarity, modality, actor/action/object, exact values, described time, and
source revision; emit contradiction/change candidates with both evidence sides
and an unresolved state. An LLM may explain a surfaced pair but cannot choose
which statement is true.

**Architecture fit:** consume exact-value/source-assertion records from C3 and
versioned corrections from C2. The UI uses a matrix/list plus evidence seek.
Do not create an independent multi-call critic pipeline.

**Corpus and baseline:** synthetic matched/mismatched proposition pairs, temporal
updates, corrections, legitimate non-conflicts, reported speech, and Vietnamese
human-labelled cross-file cases. Baselines: exact-key/rule matching and analyst
manual review.

**Metrics:** contradiction pair precision/recall/F1; change-type accuracy;
false merge/split rate; evidence-side completeness; time-to-identify material
conflict; verification-question usefulness.

**Falsification:** reject if routine updates are mislabelled as contradictions,
if incompatible statements are merged, if one evidence side is missing, or if
the system asserts a winner without external corroboration/human decision.

**Safety/privacy boundary:** “contradiction” means incompatible recorded
statements, not deception; no lie/credibility/guilt score; preserve source,
reported status, revision, and authorized case scope.

**Promotion gate:** material-pair precision at least 0.98 and recall at least
0.95 on the locked corpus; contradictory hard merges zero; both evidence sides
resolve 100%; lower analyst detection time without increasing false accusations.

### C5. Vietnamese ASR and diarization calibration

**Analyst question:** “Bản chép và nhãn người nói đáng tin đến mức nào cho file
này; phần nào cần nghe lại hoặc không nên dùng để gán người/số tiền?”

**Baseline:** aggregate model/runtime diagnostics and uncalibrated confidence;
failed diarization can resemble a verified one-speaker result. Existing local
A/B runs have no human transcript and therefore are not accuracy evidence.

**Candidate:** a frozen Vietnamese corpus and calibrated quality layer that
reports ASR/speaker/timing uncertainty by condition, flags spans requiring
review, and distinguishes `verified_one_speaker`, `multi_speaker`, `degraded`,
`unavailable`, and `failed`.

**Architecture fit:** keep ASR and diarization provider-neutral manifests and
metrics upstream of Analysis. Downstream analysis receives anonymous clusters,
quality state, and span uncertainty; sensitive speaker-dependent claims are
qualified/withheld when quality is degraded.

**Corpus and baseline:** authorized/de-identified Vietnamese telephone,
room/field audio, regional accents, code-switching, noise/reverb, overlap,
one-to-eight speakers, silence, names/numbers/accounts/plates, and short/long
durations. Double-annotate transcript, word times, speaker turns, and critical
fields. Compare current large-v2/pyannote path with pinned challengers.

**Metrics:** WER/CER; critical-field precision/recall; omitted voiced seconds;
false speech in silence; timestamp MAE; DER/JER; speaker-count accuracy; overlap
recall; cpWER/tcpWER or speaker-attributed WER; calibration error/coverage-risk;
RTF, RAM/VRAM, and unresolved mapping rate.

**Falsification:** reject a model/calibrator if aggregate WER improves while any
critical field/speaker/noise slice materially regresses, if selective abstention
does not achieve its declared risk coverage, or if confidence is presented as a
correctness probability without calibration.

**Safety/privacy boundary:** diarization clusters are not identities; no emotion,
gender, age, ethnicity, deception, or health inference; raw authorized audio and
human labels remain outside Git with controlled access and retention.

**Promotion gate:** thresholds frozen after pilot; no critical slice below its
locked non-inferiority boundary; wrong-speaker sensitive attribution zero;
calibration/abstention coverage met; offline artifact/model/config reproduction
and network-denied run PASS.

### C6. Cross-file timeline and uncertain entity linking

**Analyst question:** “Qua các file được phép trong cùng vụ việc, sự kiện diễn
ra theo thứ tự nào; các tên/tài khoản/mã nào có khả năng cùng một thực thể; bằng
chứng và mức chưa chắc chắn là gì?”

**Baseline:** per-file analysis cards and manual cross-file comparison; exact
string matches either miss aliases or over-merge common names.

**Candidate:** first build a cross-file timeline from explicit described times
and neutral source order. Entity linking emits candidates using exact
identifiers, normalized strings, stated aliases, and contextual evidence; it
never auto-merges ambiguous people. Analysts confirm/reject links, producing a
versioned map.

**Architecture fit:** consume C1 evidence selectors, C2 corrections, C3 exact
values, and C5 quality states. Store file-local mentions separately from
case-local canonical entity candidates. Visualization distinguishes confirmed,
candidate, rejected, and conflicting links.

**Corpus and baseline:** multi-file cases with aliases, homonyms, repeated phone/
account/document identifiers, corrections, conflicting dates, relative time,
and no-link cases. Baselines: exact string/identifier matching and manual review.

**Metrics:** entity-link pair precision/recall/F1 and B-cubed/CEAF where suitable;
false-merge count; unresolved rate; event-time extraction accuracy; pairwise
ordering accuracy; timeline evidence coverage; analyst time-to-reconstruct case.

**Falsification:** reject if false merges of people/accounts occur, if relative
or audio times are presented as exact event time, if stale revisions remain in
the timeline, or if time savings require lower reconstruction correctness.

**Safety/privacy boundary:** case-scoped only; cross-case linking is prohibited
without separate explicit authority; candidate links are not identities or
association proof; no location tracking/geocoding unless explicitly authorized
and necessary.

**Promotion gate:** sensitive-identifier false merges zero; person-link precision
at least 0.99 with uncertain cases unmerged; explicit-time accuracy at least
0.99; pairwise ordering at least 0.95; 100% event/link evidence resolution;
lower reconstruction time without lower correctness.

### C7. Offline, access-controlled, auditable deployment

**Analyst question:** “Ai có thể xem/chạy/sửa/xuất dữ liệu nào; hệ thống có hoạt
động không mạng; mọi truy cập và thay đổi có kiểm chứng được không?”

**Baseline:** authentication/case checks and some audit infrastructure exist,
but offline release completeness, least-privilege roles, export governance,
tamper-evident logs, model manifests, and clean-machine reproduction remain
incomplete.

**Candidate:** deny-by-default per-case/per-resource authorization, explicit
roles for view/reveal/analyze/correct/review/export/admin, session/device checks,
network-denied model execution, signed/hash-bound release manifests, append-only
audit events, retention/legal-hold/redaction controls, and export confirmation.

**Architecture fit:** harden API/service boundaries, not only frontend buttons.
Bind tasks, indexes, corrections, analysis artifacts, exports, model/config, and
audit records to immutable IDs/hashes. Health checks distinguish artifact
availability, load readiness, and live model state without unexpected network or
GPU load.

**Baseline and corpus:** permission matrix across cases/roles/actions; attack
fixtures for IDOR, stale sessions, cross-case search, hidden-value reveal,
export bypass, log injection, prompt injection, network fallback, tampered
models/manifests, missing migrations, and clean-machine installation.

**Metrics:** unauthorized access/reveal/export count; audit coverage and
ordering; manifest/hash mismatch detection; network attempt count; external
cache mutation; recovery time; clean-install success rate; supported-hardware
latency/resource budget.

**Falsification:** reject release if any unauthorized action succeeds, a material
action lacks an audit event, logs contain raw secrets unnecessarily, offline mode
uses network/provider fallback, tampered assets load, or a clean clone cannot
reproduce the declared stack.

**Safety/privacy boundary:** collect and expose only data necessary for the
authorized purpose; enforce retention and legal hold; do not claim that technical
controls establish legal authority or admissibility; no automated adverse person
decision.

**Promotion gate:** zero unauthorized accesses/exports in the locked matrix;
100% material-action audit completeness; network-denied replay and clean-machine
preflight PASS; tamper/missing asset fails before processing; secrets scan PASS;
restore/recovery drill and independent access-control review PASS.

## 5. Recommended development sequence

### Phase A - Evidence navigation and learning foundation

1. C1 evidence retrieval/audio seek.
2. C2 correction, review, and evaluation ledger.
3. Shared blind time-to-answer study harness.

This phase should deliver the first directly measurable analyst benefit while
creating the evidence and labels needed for later features.

### Phase B - High-value structured intelligence

4. C3 exact values and explicit flows.
5. C4 contradictions and changes.
6. Extend evidence seek/corrections to every structured item.

These capabilities must remain deterministic or evidence-bound and must not
reintroduce multi-stage semantic rejection into the simple analysis request.

### Phase C - Quality calibration and multi-file synthesis

7. C5 Vietnamese ASR/diarization calibration runs in parallel from the start,
   but model promotion waits for the frozen corpus.
8. C6 cross-file timeline first; uncertain entity linking only after C1-C5 are
   stable and false-merge evaluation is available.

### Phase D - Release authority

9. C7 access control, audit, offline bundle, and clean-machine gate is mandatory
   throughout all phases and blocks deployment with sensitive real data.

## 6. Shared analyst usefulness experiment

### Research question

Does the candidate workspace reduce time needed to answer material evidence
questions without lowering correctness or increasing unsupported claims?

### Design

- Participants: qualified analysts or trained proxy reviewers; record experience.
- Cases: de-identified/authorized Vietnamese audio, stratified by duration,
  speaker count, noise, critical values, contradiction, and no-answer queries.
- Conditions: baseline transcript/audio player versus candidate capability;
  randomized within-subject crossover with counterbalanced order.
- Questions and scoring keys are locked before exposure to results.
- Reviewers cannot see system/model version.
- Log answer, evidence click/seek, elapsed time, corrections, and confidence.

### Primary endpoints

1. time-to-correct-answer;
2. answer correctness;
3. critical evidence recall;
4. unsupported statement rate.

Secondary endpoints: time-to-first-evidence, clicks/seeks, cognitive workload,
preference, correction rate, and confidence calibration.

### Global falsification condition

Do not promote a capability if time improves but correctness/evidence recall
falls, unsupported person-level statements rise, or any critical safety/access
gate fails. Report per-slice estimates and bootstrap confidence intervals; do
not hide a failed speaker/noise/value slice behind an aggregate mean.

## 7. Architecture invariants

Every future capability must preserve these invariants:

1. One-file Analysis remains one complete-transcript LLM call with tolerant
   partial output; no writer/critic/repair chain is added to the normal path.
2. Retrieval, charts, metrics, indexes, and access decisions never generate
   facts with an LLM.
3. Every displayed evidence-dependent item resolves to the authorized current
   case, file, transcript revision, segment, and audio interval.
4. Audio occurrence time and described external-event time remain separate.
5. File-local speaker clusters are not identities.
6. Source statements, analysis observations, uncertainties, hypotheses, and
   human corrections remain visibly distinct.
7. Corrections supersede; they do not erase history.
8. Missing information is omitted or shown as a gap, never filled by inference.
9. Cross-case access/linking is denied unless explicitly authorized by a
   separate workflow.
10. Offline strict mode performs no network/provider fallback.

## 8. Primary/official source register

Source verification date: 2026-08-14.

| Source | URL | Use in this roadmap | Limitation |
|---|---|---|---|
| UNODC Criminal Intelligence Manual for Analysts | https://www.unodc.org/documents/organized-crime/Law-Enforcement/Criminal_Intelligence_for_Analysts.pdf | Link, event, flow, frequency, premise/inference, hypothesis and gap analysis | General manual; not AI validation or Vietnamese legal authority |
| INTERPOL Criminal Intelligence Analysis | https://www.interpol.int/How-we-work/Criminal-intelligence-analysis | Timely, accurate intelligence analysis and joining data points | High-level institutional description |
| INTERPOL/UNICRI Artificial Intelligence Toolkit | https://www.interpol.int/en/How-we-work/Innovation/Artificial-Intelligence-Toolkit | Responsible law-enforcement AI, human rights, ethics, policing principles and lifecycle governance | Does not approve a particular product or deployment |
| NIST AI RMF 1.0 | https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf | Scope, benchmarks, uncertainty, TEVV, feedback, independent review and human oversight | General voluntary risk framework |
| NIST OpenASR21 Evaluation Plan | https://www.nist.gov/system/files/documents/2021/08/31/OpenASR21_EvalPlan_v1_3_1.pdf | WER, references, segment/timing formats and reproducible evaluation | Not Vietnamese investigative calibration |
| DIHARD III official challenge | https://dihardchallenge.github.io/dihard3/ | Diverse “who spoke when” diarization evaluation and calibration | Research challenge, not identity proof |
| NIST SRE24 Evaluation Plan | https://www.nist.gov/system/files/documents/2024/06/11/NIST_2024_Speaker_Recognition_Evaluation_Plan.pdf | Miss/false-alarm calibration and duration/source conditions | Speaker recognition is separate from diarization and legal identity |
| NIST IR 8387 | https://nvlpubs.nist.gov/nistpubs/ir/2022/NIST.IR.8387.pdf | Hashing, preservation, secure storage and evidence management | Hash consistency does not prove original truth |
| NIST SP 800-53 Rev. 5 Update 1 | https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final | Configurable security/privacy controls and assurance | Control catalog must be tailored to local policy |
| NIST SP 800-92 | https://csrc.nist.gov/pubs/sp/800/92/final | Enterprise log management practices | 2006 guidance; apply with current platform controls |
| NIST SP 800-207 | https://csrc.nist.gov/pubs/sp/800/207/final | Per-resource authentication/authorization and no implicit network trust | Architecture guidance, not a complete authorization policy |
| VinAI PhoWhisper | https://github.com/VinAIResearch/PhoWhisper | Vietnamese-specific ASR challenger and published benchmark table | Reported benchmarks do not match covert/noisy product audio |
| OpenAI Whisper large-v3 | https://huggingface.co/openai/whisper-large-v3 | Strong multilingual ASR challenger | Model card is not local product evidence |
| pyannote.audio official releases | https://github.com/pyannote/pyannote-audio/releases | Offline/local diarization artifact and API behavior | Local Vietnamese evaluation remains mandatory |

Locally cached primary PDFs and hashes are already recorded in
`output/research/analysis-visualization-20260810/source-manifest.json`. Existing
Vietnamese ASR and diarization research remains in
`docs/research/2026-08-11-vietnamese-asr-product-review.md` and
`docs/research/2026-08-09-investigative-bulletin-diarization-evidence-refresh.md`.

## 9. Current blockers and residual uncertainty

1. There is no sufficiently large, authorized, human-labelled Vietnamese
   investigative audio corpus.
2. The current real-task set is useful for regression but too small and lacks
   gold labels for population-quality or analyst-productivity claims.
3. Legal authority, purpose limitation, retention, disclosure, admissibility,
   and cross-case processing require jurisdiction/agency-specific review.
4. Retrieval embeddings, entity linking, speaker attribution, and corrections
   can create sensitive derivative data; their lifecycle and access must be
   governed like source evidence.
5. Manual semantic audit remains necessary: one-call valid JSON can still contain
   unsupported actor or attitude interpretation on noisy ASR.
6. Exact numeric promotion thresholds proposed above must be frozen after a
   representative pilot and may need stricter values for critical person-level
   or financial use.

## 10. Immediate next research package

Before implementing the next product feature, create a scoped protocol for C1
and C2 containing:

- query/evidence fixture manifest and immutable hashes;
- transcript-segment-to-audio selector contract;
- baseline BM25/FTS retrieval;
- correction/reviewer event contract;
- blind time-to-answer study worksheet;
- negative access/cross-case/stale-revision fixtures;
- locked pass/fail thresholds and a no-sensitive-data-in-Git rule.

This package gives the product an evidence-navigation foundation and a reliable
learning loop before attempting high-risk entity linking or intelligence
inference.

