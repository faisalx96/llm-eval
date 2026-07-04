# Platform User Guide

The qym platform is the deployed web app that stores evaluation runs centrally and hosts the live dashboard for reviewing, comparing, and analyzing results.

## Table of Contents

1. [Access Model](#access-model)
2. [Organization & Roles](#organization--roles)
3. [Profile Page](#profile-page)
4. [Runs Dashboard](#runs-dashboard)
5. [Single Run View](#single-run-view)
6. [Compare View](#compare-view)
7. [Charts View](#charts-view)
8. [Trace Viewer](#trace-viewer)
9. [AI Root Cause Analysis](#ai-root-cause-analysis)
10. [Corrections Review](#corrections-review)
11. [Run Workflow & Statuses](#run-workflow--statuses)
12. [Uploading & Submitting Runs](#uploading--submitting-runs)
13. [CLI Commands](#cli-commands)
14. [Admin Panel](#admin-panel)

---

## Access Model

The platform identifies users via reverse-proxy headers:
- `X-User-Email` (preferred) or `X-Email`

First admin bootstrap:
1. Set `QYM_ADMIN_BOOTSTRAP_TOKEN`
2. Send `X-Admin-Bootstrap: <token>` + `X-User-Email: you@company.com` on your first request

---

## Organization & Roles

### Organizational Hierarchy

Users are organized into a three-level hierarchy:
- **Sector** → **Department** → **Team**

Each user belongs to exactly one Team, which determines their visibility and approval authority.

### Roles

| Role | Visibility | Can Approve/Reject |
|------|-----------|-------------------|
| **EMPLOYEE** | Own runs only | No (can submit) |
| **MANAGER** | Managed team(s)' runs | Yes |
| **GM** | Approved runs only (configurable) | No |
| **VP** | Approved runs only (configurable) | No |
| **ADMIN** | All runs and settings | Yes (full access) |

### Visibility Rules (Admin Configurable)
- **GM/VP Approved-Only**: When enabled, GM and VP users can only see runs that have been approved
- **Manager Visibility Scope**: Controls whether managers see all runs in their org subtree or just their direct team

---

## Profile Page

Access at `/profile`. From here you can:

- **View** your profile and organization info
- **Manage API keys** for SDK integration — click **Create New Key**, name it, and copy the token (shown only once)
- **Configure your LLM provider** for AI root cause analysis — set model, API key, and base URL for any OpenAI-compatible provider (OpenAI, OpenRouter, Azure, Ollama, vLLM), with a **Test Connection** button to verify

A **user dropdown** in the header across all pages provides quick access to Profile and Admin.

---

## Runs Dashboard

Open `http://<platform>/` to view all evaluation runs.

### Run Listing

- **Smart grouping** — runs with identical configurations are grouped with collapsible sections and a "Compare All" shortcut. Repeat runs (`samples=k`) are **one row**, not a group: they carry a `×k` pill, an `±CI` beside each metric mean, and an expand arrow that reveals the per-pass slices plus the group set (`Pass@k · Pass^k · Avg@k · Max@k · Consistency · Reliability`). Legacy timestamp-grouped runs keep the old behavior.
- **Paginated loading** — the first page renders immediately, then remaining pages fetch in the background and merge without discarding visible data
- **Owner column** with color-coded avatars — see who ran what at a glance
- **Readable run names** instead of cryptic IDs
- **Version column** — shows git branch and commit for each run, with search and sorting
- **Live progress column** — real-time completion percentages and item counts
- **Sticky first columns** and sticky group headers — wide tables remain usable while scrolling

### Filtering

- **Status filter** — filter by `RUNNING`, `PENDING`, `COMPLETED`, `FAILED`, `STOPPED`, `DRAFT`, `SUBMITTED`, `APPROVED`, `REJECTED`
- **Task, dataset, model** filters always visible in a filter status bar
- **Search** across run names
- **Version filter** — filter by git branch or commit

### Metric Visibility

A **metric visibility dropdown** lets you select which metrics appear in the runs table. Preferences persist per user. Use Select All / Select None for quick toggling — hide noisy metrics without affecting others.

### Actions

- Role-aware action menu per run — **Submit**, **Approve**, **Reject**, or **Delete** in one click
- **Langfuse integration** — one-click jump to the trace
- Click a run ID to open the single run view (`/run/<run_id>`)
- Select multiple runs and click **Compare Selected** to open the compare view

---

## Single Run View

The single run view shows detailed results for one evaluation run.

### Features

- **Performance summary cards** — overall pass rate, average scores, latency statistics
- **Items table** — every evaluation item with input, output, expected output, and per-metric scores
- **Metadata breakdown cards** — color-coded by complexity, domain, or any custom metadata field. Click **category chips** to filter items by metadata value without opening dropdowns
- **Metric drill-down** — click pass/fail bars on metric cards to filter the items table to passing or failing rows
- **Per-item metadata badges** — complexity, domain, and custom fields displayed as styled badges
- **Markdown rendering** for inputs, outputs, and expected answers
- **Hover-to-copy** on any field
- **Collapsible expected output** for long values
- **Pass/Fail badges** — clear green Pass or red Fail indicator based on the selected metric's threshold
- **Tabular data rendering** — list-of-lists in metric metadata render as HTML tables

### Samples Analysis (repeat runs)

Runs executed with `samples=k` (every item evaluated k times as one run) get extra views:

- **Samples analysis card** — the group set (`Pass@k`, `Pass^k`, `Avg@k`, `Max@k`, Consistency, Reliability) as stat cards, plus an **accuracy-vs-k curve**: Pass@k (capability) against Pass^k (reliability) for *every* k ≤ samples, computed on demand from the stored passes — no re-running
- **Per-pass table** — each pass's mean score, latency, and status (passes complete sequentially, so during a live run finished passes are final while the current one streams)
- **Pass-dot strips** — each item row shows one dot per pass (green pass / red fail at the current threshold) next to its Pass/Fail badge; hover for the raw per-pass scores
- The hero header shows `Samples ×k` and, while running, the live `pass j/k` cursor

### Root Cause Analysis

Each item can have a **root cause category**, **detail**, **note**, **solution**, and **solution note** — assigned by AI or a human reviewer. AI-suggested values show a robot prefix with confidence; human-confirmed ones show a checkmark. See [AI Root Cause Analysis](#ai-root-cause-analysis).

### Trace Viewer

Each item row has a trace icon. Click it to open the **embedded Trace Viewer** showing the full span tree for that item's execution. See [Trace Viewer](#trace-viewer).

### HTML Export

Click **Share** to generate a **self-contained HTML export** of the run page. The exported file inlines all CSS, data, and assets for offline viewing. You can edit annotations locally in the browser, then click **Download with Changes** to get a new file with edits baked in.

### Approval Filtering

A simple **All / Approved / Not Approved** toggle filters items by their review correction approval status.

---

## Compare View

Select multiple runs and open the compare view to analyze differences.

### Overview Metrics

| Metric | Description |
|--------|-------------|
| **Pass@K** | % of items where at least one run passed |
| **Pass^K** | % of items where all runs passed |
| **Max@K** | Average of best scores per item |
| **Stability** | % of items where all runs got the same score |
| **Avg Score** | Mean score across all items and runs |
| **Avg Latency** | Mean response time |

Each metric has an info icon (i) with a detailed tooltip. For continuous metrics (0-100), a "Pass if ≥" slider lets you define the passing threshold (default: 80%). Boolean metrics (0/1) automatically use 100%.

> **Repeat runs pool their attempts.** When a selection includes a `samples=k` run, that run contributes its k per-pass scores to the pool (the attempt is the atomic unit), so Pass@K math runs over all attempts — never "pass@k of pass@k".

### Item Comparison

- **Side-by-side outputs** — each model's response height-matched for easy reading
- **5-color score scale**: green (90%+), lime (75%+), yellow (60%+), orange (40%+), red (<40%)
- **Winner badges** — gold star on the best-performing run per item
- **Instant search** across all items
- **Metadata filters** — slice by complexity, domain, or any custom field
- **Score range filters** — greater-than / less-than on any metric
- **Category chip selectors** on breakdown cards for quick filtering

### Metric Drill-Down

In compare view, clicking winner or pass-rate distribution segments switches the item grid to the same metric used by the overview card before applying the filter. Hover affordances make this discoverable.

### Domain & Metadata Breakdown

- **Performance by Category cards** show both average score and pass-at-K as big color-coded numbers
- **Multi-value domains** — list-valued fields like domain are unnested into individual badges, breakdown cards, and filter entries
- Domain filtering supports **AND matching** plus an **exclusive second-click mode** for sole-domain items
- Breakdown cards sort non-root-cause groups by score instead of alphabetically

### Root Cause Analysis

- **Root cause breakdown** — aggregate cards show root cause distribution across runs with a dedicated filter to drill down by cause
- Separate badges for **root-cause category**, **detail**, and **solution**
- **Solution Sankey view** — root-cause-to-solution flow visualization
- **Approval filtering** — All / Approved / Not Approved toggle

### Export

- **CSV export** with active filters applied — a column selector modal lets you pick which columns to include, with object fields (input, output, expected) expanded into selectable sub-fields
- Exports include item metadata, metric metadata, root causes with feedback, trace URLs, and per-run status

---

## Charts View

The charts view shows performance trends across all runs.

### Layout

- **One card per task** with **dataset tabs** inside each card — switch datasets without losing the task-level grouping
- Inline **Run / Version / Model** segmented control in chart tables
- Collapsible grouped rows with version-aware grouping
- Consistent latency-last column layout

### Version Leaderboard

Aggregates performance by git commit, including:
- Run counts per version
- Best-performing model per version
- Version filter plus tooltips and badges

### Filtering

- Filter by time range, task, model, dataset, or version
- **Version multi-select** filters
- Better wide-table scrolling behavior
- Unified **Select All / None** controls across all multi-select dropdowns

---

## Trace Viewer

The trace viewer is embedded directly into single-run and compare pages. Click the trace icon on any item row to inspect the full execution trace.

### What You See

A **span tree** showing every operation that happened inside your task function for that item:

```
eval-my-run-item-0                          [root, 4.2s]
├── openai.chat                             [LLM, gpt-4o, 1.1s]
│   └── tool: search_database              [TOOL, 0.3s]
├── openai.chat                             [LLM, gpt-4o, 0.8s]
│   └── tool: calculate_score              [TOOL, 0.1s]
└── openai.chat                             [LLM, gpt-4o, 0.6s]
```

### Span Tree

- **Typed SVG icons** for each span kind — LLM (chat bubble), TOOL (wrench), AGENT (person), CHAIN (link), EVALUATOR (star), RETRIEVER (search), EMBED (matrix) — color-coded by type
- **Icons sit in the gutter** with pipe-to-icon centering at all nesting depths
- **Waterfall duration bars** show each span's relative timeline position and duration
- **Red L-shaped error connectors** extend from error spans up to the parent branch, making error paths immediately visible
- **Error spans auto-expand** on load — the first error span and all its ancestors are expanded so you land on the problem immediately
- **Framework noise auto-collapse** — LangChain/LangGraph internal wrapper spans (ChannelRead, ChannelWrite, RunnableLambda, routing nodes) are collapsed while preserving meaningful user-defined graph nodes

### Detail Panel

Click any span to open a **tabbed detail panel** (resizable via drag divider):

| Tab | Content |
|-----|---------|
| **Messages** | LLM input/output rendered as chat bubbles with role, content, tool calls, and tool results |
| **Response** | Model name, token usage (prompt + completion), cost |
| **Input/Output** | Tool arguments and results |
| **Metrics** | Span-level metric scores |
| **Scores** | Score pills |
| **Raw** | Full span attributes as syntax-highlighted JSON (CodeMirror 6) with modal expand for large payloads |

Tabs appear dynamically based on span type — LLM spans show Messages and Response, tool spans show Input/Output, etc.

### LLM Message Features

- **"Show Thinking" expandable sections** on assistant messages for reasoning content (Anthropic, DeepSeek, etc.)
- **Message enrichment** reconstructs LLM chat histories from flat OTEL attributes into structured message bubbles
- Reasoning is matched to assistant messages via smart indexing, so multi-turn conversations show thinking alongside the correct response

### Error Details

Error spans show an error detail box with error type, message, and stack trace, each with copy buttons.

### Navigation

- **Real-time span search** — type to filter spans
- **Keyboard navigation** — `j`/`k` or arrow keys to move, `/` to focus search, Enter/Escape to expand/collapse
- **Header metadata chips** showing span count, total duration, total tokens, total cost, error count, and score pills
- **Shareable trace URLs** via `?trace=itemId` query parameter for direct linking to a specific item's trace

### Setup

Traces require SDK instrumentation support. Install `qym`, run your evaluation, and supported LLM calls will be captured automatically when tracing is enabled.

---

## AI Root Cause Analysis

The platform includes LLM-powered root cause analysis for understanding why items fail.

### Prerequisites

Configure your LLM provider on the **Profile** page — set model, API key, and optional base URL. Any OpenAI-compatible provider works (OpenAI, OpenRouter, Azure, Ollama, vLLM). Use the **Test Connection** button to verify.

### Using Auto-Analyze

1. Open a run or compare view
2. Click **Auto-Analyze**
3. Configure filters — pass/fail, score threshold, skip already-analyzed items
4. The LLM analyzes each item and assigns:
   - **Root cause category** (e.g., Hallucination, Reasoning Error, Context Missing, Knowledge Gap)
   - **Root cause detail** — specific sub-issue within the category
   - **Root cause note** — explanation
   - **Solution** — suggested fix
   - **Solution note** — additional solution context

AI-suggested values show a robot icon with confidence indicator. Human-confirmed ones show a checkmark.

### AI Evaluator Playground

Before running analysis, click **Auto-Analyze** to open the **Playground** modal where you can:

- **Edit the system prompt** and preview the rendered prompt
- **Map variables** and add **additional instructions** with custom-variable interpolation
- **Toggle the correction bank** — approved corrections are used as few-shot examples
- **Adjust temperature** and other settings
- **Edit category and detail catalogs** — add/remove root cause categories and their nested detail sub-issues
- **Edit solution categories**
- **Run test analyses** on selected items and inspect the generated context, few-shot examples, and results before launching the full analysis

### Correction Bank

Every human correction (with feedback notes) is stored as a few-shot example. Only **approved** corrections feed the bank. The analyzer's catalogs merge built-in defaults, current-run values, and approved history so suggestions reflect real reviewer vocabulary.

---

## Corrections Review

A dedicated review page for managing root cause corrections.

### Accessing

Click **Corrections Review** in the dashboard navigation, or navigate to `/reviews`.

### Features

- **Correction cards** with searchable interface and status statistics (total, pending, approved, rejected)
- **Filters** — by task, source (AI vs human), confidence level
- **Inline editing** — edit root cause category, detail, note, solution, and solution note directly from the review page
- **Bulk actions** — select multiple corrections and approve, reject, or delete in bulk
- **Review comments** — add notes when approving or rejecting

### Approval Workflow

Each correction goes through a status lifecycle:

1. **Pending** — newly created, awaiting review
2. **Approved** — reviewed and accepted (feeds the correction bank for future AI analyses)
3. **Rejected** — reviewed and declined
4. **Superseded** — a newer approved correction replaced this one for the same item
5. **Withdrawn** — manually withdrawn

### Revision History

Corrections maintain an **append-only revision history** with:
- Numbered revisions with before/after states
- Actor source (AI or human)
- Linked review candidates
- Snapshots of input, expected output, output, and scores at correction time
- Review comments and statuses per revision

Only one active approved example exists per item — approving a new correction supersedes the previous one. Approving a stale correction ID promotes the active candidate for that run item.

### Syncing

Editing a correction from the reviews page syncs the corresponding run item metadata, so review, run, and compare views stay consistent. Run payloads expose per-item review correction status for inline rendering.

---

## Run Workflow & Statuses

Runs go through a lifecycle of statuses:

| Status | Description |
|--------|-------------|
| **PENDING** | Run created, waiting to start |
| **RUNNING** | Evaluation in progress |
| **COMPLETED** | All items finished successfully |
| **FAILED** | Run encountered a fatal error |
| **STOPPED** | Run interrupted by user (Ctrl+C) — the SDK sends this instead of leaving runs stuck in RUNNING |
| **DRAFT** | Run completed but not submitted for approval |
| **SUBMITTED** | User submitted run for approval |
| **APPROVED** | Manager approved the run (visible to GM/VP) |
| **REJECTED** | Manager rejected the run |

Dashboard status filters, auto-refresh, polling, and badges treat PENDING as active and display STOPPED explicitly.

---

## Uploading & Submitting Runs

### From the SDK (Live Streaming — Recommended)

```bash
export QYM_API_KEY=your-api-key
qym run create --task-file my_task.py --task-function my_func \
  --dataset my-dataset --metrics exact_match
```

Results stream to the platform in real time. The SDK auto-detects git branch and commit for version tracking.

If your own application also needs live progress, use the SDK's `progress_callback` in the Python wrapper that launches the run. This is separate from platform ingestion: the platform still receives streamed events through `QYM_BASE_URL` and `QYM_API_KEY`, while your callback can update an internal job record, queue, websocket, or notebook cell.

If the SDK cannot submit runs because your platform uses an internal or self-signed HTTPS certificate, set `QYM_PLATFORM_CA_BUNDLE=/path/to/internal-ca.pem` wherever the SDK/CLI runs. For local development only, `QYM_PLATFORM_SSL_VERIFY=false` disables certificate verification.

```python
from qym import Evaluator, ProgressSnapshot

def on_progress(snapshot: ProgressSnapshot):
    update_internal_job(
        run_id=snapshot.run_id,
        event=snapshot.event,
        finished=snapshot.finished,
        total=snapshot.total_items,
        percent=snapshot.percent_complete,
        failed=snapshot.failed,
    )

Evaluator(
    task=my_task,
    dataset=my_dataset,
    metrics=["exact_match"],
    progress_callback=on_progress,
).run(show_tui=False)
```

### Upload a Saved Results File

```bash
qym submit --file results.csv --task my_task --dataset my-dataset
```

Or via the API:
```bash
curl -X POST http://<platform>/v1/runs:upload \
  -H "Authorization: Bearer $API_KEY" \
  -F "file=@results.csv" \
  -F "task=my_task" \
  -F "dataset=my-dataset"
```

**Note**: Uploaded files are parsed and ingested into the database. Raw uploaded files are NOT stored persistently.

---

## CLI Commands

The qym CLI uses noun-verb command groups. All commands support `--json` for structured output.

### Run Commands

```bash
qym run create   # Execute an evaluation run (replaces old `qym --task-file`)
qym run list     # List recent evaluation runs
qym run get      # Get detailed data for a specific run
qym run tasks    # List distinct task names from the platform
qym run failed   # Get only failed/error items from a run
qym run compare  # Compare multiple runs side-by-side
```

### Analysis Commands

```bash
qym analyze run      # Trigger AI root-cause analysis on a run's items
qym analyze summary  # Get aggregated root-cause analysis summary
```

### Other Commands

```bash
qym metric list   # List all available evaluation metrics
qym config show   # Show resolved platform configuration
qym config check  # Validate connectivity to the platform API
qym dashboard     # Open the platform dashboard in your browser
qym submit        # Upload a saved results file to the platform
```

### Legacy Compatibility

Old-style invocations like `qym --task-file ...` and `qym resume --run-file ...` are automatically rewritten to the new format.

---

## Admin Panel

Access at `/admin` (ADMIN role only). The platform README covers bootstrap, org structure, API keys, and admin settings. From the admin panel you can:
- User management
- Organization structure (Sector → Department → Team)
- Platform settings (visibility rules, hidden tasks)
- API key management

### Hidden Tasks

Operators can configure `hidden_tasks` in platform settings to hide specific tasks from run listings and task discovery — both the CLI (`qym run tasks`) and the dashboard respect this setting.
