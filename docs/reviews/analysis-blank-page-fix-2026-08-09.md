# Analysis Blank Page Fix Review

Date: 2026-08-09

## Decision

PASS for the reported completion-time blank-page defect.

## Confirmed Root Cause

The visualization request completed successfully. The crash happened while rendering the completed payload:

- `context_analysis.slang_detected` can be an object such as `{has_slang: false, terms: []}`.
- `InvestigationSummaryCard` passed that object directly to a React child inside an alert.
- React raised `Objects are not valid as a React child` and unmounted the application root.

The browser/network trace eliminated the initial race-condition hypothesis for this incident. Summarize and Visualize have overlapping responsibilities and duplicate persistence paths, but the reproduced request contained one visualization POST and the fatal error occurred deterministically during render.

## Fix

- Added recursive, cycle-safe normalization for scalar, array, object, empty, and legacy analysis values in `frontend/src/utils/analysisRender.ts`.
- Added domain-specific normalization for `slang_detected`: an explicit no-slang object renders nothing; terms render as text; a positive flag without terms renders a concise message.
- Routed analysis-card fields through normalized strings before they reach React children.
- Added `frontend/tests/analysisRender.test.ts` to cover string, number, boolean, null, array, generic object, circular object, and slang-object variants.
- Restored reproducible frontend dependency declarations for imports already present in the tracked application (`dayjs`, `react-h5-audio-player`, and the `react-copy-to-clipboard` type package). A clean index checkout had exposed that prior local builds depended on undeclared packages left in `node_modules`.

## Verification

- `node --test tests/analysisRender.test.ts`: 2 passed.
- Clean staged snapshot: `npm ci`, `node --test tests/analysisRender.test.ts`, and `npm run build`: PASS.
- Authenticated Playwright reproduction against the same completed payload: visualization POST 200 and task GET 200.
- The selected case/file remained mounted.
- Overview, relationship graph, timeline, insight, sensitive-information, and sentiment tabs rendered without a fatal exception.
- Browser console contained no invalid React-child error after the fix.

Local evidence is stored under `output/playwright/analysis-completion-blank-page-duplicate-flow/`. The trace and screenshot are intentionally not committed because they contain live case/task context and authenticated runtime data.

## Residual Risks

- Summary and Visualization still overlap in structured-analysis generation and persistence ownership. This is not the root cause of this crash, but it should be consolidated into one canonical analysis pipeline with idempotent writes.
- Pre-existing MUI warnings remain for tooltips wrapping disabled buttons; they do not crash the application but should be cleaned up in a UI hygiene task.
- Payload normalization prevents render failures; it does not by itself improve the investigative quality, factual coverage, or adaptive reasoning of Summary/Analysis. Those require the separate evidence-first redesign and evaluation plan.
