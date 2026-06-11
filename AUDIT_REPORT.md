# qym — Full Codebase Audit

**Date:** 2026-06-10
**Scope:** Entire repository — SDK (`packages/sdk`), platform (`packages/platform`), dashboard frontend (`_static`), docs portal, internal docs, examples, Docker deployment, ops tooling, tests, repo hygiene.
**Method:** 87 specialized audit agents across 19 dimensions (security/auth, API security, database, API design, SDK core, metrics & judges, client/CLI, OTel tracing, frontend architecture, HTML pages, visual design/CSS, UX & copy, docs accuracy, deployment, business logic, testing, plus 3 gap-sweep areas: examples, ops tools, TUI/observers). Every critical/high technical claim was then adversarially re-verified by independent skeptic agents instructed to refute it against the actual code; **0 of 61 were refuted** (several had severity adjusted). Many findings were reproduced empirically (pytest runs, exploit-path tracing, signature inspection, WCAG contrast computation).

**Totals: 296 unique findings — 1 critical, 35 high, 179 medium, 81 low.**

---

## Executive summary

qym is an ambitious and in many places impressively engineered LLM-evaluation platform: the event-ingestion contract is versioned and idempotent, run authorization is consistently enforced, password/API-key storage is textbook-correct, asyncio orchestration shows real sophistication, and the dashboard has a genuine design-token system. The bones are good.

But the project is currently in a state where **its documented happy path does not work end-to-end**, and the root cause is structural: **there is no CI**, the test suite is ~17% red with 5 modules that don't even import, and the codebase has lived through two major architecture pivots (Langfuse → native datasets; org-hierarchy → project model) **without the docs, examples, tests, or dead code being brought along**. The result:

- The **primary documented CLI command crashes** (`qym run create` passes kwargs `Evaluator.run()` doesn't accept).
- **Every one of the 12 examples is broken** for an external user — the quickstart notebook still imports the pre-rename `llm_eval` package.
- A **critical unauthenticated path-traversal** in the docs server can read `.env` (session secret, DB URL, encryption key, OAuth secrets).
- The **default deployment is unauthenticated-admin** (`QYM_AUTH_MODE=none` default), and the compose file silently lost its production-safe auth default — a regression the (dead) test suite would have caught.
- The product's core promise — trustworthy scores — is undermined by **error-as-0.0 aggregation**, a **tool-calling judge that never sees the model's output**, **judge prompt injection**, and a **direction-inverted exact-match in the flagship customer eval**.

The fastest way to raise the quality floor is not fixing any single bug: it is (1) CI that runs a green test suite, (2) a docs/examples purge pass for the two pivots, and (3) the five security fixes below. Detailed findings follow, ordered by theme; a complete appendix of all medium/low findings is at the end.

---

## Scorecard

| Area | Grade | One-line assessment |
|---|---|---|
| Auth primitives (hashing, keys, secrets) | **A−** | PBKDF2-600k, hashed API keys, Fernet-encrypted LLM creds — but unsafe defaults around them |
| Endpoint authorization (IDOR) | **B+** | Consistently scoped lookups; holes are in docs server, LLM connections, /v1/users |
| Deployment security posture | **D** | auth=none default, trusted proxy headers, DB on 0.0.0.0, root containers |
| Database schema & migrations | **B−** | Good constraints/idempotency; FK-violating deletes, O(N²) ingest, no retention |
| API design | **C** | "Three APIs in a trench coat": modern datasets router vs legacy RPC surface |
| SDK core engine | **B−** | Sophisticated asyncio undermined by `except: pass` hiding dead/broken paths |
| Metrics & judges (eval integrity) | **C−** | Error-as-0.0, blind tool_calling judge, prompt injection, broken judge tests |
| OTel tracing | **C** | Capable but achieves it via irreversible global monkey-patching; O(N²) ingest side |
| Frontend architecture | **D+** | 15.7k lines untested vanilla JS, ~100 functions duplicated across inline scripts, XSS bypasses |
| Visual design | **B−** | Real token system and coherent aesthetic; weak enforcement, 3 brand palettes |
| Accessibility | **D** | Muted text fails WCAG AA, zero `:focus-visible` in 7,900-line stylesheet |
| UX & copy | **C+** | Excellent moments (datasets wizard) next to copy that lies about destructive actions |
| Documentation | **D** | Extensive and well-written — about a product two pivots ago |
| Examples | **F** | 0 of 12 runnable by an external user |
| Testing & CI | **F** | No CI; suite red; authz tests dead; migrations and frontend untested |
| Repo hygiene | **D+** | 23MB of committed .pptx decks, customer script at root, dead org module |

---

## 1. Security

### 1.1 CRITICAL — Arbitrary file read via docs static server
[docs_site.py:46](packages/platform/qym_platform/docs_site.py:46) — In `_candidate_paths`, when a path segment equals `assets`, the candidate `(docs_root / Path(*parts[asset_index:])).resolve()` is yielded **without** the containment check applied to the normal branch. `GET /docs/assets/..%2f..%2f..%2f..%2f.env` reads files outside the docs tree — including the repo `.env` (session secret, `QYM_DATABASE_URL`, `QYM_LLM_CONFIG_ENCRYPTION_KEY`, Google/GitHub OAuth secrets) and any source file. The app catch-all only intercepts dot-less names, so dotted targets reach the handler. Verified end-to-end by the auditor and an independent verifier.
**Fix:** apply the same containment check to every candidate; reject `..` segments outright.

### 1.2 HIGH — Provider API-key exfiltration via SSRF on LLM connections
[projects.py:281](packages/platform/qym_platform/api/projects.py:281) — Any project **member** can update a connection's `llm_base_url` (no scheme/host validation) while keeping the stored key via `llm_api_key="__KEEP__"`, then call `/test` (or `/analyze`): the platform decrypts the stored provider key and sends it in an Authorization header to the attacker's URL. Also a general SSRF primitive against internal networks.
**Fix:** require manager/admin for connection changes; validate/allowlist base URLs (https, no private/metadata ranges); force re-entry of the key when the destination changes.

### 1.3 HIGH — Default deployment is unauthenticated admin
[settings.py:23](packages/platform/qym_platform/settings.py:23), [auth.py:135](packages/platform/qym_platform/auth.py:135) — `auth_mode` defaults to `none`, and `.env.template` hardcodes it. In `none` mode every anonymous request gets a synthetic `dev@local` **ADMIN** principal. Fine for localhost dev; catastrophic as a default for a product whose README pitches self-hosting.
**Fix:** refuse `none` unless `QYM_ENVIRONMENT` is dev/test; fail fast on unknown/empty mode.

### 1.4 HIGH — Proxy-header identity trusted with no proxy binding
[auth.py:119](packages/platform/qym_platform/auth.py:119) — `proxy_headers` mode (and fallback paths in other modes) authenticates purely from client-supplied `X-User-Email`, with auto-provisioning on by default. Nothing verifies the request transited the trusted proxy. Anyone who can reach the app port directly can impersonate any user, including admins.
**Compounding regression (MEDIUM):** [docker-compose.yml:30](docker/docker-compose.yml:30) lost its `${QYM_AUTH_MODE:-proxy_headers}` production-safe default — the deployment-config test that asserts it **fails on main today** — so compose now injects an empty string, an undefined mode in which spoofed `X-User-Email` headers still authenticate while the API is published on `0.0.0.0:8000`.
**Fix:** require a shared secret/HMAC header from the proxy; strip inbound identity headers; restore the compose default; default `auto_provision_users` to false.

### 1.5 HIGH — Stored XSS across the dashboard
[dashboard.js](packages/platform/qym_platform/_static/dashboard/dashboard.js) (lines 1904, 1966, 2226–27, 2657, 3176–3555, 4373), both `ui/app.js` copies — `escapeHtml` exists and is used in most places, but is bypassed for dataset tab labels, task names, git version tags, run-name tooltips, `title`/`data-model` attributes, an unsanitized `langfuse_url` href (`javascript:` URLs execute on click), and raw model input/output/expected in run-detail tables. Run names, git branches, and **model outputs** are all attacker-influenceable and shared per-project — a low-privilege user can attack admins who view a run.
**Fix:** escape every interpolation including attributes; validate URL schemes; render model output via `textContent`; add `eslint-plugin-no-unsanitized` to CI.

### Other notable security findings (medium unless noted)
- **Local dashboard server arbitrary file read** — `GET /api/runs/{path}` accepts absolute paths with no containment check (write endpoints are guarded; read is not). Localhost-bound, but reachable via browser requests. [dashboard_server.py:163](packages/sdk/qym/server/dashboard_server.py:163)
- **Full user directory disclosure** — `/v1/users` returns every user to any authenticated principal. [web.py](packages/platform/qym_platform/api/web.py)
- **No rate limiting/lockout** on login, signup, and admin-bootstrap; bootstrap token compared non-constant-time. [api/auth.py](packages/platform/qym_platform/api/auth.py)
- **API-key scopes documented but not enforced** — any member can mint a full-access key. [auth.py](packages/platform/qym_platform/auth.py)
- **Open-redirect bypass** in `sanitize_next` via backslash paths. [auth_oidc.py](packages/platform/qym_platform/auth_oidc.py)
- **Unbounded request bodies** on ingest/upload endpoints (memory-exhaustion DoS). [ingest.py](packages/platform/qym_platform/api/ingest.py)
- **Judge prompt injection** — `_safe_substitute` re-scans substituted text, so a model output containing `{expected}` gets the ground-truth answer injected into its own "[Actual Response]" slot → guaranteed "correct" verdict (eval gaming). Verified by execution. [judges/base.py:227](packages/sdk/qym/metrics/judges/base.py:227)
- **Analyzer prompt injection** path from evaluated outputs and correction snapshots into LLM analysis prompts, with a poisoning loop via the correction few-shot bank. [llm_analyzer.py](packages/platform/qym_platform/services/llm_analyzer.py)
- **Secrets on argv** — `--api-key`/`--platform-api-key` are captured verbatim into `cli_invocation` and stored/displayed with the run (low, but a real leak). [cli/run.py:169](packages/sdk/qym/cli/run.py:169)
- **Phoenix export of full prompts auto-enables** from environment variables alone. [otel.py](packages/sdk/qym/core/otel.py)
- **Auth-bypassing DB write scripts** baked into the production Docker image (see §11/§14). [qym_platform/tools/](packages/platform/qym_platform/tools)

**What's good:** PBKDF2-600k with constant-time verify; API keys stored hashed with prefix lookup; Fernet-encrypted LLM credentials never echoed; consistent `can_view_run`/`can_modify_run` gating across run/correction/dataset/connection lookups (several IDOR probes came back clean); parameterized SQL everywhere; same-origin write-guard middleware; no permissive CORS.

---

## 2. Broken as shipped — the documented happy path

These are not edge cases; they are the front door.

1. **`qym run create` crashes on every documented invocation** — the CLI calls `evaluator.run(show_progress=…, show_table=…)` but `Evaluator.run()` accepts `(show_tui, auto_save, save_format, max_parallel_runs)`. `TypeError` on every single-run CLI eval, reported as a generic run failure. Verified via `inspect.signature`. [cli/run.py:233](packages/sdk/qym/cli/run.py:233)
2. **`qym analyze run` always fails** — posts to `/v1/runs/{id}/analyze`, which doesn't exist (the real route is `/api/runs/{id}/analyze`), and parses response keys the API never returns. [cli/_platform_api.py:134](packages/sdk/qym/cli/_platform_api.py:134)
3. **0 of 12 examples run** for an external user: `example.py` imports removed Langfuse at module level and lacks the `my_task` function the docs invoke; `quickstart.ipynb` still does `from llm_eval import Evaluator` (pre-rename package) and walks a removed Langfuse workflow; `text2sql` uploads its dataset to Langfuse but evals against the qym platform (can never connect) with half its imports undeclared; `multi_model.py` tasks crash on every item under the adapter's argument unpacking (reproduced); the rest reference private datasets, a missing CSV fixture, or wrong model IDs. [examples/](examples)
4. **Out-of-box Docker deploy fails** — `.env.template` is missing every variable compose requires (postgres refuses to start without `POSTGRES_PASSWORD`), and compose won't read a repo-root `.env` when invoked with `-f docker/docker-compose.yml` anyway. [.env.template](.env.template), [docker-compose.yml](docker/docker-compose.yml)
5. **The test suite cannot gate anything** — bare `pytest tests` (the documented command) aborts with 5 collection errors; forced through, **64 failed + 10 errors of ~423** (reproduced 2026-06-10). No CI exists to notice. [tests/](tests)
6. **`run_started` platform event has never fired** — payload references `self.total_items`, which doesn't exist; the `AttributeError` is swallowed by `except Exception: pass`. [evaluator.py:1065](packages/sdk/qym/core/evaluator.py:1065)
7. **Executor-shutdown cleanup is dead code** — calls `loop.get_default_executor()`, which is not an asyncio API; the hang it was written to prevent still exists. [evaluator.py:1525](packages/sdk/qym/core/evaluator.py:1525)

---

## 3. Evaluation integrity — the product's core promise

For an evaluation platform, score trustworthiness is the product. Several defects bias or corrupt scores:

- **Errors scored as 0.0 and averaged in** (HIGH) — judge API failures, refusals, and metric timeouts become `score=0.0` with the error nested in `metadata`, which `get_metric_stats` does **not** exclude (it only checks top-level `error`). A rate-limit outage drags means toward 0 while `success_rate` stays 100%. For `toxicity` (0.0 = toxic), an API error is numerically the worst verdict. Two failure paths use different conventions, so identical failures are sometimes excluded, sometimes counted. [judges/base.py:169](packages/sdk/qym/metrics/judges/base.py:169), [results.py:114](packages/sdk/qym/core/results.py:114)
- **`tool_calling` judge never sees the model's output** (HIGH) — its `{tool_calls}` placeholder fills from the static dataset input, so the verdict is independent of the system under test. [judges/tool_calling.py](packages/sdk/qym/metrics/judges/tool_calling.py)
- **Checkpoint resume can silently swap score columns** (HIGH) — resume validation is order-insensitive, but the CSV appender uses the new metric order against the old header: resumed rows write metric A's score under metric B's column. [checkpoint.py:148](packages/sdk/qym/core/checkpoint.py:148)
- **insightor exact_match is direction-inverted** (HIGH) — computes precision over LLM rows instead of recall over gold rows, so an answer returning 1 of 10 required rows passes at 100%; its `extract_tables` metric always fails on a missing import; infrastructure failures are recorded as "wrong answer". [insightor_eval.py:384](insightor_eval.py:384)
- **Three inconsistent error semantics** between live TUI averages, final summary, and resume seeding — the numbers on screen at run-end disagree with the summary printed below them. [dashboard.py:225](packages/sdk/qym/core/dashboard.py:225)
- **Means disagree across the three aggregation sites** (EvaluationResult vs RunDiscovery vs group_analysis) for the same run.
- Judge-layer mediums: valid-JSON-non-object responses crash verdict parsing; unfilled placeholders sent to the LLM as literal `{question}`; pairwise judge has no position-bias mitigation; registry silently overwrites on name collision; `token_count` returns raw ints on a 0–1 scale; misconfigured judges fail **per item after** the full paid task run instead of pre-flight; `METRIC_BANK.md` presents `exec()` with empty `__builtins__` as "Sandboxed" (it is not).

**What's good:** three-stage verdict parsing with longest-first rail-snapping; true wall-clock judge timeouts with jittered backoff; temperature=0/max_tokens defaults; SQuAD-faithful correctness builtin; consistent `>=` threshold semantics; helpful unknown-metric errors.

---

## 4. Database & ingestion performance

- **Dataset item hard-delete always FK-violates on PostgreSQL** (HIGH) — delete first inserts a revision row referencing the item, then deletes the item; FKs have no `ON DELETE`. Guaranteed 500 in production; invisible in tests because they run SQLite with FKs unenforced. [datasets.py:1068](packages/platform/qym_platform/api/datasets.py:1068), [models.py:358](packages/platform/qym_platform/db/models.py:358)
- **O(N²) ingestion** (HIGH) — every `span_completed`/item event triggers `_refresh_live_trace_stats`, which re-reads **all** items and **all** spans of the run and rewrites item metadata; `_upsert_trace_aggregate` re-reads every span of the trace per event. Agentic runs with thousands of spans hammer the DB progressively harder while live. [ingest.py:540](packages/platform/qym_platform/api/ingest.py:540)
- **One mistyped event 500s an entire NDJSON batch** (HIGH) — the second-stage payload parse sits outside the try/except whose comment promises "one bad span_completed must never take down an item_completed"; a poison event fails every retry of its batch. [ingest.py:898](packages/platform/qym_platform/api/ingest.py:898)
- **Savepoint error path never rolls back** — a span-storage failure poisons the session for the rest of the batch on Postgres (the exact failure the savepoint was meant to contain).
- Check-then-insert races with no `IntegrityError` handling turn constraint hits into 500s; `runs:upload` commits a COMPLETED run before validating the file (orphan runs; advertised XLSX is rejected); `sent_at` timestamps mix naive/aware interpretations; no composite index for the dominant runs-list query; no retention story for `run_events`/`spans`/`audit_logs`; `DB_SCHEMA.md` documents a deleted schema.

**What's good:** natural-key unique constraints make ingestion idempotent by design; the hottest list endpoint was deliberately de-N+1'd; soft-delete is consistently applied via `Run.active()`; Postgres enum migrations use the correct rename/recreate/USING pattern; migration 0007's backfill is careful and 0014 honestly refuses to downgrade.

---

## 5. API design

The platform is **three APIs in a trench coat**: a modern datasets router (proper 409s, draft guards, `total`/`next_offset` pagination), a documented product-evals envelope (`{ok,data,error}`, 202/429 semantics), and a legacy `/api/runs/*` RPC surface (delete-via-POST keyed by `file_path`, 200-with-`{"error"}` responses, raw dict bodies on nine mutation endpoints).

- `GET /api/runs/{id}` returns **HTTP 200 with `{"error": "Access denied"}`** — and the docs direct automation at this endpoint.
- `conventions.mdx` promises `/openapi.json` as the "machine-readable source of truth" — but almost no endpoint declares a response model, and HTML pages pollute the schema.
- The documented `/v1`-ingestion vs `/api`-review split is violated: the approval workflow lives under `/v1` with session-only auth, so the **documented API-key automation flows cannot work**.
- `PRODUCT_EVAL_API_GUIDE` documents `poll_url`/`qym_run_id`/`qym_runs` fields the code never returns — a client built from the guide cannot complete the documented flow.
- Four error-response shapes, four pagination envelopes, 200-for-create, negative `limit` accepted (500 on Postgres), event `sequence` stored but never enforced, `POST /v1/runs` not idempotent despite `external_run_id` being documented as the stable client identifier.

**What's good:** the `RunEventV1` contract itself — `schema_version`, UUID `event_id` idempotency, per-run sequence — is the best-designed contract in the repo, and dedup genuinely works; 410-with-timestamp for deleted-run ingestion is exemplary.

---

## 6. SDK core engine

Genuinely sophisticated asyncio (shielded finalization with documented contextvars reasoning, bounded worker pools, a clever blocking-call canary probe, per-metric timeout isolation) — undermined by pervasive `except Exception: pass`, which let §2.6 and §2.7 ship dead.

Mediums of note: checkpoint-writer failure **deadlocks** `arun` (`write_queue.join()` waits forever); non-JSON-serializable `run_metadata` crashes workers mid-run (`json.dumps` without `default=str`); truncated checkpoint rows accepted as completed on resume; `auto_save` format silently ignored when checkpointing is on (the default); item-ID schemes diverge between checkpoint rows and platform events; `should_stop` silently dropped in multi-model runs; display name clobbered (runs render as "None [task]"); error-row detection greps the substring `'ERROR'` in only the first metric; sync tasks that outlive timeouts leak threads in an undersized shared pool; `Evaluator` is a 2,700-line god object whose duplicated state derivations are the root cause of several of these.

---

## 7. Observability (OTel)

- **Evaluator shutdown kills the global TracerProvider** (HIGH) — including processors it does not own; host-app tracing silently stops, and Phoenix export dies after the first run in a process (multi-model runs lose it). [otel.py:294](packages/sdk/qym/core/otel.py:294)
- **Anthropic has no LLM-span instrumentation, and the skip-list blocks the official instrumentor** (HIGH) — Anthropic runs report `llm_calls=0`; worse, enrichment still writes onto whatever span is current, marking successful items as **errored**. [otel.py:1120](packages/sdk/qym/core/otel.py:1120)
- Irreversible global monkey-patching of OpenAI/Anthropic SDK methods with no unpatch path; `set_tracer_provider` claimed once per process; repeated Evaluator construction leaks span processors.
- 64KB truncation produces **invalid JSON** in span attributes that downstream parsing depends on; the cost pipeline reads `llm.cost.total`, which nothing ever writes (dead feature); tool-span timings are fabricated and feed `avg_tool_ms` as if real; enrichment runs unguarded inside the user's LLM call (can consume streaming generators).

**What's good:** span ingestion idempotency is regression-tested; the contextvar gate scoping capture to the active run is correct and tested; metric-scoped LLM usage is properly excluded from trace stats; live stats are tested to match final computation.

---

## 8. Frontend architecture

15.7k lines of framework-less, build-less, **test-less** vanilla JS, plus ~32k lines of HTML much of which is inline application logic.

- **~101 functions are defined identically in both `compare.html` and `run.html` inline scripts** (`escapeHtml`, `parsePythonDict`, `showToast`, `drawSankeyPaths`, `csvEscape`, …), several a third time in dashboard.js/reviews.html — and the copies have **already drifted** (run.html ES5 vs compare.html ES6).
- The two `ui/app.js` forks (platform vs SDK) have diverged by ~198 lines.
- XSS bypasses (§1.5); `sortRuns` crashes on undefined fields; `run.html`/`compare.html` call `showToast` but never include the toast container (toasts silently no-op); leftover mock/dev pages (`mock_navigation.html`, `mocks/`) ship in the production package and are publicly served.
- No ESLint, no bundler, no tests of any kind for the highest-churn code in the repo.

**What's good:** `escapeHtml` exists everywhere (gaps are bypasses, not missing tooling); `fetchRuns` has in-flight + stale-render-token guards; `metrics.js` is a genuine shared single-source-of-truth for pass@k math.

---

## 9. Visual design & accessibility

**Design:** a real token system exists (surface ladder, 4-step text hierarchy, semantic + 5-step score scale, 20-color chart palette) and `shell.css` is clean and fully token-driven. Enforcement is weak: 56 hardcoded hex colors and 24 font sizes in `dashboard.css` alone, ~69% of paddings off-scale, 13 ad-hoc radii, 4,200/3,400-line inline `<style>` blocks per page colliding with global class names in one namespace, and **three different brand palettes** across dashboard (teal), SDK report (purple, with leftover wrong-brand styling and an unreachable light theme in a drifted fork), and docs (green).

**Accessibility (the serious part):**
- `--text-muted` = 3.7–4.4:1 and `--text-dim` = 2.0–2.3:1 against their backgrounds — the two workhorse secondary-text tokens **fail WCAG AA** across table headers, stat labels, timestamps, placeholders (computed ratios, HIGH). The report-UI "Export CSV" button is white-on-teal at **1.91:1**.
- **Zero `:focus-visible` rules in the 7,900-line dashboard.css**; a range slider sets `outline: none` with no replacement. Keyboard users get nothing.
- Text as small as 7–9px; no `prefers-reduced-motion` despite infinite animations; modals don't trap or restore focus; async regions lack `aria-live`; filter inputs are unlabeled; clickable divs aren't keyboard-accessible.
- CSS bugs: alpha-hex concatenated onto `var()` (declarations silently dropped); references to never-defined tokens; `!important` inside `@keyframes` (animation is a no-op); unmanaged z-index 0→50,000 (toasts render beneath the trace viewer).
- Responsive story is "amputation, not adaptation"; login.html is, ironically, the best page (proper focus states and a 480px pass).

---

## 10. UX & copy

**The most safety-critical copy lies about what the system does:**
- Run delete warns "**This action cannot be undone**" — it's a soft delete, restorable from the Trash page that ships with the product.
- Project Danger Zone claims permanent deletion of "all runs and data" — the backend **archives** when runs exist and never deletes runs; meanwhile the admin "**Archive**" button (confirmed with a casual "Archive this project?") **hard-deletes** empty projects including API keys. The "safe" button can destroy; the "destructive" button doesn't. Both call the same endpoint. (HIGH) [projects.py:763](packages/platform/qym_platform/api/projects.py:763)
- The overview dashboard computes "Avg Success", "Models", and "Items Evaluated" from **only the 5 most recent runs** and presents them as project-wide totals; "Avg Success" is actually the mean of whichever metric is first, not success rate. (HIGH) [overview.html:289](packages/platform/qym_platform/_static/dashboard/overview.html:289)
- **Annotation saves fail silently** on the core review surfaces — feedback/root-cause/solution save errors go only to `console.error`; reviewers lose work without knowing. [run.html:6465](packages/platform/qym_platform/_static/dashboard/run.html:6465)
- Terminology drift: Review/Approve/Reject names two unrelated workflows (runs vs corrections); Sign in/Sign Out/Logout; Owner vs User; "Eval Runs" vs "Runs". Empty state tells members to "Create a project" they lack permission to create; first-run empty state teaches deprecated CLI syntax the CLI itself nags about; archiving has no unarchive control; delete-run errors always read "Unknown error" (parses `data.error`, API returns `detail`).

**What's good:** the Datasets first-run flow (skeletons, focused empty state, 3-step upload wizard with column mapping) is excellent; Models-view tooltips explain pass@k in plain language; type-to-confirm project deletion; CLI errors are structured with actionable suggestions; interrupted runs print exact resume commands; the Trash page turns 403 into a helpful explainer.

---

## 11. Business logic & product design

- **Approved runs are not frozen** — ingest never checks review status, so the owner's API key can rewrite scores and outputs **after** a manager approves; the Approval record stays attached to silently altered data. (verified; medium-after-review) [ingest.py:1044](packages/platform/qym_platform/api/ingest.py:1044)
- **Review states are clobbered by trailing runner events** — `mark_run_running` protects only COMPLETED/FAILED/STOPPED; a late heartbeat or span flush demotes SUBMITTED/APPROVED to RUNNING, wipes `ended_at`, and strands the run in a state from which it can't be resubmitted. Execution status and review status need to be separate columns. [run_lifecycle.py:10](packages/platform/qym_platform/services/run_lifecycle.py:10)
- **Stale-run recovery diverges from its own design doc** — recovery is lazy on-read reconciliation only on the runs-list path; dead runners' runs stay RUNNING forever via the product-evals API and most read paths. The documented LOST status/background sweeper were never built.
- **Product-eval jobs live in process memory** — restart orphans them; "stopped" jobs keep executing and ingesting (DB says STOPPED while the evaluator continues); the queue can be filled by the smoke-test preset that ships to production.
- **The correction loop doesn't close** — corrections feed only LLM-analyzer few-shot prompts; they never flow back into datasets or metrics, and the entire "solution" half of the pipeline is collected and never used. `unapprove`/`unreject` hardcode `status=COMPLETED`, converting FAILED runs into COMPLETED. Approval decisions have no audit trail and race without locking. Auto-approve on human edit fabricates reviewer provenance. Reviewers == viewers == modifiers (no separation of duties).
- **One-customer coupling:** `insightor_eval.py` (a customer eval) sits at repo root, is baked into the Docker image, located via fragile `parents[4]` traversal, imports undeclared `langfuse`, hardcodes internal hostnames with TLS verification disabled, and contains the inverted exact-match (§3). Ops scripts in `qym_platform/tools/` default to a personal email, a customer project slug, and three specific production run IDs; `import_local_results.py` is non-idempotent, commits runs before items, mints users from typos, and stamps APPROVED with no Approval row.

---

## 12. Documentation

Extensive, well-written — and describing a product **two architecture pivots ago**:

- **Langfuse purge never happened in docs** (HIGH): README, SDK README, SDK USER_GUIDE, SDK_INTEGRATION_GUIDE, and most docs_portal pages still teach Langfuse dataset creation and LANGFUSE_* credentials; the actual native dataset system (`QymDataset`, `qym dataset` CLI, versions/aliases) is **documented nowhere**.
- **Org-model docs describe deleted code** (HIGH): EMPLOYEE/MANAGER/GM/VP roles, Sector→Department→Team hierarchy, per-user API keys at `/v1/me/api-keys`, and "useful admin endpoints" from an `org.py` module that isn't even mounted (and would crash on import).
- **A documented privacy control doesn't exist** (HIGH): "set `TRACELOOP_TRACE_CONTENT=false` to disable prompt capture" — zero occurrences in the codebase; users who think they disabled sensitive-content capture are still sending it.
- `qym.__version__` says 0.9.0 while pyproject says 1.1.0 (and that's what runs report to the platform); release notes stop at 0.9.x; documented CLI flags (`--concurrency`, `--no-tui`) don't exist; the recommended resume config raises `ValueError`; internal docs (DB_SCHEMA, RUN_EVENT_SCHEMA with a literal diff artifact embedded, heartbeat design) are stale; SDK_INTEGRATION_GUIDE is a hand-maintained near-duplicate of a portal page, already drifted.

**What's good:** the generated-docs pipeline (`tools/docs/generate.py`) derives CLI/API/env references from live code — those stay correct; Product Eval API endpoint/scope docs match implementation precisely; the Python 3.9+ claim was verified true via AST parse of every module.

---

## 13. Testing & CI

- **No CI of any kind** (no `.github/`, no GitLab/Jenkins/azure config). This is the root enabler of most decay in this report.
- **Suite red** (§2.5): collection errors in 5 modules; 64 failures + 10 errors when forced. Failures are overwhelmingly stale tests asserting removed behavior (old role model, old JudgeConfig defaults, `runs.project_id` now NOT NULL, removed functions).
- **The endpoint-authorization test suite is dead** — `test_endpoint_security.py` fails at import (removed `OrgUnit`); zero executable authz tests gate the dashboard API.
- **Proven inter-test interference**: module-level `os.environ` writes with conflicting `QYM_AUTH_MODE` values and `sys.modules['openai'] = MagicMock()` in 6+ files — results depend on which subset you run (reproduced: 3 failures in-suite vs 0 standalone for `test_secret_storage`).
- `tests/sdk/test_native_datasets.py` is **silently never collected** in full-suite runs (duplicate basename, no `__init__.py`).
- **Migrations never executed by tests** (SQLite `create_all` vs production Postgres + 21-revision Alembic chain); ~15k lines of JS + 32k of HTML have **zero** executable frontend tests; no SDK↔platform contract tests; OIDC token exchange is 100% mocked (one test verifies its own mock); builtin-metric coverage is essentially `exact_match` only.

**What's good:** platform API tests use a real TestClient with real assertions; local-auth coverage includes thorough negative paths; incident-driven regression tests document real production failures; benchmarks are correctly excluded from collection.

---

## 14. Deployment, packaging & repo hygiene

- Postgres published on `0.0.0.0` by default (HIGH — remove the port mapping or bind loopback); API also on 0.0.0.0 while trusting proxy headers.
- Containers run as root; no `HEALTHCHECK` in the Dockerfile; base images unpinned; no restart policies or resource limits; DB healthcheck hardcodes user `qym` (breaks any non-default config); migrations run unconditionally on every container start with no concurrency guard (multi-replica race).
- `backup.sh` writes non-atomic dumps, crash-loops on failure, and has **no restore story**; the default image contains no docs portal, contradicting the docker-deployment and air-gapped docs.
- `build-sdk.sh` downloads `qym` from **public PyPI** instead of the locally built wheel (supply-chain risk for the air-gapped flow it serves); internal government hostnames hardcoded as defaults; no dependency locking anywhere (open-ended ranges for the deployed app).
- Repo hygiene: **23MB of AI-generated .pptx decks** committed under `outputs/`; `tmp/` mocks tracked despite `.gitignore`; `node_modules` stubs with a developer's machine paths; `mock_navigation copy.html` shipped in the production static dir; dead `api/org.py` (642 lines, crashes on import); `qym_platform/tools` lacks `__init__.py` so it's excluded from wheels (works in Docker only via editable install); `.dockerignore` missing `.git`/`outputs`/`tmp`.

---

## 15. What's genuinely good

Worth saying plainly, because the team's instincts are visible: the event contract (versioned, idempotent, sequenced); consistent authorization helpers actually used everywhere they matter; correct password/key/secret primitives; deliberate de-N+1 of the hottest endpoint; thoughtful enum migrations and an honest non-reversible migration; shielded cancellation paths with documented contextvars reasoning; the blocking-call canary; the metrics.js shared library; a real CSS token system; the datasets upload wizard; structured CLI errors with exact resume instructions; the generated-docs pipeline; LF enforcement via `.gitattributes`; dry-run-by-default ops scripts with single-transaction writes.

---

## 16. Prioritized action plan

**P0 — this week (security + stop the bleeding):**
1. Fix the docs-server path traversal ([docs_site.py](packages/platform/qym_platform/docs_site.py)) and rotate every secret in the deployed `.env` (assume readable).
2. Lock down LLM connections: manager-only writes, URL validation, no `__KEEP__` across base_url changes.
3. Fail fast on `auth_mode` ∈ {none, empty} outside dev; restore the compose `proxy_headers` default; bind Postgres to loopback; add a proxy shared-secret check.
4. Fix `qym run create` (one-line kwarg fix) and `qym analyze run` (route + keys).
5. Sweep the XSS bypasses (escape attributes, validate URL schemes, `textContent` for model output).

**P1 — this month (trust + repeatability):**
6. Stand up CI: fix/delete the stale test modules, make `pytest tests` green, run it on every push; add the authz suite back (rewritten for the project model); add an Alembic-against-Postgres migration test.
7. Evaluation integrity: error-state (not 0.0) for failed metrics across all three aggregation sites; fix the tool_calling judge, the substitution injection, the checkpoint header bug, and the insightor comparison direction.
8. Make ingestion incremental (per-batch stats refresh, not per-event), move payload validation inside the skip-malformed guard, fix the savepoint rollback, add `ON DELETE` behavior for dataset-item children.
9. Docs/examples purge pass for the two pivots (Langfuse, org model); fix `.env.template`; rewrite the quickstart notebook; make `examples/` runnable (CI-check them).
10. Split execution status from review status; freeze approved runs against ingest mutation.

**P2 — this quarter (structural):**
11. Extract shared frontend modules (kill the ~101-function duplication and the app.js forks); add ESLint + a vitest/Playwright smoke suite.
12. Accessibility pass: fix the two text tokens, add global `:focus-visible`, label inputs, trap modal focus, `prefers-reduced-motion`.
13. Honest destructive-action copy and separate archive/delete endpoints; surface annotation-save failures; real project-wide overview stats.
14. Decouple the insightor customer assets from the core repo; move ops scripts behind an authenticated admin surface or out of the image; persist product-eval jobs.
15. API consistency: one error envelope, one pagination shape, response models on `/v1`, deprecate the legacy RPC surface.

---

*Appendices below list every remaining medium and low finding (titles, locations, one-line summaries). Full descriptions for any item are available in the audit working data.*

---

# Appendix — All medium & low findings

_235 findings across 18 areas. Severity in brackets; file in parentheses._

## API Design (18)

- **[MEDIUM]** Dataset CSV upload 500s on cells that look like JSON but aren't — `packages/platform/qym_platform/api/datasets.py #360-367`
- **[MEDIUM]** Documented /v1-vs-/api surface split and API-key reachability of /v1 do not match the code — `docs_portal/docs/api/conventions.mdx #conventions.mdx 10; workflows.mdx 9, 56-62, 105-108; runs.py 2050-2184; datasets.py 1458; projects.py 452-780`
- **[MEDIUM]** Documented API-key scopes are silently not enforced — `packages/platform/qym_platform/auth.py #auth.py 110-116; guide 17-22; projects.py 232-244`
- **[MEDIUM]** Event `sequence` is stored but never enforced; late events overwrite newer state and can reopen submitted/approved runs — contradicting RUN_EVENT_SCHEMA.md ordering rules — `packages/platform/qym_platform/api/ingest.py #ingest.py 885-894, 934-967; RUN_EVENT_SCHEMA.md 27-34; run_lifecycle.py 10-16, 33-38`
- **[MEDIUM]** Four different error-response shapes, mixed even within the same router — `packages/platform/qym_platform/api/product_evals.py #product_evals.py 72-90, 377-385, 774-795; runs.py 1782-1786; ingest.py 1290`
- **[MEDIUM]** Ingestion silently drops malformed/mismatched events and still returns {"ok": true} with no rejected count — but docs tell users to inspect the ingestion response — `packages/platform/qym_platform/api/ingest.py #ingest.py 858-873, 1287-1290; workflows.mdx 109`
- **[MEDIUM]** Negative `limit` accepted on two paginated endpoints — 500 on PostgreSQL — `packages/platform/qym_platform/api/runs.py #runs.py 820; datasets.py 883`
- **[MEDIUM]** POST /v1/runs is not idempotent despite external_run_id being documented as the client's stable identifier — `packages/platform/qym_platform/api/ingest.py #ingest.py 711-767; RUN_EVENT_SCHEMA.md 5-9, 42`
- **[MEDIUM]** Pagination is inconsistent across list endpoints: four envelope conventions, unbounded defaults, and unpaginated lists — `packages/platform/qym_platform/api/runs.py #runs.py 818-830, 1118-1125, 1190-1199, 1724-1739; datasets.py 641-647, 878-933; analysis.py 1285-1297; web.py 67-117`
- **[MEDIUM]** Raw Dict[str, Any] request bodies on nine mutation endpoints skip all validation (plus a nonsensical dead DecisionRequest class) — `packages/platform/qym_platform/api/runs.py #runs.py 1793-1805, 1927-1942, 1979-1988, 2015-2027, 2081-2082, 2085-2091, 2111-2117; analysis.py 1547-1553, 1605-1611, 1646-1652`
- **[MEDIUM]** Status-code semantics inconsistent: creations return 200 (not 201), conflicts are 400 in one router and 409 in another, duplicate user creation returns 200 — `packages/platform/qym_platform/api/projects.py #projects.py 345, 480, 562, 713, 752; datasets.py 566, 781, 978; web.py 120-141; auth.py 180, 196; ingest.py 711`
- **[MEDIUM]** Three competing action/URL conventions coexist: colon custom-methods, slash verbs, and legacy RPC POSTs (including delete-via-POST keyed by 'file_path') — `packages/platform/qym_platform/api/runs.py #runs.py 1792-2047; datasets.py 762, 1083, 1247, 1321, 1409; ingest.py 1293; projects.py 397-415`
- **[MEDIUM]** api/org.py is 642 lines of dead, un-importable code duplicating admin user endpoints — `packages/platform/qym_platform/api/org.py #13-24, 49-54, 100-117 (web.py)`
- **[MEDIUM]** conventions.mdx calls /openapi.json the 'stable machine-readable source of truth', but the schema has no response models, no tags on most routers, and is polluted with HTML page routes — `docs_portal/docs/api/conventions.mdx #conventions.mdx 7, 15; runs.py 60; projects.py 37; datasets.py 42; web.py 16; auth.py 38`
- **[LOW]** Bulk corrections endpoint accepts unknown actions and returns success — `packages/platform/qym_platform/api/analysis.py #1695-1763`
- **[LOW]** Duplicated/ambiguous admin endpoints: two project-creation routes, DELETE that sometimes archives, and overlapping user listings — `packages/platform/qym_platform/api/projects.py #projects.py 470-500, 705-734, 763-780; web.py 67-83, 100-117`
- **[LOW]** GET /api/compare issues full per-run detail builds sequentially (N+1 over heavy _build_run_data) and silently omits inaccessible runs — `packages/platform/qym_platform/api/runs.py #1389-1435`
- **[LOW]** RUN_EVENT_SCHEMA.md is stale versus events.py: missing STOPPED, missing 5 event types, unimplemented WS transport, and embedded diff artifacts — `docs/internal/RUN_EVENT_SCHEMA.md #doc 12-14, 28, 36-98; events.py 10-22, 109`

## Business Logic (20)

- **[MEDIUM]** Analyzer max_tokens is accepted end-to-end but never sent to the LLM — `packages/platform/qym_platform/services/llm_analyzer.py #670-695`
- **[MEDIUM]** Approval decisions have no audit trail and race without locking — `packages/platform/qym_platform/api/runs.py #2085-2184`
- **[MEDIUM]** Auto-approve on human edit fabricates reviewer provenance — `packages/platform/qym_platform/services/root_cause_changes.py #445-476`
- **[MEDIUM]** Correction review has no separation of duties: reviewers == viewers == modifiers — `packages/platform/qym_platform/permissions.py #43-52`
- **[MEDIUM]** Hard-deleting corrections destroys review snapshots while revisions survive as dangling history — `packages/platform/qym_platform/api/analysis.py #1260-1282, 1758-1759, 1766-1781`
- **[MEDIUM]** Heartbeat/stale-run design doc is not what is implemented; recovery is lazy and most read paths never reconcile — `docs/internal/RUNNER_HEARTBEAT_AND_STALE_RUN_RECOVERY.md #doc (all); run_lifecycle.py:29-30,54-69; runs.py:270-281,900,1162,1787`
- **[MEDIUM]** No cost ceilings or spend protection on run analysis: unbounded item counts, save-only-at-end, no disconnect cancellation — `packages/platform/qym_platform/api/analysis.py #71-87, 335-379, 448-526, 626-663`
- **[MEDIUM]** Product evals are hardwired to one internal customer product, and the preset script path breaks for installed deployments — `packages/platform/qym_platform/services/product_evals.py #product_evals.py:235-240, 268-299; insightor_eval.py:254, 817`
- **[MEDIUM]** Product-eval jobs live only in process memory: restart orphans them, dict grows unbounded, and 'stopped' jobs hold worker threads while freeing the capacity counter — `packages/platform/qym_platform/services/product_evals.py #441-457, 186-213, 489-494`
- **[MEDIUM]** Prompt injection path from evaluated outputs and correction snapshots into the analyzer, with a poisoning loop via the correction bank — `packages/platform/qym_platform/services/llm_analyzer.py #335-414, 417-466, 555-586`
- **[MEDIUM]** Stop marks runs STOPPED in the DB while the evaluator keeps executing and ingesting into them — `packages/platform/qym_platform/api/product_evals.py #api:388-420; services:711-724`
- **[MEDIUM]** The 'solution' half of the correction pipeline is collected but never used by the AI — `packages/platform/qym_platform/services/llm_analyzer.py #30-39, 41-59, 452-466, 469-591, 620-627`
- **[MEDIUM]** The review/correction loop closes only into analyzer prompts — never into datasets or metrics — `packages/platform/qym_platform/services/llm_analyzer.py #llm_analyzer.py:92-127; models.py:539-582`
- **[MEDIUM]** insightor_eval extract_tables always fails: sqlglot is never imported — `insightor_eval.py #425-458, 749-755`
- **[MEDIUM]** insightor_eval get_results converts infrastructure failures into 'wrong answer' scores; hardcoded CURRENT_DATE; TLS verification disabled — `insightor_eval.py #270-295, 85, 1034, 1106`
- **[MEDIUM]** unapprove/unreject hardcode status=COMPLETED, converting FAILED runs into COMPLETED — `packages/platform/qym_platform/api/runs.py #2062, 2157, 2182`
- **[LOW]** A smoke-test preset ships in production and can occupy the entire product-eval queue — `packages/platform/qym_platform/product_eval_presets/test_eval.py #test_eval.py:33-43,54-56; product_evals.py:283-298`
- **[LOW]** Dead 'legacy analyzer' compatibility shim (~100 lines) that can never execute, with latent bugs if it did — `packages/platform/qym_platform/api/analysis.py #186-251, 487-497, 578-588, 706-710, 766-770, 783-788`
- **[LOW]** Direct APPROVED→REJECTED correction transitions and last-write-wins reviews without concurrency guards — `packages/platform/qym_platform/api/analysis.py #1646-1668, 1212-1257, 1701-1763`
- **[LOW]** Revision number allocation races under concurrent edits (max+1 with a unique constraint) — `packages/platform/qym_platform/services/root_cause_changes.py #189-195, 421-433`

## Database (15)

- **[MEDIUM]** Check-then-insert and read-modify-write races with no IntegrityError handling — `packages/platform/qym_platform/api/ingest.py #ingest.py 875-894, 570-584; datasets.py 322-339, 973, 1078, 1118-1128; root_cause_changes.py 189-195`
- **[MEDIUM]** DB_SCHEMA.md documents a schema that no longer exists — `docs/internal/DB_SCHEMA.md #1-22`
- **[MEDIUM]** N+1 query patterns in dataset listing payload builders — `packages/platform/qym_platform/api/datasets.py #234-298 (_version_payload/_dataset_payload), call sites 537, 638, 854-864`
- **[MEDIUM]** No composite index for the dominant runs list query (project + soft-delete + created_at sort) — `packages/platform/qym_platform/db/models.py #models.py 182-210; runs.py 831-899, 1126, 1205-1211`
- **[MEDIUM]** No retention story for unbounded append-only tables (run_events, spans, audit_logs, revisions) — `packages/platform/qym_platform/db/models.py #models.py 445-459 (RunEvent), 462-483 (Span), 432-442 (AuditLog), 519-536 (RootCauseRevision), 354-369 (DatasetItemRevision)`
- **[MEDIUM]** RunEvent.sent_at not normalized to UTC on write and misinterpreted as local time on read — `packages/platform/qym_platform/api/ingest.py #ingest.py 891 vs 926; runs.py 1476-1485`
- **[MEDIUM]** Savepoint failure path in span ingestion leaves session broken, losing the whole batch — `packages/platform/qym_platform/api/ingest.py #1239-1285`
- **[MEDIUM]** Unique-constraint violations surface as 500s in several dataset write endpoints — `packages/platform/qym_platform/api/datasets.py #1379-1394 (upload_dataset), 594-604 (update_dataset), 1042 (update_item), 723-739 (create_version)`
- **[MEDIUM]** list_items aggregates the entire run_items table on every dataset page view — `packages/platform/qym_platform/api/datasets.py #895-900, 1212-1225`
- **[MEDIUM]** upload_run commits the Run row before parsing the file, leaving orphan runs on failure — `packages/platform/qym_platform/api/ingest.py #1313-1330, 1332-1333, 1516-1519`
- **[LOW]** Archived (is_active=false) projects remain fully accessible through dataset endpoints — `packages/platform/qym_platform/api/datasets.py #121-139`
- **[LOW]** Dataset reference resolution is ambiguous (id OR slug OR display name) — `packages/platform/qym_platform/api/datasets.py #142-154, 726-728`
- **[LOW]** Dead code referencing dropped tables: api/org.py would crash on import; unused helpers in runs.py — `packages/platform/qym_platform/api/org.py #org.py 13-20, 44-57; runs.py 426-540, 2081-2082`
- **[LOW]** Migration portability/safety nits: ADD VALUE in transaction; version copy is row-at-a-time — `packages/platform/qym_platform/migrations/versions/0009_add_stopped_pending_status.py #0009 lines 19-20; 0014 lines 95-96; datasets.py 740-756`
- **[LOW]** Model-declared indexes missing from the migrated (production) schema — `packages/platform/qym_platform/db/models.py #models.py 450 (RunEvent.event_id), 466 (Span.run_id); 0014 lines 300-332`

## Deployment & Hygiene (16)

- **[MEDIUM]** 23MB of junk committed: 15 near-duplicate .pptx decks, tmp/ mocks, node_modules stubs with developer machine paths, mock files inside the shipped wheel — `outputs/ #n/a`
- **[MEDIUM]** Containers run as root; no HEALTHCHECK in Dockerfile; base images unpinned — `docker/Dockerfile #1-85`
- **[MEDIUM]** Customer-specific insightor_eval.py lives at repo root, baked into the image, located via fragile parents[4] traversal — `insightor_eval.py #Dockerfile:26,60; product_evals.py:235-240`
- **[MEDIUM]** Default image contains no docs portal, contradicting docker-deployment and air-gapped docs — `docker/Dockerfile #Dockerfile:75-85; docker-deployment.mdx:3,12-14`
- **[MEDIUM]** Internal government hostnames hardcoded as defaults; TLS verification disabled in tooling — `upload-sdk-to-nexus.sh #upload-sdk-to-nexus.sh:43,183,201; insightor_eval.py:254,817`
- **[MEDIUM]** Migrations run unconditionally on every container start with no concurrency guard — `docker/entrypoint.sh #entrypoint.sh:5; env.py:43-56`
- **[MEDIUM]** No CI whatsoever: no GitHub Actions, no lint/test enforcement — `.github (absent) #pyproject.toml:41-48`
- **[MEDIUM]** No dependency locking for the deployed application: all Python deps are open-ended ranges — `packages/platform/pyproject.toml #platform:14-32; sdk:25-38`
- **[MEDIUM]** No restart policy on api/db and no resource limits anywhere in compose — `docker/docker-compose.yml #4-51,69`
- **[MEDIUM]** backup.sh: non-atomic dump files, crash-loop on failure, mismatched defaults, and no restore story — `docker/backup.sh #backup.sh:6-7,16; docker-compose.yml:63-64`
- **[MEDIUM]** build-sdk.sh downloads 'qym' from public PyPI instead of using the locally built wheel — `build-sdk.sh #93-98`
- **[MEDIUM]** db healthcheck hardcodes user/db 'qym' while POSTGRES_USER/DB are configurable — `docker/docker-compose.yml #15`
- **[LOW]** .dockerignore missing .git, outputs/, tmp/, node_modules - bloated build context — `.dockerignore #1-31`
- **[LOW]** .gitignore inconsistencies: tracked files matching ignore rules, duplicates, and over-broad global patterns — `.gitignore #75,87,90-98,126`
- **[LOW]** Dead and stale packaging config: unused artifact_store_path setting, phantom SDK package-data glob, obsolete compose version key — `packages/platform/qym_platform/settings.py #settings.py:44; sdk pyproject:60; compose:1`
- **[LOW]** relativize-build.mjs rewrites bundler internals with regexes - brittle against Docusaurus upgrades — `docs_portal/scripts/relativize-build.mjs #relativize-build.mjs:13-17,62-65`

## Documentation (14)

- **[MEDIUM]** AGENTS.md is stale: old QYM_PLATFORM_URL env var, wrong docs layout, broken example command, Langfuse-first credential guidance — `AGENTS.md #28-30, 43-46, 49, 51, 71-75`
- **[MEDIUM]** Docker quickstart documented in READMEs cannot work from the committed .env.template (missing required compose variables) — `.env.template #.env.template:1-14; packages/platform/README.md:21-31; README.md:150-154`
- **[MEDIUM]** SDK USER_GUIDE documents non-existent CLI flags --concurrency and --no-tui; --output mislabeled — `packages/sdk/docs/USER_GUIDE.md #1053-1068`
- **[MEDIUM]** SDK_INTEGRATION_GUIDE documents EvaluatorConfig fields that do not exist (langfuse_*), which are silently ignored — `SDK_INTEGRATION_GUIDE.md #SDK_INTEGRATION_GUIDE.md:1234-1243; docs_portal/docs/sdk/configuration.mdx:78-81; packages/sdk/docs/USER_GUIDE.md:1435-1438`
- **[MEDIUM]** SDK_INTEGRATION_GUIDE's recommended resume config raises ValueError (resume_rerun_errors) — `SDK_INTEGRATION_GUIDE.md #1171, 1183-1186`
- **[MEDIUM]** docs/internal/DB_SCHEMA.md and RUN_EVENT_SCHEMA.md are stale and RUN_EVENT_SCHEMA contains a literal diff artifact — `docs/internal/DB_SCHEMA.md #DB_SCHEMA.md:9-13; RUN_EVENT_SCHEMA.md:28,36,98; ARCHITECTURE.md:18`
- **[MEDIUM]** docs/internal/RUNNER_HEARTBEAT_AND_STALE_RUN_RECOVERY.md describes a design (LOST status, last_heartbeat_at, background sweeper) that was implemented differently — `docs/internal/RUNNER_HEARTBEAT_AND_STALE_RUN_RECOVERY.md #4-13, 29-47, 55-63`
- **[MEDIUM]** examples/example.py is unrunnable and is the file referenced by docs and generated docs overlays with the wrong function name — `examples/example.py #examples/example.py:15,22; docs_portal/docs/examples/minimal-task.mdx:12`
- **[MEDIUM]** qym.__version__ is '0.9.0' while pyproject.toml says 1.1.0; release notes stop at the 0.9.x era — `packages/sdk/qym/__init__.py #packages/sdk/qym/__init__.py:9; packages/sdk/pyproject.toml:7; docs/RELEASE_NOTES.md:1-7`
- **[LOW]** Generated CLI reference: subcommand links on group pages resolve to the wrong path — `tools/docs/generate.py #471-480`
- **[LOW]** Platform USER_GUIDE access-model and dashboard-action claims partially stale (proxy-headers-only auth story, Langfuse trace jump) — `packages/platform/docs/USER_GUIDE.md #24-32, 100-101`
- **[LOW]** SDK_INTEGRATION_GUIDE.md is a hand-maintained near-duplicate of docs_portal/docs/sdk/integration-guide.mdx (already drifting) — `SDK_INTEGRATION_GUIDE.md #1-1351`
- **[LOW]** USER_GUIDE misdocuments the built-in metric set: claims 'faithfulness' is not built-in (it is) and omits four registered metrics — `packages/sdk/docs/USER_GUIDE.md #USER_GUIDE.md:282-287,641-643,1524; packages/sdk/README.md:265-272`
- **[LOW]** docs/internal/DATASETS_AND_LANGFUSE_REMOVAL_PROPOSAL.md describes its 'Current State' as pre-implementation although the proposal has shipped — `docs/internal/DATASETS_AND_LANGFUSE_REMOVAL_PROPOSAL.md #34-49`

## Examples (gap sweep) (8)

- **[MEDIUM]** Examples require packages that qym does not declare, with no examples-level requirements or README — `examples/rag_eval.py #rag_eval.py:26; rag_eval_judges.py:27; task.py:10; example.py:15`
- **[MEDIUM]** Hardcoded private platform datasets make five examples non-reproducible, with instructions pointing at a nonexistent upload script — `examples/example.py #example.py:106; multi_model.py:29,36; scale_example.py:35,43; rag_eval.py:138; rag_eval_judges.py:10-11,108`
- **[MEDIUM]** csv_dataset_eval.py references examples/datasets/qa.csv which does not exist in the repository — `examples/csv_dataset_eval.py #23-28`
- **[MEDIUM]** text2sql execution_accuracy metric is vacuous: schema-only dataset means any error-free query scores 1.0 — `examples/text2sql/metrics.py #121-177`
- **[MEDIUM]** vector_rag_chroma.py defaults to OpenRouter-style model ID 'openai/gpt-4o-mini' while blessing plain OPENAI_API_KEY configuration — `examples/vector_rag_chroma.py #20-22, 136-143, 154, 181, 215`
- **[LOW]** Inaccurate inline documentation: wrong dataset name, false 'HHEM' metric claim, dead imports, and phantom output columns — `examples/rag_eval.py #rag_eval.py:5,9,138; rag_eval_judges.py:129-133; example.py:16`
- **[LOW]** Stale Langfuse-era docstrings and comments persist in otherwise-current examples — `examples/csv_dataset_eval.py #csv_dataset_eval.py:8; rag_eval.py:64; task.py:43; example.py:6,32`
- **[LOW]** rag_eval_judges.py claims judges work 'by default' with OPENAI_API_KEY, but QYM_JUDGE_MODEL has no default and is required — `examples/rag_eval_judges.py #13-14`

## Frontend Pages (5)

- **[MEDIUM]** Async-updated regions have no aria-live; clickable divs are not keyboard-accessible; renderMarkdownSafe injects unvalidated link hrefs — `packages/platform/qym_platform/_static/dashboard/run.html #aria-live run.html 3554/index.html 189; div-buttons reviews.html 2348/compare.html 7448; xss compare.html 9453/run.html 3954`
- **[MEDIUM]** Custom modals lack focus trapping and focus restoration — `packages/platform/qym_platform/_static/dashboard/compare.html #compare.html 9238-9315; index.html 149-215; project_settings.html 665-678; reviews.html 1316-1331`
- **[MEDIUM]** Filter-panel inputs labeled with non-associated span text, leaving controls unlabeled — `packages/platform/qym_platform/_static/dashboard/compare.html #compare.html 4287-4392; run.html 3461-3548; index.html 18-53`
- **[MEDIUM]** Leftover mock/dev pages shipped in the package and downloadable in production — `packages/platform/qym_platform/_static/dashboard/mock_navigation.html #mock_navigation.html 1-1363; mock_navigation copy.html 1-1693; mocks/output-card-mocks.html 1-700`
- **[MEDIUM]** run.html and compare.html call showToast but never include the toast container — `packages/platform/qym_platform/_static/dashboard/run.html #run.html 4161-4162; compare.html 9525-9526`

## Metrics & Judges (16)

- **[MEDIUM]** Hardcoded response_format/temperature/max_tokens with indiscriminate retries breaks or slow-fails on several OpenAI-compatible backends — `packages/sdk/qym/metrics/judges/base.py #63-97`
- **[MEDIUM]** METRIC_BANK.md mismatches the code: wrong registry name 'contains_expected', fuzzy_match shown case-insensitive, builtin 'faithfulness'/'correctness' heuristics undocumented — `packages/sdk/docs/METRIC_BANK.md #METRIC_BANK.md:25, 86, 347-367; __init__.py:10; builtin.py:66-69, 169-303`
- **[MEDIUM]** METRIC_BANK.md presents exec(output, {'__builtins__': {}}) as 'Sandboxed' — it is not — `packages/sdk/docs/METRIC_BANK.md #520-544`
- **[MEDIUM]** Metric named 'toxicity' returns 1.0 for non-toxic content (and 'hallucination' returns 1.0 for grounded) — score direction inverted vs metric name, with the direction field unused — `packages/sdk/qym/metrics/judges/toxicity.py #toxicity.py:20; hallucination.py:21; result.py:22`
- **[MEDIUM]** Metric registry silently overwrites on re-registration and lets custom metrics shadow builtins — `packages/sdk/qym/metrics/registry.py #11-19, 35-41`
- **[MEDIUM]** Pairwise judge has no position-bias mitigation (A is always shown first) — `packages/sdk/qym/metrics/judges/base.py #322-410`
- **[MEDIUM]** Score-scale inconsistency: token_count returns raw ints (e.g. 130) and response_time is a constant-1.0 placeholder, both exposed as registry metrics — `packages/sdk/qym/metrics/builtin.py #builtin.py:72-104; __init__.py:8-16`
- **[MEDIUM]** Unfilled judge template placeholders are sent to the LLM as literal '{question}' with no warning — `packages/sdk/qym/metrics/judges/base.py #base.py:298-308; relevance.py:10`
- **[MEDIUM]** _parse_verdict crashes with uncaught AttributeError on valid-JSON non-object responses, bypassing all fallbacks — `packages/sdk/qym/metrics/judges/base.py #100-128, 178`
- **[LOW]** A new AsyncOpenAI client is constructed per judge call and never closed — `packages/sdk/qym/metrics/judges/base.py #150-154`
- **[LOW]** All built-in judges are binary verdicts with terse rubrics — no partial credit or calibration anchors — `packages/sdk/qym/metrics/judges/correctness_llm.py #correctness_llm.py:5-14; conciseness.py:5-13; relevance.py:5-13`
- **[LOW]** Builtin metric test coverage is near-zero: only exact_match has tests — `tests/sdk/test_builtin_metrics.py #1-13`
- **[LOW]** Minor builtin.py defects: dead 'exact' computation in correctness; unguarded .get on input_data['input'] in faithfulness — `packages/sdk/qym/metrics/builtin.py #193, 238-239`
- **[LOW]** create_judge offers no per-judge temperature/max_tokens/timeout override and records no provenance metadata on success — `packages/sdk/qym/metrics/judges/base.py #239-248, 219-224`
- **[LOW]** fuzzy_match 'threshold' parameter is dead, and the evaluator's positional fallback passes input_data into it — `packages/sdk/qym/metrics/builtin.py #builtin.py:50-69; evaluator.py:1673-1692`
- **[LOW]** has_judges() and the ImportError guard never actually check for openai — judge availability is always reported True — `packages/sdk/qym/metrics/__init__.py #__init__.py:18-26, 48-50; base.py:139-145`

## OTel Tracing (15)

- **[MEDIUM]** 64KB truncation produces invalid JSON in input.value/output.value, silently breaking downstream parsing — `packages/sdk/qym/core/otel.py #otel.py 484-500, ingest.py 130-135`
- **[MEDIUM]** Cost pipeline is dead code: llm.cost.total is read but never written anywhere — `packages/platform/qym_platform/api/ingest.py #ingest.py 382-387`
- **[MEDIUM]** Enrichment wrappers run unguarded inside the user's LLM call: generator messages get consumed, exceptions and span leaks propagate — `packages/sdk/qym/core/otel.py #1021-1032, 883-960, 897-909`
- **[MEDIUM]** Full request/response serialized twice per LLM call even when the instrumentor already populated the attributes — `packages/sdk/qym/core/otel.py #476-500`
- **[MEDIUM]** Per-message span attributes are uncapped; base64 image payloads get JSON-dumped into span attributes — `packages/sdk/qym/core/otel.py #423-451, 319-325, 348-351, 930-936`
- **[MEDIUM]** Phoenix export of full prompts auto-enables from environment variables alone; request capture excludes only three kwargs — `packages/sdk/qym/core/otel.py #1299-1327, 476-489`
- **[MEDIUM]** Repeated Evaluator construction leaks QymSpanProcessors onto the global provider — `packages/sdk/qym/core/otel.py #1336-1339`
- **[MEDIUM]** Savepoint failure path never rolls back, poisoning the session for the rest of the batch on Postgres — `packages/platform/qym_platform/api/ingest.py #1239-1285`
- **[MEDIUM]** Tool span timings are fabricated and feed avg_tool_ms as if real; children start before their parent span — `packages/sdk/qym/core/otel.py #otel.py 913-960, ingest.py 396-398`
- **[LOW]** FunctionAdapter clobbers the user function's model default with explicit None; TaskAdapter.run() breaks inside running loops — `packages/sdk/qym/adapters/base.py #82-84, 27-29`
- **[LOW]** ID-less tool results can be falsely deduplicated across successive LLM calls — `packages/sdk/qym/core/otel.py #902-909`
- **[LOW]** Nested LLM-span dedup is fragile: relies on hardcoded span names at on_start and clears its entire ID set at 10k — `packages/sdk/qym/core/otel.py #133-149, 174-178`
- **[LOW]** Run-level token/cost stats exclude retried attempts and span-less items, under-reporting actual usage — `packages/platform/qym_platform/api/ingest.py #654-664, 494-529`
- **[LOW]** Span run_id index name diverges between migration and model; integration test exercises traceloop, not qym's production OpenInference path — `packages/platform/qym_platform/migrations/versions/0011_add_spans_table.py #0011:36, models.py:466, test_otel_integration.py:1-86, evaluator.py:469`
- **[LOW]** Spans from user-spawned threads are silently dropped by the stream gate — `packages/sdk/qym/core/otel.py #162-166`

## Ops DB Scripts (gap sweep) (14)

- **[MEDIUM]** Ad-hoc score coercion and silent score/provenance rewriting diverge between sibling ingestion paths — `packages/platform/qym_platform/tools/upload_csv_sql_only.py #60-61+74-77+80-117+179-190+317-323; 173-181`
- **[MEDIUM]** Customer-specific identifiers (personal email, project slug, production run ids) hardcoded as defaults in shipped package code — `packages/platform/qym_platform/tools/upload_csv_sql_only.py #349-350+183+158; 225-226+93; 48-52+257-258; 12`
- **[MEDIUM]** Duplicate-run guard breaks when external_run_id is None (IS NULL match) — false abort or no guard at all — `packages/platform/qym_platform/tools/upload_csv_sql_only.py #187-201; 95-107; 93`
- **[MEDIUM]** SQL-only transform silently replaces any unparseable output with {"sql": ""} — `packages/platform/qym_platform/tools/upload_csv_sql_only.py #134-141+272-276; 35-66`
- **[MEDIUM]** Unaudited, auth-bypassing DB write paths shipped in the production image — `packages/platform/qym_platform/tools/upload_csv_sql_only.py #upload_csv_sql_only.py:50+364; backfill_item_domain.py:264`
- **[MEDIUM]** backfill_item_domain run selection uses OR-union and matches external_run_id across all projects — `packages/platform/qym_platform/tools/backfill_item_domain.py #118-148`
- **[MEDIUM]** backfill_item_domain.py depends on sqlglot, which is not a declared dependency and is not installed in the Docker image — `packages/platform/qym_platform/tools/backfill_item_domain.py #40; 14-32; 25-38; 64-65`
- **[MEDIUM]** duplicate_run_sql_only commits unconditionally (no dry-run), drops dataset linkage, and can resurrect soft-deleted runs — `packages/platform/qym_platform/tools/duplicate_run_sql_only.py #76-108, 165`
- **[LOW]** Dry-run prints a rolled-back run_id on stdout with the same contract as commit mode — `packages/platform/qym_platform/tools/upload_csv_sql_only.py #389-398; 263-271`
- **[LOW]** Metric-name derivation strips every '_score' occurrence, silently nulling scores for metrics whose name contains '_score' — `packages/platform/qym_platform/tools/upload_csv_sql_only.py #163-167; 76-80`
- **[LOW]** Scripts crash with raw tracebacks on malformed CSV fields the API tolerates, contradicting the 'mirrors POST /runs:upload exactly' docstring — `packages/platform/qym_platform/tools/upload_csv_plain.py #3-4+87-88+165; 174-175+288`
- **[LOW]** Zero behavioral test coverage for 1,363 lines of DB-mutating tooling — `tests/test_restructure.py #134-135`
- **[LOW]** ast.literal_eval on CSV content is not an RCE vector, but uncaught RecursionError/MemoryError can crash ingestion — `packages/platform/qym_platform/tools/upload_csv_sql_only.py #120-131; 35-51`
- **[LOW]** qym_platform/tools has no __init__.py — excluded from wheels; works in Docker only because of editable install — `packages/platform/qym_platform/tools #pyproject.toml:37-38; Dockerfile:65`

## SDK Client & CLI (10)

- **[MEDIUM]** Background streamer retries non-idempotent event POSTs without jitter, risking duplicate events on the platform — `packages/sdk/qym/platform/client.py #client.py:310-345`
- **[MEDIUM]** RunSpec.output_path is typed str but loader and run.py pass Path objects, raising pydantic ValidationError — `packages/sdk/qym/cli/_legacy.py #_legacy.py:141-142,159-174; config.py:86`
- **[MEDIUM]** Test imports rebuild_langfuse_urls which no longer exists in dashboard_server (broken test, dead reference) — `tests/sdk/test_run_discovery_dashboard.py #test_run_discovery_dashboard.py:6,128`
- **[MEDIUM]** qym dashboard host is hardcoded to 127.0.0.1 with no port-collision handling; default port 8080 can fail to bind — `packages/sdk/qym/server/dashboard_server.py #dashboard_server.py:410-411,460-474`
- **[MEDIUM]** qym dataset download has no error handling and writes the output file before checking the response — `packages/sdk/qym/cli/dataset.py #dataset.py:126-143`
- **[MEDIUM]** run create overloads exit code 2 for both usage errors and the 'low success rate' warning — `packages/sdk/qym/cli/run.py #run.py:139-141,279-283`
- **[LOW]** Legacy argv rewriting silently injects 'run create' and can mask real usage errors — `packages/sdk/qym/cli/app.py #app.py:142-192`
- **[LOW]** QYM_PLATFORM_DEBUG opens an arbitrary attacker-influencable file path in append mode at import time — `packages/sdk/qym/platform/client.py #client.py:20-31`
- **[LOW]** __version__ (0.9.0) is out of sync with pyproject version (1.1.0); shown in TUI footer — `packages/sdk/qym/__init__.py #__init__.py:9; pyproject.toml:7`
- **[LOW]** create_run treats a 200 response missing run_id/live_url as a RuntimeError that buries the platform's actual message — `packages/sdk/qym/platform/client.py #client.py:397-401`

## SDK Core (18)

- **[MEDIUM]** Checkpoint writer failure deadlocks arun: _write_loop has no exception handling and write_queue.join() waits forever — `packages/sdk/qym/core/evaluator.py #1245-1254, 1437-1441`
- **[MEDIUM]** Error-row detection uses substring 'ERROR' on only the first metric and has two diverging implementations — `packages/sdk/qym/core/checkpoint.py #checkpoint.py:28-36, run_discovery.py:177-191`
- **[MEDIUM]** Item-ID scheme diverges between checkpoint rows and platform events / error paths — `packages/sdk/qym/core/evaluator.py #1212-1233 vs 1844, 2191, 2279, 2387, 2630`
- **[MEDIUM]** Metric means disagree between EvaluationResult, RunDiscovery, and group_analysis for the same run — `packages/sdk/qym/core/results.py #results.py:114-143, run_discovery.py:384-395, group_analysis.py:41-46`
- **[MEDIUM]** Metric timeouts are recorded as real 0.0 scores while metric errors are excluded — inconsistent aggregation that skews means — `packages/sdk/qym/core/evaluator.py #evaluator.py:2162-2168, results.py:114-143`
- **[MEDIUM]** Resume accepts truncated/partial checkpoint rows as completed items — `packages/sdk/qym/core/checkpoint.py #210-222`
- **[MEDIUM]** Sync metrics/tasks that exceed timeouts leak threads that occupy the undersized shared pool — `packages/sdk/qym/core/evaluator.py #899-906, 2136-2144, 2146-2154`
- **[MEDIUM]** auto_save format is silently ignored whenever checkpointing is enabled (the default) — `packages/sdk/qym/core/evaluator.py #797-811, 1516-1523`
- **[MEDIUM]** display_name computed by build_run_identifiers is immediately clobbered; default runs render as 'None [task]' in the TUI — `packages/sdk/qym/core/evaluator.py #523-548`
- **[MEDIUM]** serialize_checkpoint_row uses json.dumps without default=str — non-JSON-serializable run_metadata crashes workers mid-run — `packages/sdk/qym/core/checkpoint.py #100-107`
- **[MEDIUM]** should_stop callback is silently dropped in multi-model runs — `packages/sdk/qym/core/evaluator.py #evaluator.py:1738-1741, config.py:24`
- **[LOW]** Dead code cluster in evaluator.py and friends — `packages/sdk/qym/core/evaluator.py #evaluator.py:1120/1155, 1210-1222, 2727-2732, 474-475; results.py:126-127`
- **[LOW]** Evaluator is a god object: 2,700 lines spanning at least seven distinct responsibilities — `packages/sdk/qym/core/evaluator.py #414-2680`
- **[LOW]** Evaluator mutates caller-owned config and run_metadata in place; class-level registries grow unbounded — `packages/sdk/qym/core/evaluator.py #538-543, 913-915, 934-940, 417-419, 561`
- **[LOW]** Platform event stream silently drops events after retries and buffers unboundedly — `packages/sdk/qym/platform/client.py #137, 320-343`
- **[LOW]** Resume overwrites checkpoint-derived item metadata with raw dataset metadata — `packages/sdk/qym/core/evaluator.py #1179-1181, 1216-1226`
- **[LOW]** __version__ is stale (0.9.0 vs pyproject 1.1.0) and is what runs report to the platform — `packages/sdk/qym/__init__.py #9`
- **[LOW]** run() applies process-global side effects on every invocation (event loop policy, nest_asyncio) — `packages/sdk/qym/core/evaluator.py #823-839`

## SDK TUI & Observers (gap sweep) (16)

- **[MEDIUM]** CompositeEvaluationObserver swallows all observer exceptions silently — evaluator's logging is unreachable — `packages/sdk/qym/core/observers.py #observers.py:312-319; evaluator.py:718-729`
- **[MEDIUM]** Dashboard auto-refresh thread lifecycle: not exception-safe in Evaluator.arun, plus AttributeError race in shutdown() — `packages/sdk/qym/core/evaluator.py #evaluator.py:1449-1455; dashboard.py:274-280, 663-679`
- **[MEDIUM]** Item error messages are stored but never rendered anywhere in the TUI — `packages/sdk/qym/core/dashboard.py #56, 225-231, 251-256`
- **[MEDIUM]** ProgressTracker is a write-only memory sink: snapshot consumer (UIServer) was removed but the tracker still duplicates the whole dataset in memory — `packages/sdk/qym/core/progress.py #progress.py:41-60, 79-81, 137-148, 150-176; evaluator.py:946, 948-949, 75-76`
- **[MEDIUM]** Render path sorts the entire unbounded latency_samples list on every refresh — `packages/sdk/qym/core/dashboard.py #53, 218, 563-604, 785-793`
- **[MEDIUM]** Resumed runs show wildly inflated throughput and near-zero ETA — `packages/sdk/qym/core/dashboard.py #68-75, 159-170, 299-309, 537-542`
- **[MEDIUM]** TUI header always shows 'Retries: 0' in single-run mode (actual default is 2) — `packages/sdk/qym/core/evaluator.py #evaluator.py:1095-1100; dashboard.py:318-321; config.py:22`
- **[MEDIUM]** Two failure paths never emit on_item_error — interrupted/crashed items render as in-progress forever — `packages/sdk/qym/core/evaluator.py #evaluator.py:1284-1302, 2622-2653; dashboard.py:512-529`
- **[LOW]** Dead code cluster in dashboard.py, including a run-ID regex that cannot match real run IDs — `packages/sdk/qym/core/dashboard.py #15, 17, 48, 58-66, 206, 651-661, 768-774, 823-831`
- **[LOW]** Header statistics use different semantics than the per-run rows on the same screen — `packages/sdk/qym/core/dashboard.py #303-309, 326-330, 68-75, 637-643`
- **[LOW]** ProgressSnapshot exposes only item_index — consumers cannot correlate events with item_id-keyed results/platform records — `packages/sdk/qym/core/observers.py #observers.py:79-102, 216-227; evaluator.py:1844-1865, 1216-1233`
- **[LOW]** RunVisualState is mutated and rendered across threads with no synchronization (GIL-tolerated, not guaranteed) — `packages/sdk/qym/core/dashboard.py #31-56, 194-239, 261-272, 663-679`
- **[LOW]** Runs with failed items render as '✅ Done', contradicting the in-run status guard — `packages/sdk/qym/core/dashboard.py #219-221, 241-249, 431-443, 627-635`
- **[LOW]** Sparkline character ramp has duplicate blank levels and omits ▁ — fastest samples render as gaps — `packages/sdk/qym/core/dashboard.py #584-592`
- **[LOW]** Spinner instance recreated on every dashboard update resets its animation phase — `packages/sdk/qym/core/dashboard.py #627-629, 261-272`
- **[LOW]** _DashboardObserver leaks _item_starts entries for failed items — `packages/sdk/qym/core/dashboard.py #688, 698-702, 719-722, 730-732`

## Security — API (5)

- **[MEDIUM]** Full user directory disclosed to any authenticated user via unguarded /v1/users — `packages/platform/qym_platform/api/web.py #67-83`
- **[MEDIUM]** No rate limiting or lockout on password login / signup / admin-bootstrap endpoints — `packages/platform/qym_platform/api/auth.py #156-177, 180-228, 241-262`
- **[MEDIUM]** Unbounded request bodies in ingest and uploads enable memory-exhaustion DoS — `packages/platform/qym_platform/api/ingest.py #11, 850, 1308-1310`
- **[LOW]** Access-denied returned as HTTP 200 with {"error": ...} on run-data endpoint — `packages/platform/qym_platform/api/runs.py #1776-1789`
- **[LOW]** OpenAPI schema and interactive docs are publicly exposed — `packages/platform/qym_platform/app.py #26-32`

## Security — Auth (3)

- **[MEDIUM]** API-key scope enforcement disabled; any member can mint a full-access key — `auth.py #auth.py:110-116; projects.py:660-680`
- **[MEDIUM]** Admin bootstrap token compared with non-constant-time equality — `auth.py #auth.py:165; api/auth.py:248`
- **[MEDIUM]** Open-redirect bypass in sanitize_next via backslash path — `auth_oidc.py #auth_oidc.py:91-99; api/auth.py:99,144`

## Testing & CI (11)

- **[MEDIUM]** Builtin metric coverage is nearly empty: only exact_match is tested out of 8 public metrics — `tests/sdk/test_builtin_metrics.py #builtin.py:15-209`
- **[MEDIUM]** No contract tests between the SDK platform client and the platform ingest API — `tests/sdk/test_platform_client.py #test_platform_client.py:18-24`
- **[MEDIUM]** No end-to-end tests exist for either the platform web app or the SDK CLI — `tests/`
- **[MEDIUM]** No pytest configuration anywhere; platform package declares no test dependencies; repo venv cannot run tests — `packages/sdk/pyproject.toml #sdk pyproject:40-48; platform pyproject:14-32`
- **[MEDIUM]** OIDC token-exchange logic has zero real coverage; one test only verifies its own mock — `tests/platform/test_oidc_auth.py #test_oidc_auth.py:99-112,181-189; auth_oidc.py:257`
- **[MEDIUM]** Timing-dependent tests with real sleeps and wall-clock assertions make the suite slow (~100s) and load-sensitive — `tests/sdk/test_blocking_detection.py #test_blocking_detection.py:47,97,239; test_hardening_tier1.py:100-103,137,396; test_overhead_breakdown.py:197-203,291-299`
- **[MEDIUM]** conftest.py replaces rich/langfuse/bidi/openpyxl with MagicMocks process-wide, breaking test_docs_generation collection — `tests/conftest.py #conftest.py:7-24,33-42`
- **[MEDIUM]** test_dashboard_static.py is 421 lines of source-string matching, not behavior testing — `tests/platform/test_dashboard_static.py #59-144, 307-398`
- **[LOW]** Benchmark/profile scripts live in tests/ but require external services and manual invocation — `tests/benchmark_concurrency.py #benchmark_concurrency.py:12-16; profile_run.py:12,32`
- **[LOW]** test_hardening_tier1 T2.1 test depends on a sibling project outside the repository — `tests/sdk/test_hardening_tier1.py #443-462`
- **[LOW]** test_restructure.py contains an assertion that can never fail and a 690-line suite frozen to a past migration — `tests/test_restructure.py #660-672`

## UX & Copy (17)

- **[MEDIUM]** 'Review/Approve/Reject/Pending' names two unrelated workflows, guaranteeing confusion — `packages/platform/qym_platform/_static/dashboard/overview.html #overview.html:115,355; reviews.html:1199-1210; dashboard.js:3228,4894; run.html:3515-3521,6178`
- **[MEDIUM]** Admin 'Create User' gives zero feedback on failure (unhandled promise rejection) — `packages/platform/qym_platform/_static/dashboard/admin.html #595-609`
- **[MEDIUM]** Archiving a project is one-way in the UI — no unarchive control exists — `packages/platform/qym_platform/_static/dashboard/admin.html #admin.html:435-440; projects.py:737-760`
- **[MEDIUM]** Delete-run error always shows 'Unknown error' (reads data.error, API returns detail) and uses alert() instead of toasts — `packages/platform/qym_platform/_static/dashboard/dashboard.js #dashboard.js:4424,4809-4812,4870; runs.py:1988,1994`
- **[MEDIUM]** Deletion semantics differ per object type while sharing identical warning copy — `packages/platform/qym_platform/_static/dashboard/datasets.html #datasets.html:2759, reviews.html:2279, index.html:158, datasets.py:617`
- **[MEDIUM]** Docs describe endpoints and roles that do not exist — `docs_portal/docs/api/workflows.mdx #workflows.mdx:89; review-approval.mdx:48-53,87-90`
- **[MEDIUM]** Empty-projects state tells members to 'Create a project' they are not allowed to create — `packages/platform/qym_platform/_static/dashboard/projects.html #projects.html:143-144,153; projects.py:477`
- **[MEDIUM]** Exit code 2 (USAGE_ERROR) is reused for 'success rate below 50%', breaking the CLI's own semantic contract — `packages/sdk/qym/cli/run.py #run.py:279-283; _exit_codes.py:9`
- **[MEDIUM]** First-run empty state teaches deprecated CLI syntax that the CLI itself nags about — `packages/platform/qym_platform/_static/dashboard/index.html #index.html:86-87; app.py:155,168`
- **[MEDIUM]** `qym dataset` subcommands: raw JSON as human output, error bodies discarded, and download crashes with a traceback — `packages/sdk/qym/cli/dataset.py #36-67, 126-143`
- **[MEDIUM]** `qym run list` is silently scoped to one default project and 100 runs, with no project flag or hint — `packages/sdk/qym/cli/run.py #run.py:328-340, _platform_api.py:122-124, runs.py:818-850`
- **[LOW]** Inconsistent action vocabulary: Sign in / Sign Out / Logout; Owner vs User column labels — `packages/platform/qym_platform/_static/dashboard/shell.js #shell.js:397; auth.js:118; overview.html:76,92; index.html:112`
- **[LOW]** Keyboard shortcuts help modal documents fewer than half the actual shortcuts — `packages/platform/qym_platform/_static/dashboard/index.html #index.html:199-213; dashboard.js:5902-5935`
- **[LOW]** Micro-copy and grammar inconsistencies: 'All Status', 'SELECTED 0 RUNS', 'Eval Runs' vs 'Runs' — `packages/platform/qym_platform/_static/dashboard/index.html #index.html:47,62; models.html:40,68; charts.html:47; admin.html:144,410`
- **[LOW]** Mock/demo pages ship in the production static directory and are publicly served — `packages/platform/qym_platform/_static/dashboard/mock_navigation.html #app.py:74`
- **[LOW]** Profile page leads with migration-era copy meaningless to new users — `packages/platform/qym_platform/_static/dashboard/profile.html #178`
- **[LOW]** Run-level category deletion uses bare confirm() for a run-wide destructive bulk edit — `packages/platform/qym_platform/_static/dashboard/run.html #run.html:6526,6633; compare.html:9957`

## Visual Design (14)

- **[MEDIUM]** 4,200- and 3,400-line inline <style> blocks share one global namespace with dashboard.css and collide — `packages/platform/qym_platform/_static/dashboard/compare.html #compare.html 15-4215, 152-156; run.html 15-3423, 39-47; dashboard.css 155-171, 1067-1080`
- **[MEDIUM]** Duplicate contradictory selector definitions within the same stylesheet — `packages/platform/qym_platform/_static/dashboard/dashboard.css #dashboard.css 1087-1110 vs 3256-3266, 1121-1128 vs 3947-3955; run.html 111-121 vs 255-265`
- **[MEDIUM]** Invalid CSS: alpha hex digits concatenated onto var() — declarations silently dropped — `packages/platform/qym_platform/_static/dashboard/dashboard.css #1054, 3094`
- **[MEDIUM]** Mobile/responsive story is amputation, not adaptation; large pages have only token breakpoints — `packages/platform/qym_platform/_static/dashboard/dashboard.css #dashboard.css 3841-3861, 144; compare.html @media at 640/760/900`
- **[MEDIUM]** No prefers-reduced-motion support despite multiple infinite animations — `packages/platform/qym_platform/_static/dashboard/login.html #login.html 38-54, 395-406; dashboard.css 478-493, 6278-6323`
- **[MEDIUM]** References to design tokens that are never defined (--bg-secondary, --radius-md, --font-mono/--text-muted in SDK copy) — `packages/platform/qym_platform/_static/dashboard/dashboard.css #6640, 6699 (dashboard.css); 60 (run.html); 239, 261-262 (sdk app.css)`
- **[MEDIUM]** Token system is bypassed at scale: 56 hardcoded hex colors, 24 font-size variants, 69% of paddings off-scale in dashboard.css — `packages/platform/qym_platform/_static/dashboard/dashboard.css #2037, 3944, 3954, 6312; compare.html 2703-2718`
- **[MEDIUM]** Typography scale broken in practice: 7-9px text and per-scope redefinition of the type tokens — `packages/platform/qym_platform/_static/dashboard/dashboard.css #dashboard.css 405, 1043, 6184; shell.css 34-39, 376-381; compare.html 2700; run.html 2344`
- **[MEDIUM]** Unmanaged z-index escalation (0 to 50000); toasts render beneath the trace viewer — `packages/platform/qym_platform/_static/dashboard/dashboard.css #dashboard.css 3967, 7740; shell.css 444, 632`
- **[MEDIUM]** platform/_static/ui/app.css and sdk/_static/ui/app.css are drifted near-duplicate forks with leftover wrong-brand styling and an unreachable light theme — `packages/platform/qym_platform/_static/ui/app.css #platform 13, 73, 83, 115, 150-158, 206-209; sdk 13; both 21-35`
- **[LOW]** !important inside @keyframes makes the chart bar grow animation a no-op — `packages/platform/qym_platform/_static/dashboard/dashboard.css #2359-2365`
- **[LOW]** 30 'transition: all' declarations and 10 distinct duration/easing combos — `packages/platform/qym_platform/_static/dashboard/dashboard.css #220, 281, 1096, 3463, 5884 (examples)`
- **[LOW]** Design/mock artifacts shipped inside the production static directory — `packages/platform/qym_platform/_static/dashboard/mock_navigation copy.html #-`
- **[LOW]** Three different brand palettes across the product surfaces; login page adds a fourth typeface via runtime Google Fonts import — `packages/platform/qym_platform/_static/dashboard/dashboard.css #dashboard.css 21; sdk app.css 13; custom.css 2; login.html 11`
