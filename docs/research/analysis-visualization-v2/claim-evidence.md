# Analysis and Visualization v2 Claim-to-Evidence Map

## 1. Primary and local sources

| Source ID | Source | Relevance | Local evidence |
|---|---|---|---|
| UNODC-CIA | UNODC, *Criminal Intelligence Manual for Analysts* | Link, event, flow, activity, frequency, premise/inference, gap, and hypothesis methods | `output/research/analysis-visualization-20260810/sources/UNODC-Criminal-Intelligence-for-Analysts.pdf`, SHA-256 `46c5be43...b3e5` |
| CIA-SAT | CIA, *A Tradecraft Primer: Structured Analytic Techniques for Improving Intelligence Analysis* | Explicit assumptions, source quality, uncertainty, alternatives, disconfirming evidence | `output/research/analysis-visualization-20260810/sources/CIA-Tradecraft-Primer.pdf`, SHA-256 `48fe6cd5...52e` |
| NIST-AIRMF | NIST AI RMF 1.0 | Intended scope, TEVV, benchmarks, uncertainty, independent review, human oversight | `output/research/analysis-visualization-20260810/sources/NIST-AI-RMF-1.0.pdf`, SHA-256 `7576edb5...9f1` |
| NIST-ASR | NIST OpenASR21 Evaluation Plan | WER and reference/segment evaluation discipline; confidence limitation | `output/research/analysis-visualization-20260810/sources/NIST-OpenASR21-Evaluation-Plan.pdf`, SHA-256 `3255dbf8...7ff` |
| NIST-SRE | NIST SRE24 Evaluation Plan | Speaker/person detection is a calibrated detection task, distinct from diarization labels | `output/research/analysis-visualization-20260810/sources/NIST-SRE24-Evaluation-Plan.pdf`, SHA-256 `f320c783...6da` |
| QMSUM | Zhong et al., *QMSum: A New Benchmark for Query-based Multi-domain Meeting Summarization*, NAACL 2021, DOI `10.18653/v1/2021.naacl-main.472` | Long multi-person, multi-topic meetings are difficult to cover with one short generic summary; user focus/query changes relevance | Live ACL/Crossref metadata checked 2026-08-14 |
| LOCAL-R1 | Existing analysis/visualization research | Repository facts, safety boundaries, source manifest | `docs/research/investigative-analysis-visualization-capability-research-2026-08-10.md` |
| LOCAL-R2 | Existing real summary replay artifacts | Four persisted task IDs, source hashes, segments, current local model/runtime evidence | `output/simple-summary-replay/20260814-005213/` |

Full primary-source provenance and hashes remain in
`output/research/analysis-visualization-20260810/source-manifest.json`. All 12
locally stored PDFs were re-hashed on 2026-08-14 and matched the manifest.

## 2. Product claims

| Claim | Evidence | Design consequence | Limitation |
|---|---|---|---|
| Investigation analysis should organize links, chronological events, flows, activities, frequencies, gaps, and premises. | UNODC manual, locally extracted lines 751-805 and 1822-1848 | Insight and visualization taxonomy includes overview, event timeline, explicit relationship graph, exact values, actions, contradictions, gaps | Techniques are general; one audio file may not contain enough data for every view |
| A chart is an aid to analysis, not an independent factual authority. | UNODC lines 798-814; chart clarity guidance lines 2454-2461 | Visualization is a deterministic projection and cannot generate facts | Does not by itself guarantee the LLM analysis is correct |
| Event views should preserve chronology and clear event descriptions. | UNODC event-flow lines 3276-3295 | Timeline uses explicit described time or stable source order | A speaker's described time is not proof the external event occurred |
| Inferences/hypotheses require premises, alternatives, gaps, and testing. | UNODC lines 800-814, 2839-2882; CIA ACH lines 611-654 | v2 prioritizes contradictions, uncertainties, and follow-ups; it does not present a model-selected story as fact | Full competing-hypothesis analysis is out of scope for the simple first release |
| Source quality and uncertainty must remain visible. | CIA lines 413-479; NIST AI RMF lines 1304-1337 | Partial/degraded states are visible; evaluation reports uncertainty and limitations | The compact schema does not provide formal confidence calibration |
| Human oversight and repeatable evaluation are required for high-impact use. | NIST AI RMF lines 1251-1273, 1304-1337, 1825-1843 | The feature is assistive; promotion requires human review and a blinded usefulness study | National law and agency policy still govern deployment |
| Speaker contribution can be visualized, but diarization labels are not identities. | NIST SRE24 task definition and multi-speaker conditions; local prior research | Contribution metrics are computed from diarized segments and labelled as file-local speakers | DER/JER and identity validation require separate annotated data |
| Long multi-speaker meetings challenge a single short generic summary. | QMSum abstract and benchmark metadata | Analysis output is category-based and length is advisory, not a fixed word quota | QMSum is mostly meeting summarization, not Vietnamese investigative audio |
| Exact structured output should degrade to useful plain text rather than trigger repair chains. | User product requirement; previous writer failure evidence; local four-task simple-summary replay | One generation call, tolerant parse, `partial` fallback, no repair call | Must be measured on the deployed local model; this is a product choice, not a literature theorem |

## 3. Current repository observations

| Observation | Evidence | Status |
|---|---|---|
| The older context service used deterministic fallback, grounding, augmentation, and strict success paths. | `src/services/summarization/context_service.py` inspected 2026-08-14 | Being simplified by the current implementation team |
| The active product supports overview, key points, participants, events, actions, entities, relationships, contradictions, uncertainties, follow-ups, and plain-text fallback. | Current backend/frontend team contract messages and local components/tests | Contract target for v2 |
| Frontend visualization scope is timeline, explicit relation graph, speaker contribution, entity frequency, and action/status overview. | Current frontend implementation owner report | Taxonomy/eval scope locked to reachable views |
| Four persisted tasks have complete transcript and top-level segments in prior read-only artifacts. | `output/simple-summary-replay/20260814-005213/*.json` | Available for post-implementation replay |

## 4. Unsupported claims

No source reviewed supports any of these as a factual model output:

- guilt, deception, dangerousness, motive, intent, or criminality from voice;
- identity proof from diarization labels;
- treating a source statement as proof an external event occurred;
- inventing a relationship because two names co-occur;
- legal admissibility or authorization conclusions;
- general production accuracy from a handful of synthetic or persisted tasks.

## 5. Source limitations

- UNODC/CIA documents establish analytic practice, not AI accuracy or Vietnamese
  legal authority.
- NIST AI RMF is a general risk framework, not a law-enforcement deployment
  authorization.
- QMSum motivates long-dialogue coverage but is not a Vietnamese police corpus.
- Live verification was limited to official/primary metadata endpoints and the
  already downloaded source bundle. The W3C page returned HTTP 403 from this
  environment; its existing local citation was not needed for the compact v2
  contract.
- The repo lacks a sufficiently large, authorized, human-labelled Vietnamese
  corpus for a production-quality claim.

