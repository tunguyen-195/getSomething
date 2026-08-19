# Analysis and Visualization v2 Taxonomy

## 1. Design principle

The taxonomy is a menu, not a mandatory checklist. The LLM selects only insight
types supported by the conversation. The UI renders only data that exists.

The four layers must remain visually distinct:

| Layer | Meaning | Example label |
|---|---|---|
| Source statement | What a speaker/transcript states | “SPEAKER_1 noi se giao ho so luc 09:00.” |
| Analysis observation | A concise organization of source statements | “Hai moc gio 08:00 va 09:00 dang mau thuan.” |
| Uncertainty/gap | What cannot be resolved from this file | “Chua xac dinh gio chinh xac.” |
| Follow-up | A suggested verification question | “Kiem tra giay moi hoac lien he ban to chuc.” |

## 2. Insight taxonomy

| Type | Useful content | Minimum support | Do not infer |
|---|---|---|---|
| Overview | Central topic, purpose, and outcome of the conversation | Whole transcript | Motive or criminal characterization |
| Key point | Material statement, decision, request, commitment, denial, or outcome | One explicit passage | Importance based only on dramatic wording |
| Participant | File-local speaker, explicitly named person, stated role | Explicit wording or diarization label | Identity behind `SPEAKER_1` |
| Event | Actor, action, object, place, described time, state | Explicit statement | That the event actually occurred outside the recording |
| Action/commitment | Who will/should/did do what, deadline, status | Explicit request, plan, promise, or completion | Completion when source says planned/conditional |
| Entity | Person, organization, location, account, phone, document, vehicle, object, money/quantity | Exact mention | Alias resolution without evidence |
| Relationship | Directed relationship stated in the conversation | Explicit predicate and endpoints | Relationship from co-occurrence alone |
| Contradiction | Incompatible time, value, owner, location, action, denial/correction | Both conflicting statements | Which statement is true |
| Uncertainty | Ambiguity, missing identity/time/place/source/corroboration | Explicit ambiguity or missing field | Fabricated confidence score |
| Follow-up | Concrete verification question/action | A stated gap or contradiction | Operational authority or intrusive action |
| Tone indicator | Wording-based conversational tone | Direct lexical/contextual support | Lie, guilt, fear, intent, personality |

## 3. Visualization taxonomy

| View | Input fields | Use when | Omit when | Truth constraint |
|---|---|---|---|---|
| Overview cards | overview, key points, counts | Always when content exists | Analysis has only plain fallback text | Counts are computed, not narrated |
| Event timeline | events/actions with time or stable source order | Two or more ordered items | No meaningful order | Separate described time from audio offset |
| Speaker contribution bars/donut | segment duration and word counts | Valid diarized segments exist | No speaker labels/metrics | Labels are anonymous clusters unless explicitly mapped |
| Entity frequency bars | normalized entity mentions | At least two supported mentions/categories | Sparse single mention | Frequency means mentions, not importance |
| Relationship network | explicit relationships | At least one valid edge | Endpoints or predicate missing | No co-occurrence edges; click-through retains source text if available |
| Action/status board | actions and follow-ups | At least one action | No actions | Status limited to stated/planned/completed/denied/unknown |
| Exact-value cards/table | money, quantities, accounts, codes, dates | Exact values exist | None exist | Preserve surface form, speaker/source, unit, owner when supplied |
| Money/object flow | explicit source, destination, object/amount | Complete directed flow exists | Direction or endpoint missing | Never fill a missing intermediary/beneficiary |
| Contradiction list/matrix | contradictions | At least one explicit conflict | No conflicts | Show both sides and unresolved state |
| Uncertainty/follow-up queue | uncertainties, follow-ups | Any open question exists | None | Suggestions are not facts or commands |
| Location cards | explicit locations | Locations are mentioned | None | No geocoding/map by default |

## 4. Projection rules

1. Normalize missing arrays to `[]` and missing prose to `""`.
2. Drop malformed individual items without dropping valid siblings.
3. Preserve original strings; normalization is for matching and layout only.
4. Never turn an entity mention into an event or relationship.
5. Never turn a reported statement into an externally verified event.
6. Never collapse opposite claims into one value.
7. Stable ordering uses source order/time first, then input order.
8. Speaker metrics are host-derived from segments:
   - `word_count`: whitespace-token count per speaker;
   - `duration_seconds`: sum of valid non-negative `end-start` spans;
   - shares use the corresponding observed total and are labelled by measure.
9. If timing spans overlap, the sum may exceed recording wall-clock duration;
   display this as speaking time, not elapsed recording coverage.
10. A chart title and legend must state what was counted.

## 5. Minimum user-facing hierarchy

Render in this order when present:

1. overview and key points;
2. events and actions;
3. people/entities and explicit relationships;
4. contradictions and uncertainties;
5. follow-ups;
6. source-derived speaker metrics;
7. provenance/runtime details in a secondary disclosure.

This order prioritizes understanding over chart density.

