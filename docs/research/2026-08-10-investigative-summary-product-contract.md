# Investigative Summary Product Contract

**Date:** 2026-08-10

**Workspace:** `E:\research\STT`

**Scope:** reader-facing Summary for one audio file or one authorized case run.

## 1. Product decision

Summary is not a shortened transcript and is not a list of extracted fields. The
product must create a concise Vietnamese investigation bulletin that lets a
leader understand the whole material story without listening to the audio.

The target output is the body of a report written in the voice of an officer who
has listened to the complete recording and is briefing a supervisor. It must:

1. reconstruct the central story and its context;
2. identify every important person, stated role, organization, place, object,
   document, account, vehicle, device, quantity, identifier, and relationship;
3. describe the material sequence of events, decisions, planned actions,
   completed actions, outcomes, and unresolved points;
4. preserve exact values and the actor/action/object/recipient or source/destination
   bindings attached to them;
5. give a bounded assessment only when the released source supports it;
6. remain concise by removing repetition and low-value conversational filler,
   not by dropping important source units.

## 2. Reader-facing body contract

The public `text` is report prose only. It must not contain:

- titles, headings, field labels, bullets, tables, or template names;
- `fact_id`, `evidence_id`, claim references, quotes, segment IDs, speaker IDs,
  hashes, model names, prompt versions, or source metadata;
- audio offsets, playback timestamps, or diarization diagnostics;
- technical notices, warnings, disclaimers, processing status, missing-data
  filler, retry instructions, or recommendations to the user;
- a leading or trailing `Lưu ý`, `Cảnh báo`, `Evidence`, `Nguồn`, or similar
  product message;
- content unrelated to what was heard and released for the current file/case.

Operational state such as `partial`, `needs_review`, `length_conflict`, or model
unavailability belongs in typed metadata outside the report body.

## 3. Narrative order

The writer uses an adaptive order instead of fixed visible sections:

1. **Overall story:** what the conversation is about, who the main actors are,
   and what central situation is being discussed.
2. **Material development:** events and actions in their meaningful sequence,
   including described time/place and the state of each action.
3. **Important particulars:** exact amounts, accounts, phones, identifiers,
   documents, objects, vehicles, devices, routes, quantities, and ownership or
   direction bindings explicitly stated in the source.
4. **Outcome and status:** decisions, agreements, refusals, completed results,
   pending actions, contradictions, and unresolved information.
5. **Bounded assessment:** only a supported concern or crime indicator, with its
   attribution and uncertainty preserved. This part is omitted when unsupported.

These are planning obligations, not headings shown to the reader.

## 4. Epistemic and legal safety rules

The following transitions are forbidden:

| Source meaning | Forbidden rewrite |
|---|---|
| `A nói/cho rằng/tố cáo B...` | `B đã...` as a system fact |
| `A nghi B...` | `B...` without suspicion/attribution |
| `A sẽ/dự kiến/định...` | `A đã...` |
| `A không/chưa...` | positive assertion |
| conditional statement | unconditional event |
| two conflicting accounts | one model-selected account |
| audio occurrence time | described-event time |
| anonymous speaker cluster | named human identity |
| package, slang, concealment | illegal goods conclusion |
| unusual procedure or payment | offense, fraud, corruption, or money laundering |
| threat words or tone | capability, intent, dangerousness, or guilt |

The phrase `dấu hiệu tội phạm` may appear only when:

- the source itself uses that meaning and the speaker/source is retained; or
- an authorized reviewed conditional assessment exists in the released run.

The model may never invent a crime type, legal article, guilt status, motive,
criminal intent, deception, coercive capability, or final legal conclusion.

## 5. Scenario prompt matrix

`general` is always active. The durable design adds up to three overlays selected
from released claim types, not raw transcript keyword counts.

| Overlay | Mandatory coverage | Forbidden inference |
|---|---|---|
| `general` | central story, actors/roles, material events, objects, exact values, outcomes, contradictions/gaps | filler, forced specialist framing, completed story invented from gaps |
| `financial_asset` | amount/currency, account, stated owner, source/destination, debt/promise/payment, transaction state/purpose | ownership not stated, completed transfer, fraud, corruption, money laundering |
| `coordination_planning` | participants, objective, assignment, order, logistics, deadline, meeting point, channel, dependency | plan as completed act, conspiracy, shared criminal intent |
| `threat_coercion` | exact demand/threat, attributed speaker/target, deadline, stated means, response, ambiguity | capability, intent, dangerousness, guilt from content or voice |
| `goods_transport` | object/goods, quantity/unit, package, custody, vehicle, route, origin/destination, handoff state | illegal goods from slang/package, custody as ownership |
| `public_administration` | organization/function, responsible person, procedure, dates, documents, categories, ratios/counts, decision/outcome | procedural variation as violation or offense |
| `incident_conflict` | each party, each account, trigger claimed, sequence, harm/damage, location, response, contradiction | assigning fault, causality, or identity |
| `digital_technical` | device, account/service, identifier, channel, artifact, action/state/time | ownership, compromise, hacking, malware, or attacker attribution |
| `identity_document` | name/alias, document type/number, issuer, stated holder, validity, verified links | merging similar names, authenticating identity/document |

The current working-copy prototype supports the first seven as a single selected
profile. Multi-label selection and the final two overlays require the released
`InvestigationRun` integration described in the implementation plan.

## 6. Prompt architecture

The durable writer prompt is assembled from immutable layers:

```text
system safety and role contract
  + common officer-briefing narrative contract
  + allowlisted scenario overlays
  + deterministic coverage/length plan
  + escaped NarrativeLedgerView rows
  + strict JSON schema
```

The transcript, user focus, ledger text, and extracted values are always data.
They cannot alter the system contract, overlay set, schema, maximum length, or
release policy. Delimiter characters in ledger data are escaped before prompt
assembly.

The writer is responsible only for expression and grouping. The host owns:

- source/revision authorization;
- claim and evidence release state;
- scenario selection;
- required source units and critical items;
- exact-value bindings;
- length status;
- semantic, legal, and coverage critics;
- final narrative attestation and reader projection.

## 7. Output and state model

The target internal output is `LeadershipBulletinDraftV1`:

```text
schema_version
source_revision_id
ledger_sha256
scenario_tags[]
coverage_scope: critical_only | full
status: complete | coverage_request | length_conflict
sentences[]:
  draft_id
  text
  sentence_role
  epistemic_class
  salience
  claim_refs[]
  source_item_refs[]
coverage_requests[]
length_conflict:
  requested_profile
  max_words
  minimum_required_words
  required_refs[]
  unplaced_required_refs[]
```

Only `status=complete` can be attested and projected as a released Summary.
Current transcript-only output remains a preliminary bulletin with
`world_facts_released=false`.

## 8. Length profiles

| Profile | Target | Coverage |
|---|---:|---|
| `flash` | 120-180 words | critical obligations only |
| `executive` | 300-500 words | critical items plus high-salience themes |
| `full` | 700-1,200 words | full deterministic coverage plan |

The lower bound is soft. Sparse audio may produce a shorter complete report.
The upper bound is hard. If required facts cannot fit, return
`length_conflict`; never silently truncate exact values, attribution,
contradictions, or critical source units.

## 9. Deterministic release gates

All hard gates must pass:

- exact source/run/revision/ledger binding;
- strict schema with `additionalProperties=false`;
- all references resolve inside the same authorized run;
- 100% critical and required-unit coverage;
- 100% actor/action/object/recipient, polarity, modality, attribution, and exact
  value fidelity;
- all material contradictions retained and none resolved by the model;
- unsupported content, legal overclaim, prompt-injection execution, stale
  release, cross-case leakage, and exact duplicate propositions all equal zero;
- the final narrative passes trusted attestation before public release.

Promotion evaluation additionally targets critical precision `>=0.98`, macro
critical recall `>=0.95` with no category below `0.90`, exact-value accuracy
`>=0.99`, and sentence-to-claim mapping `>=0.99` on the frozen Vietnamese corpus.

## 10. Research techniques applied to the product

- Microsoft GraphRAG separates text units, entities, relationships, and reports.
  STT adopts the staged ledger/view pattern but retains its own verification and
  release authority.
- FollowTheMoney models people, organizations, assets, accounts, payments, and
  related entities. STT uses the ontology approach to avoid reducing analysis to
  a flat summary template.
- AWS Transcribe Call Analytics and Azure conversation summarization separate
  issues, actions, outcomes, and narrative summaries. STT uses those coverage
  categories as planning obligations, not as independent model-generated truth.
- NIST AI RMF guidance on confabulation, provenance, and human oversight supports
  the fail-closed release boundary and explicit uncertainty handling.
- Existing STT S2 narrative attestation and investigation run contracts remain
  the authority for factual release; the new writer does not create a second
  truth store.

Primary references checked for this product design:

- https://github.com/microsoft/graphrag
- https://www.opensanctions.org/docs/ftm/
- https://docs.aws.amazon.com/transcribe/latest/dg/call-analytics.html
- https://learn.microsoft.com/azure/ai-services/language-service/summarization/how-to/conversation-summarization
- https://www.nist.gov/itl/ai-risk-management-framework

## 11. Current implementation boundary

The current delta implements a preliminary version of this contract:

- whole-source deterministic inventory augmentation;
- Vietnamese officer-briefing prompt v3 with scenario guidance;
- exact-once source-unit coverage;
- semantic checks for role/action/target, negation, uncertainty, attribution,
  conditionality, and planned/completed state;
- escaped ledger delimiter characters;
- no silent writer truncation;
- invalid cached context refresh from the current transcript;
- public projection without evidence, offsets, speaker IDs, hashes, or notices.

It still consumes `GroundedContextAnalysisPayload`, not a released
`InvestigationRun`. Therefore it is a working-copy product prototype and must
not be represented as final factual release authority.
