# Findings

## Current Understanding

- The product already has a usable end-to-end ownership path for Analysis:
  API request, one service call, task-result persistence, task retrieval, and
  frontend rendering. A new release-run subsystem is not required to deliver
  the requested product behavior.
- The legacy context implementation is over-constrained: strict nested schema,
  evidence binding, deterministic augmentation, grounding validation, and
  fallback generation can reject or replace otherwise useful LLM analysis.
- Visualization can be generated entirely from the Analysis payload plus
  deterministic speaker statistics derived from diarized segments.

## Product Direction

- Prefer useful partial analysis over an all-or-nothing response.
- Ask the model to distinguish reported, planned, completed, uncertain, and
  conflicting content, but do not require every category to be present.
- Keep tone/sentiment explicitly indicative; never present guilt, deception,
  criminal intent, identity, or psychological state as facts.
- Use charts only when the data supports them: timeline, relationship graph,
  speaker contribution, entity frequency, and action status.

## Lessons And Constraints

- Fixed word-count targets and hard semantic gates previously caused avoidable
  failures in Summary and should not be reproduced in Analysis.
- Missing optional insight types are normal for real conversations.
- LLM JSON can be imperfect. Recover a JSON object when possible and preserve
  non-empty plain analysis text rather than failing the whole feature.
- Clone/run stability must be verified after implementation because the current
  workspace has many local scripts, generated artifacts, and dirty changes.
- V6 demonstrates that adding more category-specific instructions can increase
  schema population while reducing factual quality. Optional analysis sections
  need an explicit empty-by-default policy and evidence-first selection.
- Actor/object binding and temporal modality are the highest-risk failure modes
  in the locked real tasks; an output can be fluent and still reverse who
  requested an action or turn an announced event into an occurred event.
- Read-only replay and runtime persistence are separate gates. A stale V6 E2E
  proved persistence/cache behavior but cannot promote V7 semantic quality.
- For the deployed local 8B model, optional fields in the JSON schema behave as
  generation affordances, not merely storage slots. Prompting them to stay empty
  is weaker than excluding them from the provider contract.
- Requiring an evidence quote beside a free-form paraphrase is insufficient:
  the paraphrase can still change units or actors while the quote remains
  correct. For the product's current model, source quotes are a safer key-point
  and action representation, with the LLM reserved for the overview.
- V9 shows that reserving even the overview for free-form generation is still
  too permissive for the current local model: it can add an administrative
  level that the transcript does not state. Open-action selection also cannot
  reliably distinguish questions that were answered later in the same call.
- V10 therefore uses the LLM only as a passage selector. Product usefulness is
  measured by main-thread quote coverage, while factual correctness is bounded
  by contiguous-source projection rather than a downstream semantic gate.
- V10 demonstrates a safety/usefulness trade-off: exact quote selection avoids
  fabricated facts, but it is not the contextual analysis experience requested
  by the product and its uncertainty classification remains noisy.
- The simpler product architecture is V11 direct text: one carefully scoped
  prompt, one model response, direct persistence and direct UI rendering. The
  model is evaluated by replay and human factual review instead of forcing its
  prose through a brittle structured parser or repair pipeline.
- Direct text is an architecture simplification, not a factual guarantee. V11
  showed that prompt context can still encourage story completion on sparse
  audio. Short/noisy sources need an explicit abstention-style instruction,
  while long sources need coverage guidance that does not invite unsupported
  participants, relationships or emotions.
- Actor reversal remains a high-severity failure even in direct prose. Prompt
  evaluation must explicitly audit who required, promised, sent, received or
  paid what; preserving the nouns and amount alone is insufficient.

## Open Questions

- How well does the current local 8B model populate the compact schema across
  short, long, single-speaker, and multi-speaker transcripts?
- Which product capabilities provide measurable analyst time-to-answer gains
  without overstating uncertain model inference?
