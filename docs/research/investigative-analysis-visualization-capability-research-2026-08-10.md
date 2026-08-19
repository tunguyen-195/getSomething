# Investigative Analysis and Visualization Capability Research

**Date:** 2026-08-10

**Workspace:** `E:\research\STT`

**Status:** Source-backed product design; implementation and promotion remain gated

**Parent objective:** P0-P8 evidence-backed audio intelligence remediation

## 1. Decision

The product should become an **evidence-first Conversation Intelligence
Workspace**, not a crime-classification dashboard.

- **Analysis** performs bounded reasoning over sealed transcript/audio evidence.
  It produces released source assertions, evidence-backed insights, explicitly
  non-factual hypotheses, and verification actions.
- **Visualization** performs no factual extraction and no LLM reasoning. It is a
  deterministic, hash-bound projection of one released `InvestigationRun`.
- Audio normally proves that a source or speaker **said** something. It does not
  by itself prove that the described external event occurred.
- The system must not infer guilt, criminality, deception, intent, emotional
  state, protected traits, or a verified human identity from voice features.

This boundary is the main product requirement. Adding more charts without it
would make unsupported conclusions look more authoritative.

## 2. Falsifiable requirements

The target is accepted only when all of the following are true:

1. Every factual item opens an exact quote and authorized audio span from the
   current source revision.
2. Every speaker-sensitive fact carries an explicit speaker assignment state;
   ambiguous diarization cannot release a sensitive attribution.
3. Summary, Analysis, and Visualization use the same released claim set and run
   identity.
4. Visualization navigation, filtering, layout, aggregation, and export make no
   LLM request and create no new fact.
5. Facts, source assertions, insights, hypotheses, and verification actions are
   visibly and structurally distinct.
6. Reported speech, allegation, plan, denial, quotation, uncertainty, and
   negation cannot be promoted to an established world event.
7. Contradictions remain separate; they are not removed by deduplication.
8. Long-audio coverage is measurable so a plausible-looking output cannot hide
   omitted middle or tail segments.
9. Unsupported high-risk releases, wrong-speaker sensitive releases, cross-case
   evidence references, and prompt-injection release changes are zero.
10. A human analyst can verify, reject, supersede, or request more evidence
    without mutating the original model run.

## 3. Current repository evidence

### Strong foundations already present

- `InvestigationRun`, typed epistemic status, reasoning contracts, verification,
  narrative attestation, and release seals are present under
  `src/services/investigation/`.
- `src/services/visualization/projector.py` requires an authority-sealed run and
  projects nodes, edges, timeline, events, entities, and evidence without model
  inference or persistence.
- `src/services/visualization/contracts.py` binds a visualization to run ID,
  source revision, release subject hash, content hash, evidence hashes, speaker,
  and audio time.
- Discovery code treats transcript/focus content as untrusted data and prevents
  the model from owning IDs, release status, risk, criminality, or surveillance
  conclusions.

### Product gaps in the active path

- `frontend/src/components/AnalysisPanel.tsx` still reads legacy
  `context_analysis`, directly calls `/api/v1/summaries/analyze`, and renders
  mostly key points plus basic released entity/event/timeline counts.
- Production code does not yet create, persist, seal, or safely rehydrate the
  `InvestigationRun` required by the strict visualization projector. The
  released-artifact path therefore has no trusted production owner.
- `frontend/src/components/VisualizationDialog.tsx` can render both a released
  artifact and a transcript-evidence preview under a similar surface. The
  preview is useful, but it must remain visually and contractually distinct.
- The current `Grounded` label is weaker than the domain contract: an analysis
  status can be successful even when the UI has not resolved every evidence ID,
  source revision, quote, speaker, and audio span. Deterministic transcript
  fallback is useful for continuity but is not substantive investigative
  reasoning and must be labelled as such.
- The UI does not yet expose full premise/counterevidence, exact-value ownership,
  relationship state, contradictions, hypotheses, verification actions,
  source-coverage quality, or speaker uncertainty.
- Append-only production ownership, active/superseded run persistence, and a
  single idempotent orchestration entrypoint remain incomplete.
- Current quality evidence is structural/smoke evidence, not a human-labelled
  Vietnamese investigative corpus.
- Diarization and cross-file speaker isolation remain product blockers. The same
  label such as `SPEAKER_00` must never imply the same person across files.

## 4. Truth and reasoning layers

The UI and contracts should expose these layers explicitly:

| Layer | Meaning | May enter factual narrative? |
|---|---|---:|
| Source evidence | Exact audio/transcript material with integrity metadata | No, it is the supporting source |
| Released source assertion | A source/speaker stated a proposition | Yes, as an attributed statement |
| Corroborated world finding | External evidence authority confirms the event/entity fact | Not available until a separate authority exists |
| Evidence-backed insight | Bounded derivation from released premises | Analysis only, clearly labelled |
| Hypothesis | Tentative explanation with alternatives and falsification criteria | Never |
| Verification action | Concrete next question and authorized source needed | Never |

## 5. Information to extract from each audio file

The business ontology should remain open. The following are coverage targets,
not mandatory form fields.

| Object | Required content |
|---|---|
| Source revision | Case/file/audio ID, collection authority, custodian, acquisition method, original/archive/working-copy hashes, transfer log, transcript and diarization revision, authorization scope, model/config manifest |
| Audio quality | Codec/channel/sample rate, clipping/noise/reverb, missing/corrupt range, enhancement/transcoding history, exact tool/version/settings, original-versus-processed comparison, timestamp quality |
| Speaker turn | File-local anonymous speaker cluster, start/end, overlap, confidence/ambiguity, exact words, ASR confidence |
| Entity mention | Exact surface, open type, normalized value, explicit role, aliases, evidence; identity resolution remains separate |
| Sensitive exact value | Phone, account, ID, address, money, currency, quantity/unit, vehicle plate, device, document, URL, coordinate, code |
| Atomic source assertion | Who stated what, polarity, modality, reported/quoted status, certainty, conditions, source attribution, evidence |
| Event | Actors and roles, action, object, place, described event time and precision, audio occurrence time, planned/completed/denied/reported state |
| Relationship | Directed endpoints, open predicate, explicit or derived state, validity interval, premise claims, evidence |
| Communication occurrence | Initiator, recipient or addressee if explicit, channel, time, frequency, duration, direction; do not invent call metadata from one audio file |
| Financial/commodity movement | Source, destination, beneficiary, amount/unit, object/commodity, date, method, intermediary, evidence |
| Commitment and plan | Actor, intended action, deadline, location, dependency, contingency, cancellation or denial state |
| Instruction and control | Issuer, recipient, requested action, authority wording, conditions, response, evidence |
| Contradiction | Canonical proposition, incompatible claims, polarity/time/owner/value conflict, unresolved state |
| Repeated pattern | Recurrent released events, participants, identifiers, timing, method, or sequence across authorized files |
| Intelligence gap | Missing identity, time, location, owner, amount, relation, corroboration, or source needed to resolve a question |
| Safety metadata | Sensitivity class, redaction/export policy, legal hold, reviewer state, superseded state |

### Audio-specific rules

- Diarization produces anonymous clusters, not identities.
- A speaker-to-person mapping is a separate human-reviewed artifact with its own
  evidence and revision.
- Overlap, silence, interruption, turn duration, and channel changes may be
  displayed as observable signal properties. They must not be labelled as fear,
  deception, guilt, dominance, or intent.
- Slang or coded-language interpretations remain hypotheses unless the meaning
  is explicitly defined in the conversation or corroborated by authorized
  evidence.

## 6. Analytical tasks that create investigative value

### A. Evidence-backed briefing

Rank released claims by legal/operational salience, recency within the described
events, source coverage, and analyst focus. Preserve exact names, roles,
identifiers, values, time, location, event links, and speaker attribution.

### B. Exact-value recovery and ownership

Recover every sensitive value without value-only deduplication. Store who used,
owned, received, sent, or referred to the value, with unit, formatting, time,
speaker, file, and evidence.

### C. Speaker and role attribution

Answer who said what at the source level. Separate anonymous speaker cluster,
explicit self-identification, another speaker's allegation, and human-verified
identity mapping. If speaker recognition is ever added, expose calibrated
log-likelihood evidence, the applicable miss/false-alarm operating point,
duration/source/language conditions, and a human decision; never render the
score as identity proof.

### D. Event reconstruction

Build two timelines:

1. **Audio occurrence time**: when the statement appears in the recording.
2. **Described event time**: when the speaker says the external event occurred
   or should occur.

These times must never be merged silently.

### E. Association and network analysis

Represent people, organizations, locations, identifiers, devices, vehicles,
documents, events, and accounts. Each edge carries direction, relationship type,
explicit/derived status, strength basis, time validity, claim refs, and evidence.
Graph centrality is a navigation aid, not proof of criminal importance.

### F. Financial and commodity flow analysis

Trace money, goods, documents, devices, drugs, stolen property, or other
explicitly mentioned objects from source to destination. Preserve amounts,
units, dates, intermediaries, and final beneficiaries when stated. Hidden
beneficiary or hierarchy conclusions remain hypotheses.

### G. Communication pattern analysis

Across authorized files, compare repeated participants, identifiers, contact
direction, timing, duration, and frequency when such metadata is actually
available. Conversation content alone must not fabricate call-detail records.

### H. Contradiction and change analysis

Surface incompatible values, dates, ownership, locations, denials, corrections,
and changing accounts. Display both claims and their evidence; do not choose a
winner automatically.

### I. Bounded insight generation

Useful insight types include:

- an operational sequence implied by multiple released events;
- a repeated method or coordination pattern;
- an explicitly evidenced division of roles;
- a bottleneck, intermediary, or beneficiary in a released flow;
- an inconsistency that changes the investigative question;
- a missing piece of evidence that blocks a conclusion.

Every insight requires premise claim IDs, a typed derivation, applicability
scope, counterevidence review, and an evidence path.

### J. Competing hypotheses and verification planning

For each material ambiguity, retain alternatives rather than one model-selected
story. A hypothesis requires premises, alternatives, disconfirming evidence,
confidence language, falsification criteria, and human review. A verification
action states the concrete question, authorized source type, responsible role,
priority, and promotion/rejection criterion.

## 7. Required visualization views

| Analyst question | Deterministic view | Non-negotiable behavior |
|---|---|---|
| What matters now? | Briefing and gap dashboard | Separates facts, insights, hypotheses, actions, and degraded state |
| What exact values were mentioned? | Exact-value provenance table | Keeps owner/unit/file/speaker/time and duplicate provenance |
| Who said what? | File-aware speaker lanes | Shows overlap and ambiguity; click seeks audio |
| What happened in what order? | Dual event timeline/swimlanes | Separates audio time from described event time |
| How are entities connected? | Association/link graph | Every node/edge opens claims and evidence; uncertain edges look different |
| How did money or goods move? | Directed flow graph/matrix | Labels direction, amount/unit/date; no implied missing edge |
| Where do accounts conflict? | Contradiction matrix | Shows both sides, proposition key, and unresolved state |
| Which hypotheses remain? | Competing-hypothesis matrix | Premises, contradictions, missing indicators, reviewer state |
| What should be checked next? | Evidence-gap/action queue | Concrete question, source, owner, priority, criterion |
| Is this artifact trustworthy? | Provenance and quality drawer | Run/revision hashes, coverage, ASR/diarization degradation, stale/superseded state |
| Where are explicit locations? | Optional map | Only explicit safely geocoded locations; no inferred tracking |

The graph layout, ordering, aggregation, filtering, metrics, labels, and export
must be deterministic functions of the released artifact. A chart is an
analytical aid, not an independent factual authority.

## 8. Evidence-to-release workflow

1. Authorize the exact case/file scope.
2. Preserve original audio and create a hashed working copy.
3. Freeze audio, transcript, diarization, prompt, schema, model, config, and Git
   revisions.
4. Build a position-balanced segment coverage manifest.
5. Run deterministic exact-value detectors and open-schema LLM discovery; the
   model emits candidates only.
6. Resolve every candidate to exact current-revision quote/offset/time/speaker.
7. Verify atomicity, attribution, polarity, modality, owner, unit, event time,
   and speaker state.
8. Canonicalize only conservative duplicates and preserve contradictions.
9. Generate typed insights, hypotheses, and verification actions from released
   premises.
10. Apply risk, speaker, counterevidence, narrative, authorization, and human
    review gates.
11. Atomically publish one append-only run or publish diagnostics with no factual
    projection.
12. Derive Summary, Analysis, and Visualization from that run.
13. Corrections create a new source revision and superseding run.

## 9. Fail-closed gates

Release stops when:

- authorization scope is missing or changed;
- source/transcript/diarization/model/config hashes are stale;
- segment coverage is incomplete;
- evidence does not resolve to current bytes;
- owner, unit, time, polarity, modality, attribution, or speaker conflicts with
  the evidence;
- speaker identity is ambiguous for a sensitive assertion;
- an allegation, denial, plan, quotation, or reported statement is being
  promoted to world fact;
- contradictory claims were hard-merged;
- a high-risk item lacks current human attestation;
- narrative adds unsupported meaning or omits a released critical claim;
- Summary and Analysis release sets differ;
- visualization hashes do not bind the active released run;
- export lacks authorization, redaction confirmation, provenance, or audit log.

`needs_review`, `failed`, `degraded`, and `superseded` must be visible states.
They must never silently fall back to legacy analysis or transcript preview.

Case-scoped authorization, need-to-know access, reveal/export logging,
minimization, retention, legal hold, redaction, and reviewer identity are part
of the release contract. The product must not make a solely automated adverse
decision about a person.

## 10. Capabilities that should not be implemented as factual AI outputs

- lie or deception detection from voice;
- guilt, criminality, dangerousness, radicalization, or surveillance targeting;
- emotion, mental health, ethnicity, age, gender, or other protected/sensitive
  trait inference from voice;
- verified human identity from diarization or voice similarity alone;
- hidden relationship, code-word meaning, motive, hierarchy, or intent without
  explicit premises and human-reviewed hypothesis status;
- automatic legal conclusions or evidentiary-admissibility claims;
- cross-case entity linking without explicit authorization and review.

## 11. Evaluation requirements

### Corpus

- Tier A: deterministic mutation pairs for values, ownership, units, negation,
  reported speech, contradictions, stale revision, and injection.
- Tier B: scripted/de-identified Vietnamese calls, 5-30 minutes.
- Tier C: authorized real audio, paired human/ASR transcripts and gold/predicted
  diarization, outside Git.
- Tier D: multi-file cases with aliases, repeated values, corrections,
  contradictions, and cross-file timelines.
- Tier E: adversarial safety cases including false accusation, fabricated
  confession, criminality/deception inference, and cross-case leakage.

Required slices include Vietnamese regions, code-switching, phone codecs,
noise/reverb, one to eight speakers, overlap, short/long calls, middle-position
evidence, sensitive values, correction, denial, ambiguity, and no-claim cases.

ASR evaluation must report WER/CER together with critical-field error rates for
names, numbers, addresses, accounts, plates, dates, and money. Aggregate WER
cannot hide a low investigative-value transcript. Raw word confidence requires
local calibration and cannot be displayed as correctness probability. Speaker
and diarization evaluation must report DER/JER, speaker-count accuracy, overlap
recall, speaker-attributed WER, and duration/source/language slices.

### Proposed promotion gates

| Dimension | Gate |
|---|---:|
| Evidence selector resolution | 100% |
| Released sentence support | 100% |
| Critical exact value + owner + unit accuracy | >= 0.99; wrong-owner count 0 |
| Released factual event precision | >= 0.98 |
| Directed relationship/evidence precision | >= 0.98 |
| Explicit time accuracy | >= 0.99 |
| Pairwise event ordering | >= 0.95 |
| Claim-speaker precision | >= 0.98; wrong-speaker sensitive release 0 |
| Critical atomic claim precision | >= 0.98 |
| Critical atomic claim recall | >= 0.95; no critical slice below 0.90 |
| Insight premise coverage | 1.00 |
| Hypothesis leakage into factual projection | 0 |
| Contradictory hard merge | 0 |
| Unsupported high-risk/legal/deception output | 0 |
| Injection release/tool/leak success | 0 |
| Deterministic visualization dangling refs/hash mismatch | 0 |
| Desktop/mobile/keyboard evidence-navigation E2E | 100% |

Quality thresholds must be frozen after a double-annotation pilot and reported
with confidence intervals and per-slice results. Current synthetic fixtures are
regression assets, not production quality evidence.

## 12. Primary-source claim map

| Design requirement | Source support | Limitation |
|---|---|---|
| Link, event, flow, activity, financial, frequency, and telephone analysis are relevant intelligence techniques | UNODC Criminal Intelligence Manual, sections 6-10 | General international manual; local law and agency practice govern use |
| Inferences must follow premises and be tested before acceptance as fact | UNODC manual, intelligence process and inference development | Does not validate an AI implementation |
| Competing hypotheses, key assumptions, indicators, and counter-analysis reduce premature closure | CIA Tradecraft Primer | General intelligence method, not criminal evidence authority |
| Original/earliest audio, working copies, hashes, documentation, chain of custody, and controlled enhancement are required | SWGDE Forensic Audio and Digital Audio Authentication | Laboratory best practice; does not validate ASR/diarization accuracy |
| Speaker comparison/identification requires specialist treatment | SWGDE Forensic Audio section 8.5 | Supports conservative identity handling, not a specific model threshold |
| Digital evidence handling should preserve integrity and chain of custody | UNODC Digital Evidence, NIJ guide, NIST SP 800-86 | Some sources are general or older; legal procedure is jurisdiction-specific |
| Preserve original-source documentation, early hashes, verified copies, secure hash records, and transfer history | NIST IR 8387; SWGDE Digital Evidence Collection 18-F-002-2.0 | A hash proves consistency from the hashing point, not the truth of pre-hash circumstances |
| Forensic workflow separates collection, examination, analysis, and reporting | NIST SP 800-86 | Incident-response context; used as process pattern only |
| Audio enhancement must use a working copy, retain settings/intermediates, compare processed with unprocessed audio, and disclose limitations | SWGDE Enhancement of Digital Audio 20-A-001-2.0 | Enhancement can distort content and intelligibility remains partly subjective |
| ASR must be evaluated with human references, WER/CER, timing, and relevant language/condition slices | NIST OpenASR21 Evaluation Plan | Optional model confidence was not used by the NIST scorer and requires local calibration |
| Speaker recognition must be calibrated and evaluated against miss/false-alarm trade-offs and duration/source conditions | NIST SRE24 Evaluation Plan | Technology evaluation is not an identity-proof or admissibility standard |
| Criminal intelligence analysis supports operational and strategic decisions by structuring multi-source patterns and links | INTERPOL Criminal Intelligence Analysis | High-level institutional guidance, not a validation or legal threshold |
| AI needs validity, transparency, explainability, privacy, uncertainty measurement, independent review, and human oversight | NIST AI RMF 1.0 | General risk framework, not law-enforcement-specific authorization |
| Sensitive-data processing, logging, human oversight, and limits on solely automated decisions require explicit governance | EU AI Act 2024/1689 and Directive 2016/680 | EU-specific; national authority, criminal procedure, retention, disclosure, and admissibility still control |
| Exact quote and position selectors strengthen traceability | W3C Web Annotation Data Model | Selector pattern still requires immutable source hash and project validation |

## 13. Source limitations and residual uncertainty

1. No primary source authorizes model-generated accusations or guilt findings.
2. Legal admissibility, surveillance authority, retention, disclosure, and data
   protection require jurisdiction-specific review outside this research.
3. Audio authenticity, speaker identity, ASR correctness, and event truth are
   separate questions and require separate evidence.
4. The project lacks a sufficient authorized Vietnamese quality corpus.
5. Automatic factuality and relation metrics require Vietnamese human
   calibration.
6. Multi-stage extraction improves control but can increase latency and GPU
   pressure; model assignment requires measured ablations.
7. Privacy, collection authority, admissibility, and disclosure requirements
   vary by jurisdiction; the cited EU safeguards are design controls, not a
   claim that EU law governs every deployment.

## 14. Research evidence

- Source manifest: `output/research/analysis-visualization-20260810/source-manifest.json`
- Downloaded primary sources and extracted text:
  `output/research/analysis-visualization-20260810/sources/`
- Implementation plan:
  `docs/plans/2026-08-10-investigative-analysis-visualization-plan.md`

This research defines the target capability and falsification gates. It does not
claim that the current model, diarization stack, or UI has achieved them.
