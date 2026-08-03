# Architecture (qym platform)

## Components

- **SDK (`packages/sdk/qym/`)**: runs evaluations locally (TUI), streams events and/or uploads artifacts to the platform.
- **Platform (`packages/platform/qym_platform/`)**: FastAPI service + Postgres schema hosting:
  - project dashboard (`/projects/<project_slug>`)
  - project-scoped run, chart, model, dataset, review, and settings views
  - run detail UI (`/projects/<project_slug>/runs/<run_id>`)
  - ingestion APIs (`/v1/...`)

## Live streaming

The SDK uses a lightweight NDJSON event stream (RunEventV1):
- SDK creates a run via `POST /v1/runs`
- SDK streams events to `POST /v1/runs/{run_id}/events`
- Platform writes normalized state into DB and serves the live run UI from the same `/run/<run_id>` page

RunEventV1 schema is documented in `internal/RUN_EVENT_SCHEMA.md`.

## Repeat runs (samples=k)

`Evaluator(..., samples=k)` evaluates every dataset item k times as k
sequential passes inside ONE logical run (SDK: `qym/core/reducers.py` +
pass-aware checkpointing). Item events carry `pass_number`; a
`pass_completed` event fires at each pass barrier. The platform stores
per-pass scores in `run_item_pass_scores`, keeps the reduced mean in
`run_item_scores` (compatibility contract: one row per item/metric), and
serves per-pass slices (`/api/runs/{id}/passes`) plus on-demand group
metrics and the full accuracy-vs-k band (`/api/runs/{id}/group-metrics`).
The dashboard renders every repeat as one ordinary `×k` row with expandable
pass rows and group metrics. It does not infer run groups from timestamps.
Whole repeats contribute `k` execution units to comparisons; a completed pass
can also be selected directly as one execution through a `::passN` reference.
Run detail stores and renders each pass's output, score, label, metric metadata,
error, and judge explanation; identical outputs fold into variant columns.

