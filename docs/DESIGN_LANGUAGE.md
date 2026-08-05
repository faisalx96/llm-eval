# qym Design Language

**The single source of truth for all UI work in this repo.** If you are styling,
editing, or generating anything under `packages/platform/qym_platform/_static/`,
follow this document. It is enforced by `tests/platform/test_design_language.py` —
violations fail CI, so read this before writing CSS, not after.

Scope: the platform dashboard (`_static/dashboard/`). Two sanctioned exceptions
are listed at the end (docs prose scale, the separate `/ui` app).

---

## 1. Vocabulary: design tokens

All colors, sizes, spacing, and fonts come from the `:root` block in
[`dashboard.css`](../packages/platform/qym_platform/_static/dashboard/dashboard.css).
**Never hardcode a value that has a token.** If you need a value that doesn't
exist, add a token first, then use it.

### Text color ramp

| Token | Value | Contrast (on `--bg-surface`) | Use for | Never for |
|---|---|---|---|---|
| `--text-primary` | `#ededf0` | 14.7:1 | Titles, key values, table content that matters | — |
| `--text-secondary` | `#a8a8ba` | 7.3:1 | Body copy, table cells, descriptions | — |
| `--text-muted` | `#9a9ab2` | 6.3:1 | Labels, meta lines, captions, **table headers**. The minimum color for readable text. | — |
| `--text-dim` | `#6b6b80` | 3.3:1 (below AA) | Placeholders, disabled states, decorative glyphs (chevrons, separators, sort arrows) | **Any readable content**: headers, labels, timestamps, counts, IDs, values |

The dim rule is the one most often violated, and it is absolute: if a human is
expected to read it, it is `--text-muted` or brighter.

Semantic colors (`--success/--warning/--error/--info`), the 5-step score scale
(`--score-1..5`), chart colors (`--chart-1..5`), and accents
(`--accent-primary/secondary/tertiary/tertiary-soft`) are for state and data
encoding — they are not part of the hierarchy ramp and don't substitute for it.

### Type scale — every element maps to exactly one role

| Role | Token | Size / weight | Color | Notes |
|---|---|---|---|---|
| Page title | `--font-title` | 22px / 600–650 | primary | One per page. No page invents its own title size. |
| Stat / hero value | `--font-stat` | 26px / 700 | primary or score color | Mono, `tabular-nums`. |
| Modal / empty-state title, mid-tier value | `--font-xl` | 18px / 600–650 | primary | Also emphasized inline stats (e.g. drawer aggregates). |
| Section header | `--font-lg` | 15px / 600 | primary | |
| Card title / sub-header | `--font-md` | 13px / 600 | primary | Also form inputs. |
| Body / table cell / code | `--font-base` | 12px / 400 | secondary | |
| Meta / caption / label / **table header** | `--font-sm` | 11px / 400 (labels 600–650) | muted | Uppercase labels get `letter-spacing: 0.05em`. |
| Badge / pill | `--font-xs` | 10px / 650 | semantic | Badges only — nothing else may be 10px. |

Major analytical sections use a sentence-case `--font-lg` section title followed
by a concise muted `--font-sm` description. Do not introduce a major section
with an uppercase metadata-style label.

**Floor: no readable text below 11px.** 10px is reserved for badge/pill chrome.
Off-scale values (9px, 10.5px, 11.5px, 12.5px, 13.5px, 14px, 16px, 17px, 20px…)
must snap to the nearest role token.

**Glyph exemption:** decorative glyphs — `×` close buttons, `▶`/`▼` disclosure
arrows, `●` markers, `↕` sort hints, emoji, and oversized empty-state icons
(32–48px) — may keep hardcoded pixel sizes. They are icons drawn with text, not
text. The CI test freezes the current inventory of these; adding a new one means
updating the test's allowlist deliberately.

### Font families

- `--font-sans` — everything humans read: names, descriptions, prose, buttons,
  headers, labels.
- `--font-mono` — **data only**: IDs, row numbers, JSON, code, metric/latency
  values, timestamps, version strings. Never for prose or UI chrome. When in
  doubt: if it could contain a sentence, it's sans.
- No other families. No webfonts (DM Sans and Georgia were removed; the CI test
  bans them).

### Shell chrome scale

The sidebar/topbar run 2px larger than page content, via explicit
`--shell-font-xs..lg` tokens (12–17px) defined in `shell.css`. Use these only
for navigation chrome. Never redefine `--font-*` in a scope — that fork was
removed on purpose; one token name means one value everywhere.

### Spacing, surfaces, borders

- Spacing: `--space-xs/sm/md/lg/xl` (4/8/14/20/32px).
- Surfaces (dark → light): `--bg-void` page ground, `--bg-base` content area,
  `--bg-surface` cards/panels, `--bg-elevated` table headers/inputs/nested
  surfaces, `--bg-hover`/`--bg-active` interaction states.
- Borders: `--border-subtle` (default hairlines), `--border-default`
  (inputs, popovers), `--border-strong` (emphasis/dividers).

---

## 2. Hard rules (CI-enforced)

1. **Tokens only** for font sizes and text grays. No new hardcoded `font-size: Npx`
   (CSS) or `fontSize: 'Npx'` (JS) outside the frozen glyph allowlist.
2. **`--text-dim` never on readable content.**
3. **No readable text below 11px.**
4. **Mono for data, sans for words.**
5. **No new font families**; DM Sans / Georgia / webfont imports are banned.
6. **The old grays `#7a7a90` and `#50505e` must not reappear** (they were the
   pre-2026-07 sub-AA ramp).
7. JS-generated markup follows the same rules — `var(--font-sm)` etc. work fine
   inside inline `style` strings; use them.
8. Hex colors may be hardcoded in JS **only** when concatenated with alpha
   suffixes (e.g. `color + '40'`) where `var()` is impossible — note it with a
   comment.

---

## 3. Component recipes (copy these, don't invent)

The shared control and display primitives live in
[`ui_components.css`](../packages/platform/qym_platform/_static/dashboard/ui_components.css),
with shared keyboard/touch behavior in
[`ui_components.js`](../packages/platform/qym_platform/_static/dashboard/ui_components.js).
Load the stylesheet after page-local styles and load the script with `defer`.
New markup uses the canonical `qym-*` classes; the legacy selectors listed
beside them are migration aliases only.

### Control
`.qym-control` is the single aligned-density input recipe: 24px high, 5px
radius, `--font-sm`, and `--font-sans`. The 24px height keeps control text
visually level with adjacent 11px toolbar labels. Add `.qym-input`,
`.qym-select`, or `.qym-search` to describe behavior, not density. There are no
compact or roomy variants. Compact inline action buttons beside these controls
use `.qym-inline-action` and the same height. Add
`.qym-inline-action--neutral` for secondary toolbar actions or
`.qym-inline-action--accent` for the primary action in that row; both use the
shared borderless rounded-rectangle surface. External integration actions may
use a documented brand modifier such as `.qym-inline-action--langfuse`; brand
color belongs to the integration action, never to generic controls. Textareas,
range inputs, the 42px authentication fields, and composite controls such as
the playground connection picker remain separate recipes and must not inherit
`--control-height`.
Within a mixed header action cluster, align direct actions and an adjacent
status badge to the same 24px control height. The badge keeps its pill
silhouette and semantic tint; actions keep their own semantic surfaces.

### Multiselect dropdown
Use `.qym-dropdown` with content in this fixed order:

1. `.qym-dropdown__search`
2. `.qym-dropdown__actions` containing Select All and None/Clear
3. 32px `.qym-dropdown__option` rows

Each option may expose `.qym-dropdown__only`, an explicit “Only” action that
clears the prior selection and keeps that option. Do not hide this capability
behind double-click.

### Tabs and switchers
Section navigation uses `.qym-tabs` + `.qym-tabs__tab`: underline-only active
state, `role="tablist"`/`role="tab"`, and synchronized `aria-selected`. Shared
behavior provides roving focus and Left/Right/Home/End navigation.
Dense dataset collection tabs inside chart cards are the exception: they keep
an elevated strip, a filled active surface with green text/underline, and a
filled count tile on every tab. Horizontally overflowing tab strips reveal
their scrollbar thumb only on hover.
In-place view, metric, repeat, and time switching uses `.qym-segmented` +
`.qym-segmented__option`. The complete segmented control is 24px high so it
aligns with adjacent selectors; options fill its inset content box, and only
the selected option has a Qym-green background. Shared behavior moves one
sliding selection indicator between options, preserves the prior position across
keyed re-renders, re-measures controls after async content or visibility
changes, and disables that motion when the user prefers reduced motion; pages
must not add page-local selection animation.

### Badges, tags, and chips
Status and outcome labels use `.qym-badge`: 20px minimum height, fully rounded,
tinted outline, sans 10px/650. Semantic tones are success
(completed/approved/improved), info (running), danger
(failed/rejected/regressed), warning (draft/stopped), and neutral
(submitted/within-noise). Statuses keep their outline and pill silhouette.

Roles, provenance, versions, passive metadata, and compact counts use
`.qym-tag`: 20px minimum height, borderless, `--control-radius`, and a
tinted/elevated fill. Add `.qym-tag--role`, `.qym-tag--accent`, or
`.qym-tag--count` for those specific meanings; use `.qym-tag--data` or
`.qym-tag--version` when the content itself is data. Semantic filled tones use
`.qym-tag--success`, `--info`, `--warning`, or `--danger`. Roles, counts, data,
and versions are mono; other human-readable tags are sans. A tag may grow
vertically when its content wraps.

Interactive filters use `.qym-chip`: 26px tall, rounded outline, sans 11px/600.
Counts remain mono. Buttons remain real buttons; passive metadata must not use
the chip recipe.

### Compact icon actions
Use `.qym-icon-action` for a single icon-only action such as copy, expand, open,
more, edit, or close. It is a 24px borderless square with
`--control-radius` and a transparent resting surface. Hover and keyboard focus
change only the glyph to Qym green platform-wide: do not add a tile, surface
tint, ring, or glow on pointer hover. Keyboard focus retains the standard thin
focus outline for accessibility. Copied confirmation keeps the green glyph
briefly. Semantic actions keep their meaning: approve/submit use green while
reject/delete use red. Help markers and passive icons are not icon actions and
must not inherit this recipe. Every copy action uses the same 24×24-viewBox
overlapping-rectangles SVG with `stroke="currentColor"`; page-local copy glyphs
or hardcoded stroke colors are not allowed.

### Connected statistics
Primary summary bands use `.qym-stat-strip` with `.qym-stat-strip__item`,
`__label`, and `__value`. The strip owns the outer border; equal cells have
dividers and no individual card borders. Labels are 13px/650 with extra vertical
space before 18px/700 mono values. Tiny card-footer metadata is not a stat strip.
The Runs-table repeat-run **Group metrics** header is also not a stat strip: it
is a compact inline summary within a table group row and intentionally keeps the
`.samples-summary-*` recipe without `qym-stat-strip` classes.
When a connected summary accompanies a section heading, use the compact header
variant: one 34px row, with each icon, label, and value inline. It should match
the heading block's visual height rather than compete with the section content.
When a statistic cell has a leading icon beside a label/value stack, align the
icon container to the top of the stack so it sits level with the label. Never
center the icon against the combined label-and-value height.
Compact model-card metric matrices also remain individual tiles; they are not
page-level summary bands and must not be converted into connected strips.

### Explanations
Use the focusable `.qym-help-marker` with a nested `.qym-help-tooltip`
(`role="tooltip"`). The same 12px marker is used for estimator definitions,
uncertainty, and confidence explanations. Hover/focus opens it; click/touch pins
one marker; outside-click and Escape close it. Shared behavior assigns tooltip
IDs and `aria-describedby`, including for dynamically rendered markers and
standalone exports.

### Data table
Use the shared `QymDataTable` component (`qym_table.js` + `.qdt-table` in
`dashboard.css`) for new tables. Its styles are the reference implementation:

```css
thead th {  /* sticky header */
  font-size: var(--font-sm);        /* 11px */
  color: var(--text-muted);
  background: var(--bg-elevated);
  text-transform: uppercase; letter-spacing: 0.05em; font-weight: 650;
}
tbody td {
  font-size: var(--font-base);      /* 12px */
  color: var(--text-secondary);
  font-family: var(--font-sans);    /* mono only on ID/number/JSON columns */
}
```
Numeric/ID columns add `font-family: var(--font-mono)` and
`font-variant-numeric: tabular-nums` per column, not per table.
Right-align scalar numeric columns. A column whose primary content is a chart,
bar, or score track aligns its header to the visualization's left edge.
Score-bearing table values use `.qym-score-value` plus the `score-1`…`score-5`
class returned by `QymMetrics.getMetricColorClass()`. Raw numeric metrics stay
neutral, and confidence intervals remain muted rather than inheriting the
estimate's score color.
Wide tables that use `.qym-scroll-mirror` expose only the persistent mirrored
horizontal scrollbar. Shared behavior adds `.qym-scroll-mirror-target` to hide
the target's native scrollbar while preserving wheel, touch, keyboard, and
programmatic scrolling; never render both controls.

### Pagination
Use `QymUIComponents.renderPagination()` with a `.qym-pagination` host for every
paginated data view. The Runs view uses the approved option A placement: the
pager is pinned inside the existing status bar, with its range summary and
controls kept together. The shared control uses individual borderless
rounded-square icon buttons for First, Previous, Next, and Last around a direct
page entry and total. The current-page entry keeps the filled rounded input
treatment but is tightly controlled: 28×24px for short values and digit-aware
growth only when the page count requires it. It must not expand into a large
selected button. Do not wrap the controls in a connected pill or repeat the
action names as visible button text. Matching disabled, hover, and focus states
apply platform-wide. Pass `pageSizeOptions` only where changing the page size is
supported. Do not build page-local pagination markup or CSS.
Changing pages in an item-by-item detail view returns its nested scroll host to
the start of the complete Item-by-Item section (title and filters included), not
merely the first card. If content above that section rerenders asynchronously,
perform the scroll after the layout has settled.

Wide tables that cannot expose their native horizontal scrollbar without
vertical scrolling use `.qym-scroll-mirror` with
`data-qym-scroll-mirror-for="<scroll-host-id>"`. The shared behavior renders an
always-visible thumb over the table's bottom edge, keeps it synchronized with
the table, and hides it when the table fits. The interaction wrapper remains
transparent: do not create a separate rail, border, or background band above
pagination. The thumb reuses the quiet, translucent neutral palette of the
platform's vertical scrollbars; interaction may increase neutral contrast but
must not introduce an accent-colored flash.

### Page hero
```
h1.page-title      → var(--font-title) / 650 / --text-primary
p.description      → var(--font-base) / 400 / --text-muted (one line, ellipsis)
div.meta-line      → var(--font-base) / 400 / --text-muted, '·' separators
```

### Stat card
```
.label → var(--font-sm) / 600 / --text-muted / uppercase / ls 0.05em
.value → var(--font-stat) / 700 / --font-mono / tabular-nums
        (--text-primary, or a --score-N color when it encodes a score)
```
Mid-tier stats embedded in drawers/tiles use `--font-xl` instead of `--font-stat`.

### Uppercase label / eyebrow
`var(--font-sm)` (or `--font-xs` only when physically inside a pill),
weight 600–700, `--text-muted`, `text-transform: uppercase`,
`letter-spacing: 0.05em`–`0.12em`.

### Status badge / pill
`var(--font-xs)` / 650, `border-radius: 999px`, 1px border, semantic color for
both text and border, transparent or `*-dim` background.

### Role / metadata tag
`var(--font-xs)` / 650, `border-radius: var(--control-radius)`, no border, and a
tinted or elevated background. Use mono only for roles, counts, IDs, and version
strings.

### Modal
Title `var(--font-xl)` (page-level modals) or reuse `.shell-modal` (body-mounted,
root-token sizes). Body text `var(--font-sm)`–`var(--font-base)` secondary.

### Empty state
Icon: hardcoded 32–48px glyph, `--text-dim`, low opacity. Title:
`var(--font-xl)` / 650 / primary. Body: `var(--font-md)` / muted, line-height ≥1.5.

---

## 4. Page anatomy

Every dashboard page presents, in order: **page title → description → meta line →
tabs (if any) → content**. Constrained pages (settings, admin, profile, projects,
overview) render inside the 1120px shell container; data-dense pages (runs,
charts, datasets, compare) go full-width with their own layout.

Pages carry their styles in an inline `<style>` block — that's accepted — but the
values inside must be tokens. Prefix page-local classes (`.dsx-`, `.pg-`, `.tv-`,
`.sweep-`) to avoid cascade collisions with `dashboard.css`.

---

## 5. Sanctioned exceptions

- **Docs pages** (`docs.css`, `docs/**/*.html`): prose reading pages keep a
  larger independent heading/body scale (28/20/16/13.5→13px) and a brighter
  `--docs-body`. They still use the shared color ramp for labels and the
  tokenized `--code-*` syntax palette.
- **`_static/ui/` (SDK-local run UI)**: a separate mini-app with its own theme
  (`app.css`), including a light mode. Do not import dashboard tokens there or
  vice versa.
- **`tmp/mockups/` (gitignored)**: design scratch files and mocks live here,
  outside the shipped package, so they are exempt from all rules and from CI.
  Do not add scratch mocks under `_static/` — they get served and shipped.

---

## 6. Self-check before you finish (any LLM session: run these)

From `packages/platform/qym_platform/_static/dashboard/`:

```bash
# New hardcoded sizes? (compare against the frozen inventory in the test)
grep -rn "font-size: *[0-9]" --include="*.html" --include="*.css" . | grep -v mock

# dim on content? (every hit must be placeholder/disabled/decorative)
grep -rn "color: var(--text-dim)" --include="*.html" --include="*.css" . | grep -v mock

# Banned fonts / stale grays?
grep -rn "DM Sans\|Georgia\|#7a7a90\|#50505e" . | grep -v mock
```

Then run the enforcement test:

```bash
pytest tests/platform/test_design_language.py -q
```

If your change legitimately adds a decorative glyph size, update the frozen
inventory in that test **in the same commit**, with the selector named in the
diff so the reviewer can see what was exempted.
