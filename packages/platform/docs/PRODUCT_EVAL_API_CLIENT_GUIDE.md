# Product Eval API Client Guide

This guide is for external applications that need to run Qym product evaluations over HTTP. You do not need Python and you do not need the Qym SDK.

The API gives you one stable `eval_id`; use that same ID to check status or stop the eval. Qym run IDs are returned only so you can open individual Qym run pages.

Supported presets:

| Preset | Purpose | Runs created |
| --- | --- | --- |
| `insightor` | Real Insightor evaluation. | Three Qym runs. |
| `test` | Client integration smoke test. No Insightor credentials required. | Three Qym runs. |

## Table Of Contents

| Section | What it covers |
| --- | --- |
| [Base URL](#base-url) | Platform URL format. |
| [Authentication](#authentication) | Bearer token and required scopes. |
| [Start An Eval](#start-an-eval) | Submit endpoint, required inputs, optional inputs, and curl example. |
| [Testing Preset](#testing-preset) | Self-contained smoke test preset for client integration. |
| [Submit Response](#submit-response) | `202 Accepted`, `eval_id`, and capacity behavior. |
| [Poll Eval Status](#poll-eval-status) | Status endpoint and running/completed/failed response examples. |
| [Stop An Eval](#stop-an-eval) | Stop endpoint and stop behavior. |
| [Returned Fields](#returned-fields) | Response field reference. |
| [Error Responses](#error-responses) | Validation, capacity, and HTTP status errors. |
| [Security Notes](#security-notes) | Secret handling and stored values. |
| [Recommended Client Flow](#recommended-client-flow) | End-to-end client sequence. |
| [Minimal JavaScript Example](#minimal-javascript-example) | Fetch-based implementation example. |

## Base URL

Your Qym platform team will give you the platform base URL.

```text
https://qym.example.com
```

All endpoint paths below are relative to that base URL.

## Authentication

Send your Qym project API key as a bearer token:

```http
Authorization: Bearer <QYM_API_KEY>
```

Required scopes:

| Action | Required scope |
| --- | --- |
| Start an eval | `runs:write` |
| Poll an eval | `runs:read` |
| Stop an eval | `runs:write` |

## Start An Eval

```http
POST /v1/product-evals
Content-Type: application/json
Authorization: Bearer <QYM_API_KEY>
```

Required inputs:

| Field | Type | Description |
| --- | --- | --- |
| `preset` | string | Use `"insightor"` for the real eval or `"test"` for the smoke-test preset. |

Additional required inputs for `preset: "insightor"`:

| Field | Type | Description |
| --- | --- | --- |
| `insightor_url` | string | Insightor base URL that Qym should call. |
| `refresh_token` | string | Refresh token used by the eval to authenticate to Insightor. Treat this as a secret. |

Optional inputs:

| Field | Type | Description |
| --- | --- | --- |
| `dataset` | string | Langfuse dataset name. Defaults to `"playground_set_v2"` if omitted. |
| `run_name` | string | Display name for the Qym runs. |
| `task_name` | string | Optional task display label. |
| `model` | string | Optional model label or model override. |
| `metadata` | object | Optional caller metadata stored on Qym runs. Do not put secrets here. |
| `agent_version` | string | Optional Insightor agent version label. |
| `image_version` | string | Optional Insightor image version label. |
| `kb_version` | string | Optional Insightor knowledge-base version label. |

Runtime settings such as concurrency, timeout, retries, and parallel attempts are controlled by the Qym platform deployment. Clients cannot override them in the request. The recommended platform-managed defaults are `max_concurrency=10` and `max_parallel_runs=1`.

If the request includes `config` or any unsupported field, the API returns `400 Bad Request` and no eval is created.

Example:

```bash
curl -X POST "$QYM_PLATFORM_URL/v1/product-evals" \
  -H "Authorization: Bearer $QYM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "preset": "insightor",
    "dataset": "customer-langfuse-dataset",
    "insightor_url": "https://insightor.example.com",
    "refresh_token": "'"$INSIGHTOR_REFRESH_TOKEN"'",
    "agent_version": "agent-v1",
    "image_version": "image-v1",
    "kb_version": "kb-v1",
    "run_name": "insightor-api-smoke-001",
    "metadata": {
      "source": "external-app",
      "request_id": "req-123"
    }
  }'
```

## Testing Preset

Use `preset: "test"` to verify your API key, request formatting, polling loop, stop behavior, and Qym UI links without calling Insightor.

The test preset:

| Property | Value |
| --- | --- |
| Required request fields | `preset` only |
| Insightor credentials | Not required |
| Dataset | Built-in test dataset; do not send `dataset` |
| Items | 50 |
| Item behavior | Each item sleeps for about 5 seconds, then returns a deterministic result |
| Metric | `exact_match` |
| Runs created | 3 |
| Per-run concurrency | 10 items |
| Compare URL | Returned after at least two test runs are created |
| `group_analysis` | Returned after all three test runs complete, using the same pass@3-style shape as `insightor` |

Example:

```bash
curl -X POST "$QYM_PLATFORM_URL/v1/product-evals" \
  -H "Authorization: Bearer $QYM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "preset": "test",
    "run_name": "client-api-smoke-001",
    "metadata": {
      "source": "external-app",
      "purpose": "connectivity-test"
    }
  }'
```

If you send `dataset` with `preset: "test"`, the API returns `400 Bad Request`. The test preset is intentionally self-contained.

## Submit Response

The submit endpoint returns `202 Accepted` when the eval is accepted.

```json
{
  "ok": true,
  "data": {
    "eval_id": "eval_3b8df7a5e0f74cf8988ab4b3ad2d7f40",
    "status": "STARTING",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "runs": [],
    "qym_compare_url": null,
    "group_analysis": null,
    "created_at": "2026-05-13T12:05:34.482720Z",
    "updated_at": "2026-05-13T12:05:34.482720Z"
  },
  "error": null
}
```

Save `data.eval_id`. You will use it for polling and stopping.

The API does not queue requests when all eval worker slots are busy. If capacity is full, the submit request returns `429 Too Many Requests` and no eval is started. Retry after the number of seconds in the `Retry-After` response header.

## Poll Eval Status

```http
GET /v1/product-evals/{eval_id}
Authorization: Bearer <QYM_API_KEY>
```

Example:

```bash
curl "$QYM_PLATFORM_URL/v1/product-evals/eval_3b8df7a5e0f74cf8988ab4b3ad2d7f40" \
  -H "Authorization: Bearer $QYM_API_KEY"
```

Recommended polling interval: every 2 to 5 seconds.

### Running Response

```json
{
  "ok": true,
  "data": {
    "eval_id": "eval_3b8df7a5e0f74cf8988ab4b3ad2d7f40",
    "status": "RUNNING",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "runs": [
      {
        "attempt": 1,
        "status": "COMPLETED",
        "qym_run_id": "run-attempt-1",
        "qym_run_url": "https://qym.example.com/run/run-attempt-1",
        "task": "insightor_api",
        "dataset": "customer-langfuse-dataset",
        "model": "gpt-4.1",
        "summary": {
          "total": 100,
          "completed": 100,
          "failed": 0,
          "in_progress": 0,
          "pending": 0,
          "metrics": ["accuracy"],
          "metric_stats": {
            "accuracy": {
              "count": 100,
              "mean": 0.84,
              "min": 0.0,
              "max": 1.0
            }
          },
          "latency_ms": {
            "count": 100,
            "mean": 1234.5,
            "min": 650.0,
            "max": 4210.0
          },
          "started_at": "2026-05-13T12:05:35Z",
          "ended_at": "2026-05-13T12:08:10Z"
        }
      },
      {
        "attempt": 2,
        "status": "RUNNING",
        "qym_run_id": "run-attempt-2",
        "qym_run_url": "https://qym.example.com/run/run-attempt-2",
        "task": "insightor_api",
        "dataset": "customer-langfuse-dataset",
        "model": "gpt-4.1",
        "summary": {
          "total": 100,
          "completed": 42,
          "failed": 1,
          "in_progress": 2,
          "pending": 55,
          "metrics": ["accuracy"],
          "metric_stats": {
            "accuracy": {
              "count": 42,
              "mean": 0.81,
              "min": 0.0,
              "max": 1.0
            }
          },
          "latency_ms": {
            "count": 43,
            "mean": 1440.2,
            "min": 700.0,
            "max": 5100.0
          },
          "started_at": "2026-05-13T12:08:12Z",
          "ended_at": null
        }
      },
      {
        "attempt": 3,
        "status": "PENDING",
        "qym_run_id": null,
        "qym_run_url": null,
        "task": null,
        "dataset": null,
        "model": null,
        "summary": null
      }
    ],
    "qym_compare_url": "https://qym.example.com/compare?runs=run-attempt-1&runs=run-attempt-2",
    "group_analysis": null,
    "created_at": "2026-05-13T12:05:34.482720Z",
    "updated_at": "2026-05-13T12:09:15.112119Z"
  },
  "error": null
}
```

### Completed Response

The `runs` array below is shortened to one attempt for readability. Completed `insightor` and `test` evals normally return three completed attempt rows.

```json
{
  "ok": true,
  "data": {
    "eval_id": "eval_3b8df7a5e0f74cf8988ab4b3ad2d7f40",
    "status": "COMPLETED",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "runs": [
      {
        "attempt": 1,
        "status": "COMPLETED",
        "qym_run_id": "run-attempt-1",
        "qym_run_url": "https://qym.example.com/run/run-attempt-1",
        "task": "insightor_api",
        "dataset": "customer-langfuse-dataset",
        "model": "gpt-4.1",
        "summary": {
          "total": 100,
          "completed": 100,
          "failed": 0,
          "in_progress": 0,
          "pending": 0,
          "metrics": ["accuracy"],
          "metric_stats": {},
          "latency_ms": {},
          "started_at": "2026-05-13T12:05:35Z",
          "ended_at": "2026-05-13T12:08:10Z"
        }
      }
    ],
    "qym_compare_url": "https://qym.example.com/compare?runs=run-attempt-1&runs=run-attempt-2&runs=run-attempt-3",
    "group_analysis": {
      "metric": "accuracy",
      "threshold": 0.8,
      "k": 3,
      "total_items": 100,
      "total_score_count": 300,
      "failed_count": 1,
      "pass_at_3": 0.92,
      "avg_at_3": 0.84,
      "consistency": 0.78,
      "reliability": 0.88,
      "avg_latency_ms": 1234.5
    },
    "created_at": "2026-05-13T12:05:34.482720Z",
    "updated_at": "2026-05-13T12:16:48.112119Z"
  },
  "error": null
}
```

When an eval has `status: "COMPLETED"`, use `data.group_analysis` for the final grouped metrics and `data.qym_compare_url` as the main Qym UI result link. For `insightor`, the grouped metric is `accuracy`; for `test`, the grouped metric is `exact_match`.

### Failed Response

If the eval fails, polling still returns `200 OK` because the status request succeeded. The failure is represented in `data.status` and `data.error`.

```json
{
  "ok": true,
  "data": {
    "eval_id": "eval_3b8df7a5e0f74cf8988ab4b3ad2d7f40",
    "status": "FAILED",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "runs": [],
    "qym_compare_url": null,
    "group_analysis": null,
    "created_at": "2026-05-13T12:05:34.482720Z",
    "updated_at": "2026-05-13T12:05:35.112119Z",
    "error": "RuntimeError: sanitized failure message"
  },
  "error": null
}
```

Treat `COMPLETED`, `FAILED`, and `STOPPED` as terminal statuses.

## Stop An Eval

```http
POST /v1/product-evals/{eval_id}/stop
Authorization: Bearer <QYM_API_KEY>
```

Example:

```bash
curl -X POST "$QYM_PLATFORM_URL/v1/product-evals/eval_3b8df7a5e0f74cf8988ab4b3ad2d7f40/stop" \
  -H "Authorization: Bearer $QYM_API_KEY"
```

The stop response uses the standard response envelope. `data.status` becomes `STOPPED`, and `data.stopped_qym_runs` tells you how many already-created Qym runs were marked stopped.

Stopping is best-effort for the in-process worker: the API immediately stops the eval state and marks created Qym runs as `STOPPED`. Attempts that have not started yet will not be launched. If a Python task call is already blocking, it may finish that call before the worker thread exits, but late SDK events will not reopen explicitly stopped runs.

## Returned Fields

| Field | Description |
| --- | --- |
| `eval_id` | Stable ID for this eval. Use it for polling and stopping. |
| `status` | Eval status: `STARTING`, `RUNNING`, `COMPLETED`, `FAILED`, or `STOPPED`. |
| `qym_project_id` | Qym project ID associated with your API key. Usually only needed for support/debugging. |
| `runs` | Qym runs created for the eval. `insightor` and `test` usually have three rows. |
| `runs[].attempt` | Attempt number, starting at `1`. |
| `runs[].status` | Attempt status: `PENDING`, `STARTING`, `RUNNING`, `COMPLETED`, `FAILED`, or `STOPPED`. `PENDING` means the attempt is planned but has not started yet. |
| `runs[].qym_run_id` | Qym run ID for that attempt, or `null` until created. |
| `runs[].qym_run_url` | URL for that attempt's Qym run, or `null` until created. |
| `runs[].task` | Qym task name for the attempt, or `null` until the Qym run exists. |
| `runs[].dataset` | Langfuse dataset name for the attempt, or `null` until the Qym run exists. |
| `runs[].model` | Model label for the attempt, or `null` until the Qym run exists. |
| `runs[].summary` | Aggregate progress and score summary for the attempt, or `null` until the Qym run exists. |
| `runs[].summary.total` | Total dataset items expected for that attempt. |
| `runs[].summary.completed` | Number of completed items. |
| `runs[].summary.failed` | Number of errored items. |
| `runs[].summary.in_progress` | Number of items currently in progress. |
| `runs[].summary.pending` | Number of items not started yet. |
| `runs[].summary.metrics` | Metrics tracked for the run. For `insightor` this includes `accuracy`; for `test` this includes `exact_match`. |
| `runs[].summary.metric_stats` | Per-metric count, mean, min, and max for numeric scores. |
| `runs[].summary.latency_ms` | Count, mean, min, and max item latency in milliseconds. |
| `qym_compare_url` | Qym compare URL for created attempts. On completion, this is the main UI result link. |
| `group_analysis` | Final pass@3, avg@3, consistency, reliability, and average latency metrics. `null` until all three runs complete. |
| `created_at` | UTC timestamp when the eval was accepted. |
| `updated_at` | UTC timestamp when the eval last changed. |
| `error` | Present only when `status` is `FAILED`. |

## Error Responses

Validation errors return `400 Bad Request`. No eval is created when validation fails.

Missing required input:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "invalid_request",
    "message": "insightor_url, refresh_token required for preset 'insightor'"
  }
}
```

Unsupported `config`:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "invalid_request",
    "message": "config is not accepted on this endpoint. Product eval runtime settings are controlled by QYM_PRODUCT_EVAL_* environment variables."
  }
}
```

Dataset sent with the test preset:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "invalid_request",
    "message": "dataset is not accepted for preset 'test'; omit it to use the built-in test dataset"
  }
}
```

Capacity full:

```http
429 Too Many Requests
Retry-After: 30
```

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "queue_full",
    "message": "Too many product eval jobs are already running. Try again later."
  }
}
```

Common HTTP statuses:

| Status | Meaning |
| --- | --- |
| `400 Bad Request` | Missing required input, unknown preset, empty `dataset`, unsupported field, or a request body containing `config`. |
| `401 Unauthorized` | Missing or invalid bearer token. |
| `403 Forbidden` | API key does not have the required scope or project access. |
| `404 Not Found` | `eval_id` does not exist or is not visible to the caller. |
| `429 Too Many Requests` | All eval worker slots are busy. Wait and retry after the `Retry-After` header. |
| `500 Internal Server Error` | Server-side preset setup problem. |

## Security Notes

- Use HTTPS.
- Treat `QYM_API_KEY` and `refresh_token` as secrets.
- Do not send secrets in `metadata`.
- `refresh_token` is not returned in API responses.
- Store `eval_id` if you need to poll later.
- Store `qym_compare_url` if you want users or operators to open the final Qym result later.

## Recommended Client Flow

1. Submit `POST /v1/product-evals`.
2. Confirm the HTTP status is `202`.
3. Save `data.eval_id`.
4. Poll `GET /v1/product-evals/{eval_id}` every 30 to 60 seconds.
5. Stop polling when `data.status` is `COMPLETED`, `FAILED`, or `STOPPED`.
6. On `COMPLETED`, read `data.group_analysis` and open `data.qym_compare_url` for the Qym UI.
7. On `FAILED`, show or log `data.error`.

## Minimal JavaScript Example

```js
async function runInsightorEval() {
  const baseUrl = process.env.QYM_PLATFORM_URL;
  const apiKey = process.env.QYM_API_KEY;

  const submitRes = await fetch(`${baseUrl}/v1/product-evals`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      preset: "insightor",
      insightor_url: "https://insightor.example.com",
      refresh_token: process.env.INSIGHTOR_REFRESH_TOKEN,
      dataset: "customer-langfuse-dataset",
      run_name: "insightor-api-smoke-001",
      metadata: { source: "external-app" },
    }),
  });

  const submitBody = await submitRes.json();
  if (!submitRes.ok) {
    throw new Error(submitBody.error?.message || "Failed to start Insightor eval");
  }

  const evalId = submitBody.data.eval_id;

  while (true) {
    await new Promise((resolve) => setTimeout(resolve, 3000));

    const statusRes = await fetch(`${baseUrl}/v1/product-evals/${evalId}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    const statusBody = await statusRes.json();
    if (!statusRes.ok) {
      throw new Error(statusBody.error?.message || "Failed to poll Insightor eval");
    }

    const data = statusBody.data;
    if (data.status === "COMPLETED") {
      return {
        qymCompareUrl: data.qym_compare_url,
        groupAnalysis: data.group_analysis,
        runs: data.runs,
      };
    }

    if (data.status === "FAILED" || data.status === "STOPPED") {
      throw new Error(data.error || `Insightor eval ${data.status.toLowerCase()}`);
    }
  }
}
```
