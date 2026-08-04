# 🚧 qym — Since v0.9.0

**📅 March 2026**

---

The entries below cover every commit after `e2fda02`, in chronological order (through `548e15a`).

---

## Unreleased — LLM analyzer context and rule lifecycle

The `llm_analyzer` branch extends the existing playground into a project-scoped,
metric-aware analysis workspace. The complete developer/operator record is in
[LLM analyzer branch changes](BRANCH_CHANGES_LLM_ANALYZER.md).

- **Metric-aware analysis** — analyze selected item/metric targets, persist
  independent diagnoses under `item_metadata.metric_analyses`, expose metric-scoped
  review candidates, and switch run/compare root-cause breakdowns by metric.
- **Project context** — add bounded reference-document libraries, nested
  field/custom-variable mapping, useful trace projection, secret
  redaction, reasoning-model parsing, confidence calibration, and prompt/test
  previews.
- **Versioned analyzer rules** — generate draft rules from project material and
  approved corrections, compare rule lineage, publish immutable snapshots, and move
  the `production` alias with guarded lifecycle operations.
- **Project LLM connections** — manage named encrypted provider configurations with
  default selection, connection testing, URL validation, DNS pinning, redirect
  blocking, and an explicit opt-in for trusted private endpoints.
- **Safe document extraction** — support text, DOCX, HTML, and PDF reference files
  with upload, expansion, page, character, CPU, and memory bounds; add `pypdf`.
- **Review semantics** — preserve append-only correction history, support metric
  scope, retain removed candidates as rejected history, and keep approved examples
  for rule inference rather than injecting them into every item prompt.
- **SDK/CLI and examples** — point `qym analyze` at the implemented `/api` route,
  report item-metric summaries, and expand the Text-to-SQL example with business
  context and judge metrics.

---

### `d226993` — Repeat runs: samples=k, pass@k, and per-pass views *(July 2026)*

- 🔁 **Native repeat runs** — `Evaluator(..., samples=8)` (or `qym run create --samples 8`) evaluates every dataset item 8 times as **one logical run**: k sequential passes with progressive per-pass metrics in the live TUI, per-(item, pass) checkpointing and resume, and the group set — **Pass@k, Pass^k, Avg@k, Max@k, Consistency, Reliability** — reported automatically
- 🎯 **Any k after the fact** — all passes are stored, so `result.pass_at(3)` / `result.pass_hat(3)` compute unbiased Pass@k/Pass^k for any k ≤ samples without re-running; `get_metric_stats()` gains bootstrap 95% CIs when sampling
- 🗄️ **Pass-aware platform storage** — migration `0023_repeat_runs` adds `runs.samples`, pass-scoped attempts (with per-pass outputs), and the `run_item_pass_scores` table; `run_item_scores` keeps one reduced-mean row per item/metric so every existing view keeps working, and old SDKs ingest unchanged
- 📊 **Repeat-run UI** — runs list shows one row per repeat run with a `×k` pill, `±CI` beside metric means, live `pass j/k` badges, and an expandable per-pass breakdown; run detail gains a **Samples analysis** card with an accuracy-vs-k curve (Pass@k vs Pass^k), a per-pass table, and per-item pass-dot strips; models-view group analysis pools attempts across selected runs
- 🧹 **Duct-tape retired** — duplicating a run spec k times for pass@k is deprecated (the SDK warns "did you mean samples=k?"), the timestamp grouping heuristic is gated to legacy runs, and product-eval presets now run one `samples=k` run instead of k parallel runs (API contract unchanged)

---

### `bd7759a` — AI evaluator playground

- 🤖 Added an **AI Evaluator Playground** modal to single-run and compare views, opened from **Auto-Analyze**, with filter-aware matched-item previews, pagination, live prompt preview, debounced auto-refresh, and one-click test runs on matched items
- ⚙️ Added playground controls for **system prompt editing**, **variable mapping**, **additional fields**, **correction-bank toggles**, **temperature**, and reusable category editing so reviewers can tune analysis before running it
- 🧪 Playground test results now expose the generated item context and few-shot examples so reviewers can inspect exactly what the analyzer will see before running it
- 🔌 Added `/api/runs/{run_id}/analyze-preview` and `/api/runs/{run_id}/analyze-test` plus config translation in the analyzer service so custom playground settings affect prompt generation and live analysis

### `b734338` — Shareable HTML exports and stricter domain drill-down

- 📄 Added **self-contained HTML export** for run pages via `/api/runs/{run_id}/export-html`, with CSS, data, and assets inlined for offline sharing
- ✍️ Run pages now expose **Share** and **Download with Changes** actions; exported HTML stays editable locally, preserves annotation edits in browser storage, and can be re-downloaded with changes baked into a new file
- 🏷️ Domain filtering now supports **AND matching** plus an **exclusive second-click mode** for sole-domain items, and performance breakdown cards now stay aligned with current item-level filters
- 📊 Breakdown cards got clearer click affordances and now sort non-root-cause groups by score instead of alphabetically

### `feb76e9` — Solution analysis

- 💡 AI analysis now suggests **solutions** alongside root causes, storing `solution`, `solution_note`, and source metadata on items and review corrections
- 🧩 Added **solution categories**, **solution notes**, and inline solution assignment/editing in run and compare views, including color-coded badges and a root-cause-to-solution Sankey view
- 🛝 Expanded the playground with **solution categories**, **additional instructions with custom-variable interpolation**, syntax-highlighted prompt previews, richer test-result inspection, and selected-item testing
- 🗃️ Added migration `0004_add_solution_fields` so AI and human solution corrections are persisted separately

### `ed12883` — Root cause details and notes

- 🔎 AI analysis now outputs **`root_cause_detail`** and **`root_cause_note`**, and both AI and human versions are stored on run items and review corrections
- 🏷️ Run and compare views now separate the **broad root-cause category** from the **specific issue detail**, with dedicated badges, shared notes, inline editors, and run-level detail cleanup flows
- 📊 Root-cause summaries became more hierarchical and filter-aware, compare view gained detail-aware category cards and solution flow visualizations, and the playground gained a reusable **detail catalog** for known sub-issues
- 🛡️ Partial saves for notes/details/solutions now preserve unrelated fields instead of clearing other analysis metadata

### `35ad025` — Corrections review UI foundation and overflow fixes

- 🧱 Added the initial **Corrections Review** UI shell with searchable correction cards, status statistics, source/confidence filters, bulk selection, and review action controls
- 🪟 Fixed long root-cause details, categories, and solution badges so they wrap correctly in single-run and compare views instead of causing horizontal overflow

### `232ca1a` — Corrections approval workflow

- 🗂️ Exposed a dedicated **Corrections Review** page from the dashboard navigation
- ✅ Added a full correction approval workflow with **pending / approved / rejected** statuses, reviewer attribution, review comments, bulk actions, and CRUD endpoints for review candidates
- 🔎 The review page now supports task search, source filters, confidence filtering, inline human edits, and bulk moderation flows for large correction queues
- 🧠 Only **approved** corrections now feed the few-shot correction bank used by AI analysis
- 🔄 Editing a correction from `/reviews` now syncs the corresponding run item metadata so review, run, and compare views stay consistent
- 🏷️ Run payloads now expose per-item **review correction status** so the rest of the dashboard can render approval state inline

### `d55dda6` — Approval filters and append-only revision history

- 🔍 Added **Approved / Not Approved** filtering to root-cause analysis in single-run and compare views, plus clearer approved-state pills and filter reset behavior
- 🕘 Introduced append-only **`root_cause_revisions`** history with numbered revisions, before/after states, actor source, and linked review candidates
- 📸 Reviews now preserve snapshots of **input**, **expected output**, **output**, and **scores** at correction time and display per-item revision timelines with review comments and statuses
- 🔒 Approval logic now **supersedes older approved candidates** for the same run item and keeps historical rows immutable, so the correction bank has one active approved example per item

### `310e6c4` — Metric visibility and stable item identity

- 👁️ Added a **metric visibility** dropdown on the runs dashboard with select-all/select-none controls and persisted preferences so users can hide noisy metrics without affecting others
- 🧬 CSV ingest and compare alignment now use deterministic **item fingerprints** when `item_id` is missing or positional, stabilizing cross-run matching for CSV datasets, imported runs, and run discovery
- 🧾 SDK CSV datasets now generate repeatable `csv_<fingerprint>__NNNN` item IDs from input, expected output, and immutable metadata, and the platform returns `compare_item_id` plus `compare_alignment_source` for transparency in comparisons and imported runs
- 🧪 Added platform and SDK test coverage around the new identity rules and CSV handling paths

### `df6d437` — Metric-driven drill-down

- 🎯 In compare view, clicking winner or pass-rate distribution segments now switches the item grid to the same metric used by the overview card before applying the filter
- 📈 In single-run view, clicking pass/fail bars on metric cards now selects that metric and filters the items table to passing or failing rows
- ✨ Added hover affordances on these metric segments so the drill-down behavior is discoverable

### `13e8dc4` — Header user menu and smarter root-cause catalogs

- 👤 Added a header **user dropdown** across run, compare, and reviews pages for quick access to **Profile** and **Admin**
- 🗃️ Analyzer root-cause catalogs now combine built-in defaults, current-run values, and approved task history, so playground suggestions reflect real reviewer vocabulary across runs
- 🔁 Approving a stale correction ID now promotes the active candidate for that run item instead of failing, and the few-shot loader can return the full approved bank when needed
- 📊 Approval-based counts and filters were tightened so approved vs not-approved items are tracked more accurately in run and compare views

### `2b2416c` — Category-to-detail maps and OTEL tracing

- 🗂️ Reworked root-cause catalog management from flat lists to **category → detail maps**, so the playground can add/remove categories and nested details and send that structure to the analyzer
- 🧠 Analyzer prompts can now bias each broad category toward the right known sub-issues from approved corrections
- 📡 Added optional **OpenTelemetry / OpenLLMetry** support in the SDK (`qym[otel]`) with spans linked to Langfuse traces, configurable OTLP export, and explicit tool-call spans between LLM calls
- 🔄 Evaluator and adapter execution now preserve tracing context across async paths so instrumented runs stay connected end to end

### `7828d5d` — Agent-native CLI package

- 🖥️ Replaced the old monolithic CLI with a Typer-based **agent-native CLI package** and noun-verb command groups: `run`, `metric`, `analyze`, and `config`
- 📦 Added structured `--json` output, standardized exit codes, shared output/error helpers, and platform API wrappers for automation-friendly use
- 🛠️ Added `qym run create/list/get/failed/compare`, `qym metric list`, `qym analyze run/summary`, and `qym config show/check`, while keeping `qym dashboard` and `qym submit` as top-level conveniences
- ♻️ Legacy invocations are auto-rewritten, including bare `--task-file ...` and `qym resume --run-file ...`

### `787144e` — Task listing and hidden tasks

- 📋 Added `qym run tasks` to list distinct task names from the platform
- 🙈 Added `hidden_tasks` platform settings support so operators can hide specific tasks from run listings and task discovery
- 🌐 The runs API now omits hidden tasks from grouped task payloads, so both CLI and dashboard listings stay focused on relevant work
- 📚 Updated operator and CLI docs, plus Docker configuration, for the new task-visibility flow

### `9353a7c` — Paginated runs loading

- ⚡ Runs API now supports **`limit` + `offset` pagination** and returns `total_count`, backed by a new run `created_at` index for faster large-list queries
- 🖥️ The dashboard renders the first page immediately, then fetches remaining pages in the background and merges them into state without discarding already-rendered data
- 🏷️ Group titles on the runs dashboard now prefer the resolved API `run_name` instead of reconstructing names from raw config
- 📈 This makes large installations feel much faster while still converging to the full run list

### `596fe81` — `PENDING` and `STOPPED` run states

- 🟡 Added **`PENDING`** and **`STOPPED`** to the run workflow status model and database
- ⛔ The SDK now sends **`STOPPED`** when a single run or multi-run session is interrupted with `Ctrl+C`, instead of leaving runs stuck in `RUNNING`
- 🔄 Dashboard status filters, auto-refresh logic, polling, and badges now treat `PENDING` as active and display `STOPPED` explicitly
- 📌 The runs table gained **sticky first columns** and sticky group headers so wide tables remain usable while scrolling
- 🧯 Event ingestion now dispatches status payloads by explicit type, fixing parsing issues around final status events

### `b1a7c80` — Version tracking

- 🌿 The SDK now auto-detects **git branch** and **git commit** for each run, with CLI overrides via `--git-branch` and `--git-commit`
- 🏷️ The runs API exposes version metadata from `run_config`, and the runs dashboard now shows a dedicated **Version** column with branch/commit search and sorting
- 🏆 Added a **Version Leaderboard** that aggregates performance by git commit, including run counts and the best-performing model per version
- 🔎 Added a version filter plus richer tooltips and badges so model comparisons can be tied back to code revisions

### `cae762d` — LLM-as-judge metric system

- ⚖️ Added **7 built-in LLM judge metrics**: `relevance`, `faithfulness_llm`, `correctness_llm`, `hallucination`, `toxicity`, `conciseness`, `tool_calling` — use them as metric names like any built-in metric
- 🏭 Added `create_judge()` **factory** for custom judges with binary or multi-level grading scales (e.g. excellent/good/poor/bad → 1.0/0.7/0.3/0.0)
- 📊 Introduced **`MetricResult`** dataclass carrying `score`, `label`, `explanation`, and `kind` for structured metric output
- 🔧 **`JudgeConfig`** with env var cascade (`QYM_JUDGE_MODEL`, `QYM_JUDGE_API_KEY`, `QYM_JUDGE_BASE_URL`) and clear error messages when not configured
- 🔁 LLM judge calls include **exponential backoff with jitter** (3 attempts) and safe prompt template substitution
- 🏷️ Platform now stores **`label`** and **`explanation`** on each metric score (new DB columns via migration `0010`), surfaced in the run detail view alongside numeric scores
- 📖 Updated **METRICS_GUIDE.md** and **USER_GUIDE.md** with built-in judge reference, custom judge examples, per-judge model overrides, and structured result documentation

### `afac91d` — Charts view redesign, dataset tabs, and retries

- 🗂️ Redesigned the charts view to render **one card per task** with **dataset tabs** inside each card, so teams can switch datasets without losing the task-level grouping
- 🧭 Added an inline **Run / Version / Model** segmented control in chart tables, including collapsible grouped rows, version-aware grouping, and consistent latency-last column layout
- 🔎 Extended dashboard filtering and presentation around datasets and versions, including version multi-select filters, better wide-table scrolling behavior, and unified **Select All / None** controls across multi-select dropdowns
- ✅ Simplified the approval filter in run and compare views to a single **All / Approved / Not Approved** select instead of the older multi-select pattern
- ⏱️ The SDK now retries failed item execution with **exponential backoff + jitter**, defaults `timeout` to **300s** and `max_retries` to **2**, and records `retry_count` per item
- 📥 Platform ingest now persists each item’s **`retry_count`** in metadata so retries remain visible after streaming to the dashboard

### `15c460b` — OTEL span capture and auto-instrumentation foundation

- 📡 Added **`span_completed` event type** and `SpanCompletedPayload` so the SDK can stream completed OTEL spans to the platform in real time alongside other run events
- 🗃️ Added a **Spans table** (migration `0011`) with `trace_id`, `span_id`, `parent_span_id`, `name`, `kind`, `start_time_ns`/`end_time_ns` (nanosecond precision), `duration_ms`, `status`, `attributes`, `events`, and `links` columns, indexed on `(run_id, trace_id)`
- 🔌 Added **trace API endpoints**: `GET /api/runs/{run_id}/spans`, `GET /api/runs/{run_id}/items/{item_id}/spans`, and `GET /api/runs/{run_id}/items/{item_id}/trace` returning spans, trace summary (span count, error count, duration), and item metadata
- 🔧 Span ingestion uses **savepoint transactions** so a span write failure never rolls back item data
- 🤖 **Auto-instrumentation** via `qym[otel]` — the SDK’s `QymSpanProcessor` captures completed OTEL spans from OpenInference instrumentors and streams them to the platform, with **deduplication** to prevent double-tracing when both a framework (e.g. LangChain) and a provider (e.g. OpenAI) instrumentor fire for the same call
- 🔇 Noise filtering removes low-value spans (`connect`, `dns.resolve`, `tls.handshake`) before storage
- 📖 Added comprehensive **AUTO_INSTRUMENTATION_GUIDE.md** covering setup, supported providers (OpenAI, Anthropic, Google, AWS Bedrock, Cohere, Mistral, Groq, Ollama, and more), frameworks (LangChain, LangGraph, LlamaIndex, CrewAI, Haystack), vector DBs (Pinecone, Chroma, Qdrant, Weaviate, Milvus), agent patterns, custom trace ID injection, privacy controls, and troubleshooting

### `ceff4fc` — Trace viewer integration into dashboard

- 🖥️ Embedded the **Trace Viewer** directly into single-run and compare pages, accessible per-item alongside existing Langfuse trace links
- 🌳 Trace viewer renders a **span tree** with typed SVG icons for each span kind — LLM (chat bubble), TOOL (wrench), AGENT (person), CHAIN (link), EVALUATOR (star), RETRIEVER (search), EMBED (matrix) — color-coded by type
- ⏱️ **Waterfall duration bars** show each span’s relative timeline position and duration within its parent
- 📋 **Detail panel** with tabbed interface: Messages (LLM input/output chat bubbles), Response (model, tokens, cost), Input/Output (tool arguments and results), Metrics, Scores, Raw attributes — tabs appear dynamically based on span type
- 🔎 Real-time **span search** with keyboard navigation (j/k, arrow keys, `/` to focus, Enter/Escape to expand/collapse)
- 📊 **Header metadata chips** showing span count, total duration, total tokens, total cost, error count, and score pills
- 🎨 CodeMirror 6-powered JSON syntax highlighting with modal expand views for large payloads

### `869d9b5` — Trace viewer styling and functionality polish

- 🎨 Major CSS and layout overhaul for the trace viewer — cleaner tree rendering, better spacing, and responsive panel sizing
- 🔄 Improved span attribute extraction and display across all tab types

### `6f19e0a` — Tree connectors, icon badges, and resizable panels

- 🌿 Added **SVG tree connectors** linking parent and child spans with clean line paths
- 🏷️ **Icon badges** with span-type coloring in the tree gutter
- ↔️ **Resizable divider** between the span tree and the detail panel — drag to adjust the split

### `a3097a8` — Event handling, span links, and ingest hardening

- 🔗 Added **span links** support (migration `0012`) for storing cross-trace references
- 🛡️ Platform span ingestion now handles **sanitization** of oversized attributes and malformed payloads, with test coverage for edge cases
- 📡 SDK platform client gained **span streaming** capabilities — completed spans are batched and sent alongside item events
- 🧪 Added platform ingest sanitization tests and SDK platform client tests for span streaming paths

### `7a38f3c` — Dashboard styling for trace viewer

- 🎨 Enhanced dashboard CSS with trace-viewer-aware styling, improved panel layouts, and refined typography for span detail views
- 📐 Trace viewer tree interactions became smoother with better expand/collapse animations and click targets

### `caa98a4` — Reasoning and message enrichment

- 💭 LLM spans now display **"Show Thinking" expandable sections** for assistant reasoning content, extracted from span attributes or structured `input.value`/`output.value` JSON
- 💬 **Message enrichment** reconstructs LLM chat histories from flat OTEL attributes into structured message bubbles with role, content, tool calls, and tool results
- 🔧 Reasoning is matched to assistant messages via smart indexing, so multi-turn conversations show thinking alongside the correct response
- 🧪 Added `test_otel_message_normalization.py` for message extraction and enrichment paths

### `f56e391` — Category chip selector for metadata breakdown

- 🏷️ Added an interactive **category chip selector** to metadata breakdown cards in both run and compare views — click chips to filter items by metadata category (e.g. complexity, domain) without opening dropdowns
- 📡 Enhanced OTEL instrumentation with improved span attribute handling and SDK dependency updates

### `5e08a1d` — Dashboard and trace viewer styling refinements

- 🎨 Refined dashboard CSS for trace viewer panels, improved responsive behavior and visual consistency
- 🔧 OTEL module refactored for cleaner span processing and attribute extraction

### `548e15a` — Trace viewer tree layout redesign, error connectors, and detail panel

- 📐 Redesigned the tree layout so span **icons sit in the gutter** with perfect pipe-to-icon centering at all nesting depths
- 🔴 **Red L-shaped error connectors** now extend from error spans up to the parent branch, making error paths immediately visible in the tree
- 🔇 **Framework noise auto-collapse** — pass-through wrapper spans from LangChain/LangGraph internals (ChannelRead, ChannelWrite, RunnableLambda, routing nodes) are automatically collapsed while preserving meaningful user-defined graph nodes
- ❌ Error spans **auto-expand** on load — the first error span and all its ancestors are expanded automatically so users land on the problem immediately
- 🔗 **Shareable trace URLs** via `?trace=itemId` query parameter for direct linking to a specific item’s trace
- 🏷️ Error detail box in the detail panel shows error type, message, and stack trace with copy buttons

---

# 🚀 qym v0.9.0 — Release Notes

**📅 March 2026**

---

## 🤖 Auto Root Cause Analysis

- 🤖 **LLM-powered auto-analyze** — one-click "Auto-Analyze" button on run and compare views pre-populates root causes using an LLM, with configurable filters (pass/fail, score threshold, skip already analyzed)
- 🔄 **Correction bank** — every human root cause assignment (with feedback notes) is stored and used as few-shot examples for future analyses, so the LLM improves over time as reviewers correct it
- ⚙️ **Per-user LLM configuration** — configure any OpenAI-compatible provider (OpenAI, OpenRouter, Azure, Ollama, vLLM) from the Profile page with connection testing
- 🧠 **Reasoning model support** — handles reasoning models like Kimi K2.5 and DeepSeek-R1 that separate thinking from output
- 🏷️ **AI vs Human badges** — AI-suggested root causes show a 🤖 prefix with confidence indicator; human-confirmed ones show ✓
- 💬 **Toast notifications** — clear guidance when LLM is not configured, directing users to the Profile page

---

# 🚀 qym v0.8.5 — Release Notes

**📅 February 2026**

---

## 📊 Compare View

- 📊 **Avg@K & Pass@K breakdown** — Performance by Category cards now show both average score and pass-at-K as big color-coded numbers, with a count toggle for root causes (All Runs vs Unique Items)
- 🏷️ **Multi-value domains** — list-valued fields like domain are unnested into individual badges, breakdown cards, and filter entries
- 💬 **Feedback on root causes** — add free-text feedback to any root cause assignment with inline editing, cancel/save actions, and visual save confirmation
- 🔍 **(No Root Cause) filter** — find items that haven't been triaged yet
- 📥 **Column selector on export** — a modal lets you pick which columns to include, with object fields (input, output, expected) expanded into selectable sub-fields

---

## 🖥️ Single & Compare Views

- 📊 **Tabular data rendering** — list-of-lists in metric metadata render as HTML tables with "Show all N rows" for large ones
- 📐 **Collapsible expected output** — long expected outputs start collapsed with a "Show more" toggle
- 🔧 **Smarter root cause dropdown** — flips above when near the page bottom, dismisses on scroll, stays open when scrolling within it
- 📥 **Richer CSV exports** — now include item metadata, metric metadata, root causes with feedback, trace URLs, and per-run status

---

## 🌐 Platform — CSV Upload

- 📋 **Full metadata ingestion** — `item_metadata` and `{metric}__meta__json` columns are now properly parsed and stored, so uploaded CSVs display metadata in the dashboard just like live runs
- 🔧 **Robustness fixes** — large fields (>128KB) and `NaN` values in metric metadata no longer cause upload failures

---

---

# 🚀 qym v0.8.4 — Release Notes

**📅 December 2025 – February 2026**

---

## 📢 Big News

**qym is now a fully deployed platform!** Evaluations are no longer confined to local machines — everything runs through a centralized web dashboard accessible to the entire organization. Run evaluations from the SDK, and results stream live to the platform where teams can review, compare, and approve them together. The local dashboard has been retired in favor of this new shared experience.

---

## 🌐 Platform

- 🆕 Centralized web platform for managing and collaborating on evaluations in one place
- 📡 Real-time streaming — results flow in live as evaluations run
- 🔄 Structured approval workflow with clear status lifecycle:
  - 🔵 RUNNING → 🟣 COMPLETED / 🔴 FAILED → 🟡 SUBMITTED → 🟢 APPROVED / ⛔ REJECTED
- 🔐 Role-based visibility:
  - 👨‍💼 **Managers** see all evaluations across the team
  - 🏢 **GMs & VPs** see only **approved** evaluations — leadership always views validated results
- 🏗️ Organization management — define **Sectors → Departments → Teams** from a full admin panel with user management, role assignment, and platform settings
- 🔑 Profile page — securely generate and manage API keys

---

## 📋 Runs View

- 📁 Smart run grouping — identical configurations are grouped with collapsible sections and a **"Compare All"** shortcut
- 👤 Owner column with color-coded avatars — see who ran what at a glance
- 🏷️ Readable run names instead of cryptic IDs
- ⋯ Role-aware action menu — Submit, Approve, Reject, or Delete in one click
- 📊 Live progress column — real-time completion percentages and item counts
- 🔗 Langfuse integration — one-click jump to the trace
- 🔎 Filter status bar — active filters for task, dataset, model, status, and search always visible

---

## 📊 Compare View

- 🛠️ Rebuilt from the ground up with 15+ new capabilities
- 🔍 Instant search across all items
- 🏷️ Metadata filters — slice by complexity, domain, or any custom field
- 📈 Score range filters — greater-than / less-than on any metric
- 📊 Interactive charts — click bar segments to filter the view
- 📥 One-click CSV export with active filters applied
- 🧩 Metadata breakdown cards — color-coded by complexity (🟢 easy → 🔴 hard → 🟣 expert) and domain, showing scores and latency
- 🏷️ Per-item metadata badges — complexity and domain displayed as styled badges on each item for quick visual context
- 📋 Per-item metadata display with configurable field selector
- 📝 Markdown rendering for inputs, outputs, and expected answers
- 📋 Hover-to-copy on any field
- 🏆 Winner badges — gold star on the best-performing run per item
- 📐 Aligned outputs — responses height-matched across runs
- ✅ Pass/Fail badges — each item shows a clear green Pass or red Fail indicator based on the selected metric's threshold
- 🔬 Root cause analysis — assign root causes to underperforming items directly from the compare view, with built-in categories (Hallucination, Reasoning Error, Context Missing, Knowledge Gap, and more) or custom values
- 📊 Root cause breakdown — aggregate cards show root cause distribution across runs, with a dedicated filter to drill down by cause
- 📊 Results and metadata are rendered as readable HTML tables when they are list-of-lists

---

## 🖥️ Single Run View

- 🎨 Completely redesigned — cleaner typography, better spacing, cohesive visual experience

---

## 📊 Models View

- 📉 Consistency and Reliability show "N/A" when data is insufficient instead of a misleading "0%"

---

## ⚡ Performance

- 🚀 Parallel metric execution — run multiple metrics simultaneously with `max_metric_concurrency`
- 🔔 Smart blocking detection — warns when code accidentally slows down the event loop, with fix suggestions right in the terminal

---

## 🛠️ SDK Enhancements

- 🔄 Zero-config platform streaming — set an API key and evaluations stream automatically
- 🏷️ `--task-name` flag — label evaluations with a custom name
- ⏱️ Accurate TUI timing — shows pure task duration, excluding metric overhead
- 💬 Friendlier error messages — clear guidance on file parsing issues
- 📁 Smarter file naming — results use the custom run name without redundant timestamps

---

## ⚠️ Breaking Changes

- 🖥️ `qym dashboard` now opens the platform instead of a local server
- 📄 Confluence publishing has been retired — use the platform or CSV export

---

Happy evaluating! 🎉
