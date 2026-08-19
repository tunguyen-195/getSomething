# Audio Investigation Product Patterns

**Date:** 2026-08-10

**Workspace:** `E:\research\STT`

**Purpose:** select proven product techniques for the SpeechToInfomation product.
This is not an academic survey and does not propose a paper or public benchmark.

## Product decision

The product should use one versioned investigation artifact as the source for
Summary, Analysis, and Visualization:

```text
audio
  -> ASR words and transcript segments
  -> verified diarization state
  -> full-transcript candidate extraction
  -> entity/value/event/relation model
  -> reviewed investigation artifact
  -> Summary + Analysis views + Visualization views
```

Summary must not be the input to Analysis. Visualization must not generate new
facts. An unavailable model, incomplete scan, or failed diarization must produce
a visible partial/degraded state, never a false successful one-speaker or
successful Analysis result.

The main Analysis UI must not show evidence quotes, segment IDs, speaker/audio
offsets, or technical provenance. Those bindings remain internal safety and
audit data. The investigator-facing surface should show the modeled content:
actors, roles, organizations, locations, sensitive values, quantities, events,
described-event timeline, relationships, flows, insights, contradictions, and
unresolved questions.

## Current product review

### Critical gaps

1. `POST /api/v1/summaries/analyze` is still the active Analysis entrypoint.
   It accepts a `summary` field, reads legacy `context_analysis`, and can
   persist a compatibility fallback instead of owning a real investigation run.
2. The old deterministic fallback sampled at most 8 source units, created an
   event from each sampled sentence, emitted no entities or relationships, and
   overloaded audio occurrence time as event time.
3. Strict discovery, verification, release, contradiction, and reasoning
   contracts already exist under `src/services/investigation/`, but no
   production orchestrator owns the complete T3 -> T4 -> T5 path.
4. Multiple legacy Visualization components remain. They can present different
   projections and make Analysis and Visualization look like competing
   functions.
5. Pyannote is not operational. The live environment has
   `pyannote.audio==3.1.1`, no complete snapshot under `models/pyannote`,
   and only 25 KB of legacy 2.1 metadata under `models/pyannote_cache`.
   Community-1 code paths require the 4.x API and a different Torch stack.
6. Current persistence can collapse diarization unavailable/failure into an
   apparent one-speaker result. Speaker-sensitive analysis is therefore unsafe.
7. The frontend now hides evidence/audio offsets, but the backend still needs a
   durable `AnalysisArtifact` contract that matches the product UI.

### Foundations worth keeping

- Typed investigation contracts, evidence selectors, contradiction handling,
  narrative attestation, release seals, and append-only run models.
- Exact-value detectors for phones, accounts, money, dates, times, quantities,
  plates, email, URLs, and coordinates, after detector-specific false-positive
  tests.
- Repository-local runtime/model manifests and fail-closed offline mode.
- Deterministic visualization projectors that do not call an LLM.
- Existing Summary request type/length contract and non-released preview state.

## External product techniques to adopt

| Project | Product technique | Application in STT |
|---|---|---|
| WhisperX | VAD-batched ASR, forced word alignment, and word-to-speaker assignment; supports min/max speaker hints | Keep word-level alignment internally so speaker turns can be assigned more accurately than winner-take-all whole segments |
| pyannote.audio Community-1 | Improved speaker counting/assignment, explicit `num_speakers`/`min_speakers`/`max_speakers`, local model loading, regular speaker turns | Use as the default offline diarization engine in an isolated compatible runtime; persist exact runtime/model status |
| NVIDIA NeMo Speech | Cascaded VAD/embedding/clustering and end-to-end Sortformer diarization, including long-audio and streaming-oriented designs | Keep as a second hard-audio profile for overlap/long recordings after the default Pyannote path is stable |
| LinTO Studio | Dedicated transcription and annotation workspace with speaker editing and timestamp alignment | Add a separate Transcript/Diarization correction workflow; do not force corrections into the Analysis dashboard |
| Vexa | Speaker-attributed draft -> confirmed transcript and propose-only agent updates requiring human approval | Separate machine candidate, reviewed, and confirmed states; analyst approval creates a new revision rather than mutating raw output |
| screenpipe | Local-first searchable audio memory, deterministic data permissions, and timeline/search as views over stored events | Keep all sensitive data local/offline, enforce per-case access outside prompts, and make search/timeline deterministic views |
| OCCRP Aleph | Language-aware entity extraction, false-positive filtering, mention storage, cross-referencing, and analyst-editable network diagrams | Store mentions separately from canonical entities; show high-value/repeated matches; allow reviewed entity/link edits and case cross-reference |
| FollowTheMoney | Pragmatic investigation schema for people, organizations, assets, accounts, payments, calls, and related entities | Reuse the schema design approach for an open product ontology rather than fixed summary form fields |
| Microsoft GraphRAG | Separate tables for text units, entities, relationships, communities, and reports | Reuse the staged data layout and multi-level overview pattern, but keep every item bound to STT verification/release rules |
| OpenCTI | One structured knowledge schema rendered through graph-oriented analyst workflows | Use one analysis artifact for overview, entity table, timeline, network, flow, and search views |
| Open Semantic Search | ETL pipeline, NER, faceted search, and knowledge-graph exploration | Add case-scoped search/filtering across transcript-derived entities and exact values |
| Sonic Visualiser | Waveform/spectrogram annotation kept separate from semantic analysis | Keep signal inspection in Transcript/Diarization or an Audio Inspector, not in the main Analysis result |

## Techniques not to copy

- Do not copy WhisperX's known limitations as product guarantees: overlapping
  speech and diarization remain imperfect, and some numeric tokens cannot be
  force-aligned.
- Do not use generic case-insensitive regexes for Vietnamese person or location
  extraction. The current cue detectors produce obvious substring false
  positives.
- Do not copy GraphRAG's model-assigned `TRUE/FALSE/SUSPECTED` claim status.
  The model may emit candidates; only deterministic verification and authorized
  human review can change product authority.
- Do not make an occurrence timeline from audio playback positions. The Analysis
  timeline contains only time described in the conversation.
- Do not regenerate entity descriptions, insights, summary, and graph
  independently. They must be projections of one artifact.
- Do not show raw evidence trails or audio offsets in the main Analysis UI.
- Do not call diarization successful merely because the fallback assigned one
  speaker.
- Do not introduce emotion, deception, guilt, intent, or identity inference from
  voice.

## Target product model

The versioned `AnalysisArtifact` should contain:

- file/case/transcript/diarization revision identity;
- processing state: `queued`, `extracting`, `linking`, `partial`,
  `needs_review`, `ready`, `failed`, or `superseded`;
- anonymous file-local speaker clusters and assignment quality;
- entity mentions and canonical entities as separate records;
- exact values with normalized value, type, owner state, and unit state;
- atomic statements with polarity, modality, attribution, and review state;
- events with actors/roles, action/object, location, described time, and state;
- directed relationships and financial/commodity/communication flows;
- contradictions, repeated patterns, bounded insights, and investigation gaps;
- internal claim/evidence bindings and hashes, omitted from the main UI;
- projection version/hash so Summary and Visualization cannot drift.

## Product UI

The Analysis workspace should have coordinated views over the same artifact:

1. **Tổng quan:** concise briefing, key actors, critical values, major events,
   important insights, gaps, and degraded state.
2. **Đối tượng:** people, organizations, places, accounts, phones, vehicles,
   devices, documents, aliases, roles, and mention counts.
3. **Timeline sự kiện:** only described event time, with unknown-time events in a
   separate group.
4. **Mối quan hệ:** directed entity links with type and review state.
5. **Dòng tiền/hàng hóa/liên lạc:** directional flow table or graph when the
   transcript contains explicit source, destination, amount, object, or channel.
6. **Mâu thuẫn và khoảng trống:** conflicting statements and information still
   needed.
7. **Visualization:** network, timeline, flow, map, and interaction matrix as
   deterministic view modes, not a second analysis engine.

The Overview page keeps separate **Summary**, **Analysis**, and
**Visualization** actions, but Analysis and Visualization read the same
`AnalysisArtifact`.

## Primary sources

Sources were checked on 2026-08-10:

- https://github.com/m-bain/whisperX
- https://github.com/pyannote/pyannote-audio
- https://github.com/NVIDIA-NeMo/Speech
- https://github.com/linto-ai/linto-studio
- https://github.com/Vexa-ai/vexa
- https://github.com/screenpipe/screenpipe
- https://github.com/alephdata/aleph
- https://github.com/alephdata/followthemoney
- https://github.com/opensemanticsearch/open-semantic-search
- https://github.com/microsoft/graphrag
- https://github.com/OpenCTI-Platform/opencti
- https://github.com/sonic-visualiser/sonic-visualiser

Important source caveats:

- Aleph's legacy open-source code states that maintenance ended after December
  2025. Its entity/cross-reference/network workflow is a design reference, not a
  dependency recommendation.
- screenpipe is source-available and some product features may have license or
  edition constraints.
- Vexa and meeting assistants optimize collaboration notes, not criminal
  investigation authority. Only their workflow patterns are reusable.
- Community-1 requires a complete gated model snapshot and a 4.x-compatible
  runtime. The current STT environment does not satisfy that contract.

## Completion implication

The immediate product work is not to add more cards to the current fallback.
It is to:

1. repair diarization truth and runtime;
2. create one real Analysis orchestrator and persisted artifact;
3. run full-transcript extraction through existing verification/release
   contracts;
4. generate Summary, Analysis, and Visualization from that artifact;
5. finish the analyst-facing workspace and product acceptance flow.
