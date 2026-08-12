# qym Platform User Guide

The qym platform stores evaluation runs, datasets, traces, reviews, and analysis in a shared, project-scoped workspace. This guide describes the current web application. SDK usage is covered in the in-app **Docs** portal.

## Contents

1. [Projects and navigation](#projects-and-navigation)
2. [Access and roles](#access-and-roles)
3. [Project settings](#project-settings)
4. [Dashboard and runs](#dashboard-and-runs)
5. [Repeat runs](#repeat-runs)
6. [Run detail](#run-detail)
7. [Compare, charts, and models](#compare-charts-and-models)
8. [Datasets](#datasets)
9. [Analysis, reviews, and traces](#analysis-reviews-and-traces)
10. [Run review and deletion](#run-review-and-deletion)
11. [Connect the SDK and CLI](#connect-the-sdk-and-cli)
12. [Administration](#administration)

## Projects and navigation

The project is the platform's main isolation boundary. Runs, datasets, API keys, LLM connections, members, and review data belong to one project.

The global navigation contains **Projects** and **Docs**. After opening a project, the project navigation contains:

- **Dashboard** — project summary and recent activity.
- **Charts** — trends across runs.
- **Runs** — searchable run table and cohort selection.
- **Models** — model-level performance summaries.
- **Reviews** — root-cause correction review.
- **Datasets** — versioned test data.
- **Project Settings** — members, API keys, and LLM connections.

Admins additionally see **Admin** and **Deleted Runs**.

The legacy Sector → Department → Team hierarchy is no longer part of the platform.

## Access and roles

### Authentication modes

Operators choose one UI authentication mode with `QYM_AUTH_MODE`:

| Mode | Behavior |
|---|---|
| `none` | Local development. qym creates/reuses `dev@local` as an admin. |
| `proxy_headers` | Trusts `X-User-Email` or `X-Email` from an authentication proxy. |
| `oidc` | Uses configured Google and/or GitHub sign-in. |

Email/password sign-in can be enabled alongside any non-`none` mode. SAML and generic enterprise SSO are not implemented.

Session-based deployments require `QYM_AUTH_SESSION_SECRET`. Browser writes are protected by a same-origin check; configure the externally visible `QYM_BASE_URL` correctly when the app is behind a proxy.

### Roles

There are two role layers:

| Layer | Role | Access |
|---|---|---|
| Global | `MEMBER` | Access only to projects where the user is a member. |
| Global | `ADMIN` | Manage users and projects, access every project, restore deleted runs. |
| Project | `MEMBER` | View and modify project data, run evaluations, and review corrections. |
| Project | `MANAGER` | Member access plus member management and run approval/rejection. |

The platform prevents removal or demotion of a project's last manager.

## Project settings

Open **Project Settings** to manage:

### Members

Managers and global admins can add members and change project roles. Project access, not an organization tree, determines run and dataset visibility.

### API keys

Any project member can create a project-bound API key. The raw token is displayed once; store it in a secret manager or `.env` as `QYM_API_KEY`. qym stores only a PBKDF2 hash.

Keys display scopes for compatibility, but scopes are not currently enforced. A valid, non-revoked key has access to its project. Project membership and the key's project binding still apply.

The key owner, a project manager, or a global admin can revoke a key.

### LLM connections

Any project member can add, test, choose a default, or remove an OpenAI-compatible LLM connection. These connections power platform-side AI analysis. They are separate from SDK judge configuration (`QYM_JUDGE_*`).

Each connection stores a base URL, a model, and an encrypted API key; the UI only shows a masked last-four-character hint. The first connection becomes the project default, and a different connection can be chosen for an individual analysis run. Updating a connection without entering a new key preserves the stored key.

The default deployment blocks provider URLs that resolve to private or loopback addresses. Set `QYM_ALLOW_PRIVATE_LLM_BASE_URLS=true` only when the platform intentionally uses a trusted local provider.

## Dashboard and runs

The Runs page presents each evaluation as one logical row. It does not infer groups from timestamps.

Use the page to:

- Search and filter by status, task, dataset, model, version, or run name.
- Choose visible metric columns; the preference persists locally.
- Inspect live progress, owner, branch, commit, and status.
- Open a run for item-level detail.
- Submit, approve, reject, unapprove, unreject, or delete when your role and the run status allow it.

### Selecting a comparison cohort

Click **Select** (or press `x`) to reveal the checkbox column. Select runs or repeat passes, then open the comparison. **Clear** or `Escape` exits selection mode.

The comparison's atomic unit is an execution:

- An ordinary run contributes one execution.
- A whole repeat run with `samples=k` contributes `k` executions.
- A selected pass reference contributes one execution.

Selecting a whole repeat and one of its own passes at the same time is blocked, as is placing a whole run opposite one of its own passes. Different passes from the same repeat may be compared with each other.

## Repeat runs

Set `samples=k` to evaluate every dataset item `k` times inside one run. In the CLI, use `qym run create ... --samples k`.

The Runs page shows one row with a `×k` marker. Expanding it reveals pass rows and group metrics; no timestamp-based reconstruction is involved.

Repeat analysis includes:

- **Pass@k** — estimated chance that at least one of `k` executions passes.
- **Pass^k** — estimated chance that all `k` executions pass.
- **Average@k / Max@k** — average and best observed score behavior.
- **Consistency / Reliability** — stability and all-pass behavior across executions.
- Accuracy-vs-k curves, bootstrap uncertainty, noise bands, p-values, and comparison verdicts where enough observations exist.

`report_k` controls the reported subset size independently of the captured `samples`. For example, a run may collect ten passes while reporting estimators at `k=3`. These are subset estimators over stored passes; they do not rerun the task.

Completed passes are durable while a later pass is still streaming. Each stored pass also retains its metric label, metadata, error, and judge explanation.

## Run detail

The run page leads with **Overview**, followed by repeat analysis when applicable, metadata breakdowns, and items.

### Overview and filters

- Summary cards show scores, pass rates, latency, status, and run metadata.
- All metadata-category cards remain visible so changing a filter does not hide the other available categories.
- Metric chips cycle through **any → passed → failed**. Active metric conditions are combined with AND.
- Metadata and review filters narrow the same item list.

### Items and repeated outputs

Each item starts as a compact one-line header. Expand it to inspect input, expected output, outputs, trace access, metric values, and details.

For repeat runs:

- Pass outputs appear side by side.
- Identical outputs are folded into variant columns instead of being repeated.
- Output chips toggle the visible pass/variant columns.
- Per-pass metric detail, including judge explanations and errors, appears beside the relevant pass.

Inputs, outputs, expected values, and structured metric metadata render in readable formats and provide copy affordances. The page can also export a self-contained HTML snapshot for offline review.

## Compare, charts, and models

### Compare

Compare treats the selected executions as one cohort and keeps the selected sides explicit. It provides:

- Cohort score, latency, Pass@K, Pass^K, stability, and best-score summaries.
- Side-by-side item outputs with winner and score indicators.
- Search, metadata, review, and metric-range filters.
- Category and root-cause breakdowns, with a metric selector that scopes the breakdown and the solution Sankey view to one metric or all metrics.
- CSV export using the active filters and selected columns.

Do not interpret a repeat as “Pass@k of Pass@k.” Its passes enter the cohort as individual executions.

### Charts

Charts show performance trends by task and dataset with run, version, and model views. Filters include time, task, dataset, model, and git version.

### Models

Models summarizes model performance and run coverage within the current project. Use it to find a model, then drill into the runs that produced its measurements.

## Datasets

Datasets are project-scoped and versioned. The platform assigns immutable human-friendly version identifiers (`v1`, `v2`, …); `version_name` is an optional descriptive label.

### Lifecycle

- A **draft** version can be edited.
- A **published** version is immutable.
- Aliases such as `production` point to a chosen version.
- Cloning creates a new version with lineage back to its source.

The UI supports creation, CSV or JSONL upload, JSONL download, publishing, aliases, cloning, version comparison, lineage, search/filtering, item revisions, bulk item operations, and run history for an item. Dataset metadata can be updated without rewriting a published version's items.

Reference a platform dataset from the SDK by name, version, or alias after setting `QYM_BASE_URL` and `QYM_API_KEY`.

## Analysis, reviews, and traces

### AI root-cause analysis

Configure at least one provider under **Project Settings → LLM Connections**. Any OpenAI-compatible provider can be used; test the connection before selecting it in the analyzer. Open **Auto-analysis** from the project navigation, or use the run-specific analyzer on a run page.

To run an analysis:

1. Choose a run and one or more metrics. Each item/metric pair is analyzed independently, so one item can carry different diagnoses for different metrics.
2. Filter by outcome, score threshold, complexity, domain, root-cause values, explicit item IDs, or already-analyzed targets. With multiple metrics selected, an item limit retains every matching selected metric for each chosen item.
3. Preview the prompt or test up to three items without saving results.
4. Start the analysis and follow its streamed progress.

The analyzer proposes a **root cause category**, a reusable **root cause detail**, and an evidence-based **note**. AI-suggested values show a robot indicator with confidence; human-confirmed values show a checkmark.

The analyzer playground supports system-prompt editing, nested input/output/metric mappings, custom-variable interpolation, category/detail catalogs, additional instructions, field selection, prompt previews, and unsaved test analyses.

Project context strengthens the analysis:

- **Project description** — explain the business domain and correctness expectations.
- **Analysis rules** — manage versioned title/instruction pairs through a draft → published → `production` alias lifecycle. Rules support lineage, comparisons, cloning, and append-only generation from selected documents and approved correction examples.
- **Reference documents** — upload PDF, DOCX, text, Markdown, HTML, CSV, JSON, or YAML into a shared project library, then select the documents a run uses. Each upload is limited to 10 MB. The normal prompt-safe representation is 40,000 characters; an explicit full-content choice can retain up to 200,000 characters. A prompt can include at most eight selected documents and 80,000 reference characters, within a final 120,000-character safety budget.

Rule generation processes large sources in bounded patches, using separate 256,000-character document/example patches and a 320,000-character request budget. HTML scripts and styles are ignored, scanned PDFs require OCR, and PDF/DOCX extraction rejects unsafe expansion. Hard-cap truncation is reported.

The default prompt sends the selected metric result, an organized view of native trace spans, project context, active rules, and selected documents. Trace evidence is grouped into agent and evaluation sections, repeated chat messages are deduplicated, and credential-like fields are redacted. Approved correction snapshots can support rule generation but are not added to per-item prompts as few-shot examples. Saved analysis metadata records the resolved production rule-version ID for reproducibility.

The platform analysis route is `/api/runs/{run_id}/analyze`; the `qym analyze run` CLI command uses the same route.

### Reviews

Reviews are project-scoped. Members can edit corrections and participate in review; approval permissions follow the project and run rules. The review page supports search and filters, inline editing, bulk approval/rejection/deletion, and review comments.

Corrections keep append-only numbered revisions, before/after values, actor source, linked review candidates, captured input/output/score snapshots, and review status. A candidate can be pending, approved, rejected, superseded, or withdrawn. Only one active candidate exists per item/metric scope: approving a newer correction supersedes the prior active one, while rejecting or removing a correction retains its audit history. Editing a correction also synchronizes the corresponding run-item metadata.

Approved correction examples can provide evidence for future analysis-rule generation, but they are not inserted into per-item analyzer prompts.

### Traces

Open an item's trace to inspect its span tree, timings, model messages, tool input/output, token and cost metadata, errors, and raw attributes. Trace links can be shared with the run/item context intact.

## Run review and deletion

Common run statuses are:

| Status | Meaning |
|---|---|
| `PENDING` / `RUNNING` | Created or actively receiving evaluation events. |
| `COMPLETED` | Evaluation finished. |
| `FAILED` | A run-level failure ended the evaluation. |
| `STOPPED` | Interrupted, or marked abandoned after its lease timed out. |
| `DRAFT` | Review draft. |
| `SUBMITTED` | Awaiting a manager/admin decision. |
| `APPROVED` / `REJECTED` | Review decision recorded. |

The run owner can submit eligible completed, failed, or previously rejected work. Project managers and global admins can approve or reject submitted work; unapprove/unreject returns it to `COMPLETED`.

A running evaluation with no events beyond `QYM_RUN_STALE_TIMEOUT_SECONDS` is lazily marked `STOPPED` with reason `lease_timeout` when read. A later valid event reopens it, so transient client disconnects are recoverable.

Deleting a run is a soft delete with an audit record. Owners, project managers, and global admins can delete according to permission checks; only a global admin can restore it from **Deleted Runs**.

Deleting a project archives it when it already contains runs. An empty project can be physically deleted.

## Connect the SDK and CLI

Create a project API key, then configure the process that runs qym:

```bash
export QYM_BASE_URL=https://qym.example.com
export QYM_API_KEY=<project-api-key>
```

Run an evaluation:

```bash
qym run create \
  --task-file examples/example.py \
  --task-function my_task \
  --dataset my-dataset \
  --metrics exact_match,fuzzy_match \
  --samples 3
```

Platform streaming activates when the API key is available. Without it, the evaluation can still complete locally.

Useful read commands:

```bash
qym run list --json
qym run get <run_id> --json
qym run failed <run_id> --json
qym run compare <id1> <id2> --json
qym config check --json
```

Saved run uploads accept `.csv` and `.json`:

```bash
qym submit --file results.csv --task my_task --dataset my-dataset
```

Raw upload files are parsed into database rows and are not retained as uploaded artifacts.

## Administration

Global admins can manage users and projects, inspect deleted runs, and restore runs. There are no organization-tree or platform-wide personal-key screens.

For deployment, auth bootstrap, migrations, backups, health checks, and the complete environment reference, see [`packages/platform/README.md`](../README.md). The live OpenAPI schema is available at `/openapi.json`, interactive API docs at `/api-docs`, and health status at `/healthz`.
