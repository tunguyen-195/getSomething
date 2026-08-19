# Analysis and Visualization v2: Falsifiable Requirements

Date: 2026-08-14  
Status: implementation contract  
Scope: analysis of one persisted audio transcript and its diarized segments

## 1. Objective

Turn a complete audio transcript into a useful Vietnamese investigative analysis
with one LLM generation call, then render deterministic visualizations from that
analysis and source-derived metrics. A usable partial answer is preferred over a
complex repair pipeline that rejects the entire result.

This feature assists an analyst. It does not establish that an external event
occurred, identify a person from a voice, determine guilt, or make an automated
adverse decision.

## 2. Product path

```text
complete transcript + optional diarized segments
    -> one Vietnamese analysis prompt
    -> one LLM response
    -> tolerant normalization
    -> analysis cards + deterministic visual projections
```

The normal path must not call a separate context model, writer, critic, semantic
gate, repair model, or visualization model.

## 3. Required input behavior

| ID | Requirement | Falsification |
|---|---|---|
| R1 | The prompt contains the complete non-empty transcript exactly once inside a clearly delimited data block. | A source substring is omitted, reordered, or treated as an instruction. |
| R2 | Diarized segments are optional. When present, their speaker labels, text, start, and end are available to the prompt or deterministic metric layer. | Missing diarization makes the whole analysis fail, or labels are presented as verified identities. |
| R3 | Transcript, filename, prior output, and metadata are untrusted data. | Spoken or embedded prompt injection changes system behavior or leaks instructions. |
| R4 | One normal analysis request performs exactly one model generation. | Generation call count differs from one on a successful/partial result. |

## 4. Required output behavior

The public contract is `investigation-analysis-simple-v2`. It accepts a compact
structured payload with these optional sections:

- `analysis_text`, `overview`, `key_points`;
- `participants`, `events`, `actions`, `entities`, `relationships`;
- `contradictions`, `uncertainties`, `follow_ups`;
- host-derived `speaker_contributions`, a small public metrics whitelist, and
  runtime metadata needed to reproduce generation.

All insight arrays may be empty. Unknown fields and malformed optional items are
ignored rather than rejecting otherwise usable content.

| ID | Requirement | Falsification |
|---|---|---|
| R5 | A valid structured response returns `analysis_status=success`. | Valid JSON is discarded because an optional category is absent. |
| R6 | A non-empty but unparseable response returns `analysis_status=partial` and preserves safe plain analysis text. | Usable text is lost or the request is marked failed solely for malformed JSON. |
| R7 | Only provider unavailable, generation exception, empty response, or no recoverable content returns `failed`. | An absent optional insight or unsupported chart fails the request. |
| R8 | Output preserves negation, reported/quoted status, uncertainty, and explicit contradictions. | “Chua chuyen” becomes a completed transfer, or one side of a conflict is silently chosen. |
| R9 | The output uses transcript-grounded language such as “nguoi noi cho biet” for external events. | A speaker statement is promoted to an independently verified world fact. |
| R10 | No hard word-count gate rejects a useful analysis. | Output is failed or regenerated only because it exceeds a fixed prose length. |

## 5. Visualization requirements

| ID | Requirement | Falsification |
|---|---|---|
| R11 | Visualization is a deterministic projection of normalized analysis plus source metrics; it performs no LLM call. | Chart construction generates a new entity, event, relation, amount, or conclusion. |
| R12 | Unsupported or empty chart types are skipped without failing the rest of the page. | One malformed visualization hides the entire analysis. |
| R13 | Timeline entries come only from returned events/actions with explicit or ordered time. | A chart invents dates or presents audio offsets as event dates. |
| R14 | Relationship edges come only from explicit normalized relationships. | Co-occurrence alone becomes a relationship edge. |
| R15 | Speaker contribution values are computed from transcript segments, never guessed by the LLM. Only whitelisted host-derived metrics enter the public payload. | LLM-returned percentages or arbitrary runtime/provider fields override measured/public metrics. |
| R16 | Categories with insufficient data use prose/list/table or are omitted. | Empty maps, fake flows, or misleading quantitative charts are shown. |

## 6. Safety and epistemic boundaries

The following outputs are prohibited as factual conclusions:

- deception, guilt, criminality, dangerousness, intent, or mental state from
  voice or conversational tone;
- emotion, age, gender, ethnicity, health, or other sensitive traits inferred
  from voice;
- verified identity from diarization labels or voice similarity alone;
- hidden relationships, motives, hierarchy, code-word meanings, or money flows
  that are not explicitly stated;
- legal conclusions, admissibility claims, or operational authorization.

Tone/sentiment may be displayed only as an indicative text description when the
conversation wording supports it, never as a truth, risk score, lie signal, or
character assessment.

## 7. Completion gates

The implementation is releasable for product testing only when:

1. focused unit tests prove one generation call and no writer/critic/repair call;
2. valid, partial, empty, missing-section, contradiction, negation, code-switch,
   and prompt-injection fixtures pass;
3. projection tests prove no dangling event/relation reference and no chart-side
   fact creation;
4. at least the four known persisted task IDs replay read-only and record prompt,
   model/config, source hashes, result status, duration, and call count;
5. frontend renders `success`, `partial`, sparse, and unsupported-chart payloads;
6. no task mutation occurs during the replay evaluation;
7. residual uncertainty is reported: there is not yet a sufficiently large,
   human-labelled Vietnamese investigative-quality corpus.

## 8. Out of scope for v2

- cross-case entity resolution;
- automatic geocoding or maps;
- speaker identification;
- external corroboration or open-source intelligence retrieval;
- automated competing-hypothesis scoring;
- evidentiary admissibility or legal decision support.
