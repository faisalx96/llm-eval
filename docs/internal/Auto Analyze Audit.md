# Auto-analysis release audit and checklist

## Current release decision

**Do not release the Auto-analysis page as a fully signed-off UI yet.** The
highest-risk persistence defect is resolved in the current implementation, and
canonical routing plus several empty/error/accessibility flows now have code,
browser, and test evidence. Remaining release gates are manual visual/assistive
technology acceptance, architecture retirement, and production-scale profiling.
Static tests alone are not sufficient evidence for those gates.

This is an executable checklist for the approved remediation plan. Checked items
are backed by current code and/or named tests; unchecked items are intentionally
release-blocking. Historical findings are retained below, with their current
status, so this document does not imply that an unverified UI fix is complete.

## Evidence-backed changes since the audit

- [x] **Metric-scoped human-label protection.** Persistence refreshes each
  target at the write boundary and skips a result when that metric now belongs
  to a human reviewer, unless `allow_human_overwrite` is explicitly set. Each
  response result reports `persistence_status`, so a client cannot represent a
  skipped output as a saved diagnosis. See
  [`analysis.py`](../../packages/platform/qym_platform/api/analysis.py).
- [x] **Intentional overwrite confirmation.** The page asks for confirmation
  before requesting an overwrite of matching human diagnoses. The server-side
  guard remains authoritative.
- [x] **Exact item/metric target selection.** Selection stores both `item_id`
  and `metric_name`; rows are keyboard-operable and expose selected state.
- [x] **Dedicated-page Escape behavior.** Page mode leaves its root mounted;
  nested dialogs own Escape.
- [x] **Document deletion confirmation.** Project document deletion uses the
  shared confirmation dialog.
- [x] **Recoverable route and load failures.** The analyzer has a loading
  state, alert-style failure state, retry action, and canonical route redirects.
  Route redirect behavior is covered by
  [`tests/platform/test_analysis_routes.py`](../../tests/platform/test_analysis_routes.py).
- [x] **Keyboard tab navigation.** The shared analysis controller handles
  arrows, Home, and End for tabs.
- [x] **Browser release gate.** The deterministic Chromium fixture serves the
  actual analyzer and shared static assets at canonical project/run routes. It
  verifies project/run scope separation, target and direction copy, retryable
  failures, no-LLM and zero-target states, keyboard tabs, 390 × 844 no-overflow
  behavior, RTL `dir=auto`, dashboard filter serialization, bounded
  heatmap-triggered occurrence pagination, console/page errors, and axe
  serious/critical violations. See
  [`test_auto_analysis_release_gate_browser.py`](../../tests/platform/test_auto_analysis_release_gate_browser.py).

The checks above establish implementation coverage, not visual or assistive
technology acceptance. They do not clear the unchecked gates below.

## Release gate checklist

### 1. Safety, data correctness, and API contract

- [x] Protect per-metric human diagnoses at the persistence boundary.
- [x] Require an explicit client confirmation before an intentional overwrite.
- [x] Return per-result persistence outcome and batch totals.
- [x] Keep a metric-specific category-catalog version/id with saved AI metric
  analysis metadata.
- [x] Add a migration and focused regressions for category versioning and
  human-edit protection.
- [x] Add API-level tests for the category-catalog manager/member authorization
  matrix, project isolation, canonical aliases, restore, and stale-save
  conflict. See
  [`tests/platform/test_analysis_routes.py`](../../tests/platform/test_analysis_routes.py).
- [ ] Decide whether aggregation/category counts must be recomputed after a
  late human-protection skip; current aggregation can occur before final
  persistence status is known.

### 2. Category catalog persistence

- [x] Expose legacy data as a synthetic, read-only catalog **v0** rather than
  silently changing existing project behavior.
- [x] Save immutable catalog snapshots with an expected-version conflict guard,
  content-hash no-op behavior, history, and restore-as-new-version semantics.
- [x] Keep the legacy `analysis-config` fields projected from the active catalog
  for compatibility.
- [x] Support optional request pinning with
  `config.category_catalog_version` and persist resolved version provenance.
- [ ] Add a UI for catalog history, conflict recovery, restore, and pinning.
- [ ] Add browser/API contract tests for the catalog UI when it is introduced.

### 3. Empty, error, and route flows

- [x] Render a retryable, alert-style analyzer load failure and preserve a
  recoverable page for missing legacy runs.
- [x] Canonicalize legacy run analyzer URLs, project `?run=` URLs, and scope
  aliases with 307 redirects while preserving safe query parameters.
- [x] Browser-test canonical project/run tab visibility, no-run project mode,
  missing/forbidden run, no-LLM configuration, zero targets, and retry.
- [ ] Browser-test zero-run project context (Rules/Documents), no-target footer
  visibility, no-LLM configuration, missing run, and every redirect variant.
- [ ] Confirm completion refreshes target filters, counts, selection, and CTA
  state in a real browser; code inspection alone is not release evidence.

### 4. Accessibility and responsive behavior

- [x] Give target rows keyboard activation and selected-state semantics.
- [x] Add Home/End tab behavior and prevent page-mode Escape from closing the
  workspace.
- [x] Run automated axe serious/critical checks against the loaded analyzer
  workspace; current Chromium coverage finds no violations at those severities.
- [x] Browser-test the 390 × 844 analyzer viewport with `dir=auto`: the body
  has no horizontal overflow and the primary run control remains discoverable.
- [ ] Run keyboard-only acceptance for every tab, nested dialog, input-mapping
  opener/return focus, upload dropzone, rule history, and error retry.
- [ ] Capture and review visual snapshots at 390px, tablet, desktop, and RTL.
- [ ] Verify the narrow shell sidebar collapses and analyzer flex/grid bases do
  not create horizontal overflow or one-character title wrapping.

### 5. Design language and information architecture

- [ ] Replace remaining analyzer-local tabs, pills, icon actions, help,
  notifications, and selection controls with the documented shared `qym-*`
  primitives where equivalents exist.
- [ ] Remove remaining raw JavaScript colors, undersized readable text,
  inappropriate mono prose, non-tokenized effects, and layout widths that
  diverge from the design language.
- [ ] Clearly label run-scoped analysis versus project-scoped Rules, Documents,
  and catalog persistence; expose saved/dirty state for any editable persistent
  configuration.
- [ ] Make score filtering and severity/limit ordering direction- and
  metric-aware in the UI, with explanatory copy.

### 6. Architecture and performance

- [x] Introduce a DOM-free analysis controller for route/view and tab-keyboard
  behavior.
- [ ] Complete the separation into explicit dedicated-page and modal renderers;
  do not rely on private Playground DOM observation/reparenting for page layout.
- [ ] Profile a realistic large project/run and establish budgets for target
  filtering, rendering, route-load requests, and chart work.
- [ ] Add browser regression tests for controller state transitions,
  initialization failure, Escape, completion refresh, deletion, and routing.

## Category-catalog and persistence contract

These APIs require a UI-session principal with project access. Writes require a
project manager. All catalog snapshots are project-scoped.

| Method | Path | Contract |
| --- | --- | --- |
| `GET` | `/api/projects/{project_slug}/analysis-category-catalog` | Return the active snapshot, or use `?version=N` to read a historic snapshot; `version=0` is synthetic legacy data. |
| `GET` | `/api/projects/{project_slug}/analysis-category-catalog/versions` | Canonical history alias; returns immutable saved snapshots plus synthetic v0 and `can_manage`. The existing `/history` path remains supported. |
| `PUT` | `/api/projects/{project_slug}/analysis-category-catalog` | Manager-only full-snapshot save. Supply `base_revision` for optimistic conflict detection; `expected_version` remains compatible. Identical normalized content returns `created: false`; a conflict is HTTP 409 with `detail.code: catalog_version_conflict` and `detail.current_catalog`. |
| `POST` | `/api/projects/{project_slug}/analysis-category-catalog/versions/{version_id}:restore` | Canonical manager-only restore alias. It creates a new immutable snapshot even when content matches the active snapshot; the existing `/{version}/restore` path remains supported. |

`POST /api/runs/{run_id}/analyze`, `/analyze-preview`, and `/analyze-test`
accept top-level optional `category_catalog_version_id`; all retain nested
`config.category_catalog_version` for numeric-version compatibility. Omit both
to use the active saved version (or synthetic v0). The resolved version and
snapshot id are saved in
`item_metadata.metric_analyses[metric_name]` as
`category_catalog_version` and `category_catalog_version_id`.

A saved snapshot keeps the legacy active-label fields (`categories`, details,
and taxonomy) and also exposes stable `category_entries` records with an `id`,
label, and `active`/`archived` status. It carries
`max_root_cause_categories`, `parent_version_id`, `restored_from_version_id`,
and `is_active`; these fields make the snapshot representation backward
compatible while retaining catalog lifecycle provenance.

Every analysis result has one of these persistence outcomes:

| `persistence_status` | Meaning |
| --- | --- |
| `persisted` | The metric analysis was written. |
| `skipped_human_protection` | A human diagnosis existed at the final write boundary and overwrite was not authorized. |
| `analysis_failed` | The analyzer errored or the returned result could not be associated with a valid requested metric target. |

Batch responses include `total_attempted`, `total_persisted`,
`total_skipped_human`, and `total_analysis_failed`; `total_analyzed` remains an
alias for attempted results. `persistence_totals` repeats the same counts for
compatibility. A caller must use these outcomes, rather than the number of LLM
responses, to report saved analysis.

Deploy migration
[`0040_project_category_catalog_versions`](../../packages/platform/qym_platform/migrations/versions/0040_project_category_catalog_versions.py)
before exposing these APIs.

## Canonical analyzer routes

The canonical focused-run route is
`/projects/{project_slug}/runs/{run_id}/analyzer`. The project workspace route
is `/projects/{project_slug}/analysis`.

- `/run/{run_id}/analyzer` redirects to the canonical focused-run route when
  the run and active project resolve.
- `/projects/{project_slug}/analysis?run={run_id}` redirects to the focused-run
  route.
- Project workspace scope aliases canonicalize as `diagnosis → categories`,
  `project → rules`, and `run → dashboard`.
- A focused-run route requested with a project-only scope redirects to the
  project workspace. Unknown/missing legacy runs still serve the analyzer page
  so it can show its own recoverable error state.

## Historical findings and rationale

The original audit identified a P0 human-correction overwrite, incorrect
item-only test selection, page-closing Escape behavior, destructive document
deletion, incomplete empty/error states, mouse-only targets, missing tab keys,
narrow-layout overflow, inconsistent components, unclear scope/persistence, and
modal-to-page DOM surgery. The first group is now partially or fully addressed
in the evidence-backed section above. The visual consistency, responsive,
information-architecture, and rendering-architecture observations remain open
until the corresponding release gates have browser and accessibility evidence.

The durable architectural direction remains a shared state model with explicit
modal and dedicated-page renderers. The current controller is a useful step,
not proof that the reparenting architecture is retired.

## Required verification record before sign-off

Record command output, browser/assistive-technology evidence, viewport sizes,
and any accepted exceptions for each unchecked item. At minimum run:

```bash
.venv/bin/pytest -q tests/platform/test_analysis_empty_context.py \
  tests/platform/test_root_cause_history.py tests/platform/test_analysis_routes.py \
  tests/platform/test_dashboard_static.py tests/platform/test_design_language.py

.venv/bin/pytest -q tests/platform -m browser
```

Then complete the manual browser matrix at 390px, tablet, desktop, and RTL for:
all tabs; zero-run/no-target/missing-run/configuration-error states; keyboard
selection; Escape/focus return; document deletion; overwrite confirmation;
completed analysis refresh; and every canonical redirect listed above.
