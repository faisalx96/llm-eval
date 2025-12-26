# API Reference (MVP)

## Auth

- **UI requests**: set `X-User-Email` (or `X-Email`)
- **Programmatic ingestion**: `Authorization: Bearer <api_key>`

## UI

- `GET /` dashboard
- `GET /run/<run_id>` run details UI (loads data from `/api/runs/<run_id>`)

## User / admin

- `GET /v1/me`
- `POST /v1/me/api-keys`
- `POST /v1/admin/users` (VP only)

## Runs

- `POST /v1/runs` create a run (returns `run_id`, `live_url`)
- `POST /v1/runs/<run_id>/events` NDJSON stream (RunEventV1)
- `POST /v1/runs/<run_id>/submit`
- `POST /v1/runs/<run_id>/approve`
- `POST /v1/runs/<run_id>/reject`
- `POST /v1/runs:upload` multipart upload (`file`, `task`, `dataset`, optional `model`)

## Legacy UI compatibility (current dashboard JS)

- `GET /api/runs` returns `{"tasks": {...}}`
- `GET /api/runs/<run_id>` returns `{run, snapshot}`


