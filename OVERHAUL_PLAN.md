# qym Platform Overhaul — Master Plan (Frontend Redesign + Audit Critical/High Remediation)

## Context

Two audits established the need:
- **DESIGN_CRITIQUE.md** (verified against the running app): right domain instincts, wrong structures — no reviewer queue, run-detail buries failures under aggregates in a card feed that dies at scale, no time-series anywhere, 3 fragmented analysis pages, status colors/destructive patterns re-decided per page, broken mobile, WCAG failures.
- **AUDIT_REPORT.md** (1 critical + 35 high of 296 findings): unauthenticated path traversal reading `.env`, SSRF/key exfiltration, unauthenticated-admin default, stored XSS, eval-integrity defects (error-as-0.0, blind judge, prompt injection), FK-violating deletes, O(N²) ingestion, no CI, red test suite, docs two pivots stale.

The current frontend is ~31.7k lines of vanilla HTML w/ inline scripts + 12.5k shared JS + 8.7k CSS, no build step, ~101 duplicated functions, zero tests. **Decision (user-confirmed): full rebuild as a React 18 + TypeScript + Vite SPA.** We are in a dev environment with no production users: **no feature-flag/staged-cutover plumbing; build and replace pages in implementation order, delete legacy at the end.** SDK's diverged local viewer (`packages/sdk/qym/_static/ui`) is **out of scope**.

---

## Stack & Architecture Decisions

| Concern | Choice |
|---|---|
| Framework | React 18 + TypeScript + Vite SPA (single app replaces all 14 dashboard pages + platform live-run UI) |
| Data/cache | TanStack Query (polling live runs, optimistic approve/reject) |
| Tables | TanStack Table v8 + TanStack Virtual (runs list, failures-first items table, leaderboard) |
| Primitives | Radix UI via shadcn-style copy-in components, restyled to qym dark tokens (fixes a11y structurally) |
| Charts | ECharts (trends time-series, distributions; dark theme; canvas perf) |
| Offline export | Dedicated `export.html` entry + `vite-plugin-singlefile` (replaces regex-inlining in `runs.py:1628`) |
| API types | Pydantic response models (new `schemas.py`) → `openapi-typescript` codegen, CI drift check |
| Lint/test | ESLint (`typescript-eslint`, `jsx-a11y`, **`eslint-plugin-no-unsanitized`**), vitest, Playwright + axe |
| API consolidation | New endpoints on `/v1` with response models; legacy `/api/*` frozen, deleted with legacy pages ("three APIs in a trenchcoat" cleanup starts here) |

### Repo layout
```
packages/platform/frontend/            ← Vite workspace (source)
  vite.config.ts / vite.config.export.ts
  index.html, export.html
  src/{styles/tokens.css, api/, lib/, components/, features/}
  e2e/                                 ← Playwright
packages/platform/qym_platform/_static/app/   ← build output (gitignored)
```

### Build/packaging/serving
- **Vite output** → `_static/app/`; sub-path mounts supported via `experimental.renderBuiltUrl` emitting `window.__QYM_ROOT_PATH__ + path` (matches existing injection in `runs.py:116` `_dashboard_html_response` — factor that helper into new `qym_platform/spa.py`).
- **Dev proxy**: proxy `/api`, `/v1`, `/login`, `/static`, `/ui`, `/docs` to `:8000` **and rewrite `Origin`/`Referer` headers** — the same-origin write guard (`app.py:45-60`) checks them; `changeOrigin` alone is insufficient.
- **Packaging**: switch `packages/platform/pyproject.toml` from non-recursive package-data globs to `include-package-data = true` + `MANIFEST.in` with `graft qym_platform/_static` (current globs silently drop hashed asset subdirs). Add packaging test asserting `_static/app/index.html` + `export.html` land in the wheel.
- **Docker**: add `frontend-build` node:22-slim stage mirroring the existing docs-build stage; `COPY --from=frontend-build` into the image before pip install.
- **Source installs**: built output gitignored; SPA catch-all returns a clear 503 ("run `npm run build` in packages/platform/frontend") if assets missing.
- **Serving** (`spa.py`): mount `/app-assets` (immutable cache); SPA shell handler with root-path rewrite + `window.__QYM_BOOT__` injection; catch-all registered after API routers, excluding `/api`, `/v1`, `/static`, `/ui`, `/docs`, `/healthz`, `/openapi.json`, `/login`. Keep `/login` server-rendered (OIDC target).
- **Canonical URLs + redirects** (server-side, resolve slug from run): `/run/{id}` → `/projects/{slug}/runs/{id}`; `/compare` → `/projects/{slug}/compare`; `/charts`+`/models`+`/overview` → `/projects/{slug}/analysis` / runs landing; `/reviews` → `/projects/{slug}/review`; `/trash` → `/admin?tab=trash`.

### New IA (from design critique)
- **Project sidebar**: Runs (landing) · Analysis (Trends + Leaderboard tabs) · Review (Run approvals + Corrections tabs) · Datasets · Settings
- **Global**: Projects · Docs · Admin (Users / Projects / Trash tabs). Dashboard/overview page is retired (absorbed by Runs landing + Review badges).

---

## Phase 0 — Security & broken-happy-path (backend, week 1, independent of SPA)

All locations verified by plan agents. Sizes: S ≤ ½ day, M ≤ 2 days, L ≤ 5 days.

| ID | Fix | Files | Size |
|---|---|---|---|
| SEC-1 **CRITICAL** | Path traversal: apply containment check to the `assets` branch in `_candidate_paths`; reject `..`/absolute segments | `qym_platform/docs_site.py:46-48` | S |
| SEC-1b | Rotate all secrets in `.env` (session secret, DB URL, OAuth, bootstrap token); re-encrypt LLM keys via ops script; add `.git/outputs/tmp` to `.dockerignore` | ops | S |
| SEC-3 | Fail fast on `auth_mode` ∈ {none, empty, unknown} unless `QYM_ENVIRONMENT` ∈ {dev,test,local} (startup validation in app lifespan) | `settings.py:23`, `app.py`, `auth.py:135` | S |
| SEC-4 | Proxy-header binding: require `X-Qym-Proxy-Secret` (hmac.compare_digest) in proxy_headers mode; remove header fallthrough in other modes; `auto_provision_users` default False; restore `${QYM_AUTH_MODE:-proxy_headers}` in both compose files; bind Postgres `127.0.0.1:5432`; constant-time bootstrap-token compare | `auth.py:119-174`, `docker/docker-compose*.yml` | M |
| SEC-2 | LLM connections: manager-only writes; URL validation (https, reject private/metadata IP ranges outside dev); reject `__KEEP__` when base_url changes (reorder `_apply_connection_key`) | `api/projects.py:281-449` | M |
| SEC-5 | Stored XSS: **no legacy stopgap needed (dev env, pages being deleted)** — the class is eliminated by the SPA (sanitized render chokepoint + `eslint-plugin-no-unsanitized`). Rule: do NOT deploy the legacy UI to any shared environment before cutover | — | — |
| HP-1 | `qym run create` crash: map `show_table`→`show_tui`, drop `show_progress` | `packages/sdk/qym/cli/run.py:233` | S |
| HP-2 | `qym analyze run`: fix route to `/api/runs/{id}/analyze`, fix response keys, add bearer auth to analyze endpoints (reuse `_principal_from_bearer` pattern from `datasets.py:72`) | `cli/_platform_api.py:133`, `cli/analyze.py`, `api/analysis.py:448` | S |
| HP-3 | Rewrite `.env.template` with every compose-required var (drop LANGFUSE block); move to `docker/.env.template` | `.env.template` | S |
| HP-4 | `run_started` never fires: `self.total_items` → `len(items)`; narrow the swallowing `except` | `packages/sdk/qym/core/evaluator.py:1065` | S |
| HP-5 | Executor shutdown dead code: keep executor ref, call `.shutdown(wait=False)`; remove fake `loop.get_default_executor()` | `evaluator.py:903,1525`, `multi_runner.py:311` | S |
| HYG | Delete `mock_navigation*.html` + `mocks/` from production static; delete 23MB `outputs/` decks; delete dead `api/org.py` (642 lines, unmounted) | `_static/dashboard/`, `outputs/`, `api/org.py` | S |

## Phase 1 — CI + API foundation (week 1–2, parallel with Phase 0)

- **CI-1 (M)**: `.github/workflows/` greenfield. Day-1 gate: curated green pytest subset; grows as modules are fixed. Pin Python 3.9 floor.
- **CI-2 (L)**: fix the red suite — rewrite `test_endpoint_security.py` for the project model (restores the dead authz suite); move module-level `os.environ` writes into monkeypatch fixtures (kills inter-test interference); fix the silently-uncollected `tests/sdk/test_native_datasets.py` (duplicate basename); delete tests asserting removed behavior. Done = `pytest tests` green, order-independent.
- **CI-4 (M)**: Alembic-against-Postgres job (postgres:16 service, `upgrade head` from empty + Postgres-backed test subset). Verification vehicle for DB-1/DB-4/GOV-1. Enable `PRAGMA foreign_keys=ON` in SQLite fixtures.
- **CI-5 (S)**: examples smoke job (grows with DOC-5).
- **API-1 (M)**: new `qym_platform/api/schemas.py` + `/v1` endpoints with response models (pytest: `tests/platform/test_v1_runs_api.py`):
  - `GET /v1/runs` — flat paginated list (filters: status/owner/task/dataset/model/q/needs_review; sort; total) replacing grouped `/api/runs` shape
  - `GET /v1/runs/{id}` — summary WITHOUT items (hero/verdict/config/trace_stats/approval context)
  - `GET /v1/runs/{id}/items` — slim rows (no bodies), server-side status filter/sort/pagination → powers virtualized failures-first table
  - `GET /v1/runs/{id}/items/{item_id}` — full detail for row-expand
  - `PATCH /v1/runs/{id}` — rename (`display_name`)
  - `GET /v1/projects/{id}/trends` — time-series aggregate (task+dataset+metric, group_by model|version, window)
  - `GET /v1/reviews/queue` — SUBMITTED runs with reviewer context + baseline delta
  - `GET /v1/projects/{id}/overview-stats` — real project-wide aggregates (fixes audit HIGH: stats-from-5-runs)
  - Add `response_model` to existing `/v1/me`, projects endpoints; `include_in_schema=False` on frozen `/api/*`

## Phase 2 — SPA scaffold + design system (week 2–3)

- Vite workspace, configs (incl. Origin-rewriting dev proxy), ESLint/vitest/Playwright harness, CI job (CI-3) with `no-unsanitized` + `jsx-a11y` + axe.
- `tokens.css` ported from `shell.css` `:root` with **WCAG AA fixes** (`--text-muted`, `--text-dim` contrast — audit HIGH), reserved semantic colors (red/green = fail/pass ONLY; purple = AI provenance only; COMPLETED → neutral/blue), one brand palette, global `:focus-visible`.
- Design system (~16 components): Button/IconButton · **StatusBadge** (single status→hue map consumed everywhere incl. admin) · Tabs · **ConfirmModal** (one destructive pattern; truthful soft-delete copy: "Moves to Deleted Runs — admins can restore") · DropdownMenu (kebab) · FilterBar (search + facet chips) · Pagination · EmptyState (one contract: what page shows + next action + docs link) · Tooltip · Toast · Drawer · **DataTable** (TanStack wrapper: density, column auto-hide, virtualization, selection) · MetricDelta (neutral winner encoding) · **JsonView/CodeBlock** (the sanitized rich-render chokepoint — kills the XSS class) · Skeleton/ProgressBar. Sentence-case copy standard + pluralization helper.
- App shell: new-IA sidebar, project switcher, auth bootstrap via `/v1/me`, `spa.py` + catch-all + redirects.
- Ports with golden-parity tests: `metrics.js` → `src/lib/metrics.ts` (capture legacy outputs on fixtures, assert TS matches exactly — this math is product integrity); formatting helpers → `src/lib/format.ts`.

## Phase 3 — Vertical slice: Runs list + Run detail (weeks 3–5) — the de-risking slice

- **Runs list**: dense DataTable; human run identity (single-line, middle-ellipsis; rename via PATCH; no auto-slug duplication of task/model/date columns); auto-hide zero-entropy columns (VERSION/DATASET when constant); DATE/OWNER/actions visible at 1440px (kebab right-pinned); FilterBar with type-ahead search + pinned "Needs review (N)" view for managers; honest grouping (label = what's shared/varies, contained members); selection toolbar with named chips + correct pluralization; live pill (`RUNNING · 33% · 4/12`) preserved; relative metric coloring (delta vs baseline, neutral without one).
- **Run detail**: hero (human name as H1, UUID as copyable chip) + verdict band above the fold → **failures-first virtualized items TABLE** (slim rows from `/v1/runs/{id}/items`; row-expand lazy-fetches full detail = the current card layout, with OUTPUT/EXPECTED as equal neutral panels and the verdict as the loudest element) → analysis sections (Performance by Category, Error Distribution, Root Cause) as collapsed rail/accordions, suppressed when empty; Trace Stats auto-collapses to one explanatory row when no trace data; **review-context banner** (decision/reviewer/date/comment — already in API `Approval` model); FAILED-run failure banner; live-run progress mode (progress bar "item N of M", min-n gating: neutral aggregates until n threshold); "Compare vs previous/baseline" in hero.
- **Trace viewer port**: extract span-tree/waterfall algorithms from `trace_viewer.js` (2,532 lines) as pure TS functions with fixture tests; React render; read-only parity first; proper Drawer (current overlay leaks the sidebar).
- Flip these routes to SPA when done; e2e: login → filter/group/select → run detail expand + trace → live progress (seed scripts: promote `tmp/seed/*.py` into `packages/platform/tools/seed_demo.py`).

## Phase 4 — Export rebuild (week 5–6, isolated, high-risk)

- `export.html` entry + `vite-plugin-singlefile` → `_static/app/export.html` template.
- Rewrite `export_run_html` (`api/runs.py:1628-1721`): read prebuilt template, inject `__QYM_EXPORT_DATA__` JSON, done — delete all regex-inlining.
- **Preserve the hidden re-export-with-edits feature** (run.html:7696 today): export bundle serializes edited state and re-emits itself; implement as a tested module.
- Playwright: download export → load via `file://` → assert render → edit → re-export round-trip.

## Phase 5 — Remaining screens (weeks 6–9, parallelizable)

- **Compare (L)**: delta-first opening (baseline selector, "what changed" summary: N regressed/M improved/K tied with largest deltas); keep the excellent side-by-side shared-INPUT/EXPECTED per-run-columns pattern; **differences-only default** with identical items collapsed to a summary row; neutral matrix encoding (no green floods; zeros/ties neutral); project-scoped route. Written parity contract before porting (what of compare.html's 11.5k lines is kept vs dropped).
- **Analysis (M)**: Trends tab (ECharts time-series off `/v1/projects/{id}/trends`, x = run date/version, line per model, run markers deep-link) + Leaderboard tab (ranked sortable model table; expanded row = current tile detail). Replaces Charts + Models + Overview.
- **Review (M)**: Run approvals queue (`/v1/reviews/queue`; approve/reject with required-comment-on-reject dialog; decision recorded as permanent banner) + Corrections tab (existing `/api/corrections` family; labeled Approve/Reject; Delete demoted to overflow w/ confirm).
- **Datasets (M)**: port mostly as-is (it's the best-designed area) onto the design system.
- **Settings/Admin/Projects/Profile (M)**: settings forms hydrate before render (fixes empty-form bug), Save disabled until dirty; Admin tabs Users/Projects/Trash (Trash demoted from top-level); timeless Profile copy.
- **Onboarding (S)**: empty-project checklist — `pip install qym` (copy button) → mint API key inline (existing `/v1/projects/{id}/api-keys`) → copyable pre-filled command with real base URL.
- **Mobile (S)**: one breakpoint — sidebar becomes sheet, runs table collapses to status+name+score cards. Read-only monitoring only.

## Phase 6 — Backend remediation in parallel (weeks 2–6, independent workstreams)

**Eval integrity (SDK):**
| ID | Fix | Files | Size |
|---|---|---|---|
| EI-1 | Error ≠ 0.0: one error sentinel; exclude from means at ALL THREE sites (`get_metric_stats`, `run_discovery` accumulation, `group_analysis._mean`); fix `is_error_row` first-metric-only grep | `core/results.py:114`, `run_discovery.py:380`, `judges/base.py:169` | M |
| EI-2 | `tool_calling` judge must read `{output}` (currently judges static input — verdict independent of system under test) | `metrics/judges/tool_calling.py` | S |
| EI-3 | Checkpoint resume column swap: reuse existing file header as DictWriter fieldnames; error on metric-set mismatch | `core/checkpoint.py:148-153` | M |
| EI-4 | Judge prompt injection: single-pass regex substitution, never re-scan substituted text | `judges/base.py:227-236` | S |
| EI-5 | insightor exact_match inversion: recall over gold rows (swap roles at :397); import sqlglot or delete `extract_tables`; error sentinel not score-0 | `insightor_eval.py:364-397` | S |

**DB/ingest (platform):**
| ID | Fix | Files | Size |
|---|---|---|---|
| DB-1 | Dataset-item delete FK violation: `ondelete="SET NULL"` migration + revision with null item ref | `api/datasets.py:1068`, `db/models.py:358`, new migration | M |
| DB-2 | O(N²) ingestion → per-batch: accumulate touched trace_ids, refresh once before commit; incremental `_upsert_trace_aggregate` | `api/ingest.py:540-606,997-1280` | L |
| DB-3 | Poison event: wrap payload parse + application per-event (savepoint), `rejected` counter in response | `api/ingest.py:898` | S |
| DB-4 | Savepoint rollback: `nested.rollback()` in both excepts | `api/ingest.py:1244-1285` | S |

**OTel (SDK):**
| ID | Fix | Files | Size |
|---|---|---|---|
| OT-1 | Shutdown only qym-owned processors, never the global TracerProvider | `core/otel.py:294` | M |
| OT-2 | Anthropic: create dedicated LLM span in enrichment wrapper; stop writing to ambient spans (mismarks items errored); revisit skip-list | `core/otel.py:1086-1137` | M |

**Governance (platform; coordinate payload shape with SPA before Phase 3 consumes it):**
| ID | Fix | Files | Size |
|---|---|---|---|
| GOV-1 | Split `review_status` from execution `status` (migration + backfill); `mark_run_running` can never clobber SUBMITTED/APPROVED; fix unapprove/unreject hardcoding COMPLETED | `db/models.py:200`, `services/run_lifecycle.py:10-38`, `api/runs.py:2050-2184`, migration | L |
| GOV-2 | Freeze approved runs against ingest mutation (reject score/output events on approved runs) | `api/ingest.py:1044` | M |
| GOV-3 | Split archive vs delete endpoints (current single endpoint inverts: "Archive" hard-deletes empty projects, "Delete" archives); add unarchive; SPA renders truthful copy | `api/projects.py:763-780` | M |

**Docs (HIGH items):**
| ID | Fix | Size |
|---|---|---|
| DOC-1 | Langfuse purge across README/SDK docs/docs_portal/.env.template; write native-datasets docs (QymDataset, `qym dataset` CLI, versions/aliases); CI grep-check | M |
| DOC-2 | Purge org-model docs (deleted roles/hierarchy/endpoints); document actual project/membership model | S |
| DOC-3 | Implement `TRACELOOP_TRACE_CONTENT` (documented privacy control that doesn't exist — content IS captured): gate prompt/response capture in otel enrichment | S |
| DOC-4 | Fix `qym.__version__` 0.9.0 vs pyproject 1.1.0 (read from package metadata) | S |
| DOC-5 | Examples 0/12 runnable: fix to current API or delete, each; rewrite quickstart.ipynb (depends HP-1); wire into CI-5 | M |

## Phase 7 — Cutover & deletion (week 9–10)

- All routes serve SPA; legacy handlers become redirects.
- **Delete**: all legacy `_static/dashboard/*.html`, `dashboard.js`, `shell.js`, `playground.js`, `auth.js`, `dashboard.css`, `shell.css`, `trace_viewer.js`, `metrics.js`; platform `_static/ui`; `tests/platform/test_dashboard_static.py` (asserts legacy JS source strings); legacy `/api/*` page-data endpoints (`/api/runs` grouped, `/api/compare`, `/api/models/runs`) once nothing calls them.
- Update pyproject package-data/MANIFEST, Dockerfile COPYs; final axe + Playwright full-suite run.

---

## Verification

1. **Per-phase pytest** (new: `test_v1_runs_api.py`, `test_spa_serving.py`, `test_spa_assets.py`, `test_llm_connections.py`, rewritten `test_endpoint_security.py`) — all in the CI gate.
2. **Golden-parity**: metrics.ts vs legacy metrics.js outputs on fixture snapshots (product-integrity math).
3. **Playwright e2e** against seeded Postgres (promoted seed scripts): login → runs → run detail expand/trace → approve/reject w/ comment → compare delta → export `file://` round-trip → live-run progress. **axe on every screen.**
4. **Security repros**: path-traversal 404 test; spoofed `X-User-Email` 401; SSRF URL-validation 400s; XSS payload run-name/output renders inert in SPA.
5. **Migration job**: alembic upgrade from empty Postgres + GOV-1 backfill assertions.
6. **Manual walkthrough** at the end of each screen phase against DESIGN_CRITIQUE.md's findings for that screen (the critique doubles as acceptance criteria), using the existing local deployment + seeded data.

## Risk register (top 5)

1. **Export parity** (re-export-with-edits is a hidden sub-feature) → isolated Phase 4, round-trip e2e, keep legacy export endpoint until test passes.
2. **Trace-viewer port** (2.5k lines bespoke) → pure-function extraction + fixture tests, read-only parity first.
3. **GOV-1 schema migration** (biggest backend↔SPA coupling) → land contract before Phase 3 builds against it.
4. **Items virtualization** with variable-height expanded rows → in the Phase 3 slice deliberately; server pagination fallback exists from API-1.
5. **Packaging silent-loss** (non-recursive globs drop hashed assets from wheels) → MANIFEST graft + packaging test in CI from Phase 2.
