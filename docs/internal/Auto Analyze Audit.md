# Auto-analysis release audit and checklist

## Current release decision

**The 14 design-language contradictions are resolved.** Source contracts and a
rendered five-tab browser pass now cover the typography floor, page anatomy,
shared components, token use, scope signaling, wide analytical layout, and the
dedicated-page renderer. Full release sign-off still requires the separately
listed assistive-technology acceptance and production-scale profiling gates;
those are not design-language contradictions.

This is an executable checklist for the approved remediation plan. Checked items
are backed by current code and/or named tests; unchecked items are intentionally
release-blocking. Historical findings are retained below, with their current
status, so this document does not imply that an unverified UI fix is complete.

## 2026-08-11 full-page review

This review captured the pre-remediation implementation without changing the
design-language document. It combined source and route inspection, the
deterministic browser fixture, rendered desktop checks, the existing
390 × 844/RTL/browser contracts, and
`pytest -q tests/platform/test_design_language.py` (9 passed). The remediation
and its current verification evidence are recorded below; the original findings
remain as historical evidence.

The browser review covered:

| Surface | Screens and states inspected |
| --- | --- |
| **Dashboard** | Empty/populated summaries, all nine multiselect filters, date switcher, distribution, direction-aware score context, run/category chart, a 650-occurrence paged dot map, two-run selection, and comparison controls. |
| **Analyze run** | Project no-run landing, metric/context selection, instructions, target filters/list/pagination, prompt preview, sticky connection/Test/Analyze command area, input-mapping dialog, connection picker, no-LLM state, and zero-target state. |
| **Diagnosis categories** | Category navigation, Guidance, Details, and Examples sub-tabs, category/detail search, add/remove controls, save state, and approved-example counts. |
| **Production rules** | Populated published-version initial load, rule summary/search/list/pagination, read-only state, generation precondition, source controls, version-history lineage drawer, and the compare/merge/lifecycle code paths. |
| **Documents** | Empty project library, upload dropzone, prompt-budget copy, enabled-document model, and confirmed deletion path. |
| **Cross-cutting** | Five-tab keyboard semantics, canonical routes/scope aliases, loading/retry/missing/forbidden states, dialogs and focus targets, shell integration, and responsive contracts. |

### What is aligned now

- The page anatomy is recognizable and consistent: one page title, description,
  meta line, five first-class tabs, then the active content.
- Page and category tabs use `qym-tabs`; Dashboard time/group/measure switchers use
  `qym-segmented`; Dashboard multiselects use the canonical `qym-dropdown` order;
  Dashboard statistics, tags, badges, controls, and selected-run chips use shared
  primitives.
- Major Dashboard and run sections use sentence-case `--font-lg` headings with a
  concise `--font-sm` muted description. Most colors and type sizes resolve through
  root tokens, and the analyzer-local `--text-dim` uses are decorative separators.
- The rendered page exposes tablists/tabpanels, selected/expanded/pressed state,
  focusable occurrence dots, exact item/metric target selection, keyboard tab
  movement, retryable alerts, and explicit no-connection/zero-target explanations.

### 2026-08-11 remediation verification

All 14 findings below are resolved without editing `docs/DESIGN_LANGUAGE.md`.

| # | Resolved conflict | Current implementation evidence |
| --- | --- | --- |
| 1 | Readable 10px text | Analyze run, Rules, Categories, Documents, and Dashboard have no rendered text below 11px outside canonical `qym-tag`, `qym-badge`, and `qym-help-marker` chrome. Labels and prose now use `--font-sm` or `--font-base`. |
| 2 | Hero meta role and mono prose | `.analysis-meta` renders at `--font-base`; only `.analysis-meta-data` is mono, while `metric failure diagnosis` is sans. |
| 3 | Hero ellipsis | `.analysis-description` now uses `white-space: nowrap`, hidden overflow, and text ellipsis. |
| 4 | Input mapping modal density | The rendered title is 18px; Close is a 24px `qym-icon-action`; Done is a 24px accent `qym-inline-action`. |
| 5 | Legacy pagination | Target, rule, category, and approved-example pagination use the canonical renderer with First/Previous/page entry/Next/Last and page-change callbacks. No analyzer call uses `run` or `compact` variants. |
| 6 | Recreated toolbar controls | Metrics use `qym-chip`; Select all, Clear, Input mapping, empty-state recovery, and footer actions use shared inline actions. Local 30/34/36/38px action densities were removed. |
| 7 | Noncanonical icon actions | Context links, category/document deletion, prompt expand/copy, and modal close use 24px `qym-icon-action` behavior without page-local hover tiles. |
| 8 | Custom rules help | The redundant Production-rules information marker is removed. Version behavior is conveyed by the visible header description, version state badge, and labeled actions; the custom button/popover and event controller remain gone. |
| 9 | Raw JS colors and spacing | `playground.js` has no raw hex/`rgba()` colors, fallback hex, or inline `margin-top:2px`; root-cause encoding uses chart/score/semantic tokens and CSS custom properties. |
| 10 | Local geometry/effects | The cited hardcoded radii, 30/34/36/38px controls, 22/32px actions, and numeric popover/modal shadows were replaced by root geometry/spacing tokens and shared component sizes. |
| 11 | Constrained analytics | The hero, tabs, and constrained configuration cards share the same centered 1120px edges, while Dashboard remains a full-width analytical surface. |
| 12 | Mixed project/run persistence | Max categories is a run-request control inside Targets and is serialized by the dedicated run payload. Diagnosis categories retains explicit Saved/Unsaved/Saving/failed states, category saves preserve the project default, and redundant `Project setting` heading tags are removed from every tab. |
| 13 | Local semantic pills | Rule editable/read-only and target pass/fail/error/neutral states use `qym-badge`; metric/count metadata uses `qym-tag`. Dedicated-page markup no longer emits `pg-status-badge`. |
| 14 | Modal construction/reparenting | `playground.js` now has explicit modal and `playground-page-root` renderers. Auto-analysis supplies `composePage: composeAnalyzerWorkspace`; the modal overlay, post-mount observer, and `organizeWhenReady()` path are gone. |

The analyzer-specific static contract in
`tests/platform/test_dashboard_static.py` asserts these choices directly. The
targeted verification result is 52 passed; 16 opt-in Playwright cases remain
environment-skipped when Chromium is unavailable. The same deterministic fixture
was also inspected in the in-app browser across all five tabs, the Input mapping
dialog, populated rules, no-connection/zero-target states, and wide layout.

### Historical design-language contradictions — resolved

| Severity | Contradiction | Pre-remediation evidence | Design-language requirement and impact |
| --- | --- | --- | --- |
| **High** | Readable 10px text is widespread in Analyze run, Rules, and Documents. | Rendered 10px copy includes `Task`/`Model`/`Dataset` (`.analysis-run-context-label`), `Metrics to analyze` (`.analysis-run-label`), `2 of 2 metrics selected`, all three context descriptions, the Additional instructions and Documents explanatory hints (`.pg-instructions-hint`), `80%`, target metric/count text, sticky-footer help copy, `LLM connection`, and the rule summary `2 rules · ~24 prompt tokens · no rule count limit`. | The 11px floor is absolute and 10px is reserved for badge/pill chrome. These are labels, descriptions, values, or prose, not badges. Increase them to the appropriate `--font-sm` or `--font-base` role; retain 10px only for real `qym-badge`/`qym-tag` content. |
| **High** | The hero meta line uses the wrong type role and mono prose. | `.analysis-meta` resolves to `--font-sm` (11px), while both the project value and the literal phrase `metric failure diagnosis` inherit `.analysis-meta-value { font-family: var(--font-mono) }`. | Page anatomy specifies a `--font-base` meta line. Mono is data-only and must not style a sentence or UI phrase. Keep a project slug/ID mono only when it is actually data; render `metric failure diagnosis` in sans. |
| **Medium** | The hero description does not implement the documented one-line ellipsis. | `.analysis-description` sets a maximum width and line height but has no `white-space: nowrap`, overflow clipping, or text ellipsis. It wraps at narrower widths. | The page-hero recipe specifies one line with ellipsis. Either implement that recipe or deliberately amend the UI copy/layout; the design-language document is not to be changed for this page. |
| **High** | The Input mapping modal title is a section header, not a modal title. | `.analysis-wizard-title` uses `--font-lg` (15px). The dialog also uses a custom 32px tiled close button and custom 36px footer action. | Modal titles use `--font-xl` (18px), and compact icon actions use the shared 24px recipe. The current dialog is visually subordinate to the page sections and introduces a second action density. |
| **High** | Auto-analysis invokes the shared pager with a variant that directly contradicts the documented pager recipe. | Target, rule, and category pagination call `QymUIComponents.renderPagination(..., { variant: 'run' })`. That branch renders visible `← Prev`, `Page N of M`, and `Next →` controls and omits First/Last and direct page entry. | The recipe requires four borderless icon buttons around the page entry/total and explicitly forbids repeating action names as visible button text. Use the canonical/default renderer; do not reuse the legacy `run` variant for these data views. |
| **High** | Run metric and target toolbars recreate shared control/chip densities. | `Select all`/`Clear` use `.analysis-metric-action` at 30px; metric choices use custom 34px fully rounded checkbox pills; Input mapping, zero-target, wizard, and footer controls use additional 34/36/38px local recipes. | Inline toolbar actions should use the 24px `qym-inline-action` recipe, and interactive filter choices should use the 26px `qym-chip` recipe where applicable. The current page has several visually close but measurably different control systems. |
| **High** | Icon-only actions bypass or override the canonical 24px glyph-only-hover behavior. | Context-tab links are 28px and add a border/background tile on hover; the category delete action has `qym-icon-action` but analyzer CSS adds an error-tinted tile; document delete and preview expand/copy remain 32px `.pg-icon-button`; the mapping close action is another 32px tile. | `qym-icon-action` is 24px and pointer hover changes only the glyph, with semantic red/green retained for destructive/affirmative meaning. Migrate the legacy actions and remove page-local hover surfaces. |
| **Medium** | Production-rules help recreates the help component. | `.analysis-info-button` is a custom 22px circle that toggles `.analysis-info-popover` through `aria-controls`; the copy duplicates visible version guidance. | Remove the redundant marker and keep version behavior in the visible description, semantic state badge, and labeled actions. |
| **High** | Analyzer-generated UI still contains raw color and spacing literals. | `playground.js` defines a root-cause hex palette and fallback, hardcodes confidence-dot hex colors, uses literal purple `rgba(...)` in preview loading, includes `var(--text-primary, #eee)`, and emits inline `margin-top:2px`. | Colors and spacing must come from tokens; JS is subject to the same rules. Root-cause data encoding should resolve through chart/semantic tokens, and inline layout should use spacing tokens/classes. The alpha-suffix exception does not authorize standalone raw palettes or `rgba(...)`. |
| **Medium** | Page-local geometry/effects remain extensively non-tokenized. | `analyzer.html` contains repeated hardcoded 6/8/10px radii, 30/34/36/38px control heights, 22/32px actions, and numeric 12/18/24/28/60/80px shadow components. | The vocabulary says colors, sizes, spacing, and fonts come from root tokens and new values require tokens first. These literals make the page drift independently even when typography/color tests pass. |
| **Medium** | A data-dense Dashboard and run-comparison surface is forced into the constrained-page width. | `.analysis-page` caps every tab at 1120px, including the occurrence grid and run comparison. Large maps therefore compress into the same width as configuration forms. | Page anatomy says data-dense pages such as compare/charts/datasets go full-width while constrained administrative pages use 1120px. Split the configuration and data-dense layouts, or make Dashboard/compare opt into the full-width anatomy. |
| **High** | Project persistence and run-request scope remain visually mixed. | `max_root_cause_categories` has a project default but can be overridden by an analysis request; category save lives on another tab. Rules auto-save a draft, categories require explicit save, and context switches are request-only. | Place the override with Targets, serialize it only in the run request, preserve the project default during category saves, and expose the category editor's saved/dirty state without repetitive scope tags. |
| **Medium** | Semantic state pills are only visually similar to shared badges. | Rules uses local `.analysis-rule-view-state` classes for `Read-only`/editable state, while older playground result/target states still use `pg-status-badge`/legacy action families. | Status and outcome labels use `qym-badge` semantic tones and shapes. Reusing the shared classes is required for consistent density, accessibility behavior, and future token changes. |
| **Medium** | The dedicated page still depends on modal DOM construction and reparenting. | `playground.js` builds the legacy overlay, after which `organizeAnalyzerWorkspace()` observes, extracts, moves, removes, and restyles its private sections into the five-tab page. | This is not a single CSS-token violation, but it is the reason modal-only classes and densities leak into the page. The durable direction remains explicit page and modal renderers over a shared state model. |

### Documentation contradictions corrected in this review

| Previous documentation claim | Implemented behavior now documented |
| --- | --- |
| The page had two scopes, Project context and Run analysis. | The page has Dashboard, Analyze run, Diagnosis categories, Production rules, and Documents tabs, each with explicit project/run scope. |
| Users could edit a project description in Auto-analysis. | Migration `0037_remove_project_desc` removed it; reusable context is supplied by rules, documents, category guidance, request instructions, and trace evidence. |
| Users edited the system prompt in Auto-analysis. | Three persistent system prompts live in Project Settings; Auto-analysis owns request instructions and mapping only. |
| The current page exposed all/pass/fail/error, complexity, domain, root-cause, and explicit-ID filters. | Analyze run exposes failed-target metric selection, max categories per item, max score, skip analyzed, confirmed human overwrite, optional limit, and exact target selection. Additional filters remain API capabilities. |
| The page tested up to three items. | The page tests the one selected item/metric target; the API accepts up to three item IDs. |
| A run selected individual documents. | Documents are enabled at project level; Analyze run includes/excludes the enabled set with one request switch. |
| The analyzer migration head ended at `0034_draft_rule_activation`. | The current head is `0041_analysis_prompts`, including rule merge lineage, project document enablement, multi-category/taxonomy/catalog versions, and project system prompts. |

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
- [x] **Keyboard tab navigation.** The analyzer's inline tab handler and shared
  component behavior handle arrows, Home, and End for tabs.
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

- [ ] Introduce a DOM-free analysis controller for route/view and tab-keyboard
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
modal and dedicated-page renderers. The current analyzer still owns route/view
state inline; a controller can be introduced later if the architecture is
refactored again.

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
