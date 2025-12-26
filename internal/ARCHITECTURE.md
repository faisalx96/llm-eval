# Architecture (llm-eval platform)

## Components

- **SDK (`llm_eval/`)**: runs evaluations locally (TUI), streams events and/or uploads artifacts to the platform.
- **Platform (`llm_eval_platform/`)**: FastAPI service + Postgres schema hosting:
  - historical dashboard (`/`)
  - run detail UI (`/run/<run_id>`)
  - ingestion APIs (`/v1/...`)

## Live streaming

The SDK uses a lightweight NDJSON event stream (RunEventV1):
- SDK creates a run via `POST /v1/runs`
- SDK streams events to `POST /v1/runs/{run_id}/events`
- Platform writes normalized state into DB and serves the live run UI from the same `/run/<run_id>` page

RunEventV1 schema is documented in `internal/RUN_EVENT_SCHEMA.md`.


