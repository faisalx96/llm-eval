# Platform User Guide

The llm-eval platform is the deployed web app that stores runs centrally and hosts the live run dashboard.

## Access model (MVP)

MVP is designed for a trusted internal network:
- The platform identifies users via reverse-proxy headers:
  - `X-User-Email` (preferred) or `X-Email`
- First admin bootstrap:
  - Set `LLM_EVAL_ADMIN_BOOTSTRAP_TOKEN`
  - Send `X-Admin-Bootstrap: <token>` + `X-User-Email: you@company.com` on your first request

## Roles & visibility (MVP)

- **Employee**: sees own runs; can submit a draft run.
- **Manager**: sees all runs (subtree enforcement is enabled once org import/closure is populated); can approve/reject submitted runs.
- **GM/VP**: sees approved runs only.

## Using the dashboard

- Open `http://<platform>/` to view runs.
- Click a run ID to open the run details UI (`/run/<run_id>`).
- Use the **Status** filter to show `DRAFT/SUBMITTED/APPROVED/REJECTED/...`.

## Uploading an eval run

Use the API ingestion (recommended) or file upload:

### From the SDK (live streaming)
- Run your evaluation with `--platform-url` and `--platform-api-key` (or env vars):
  - `LLM_EVAL_PLATFORM_URL`
  - `LLM_EVAL_PLATFORM_API_KEY`

### Upload a saved results file
- Use `llm-eval submit` (CLI) or `POST /v1/runs:upload`.


