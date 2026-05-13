# Product Eval API Integration Guide

This API lets an external application trigger a predefined qym evaluation over HTTP, then poll for progress and qym run links. The external app does not need Python or the qym SDK.

The platform still uses the qym SDK internally. The SDK creates the platform run, writes run items and scores, and streams normal platform events. The Product Eval API only starts the SDK run, tracks the temporary background job, and exposes a compact polling contract.

For the `insightor` preset, the API mirrors the existing script behavior: it starts three qym runs through `Evaluator.run_parallel(..., max_parallel_runs=1)`. The platform compare view is responsible for showing Pass@3, Avg@3, consistency, reliability, and latency metrics across those runs.

## Authentication

Use a project API key in the `Authorization` header:

```http
Authorization: Bearer <QYM_API_KEY>
```

Required scopes:

- Submit eval: `runs:write`
- Poll job/run: `runs:read`

The API key must be bound to the same project where the run should be created.

## Response Envelope

All Product Eval API success responses use:

```json
{
  "ok": true,
  "data": {},
  "error": null
}
```

Product Eval API request/setup errors use:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "invalid_request",
    "message": "Unknown product eval preset: example"
  }
}
```

Shared auth errors may still use the platform's normal FastAPI error shape.

## HTTP Status Codes

- `200 OK`: Poll succeeded.
- `202 Accepted`: Submit succeeded and the eval job was accepted.
- `400 Bad Request`: Invalid request, such as unknown preset or unsupported config key.
- `401 Unauthorized`: Missing or invalid bearer API key.
- `403 Forbidden`: API key lacks scope or project access.
- `404 Not Found`: Job or run does not exist or is not visible to the caller.
- `500 Internal Server Error`: Server-side preset setup problem.

Clients should branch on HTTP status first. For `2xx`, read `data`. For non-`2xx`, read `error` when present.

## Submit An Eval

```http
POST /v1/product-evals
Content-Type: application/json
Authorization: Bearer <QYM_API_KEY>
```

Request body:

```json
{
  "preset": "insightor",
  "dataset": "customer-langfuse-dataset",
  "run_name": "product-eval-smoke-001",
  "model": "optional-model",
  "metadata": {
    "source": "external-app",
    "customer_id": "customer-123"
  },
  "config": {
    "max_concurrency": 2,
    "timeout": 900,
    "max_retries": 1,
    "metric_timeout": 60
  }
}
```

Fields:

- `preset`: Required preset name. Use `test` for smoke tests or `insightor` for the real Insightor eval.
- `dataset`: Langfuse dataset name. Required for `insightor`.
- `run_name`: Optional display/run name. If omitted, the preset default is used.
- `model`: Optional model override. Some presets may ignore this.
- `metadata`: Optional caller metadata stored on the qym run.
- `config`: Optional qym runtime config overrides. Only safe keys are accepted.

Allowed `config` keys:

- `max_concurrency`
- `timeout`
- `max_retries`
- `metric_timeout`
- `max_metric_concurrency`

## Insightor Runtime Environment

The Docker image includes `/app/insightor_eval.py`, but secrets are still supplied by environment variables at runtime.

Required for `insightor`:

- `INSIGHTOR_URL`
- `REFRESH_TOKEN`
- `DATAIKU_API_KEY`
- `OPENAI_API_KEY`

Optional:

- `DATAIKU_URL` defaults to the configured Dataiku host.
- `OPENAI_BASE_URL` is used by the main judge client.
- `CONTEXT_JUDGE_API_KEY` overrides `OPENAI_API_KEY` for the context judge.
- `CONTEXT_JUDGE_BASE_URL` defaults to the configured AI gateway host.
- `MODEL`, `AGENT_VERSION`, `IMAGE_VERSION`, and `KB_VERSION` are used for run/model metadata when present.

Response:

```json
{
  "ok": true,
  "data": {
    "status": "RUNNING",
    "qym_run_id": "2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "qym_run_url": "https://qym.example.com/run/2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "qym_runs": [],
    "qym_compare_url": null,
    "poll_url": "/v1/product-evals/2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "created_at": "2026-05-13T11:17:03.655197Z",
    "updated_at": "2026-05-13T11:17:04.102901Z"
  },
  "error": null
}
```

Sometimes `qym_run_id` is temporarily `null` because the background SDK run has not created the platform run yet. In that case, use the returned job `poll_url`.

```json
{
  "ok": true,
  "data": {
    "status": "STARTING",
    "qym_run_id": null,
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "qym_run_url": null,
    "qym_runs": [],
    "qym_compare_url": null,
    "poll_url": "/v1/product-evals/jobs/7adcb65d-fdb9-4cfa-85d3-07979830b5bf",
    "created_at": "2026-05-13T11:17:03.655197Z",
    "updated_at": "2026-05-13T11:17:03.655197Z"
  },
  "error": null
}
```

## Poll A Job

Use this before the qym platform run exists, and for multi-run presets such as `insightor`.

```http
GET /v1/product-evals/jobs/{opaque_startup_id}
Authorization: Bearer <QYM_API_KEY>
```

Response:

```json
{
  "ok": true,
  "data": {
    "status": "RUNNING",
    "qym_run_id": "2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "qym_run_url": "https://qym.example.com/run/2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "qym_runs": [],
    "qym_compare_url": null,
    "poll_url": "/v1/product-evals/2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "created_at": "2026-05-13T11:17:03.655197Z",
    "updated_at": "2026-05-13T11:17:04.102901Z"
  },
  "error": null
}
```

For single-run presets, once `qym_run_id` is present, switch to polling `/v1/product-evals/{qym_run_id}`. For `insightor`, keep polling the returned job `poll_url` and use `qym_compare_url` to open the three-run compare view.

Insightor job response:

```json
{
  "ok": true,
  "data": {
    "status": "RUNNING",
    "qym_run_id": "run-attempt-1",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "qym_run_url": "https://qym.example.com/run/run-attempt-1",
    "qym_runs": [
      {
        "attempt": 1,
        "status": "COMPLETED",
        "qym_run_id": "run-attempt-1",
        "qym_run_url": "https://qym.example.com/run/run-attempt-1"
      },
      {
        "attempt": 2,
        "status": "RUNNING",
        "qym_run_id": "run-attempt-2",
        "qym_run_url": "https://qym.example.com/run/run-attempt-2"
      },
      {
        "attempt": 3,
        "status": "STARTING",
        "qym_run_id": null,
        "qym_run_url": null
      }
    ],
    "qym_compare_url": "https://qym.example.com/compare?runs=run-attempt-1&runs=run-attempt-2",
    "poll_url": "/v1/product-evals/jobs/7adcb65d-fdb9-4cfa-85d3-07979830b5bf",
    "created_at": "2026-05-13T11:17:03.655197Z",
    "updated_at": "2026-05-13T11:17:04.102901Z"
  },
  "error": null
}
```

If the background job fails before creating a platform run, the job response contains:

```json
{
  "ok": true,
  "data": {
    "status": "FAILED",
    "qym_run_id": null,
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "qym_run_url": null,
    "qym_runs": [],
    "qym_compare_url": null,
    "error": "RuntimeError: sanitized failure message",
    "created_at": "2026-05-13T11:17:03.655197Z",
    "updated_at": "2026-05-13T11:17:04.102901Z",
    "poll_url": "/v1/product-evals/jobs/7adcb65d-fdb9-4cfa-85d3-07979830b5bf"
  },
  "error": null
}
```

## Poll A Run

This is the normal progress endpoint after a platform run exists.

```http
GET /v1/product-evals/{qym_run_id}
Authorization: Bearer <QYM_API_KEY>
```

Default response is aggregate-only. It does not include per-item rows.

```json
{
  "ok": true,
  "data": {
    "qym_run_id": "2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "qym_run_url": "https://qym.example.com/run/2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "external_run_id": "product-eval-smoke-001",
    "status": "RUNNING",
    "task": "test_task",
    "dataset": "product-eval-test-dataset",
    "model": "test-model",
    "metrics": ["exact_match"],
    "total": 50,
    "completed": 12,
    "failed": 0,
    "in_progress": 2,
    "pending": 36,
    "metric_stats": {
      "exact_match": {
        "count": 12,
        "mean": 1.0,
        "min": 1.0,
        "max": 1.0
      }
    },
    "latency_ms": {
      "count": 12,
      "mean": 5003.4,
      "min": 4998.1,
      "max": 5012.8
    },
    "started_at": "2026-05-13T11:20:00Z",
    "ended_at": null,
    "created_at": "2026-05-13T11:20:00Z",
    "metadata": {
      "source": "external-app",
      "customer_id": "customer-123",
      "total_items": 50
    },
    "config": {
      "run_name": "product-eval-smoke-001"
    }
  },
  "error": null
}
```

Progress fields:

- `total`: Total expected items.
- `completed`: Items completed successfully.
- `failed`: Items with item-level errors.
- `in_progress`: Items created but not completed or failed.
- `pending`: Items not yet started.
- `metric_stats`: Per-metric aggregate stats over scored items.
- `latency_ms`: Aggregate item latency over items that have latency.

Caller-sent metadata remains at the top level inside `metadata`. Internal wrapper bookkeeping is not returned in the public polling payload.

## Optional Item Debugging

Per-item rows are intentionally omitted from normal polling. To debug item details:

```http
GET /v1/product-evals/{qym_run_id}?include_items=true
Authorization: Bearer <QYM_API_KEY>
```

This adds `data.items`:

```json
{
  "items": [
    {
      "index": 0,
      "item_id": "test-1",
      "status": "completed",
      "input": {"text": "item-001", "delay_seconds": 5.0},
      "expected": "ITEM-001",
      "output": "ITEM-001",
      "error": null,
      "latency_ms": 5002.3,
      "retry_count": 0,
      "trace_id": "trace-id",
      "trace_url": "https://...",
      "metadata": {"case": "uppercase", "index": 1},
      "scores": {"exact_match": 1.0},
      "metric_metadata": {
        "exact_match": {
          "expected": "ITEM-001",
          "output": "ITEM-001"
        }
      }
    }
  ]
}
```

Do not use `include_items=true` for high-frequency production polling.

## Curl Example

Submit:

```bash
curl -X POST "$QYM_PLATFORM_URL/v1/product-evals" \
  -H "Authorization: Bearer $QYM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "preset": "test",
    "run_name": "product-eval-smoke-001",
    "metadata": {
      "source": "curl"
    }
  }'
```

Poll the returned `data.poll_url`:

```bash
curl "$QYM_PLATFORM_URL/v1/product-evals/<qym_run_id>" \
  -H "Authorization: Bearer $QYM_API_KEY"
```

## Recommended Client Flow

1. Submit `POST /v1/product-evals`.
2. Read `data.poll_url`.
3. Poll that URL every 2-5 seconds.
4. If polling a job and `data.qym_run_id` appears, switch to `data.poll_url`.
5. Stop when `data.status` is terminal, usually `COMPLETED` or `FAILED`.
6. For routine progress, do not request `include_items=true`.

## Current Test Preset

The built-in `test` preset is intended for integration smoke tests:

- 50 in-memory items.
- 5 seconds per item.
- Default concurrency is 2.
- Expected runtime is roughly 125 seconds.
- Uses deterministic uppercase task and exact-match metric.
- Requires no external files, model provider, SQL database, or Python SDK in the caller.
