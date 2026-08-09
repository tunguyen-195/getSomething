# S2 Summary Surface / Visualization Separation Audit

**Date:** 2026-08-09

**Workspace:** `E:\research\STT`

**Branch:** `feature/architecture-refactor`

**Base HEAD:** `ab5016c3383d7ebac105fc110b6de779c8ff0dcc`

**Artifact:** `docs/reviews/artifacts/s2-summary-surface-separation.json`

## Objective

Close the remaining S2 UI path that could make a Summary operation appear to
generate visualization. The summary surface must render released summary facts
as readable statements, must not duplicate key points as business insights, and
must not construct graph or timeline output from raw `context_analysis`.

## Falsifiable Requirements

1. A `category=key_point` fact renders only its `statement`; internal fields
   such as `fact_id`, `category`, `evidence_ids`, `model_generated`, and
   `verification_status` are not serialized as prose.
2. Rejected facts are hidden and duplicate statements collapse to one item.
3. Business insights remain hidden until a reasoning-release authority exists.
4. `InvestigationSummaryCard` contains no graph/timeline renderer and no
   visualization-labelled tab.
5. Visualization remains a separate consumer of a strict released artifact.
6. Summary backend paths do not generate visualization and the async worker
   persists only a partial summary patch.

## Finding

The prior S2 commit correctly removed model/regex visualization generation and
added strict released-artifact validation. A residual legacy UI path remained:
`InvestigationSummaryCard` still built `ReactFlow` nodes/edges and a timeline
directly from `context_analysis`. `TaskListItem` also labelled that structured
summary surface as `Data Visualization`.

This explained why Summary could still look like it produced visualization even
though the backend no longer generated a visualization artifact.

## Implementation

- Removed `ReactFlow`, MUI timeline imports, graph projection, timeline
  projection, and their tabs from `InvestigationSummaryCard`.
- Kept the readable overview, key-point statement projection, optional released
  insight surface, sensitive-data view, and sentiment view.
- Renamed the legacy tab from `Data Visualization` to `Thong tin trich xuat`
  and `Details` to `Noi dung day du` in source Vietnamese text.
- Added negative semantic assertions that summary components cannot contain
  graph/timeline renderers or the legacy visualization label, while
  `VisualizationDialog` must still use the strict released-artifact selector.

## Verification

| Gate | Result |
|---|---|
| Frontend semantic harness | PASS, 9/9 tests |
| Frontend TypeScript + Vite build | PASS, Vite 6.3.5, 12,076 modules |
| Backend S2 targeted suite | PASS, 114 tests, 13 warnings |
| Negative source scan | PASS, zero summary-surface visualization hits |
| `git diff --check` for task files | PASS |
| Independent frontend audit | PASS, zero blocking findings |
| Live frontend/backend health | HTTP 200 / HTTP 200 |

The production build generated `710.91 kB` JavaScript (`217.83 kB` gzip). The
existing chunk-size warning remains advisory and is not caused by this patch.

A read-only PostgreSQL search found zero current task rows containing the two
exact Vietnamese statements supplied in the issue. This does not prove that no
other legacy payload exists; it only shows the exact reproducer is not present
in the current database snapshot.

## Residual Risk

- The frontend validates `content_hash` shape but does not recompute the
  canonical visualization hash. Backend validation remains authoritative.
- Trusted visualization release persistence/rehydration (C1) is still absent;
  stored JSON cannot recreate process-local release authority.
- This follow-up did not perform an authenticated browser E2E with the exact
  historical payload because that payload was not present in the live database.
- S3 summary type/length, S4 synchronous fail-closed, G1 GPU recovery, runtime
  profile, diarization completeness, and Vietnamese quality benchmarking remain
  separate tasks.

## Verdict

**PASS.** The remaining summary-owned visualization surface is removed. Summary
and visualization now have separate UI ownership, and visualization rendering
continues to require a released artifact.
