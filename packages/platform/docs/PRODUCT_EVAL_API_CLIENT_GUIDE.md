# Insightor Product Eval API Client Guide

This guide is for external applications that need to trigger the Insightor Qym evaluation over HTTP. You do not need Python and you do not need the Qym SDK.

The API starts an Insightor evaluation, creates Qym runs, and returns polling data plus Qym UI links. Insightor evaluations run as three attempts. Each attempt creates a normal Qym run, and the compare URL shows the cross-run metrics such as pass@3, avg@3, consistency, reliability, and average latency.

## Base URL

Your Qym platform team will give you the platform base URL.

Example:

```text
https://qym.example.com
```

All endpoint paths in this guide are relative to that base URL.

## Authentication

Send your Qym project API key as a bearer token:

```http
Authorization: Bearer <QYM_API_KEY>
```

Required scopes:

| Action | Required scope |
| --- | --- |
| Start an Insightor eval | `runs:write` |
| Poll Insightor eval progress | `runs:read` |

The API key must belong to the Qym project where the eval runs should be created.

## Start An Insightor Eval

```http
POST /v1/product-evals
Content-Type: application/json
Authorization: Bearer <QYM_API_KEY>
```

### Required Inputs

| Field | Type | Description |
| --- | --- | --- |
| `preset` | string | Must be `"insightor"`. If omitted, the API defaults to `"insightor"`, but clients should send it explicitly. |
| `insightor_url` | string | Insightor base URL that Qym should call during the eval. |
| `refresh_token` | string | Refresh token used by the eval to authenticate to Insightor. Treat this as a secret. |

### Optional Inputs

| Field | Type | Description |
| --- | --- | --- |
| `dataset` | string | Langfuse dataset name to evaluate. If omitted, defaults to `"playground_set_v2"`. Empty strings are invalid. |
| `run_name` | string | Display name for the three Qym runs. If omitted, Qym derives a name from the version fields when possible. |
| `model` | string | Optional model label or model override used by the Insightor preset. |
| `agent_version` | string | Optional Insightor agent version label. |
| `image_version` | string | Optional Insightor image version label. |
| `kb_version` | string | Optional Insightor knowledge-base version label. |
| `metadata` | object | Optional caller metadata stored on the Qym runs. Do not put secrets here. |
| `config` | object | Optional runtime config overrides. Only the keys listed below are accepted. |

If `config` is omitted, the Insightor eval uses these defaults:

```json
{
  "max_concurrency": 10,
  "timeout": 900,
  "max_retries": 0,
  "max_parallel_runs": 1
}
```

Recommended config for normal use is the default: `max_concurrency=10` and `max_parallel_runs=1`.

Allowed `config` keys and ranges:

| Key | Type | Description |
| --- | --- | --- |
| `max_concurrency` | integer | Item-level concurrency inside each Qym run. Default `10`; allowed range `1` to `20`. |
| `timeout` | number | Overall run timeout in seconds. Default `900`; allowed range `1` to `900`. |
| `max_retries` | integer | Retries for failed items. Default `0`; allowed range `0` to `2`. |
| `max_parallel_runs` | integer | Number of Insightor attempts to run at the same time. Default `1`; allowed range `1` to `3`. |

Unsupported `config` keys or out-of-range values return `400 Bad Request`. No eval is created when validation fails.

The effective concurrency budget must be at most `20`:

```text
max_concurrency * max_parallel_runs <= 20
```

Insightor uses a fixed `metric_timeout` of `300` seconds. Clients cannot override `metric_timeout` or `max_metric_concurrency`.

### Submit Example

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

If you want to use the default dataset, omit `dataset`. The default Insightor dataset is `playground_set_v2`.

## Submit Response

The submit endpoint returns `202 Accepted` when the eval is accepted.

The API does not queue requests when all Insightor eval worker slots are busy. If capacity is full, the submit request returns `429 Too Many Requests` and no eval is started. Retry after the number of seconds in the `Retry-After` response header.

Always read and poll `data.poll_url`. It is a relative URL, so prepend the Qym platform base URL.

Example response after the first Qym run has started:

```json
{
  "ok": true,
  "data": {
    "status": "RUNNING",
    "qym_run_id": "2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "qym_run_url": "https://qym.example.com/run/2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "qym_runs": [
      {
        "attempt": 1,
        "status": "RUNNING",
        "qym_run_id": "2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
        "qym_run_url": "https://qym.example.com/run/2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30"
      },
      {
        "attempt": 2,
        "status": "STARTING",
        "qym_run_id": null,
        "qym_run_url": null
      },
      {
        "attempt": 3,
        "status": "STARTING",
        "qym_run_id": null,
        "qym_run_url": null
      }
    ],
    "qym_compare_url": null,
    "poll_url": "/v1/product-evals/jobs/7adcb65d-fdb9-4cfa-85d3-07979830b5bf",
    "created_at": "2026-05-13T12:05:34.482720Z",
    "updated_at": "2026-05-13T12:05:35.112119Z"
  },
  "error": null
}
```

Sometimes the API accepts the request before the first Qym run exists. In that case, `qym_run_id`, `qym_run_url`, and `qym_runs` may be empty temporarily.

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
    "created_at": "2026-05-13T12:05:34.482720Z",
    "updated_at": "2026-05-13T12:05:34.482720Z"
  },
  "error": null
}
```

Do not parse or store the opaque ID inside `poll_url` as a business identifier. Store the full `poll_url` value and use it for polling.

## Poll Insightor Progress

Poll the returned `data.poll_url`.

```http
GET /v1/product-evals/jobs/{opaque_id}
Authorization: Bearer <QYM_API_KEY>
```

Example:

```bash
curl "$QYM_PLATFORM_URL/v1/product-evals/jobs/7adcb65d-fdb9-4cfa-85d3-07979830b5bf" \
  -H "Authorization: Bearer $QYM_API_KEY"
```

Recommended polling interval: every 2 to 5 seconds.

### Running Poll Response

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
    "created_at": "2026-05-13T12:05:34.482720Z",
    "updated_at": "2026-05-13T12:09:15.112119Z"
  },
  "error": null
}
```

### Completed Poll Response

```json
{
  "ok": true,
  "data": {
    "status": "COMPLETED",
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
        "status": "COMPLETED",
        "qym_run_id": "run-attempt-2",
        "qym_run_url": "https://qym.example.com/run/run-attempt-2"
      },
      {
        "attempt": 3,
        "status": "COMPLETED",
        "qym_run_id": "run-attempt-3",
        "qym_run_url": "https://qym.example.com/run/run-attempt-3"
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
    "poll_url": "/v1/product-evals/jobs/7adcb65d-fdb9-4cfa-85d3-07979830b5bf",
    "created_at": "2026-05-13T12:05:34.482720Z",
    "updated_at": "2026-05-13T12:16:48.112119Z"
  },
  "error": null
}
```

When `status` is `COMPLETED`, `group_analysis` contains the final Insightor summary metrics. Use `qym_compare_url` as the primary UI result link.

### Failed Poll Response

If the eval fails, the poll request still returns `200 OK` because polling succeeded. The failure is represented in `data.status` and `data.error`.

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
    "poll_url": "/v1/product-evals/jobs/7adcb65d-fdb9-4cfa-85d3-07979830b5bf",
    "created_at": "2026-05-13T12:05:34.482720Z",
    "updated_at": "2026-05-13T12:05:35.112119Z",
    "error": "RuntimeError: sanitized failure message"
  },
  "error": null
}
```

Treat `FAILED` as terminal.

## Returned Fields

| Field | Description |
| --- | --- |
| `status` | Current Insightor eval status. Stop polling on `COMPLETED` or `FAILED`. |
| `qym_run_id` | The first Qym platform run ID created for this Insightor eval. It may be `null` while starting. |
| `qym_project_id` | Qym project ID associated with your API key. Usually only needed for support/debugging. |
| `qym_run_url` | URL for the first Qym run. |
| `qym_runs` | The three Insightor attempts and their Qym run IDs/URLs. |
| `qym_runs[].attempt` | Attempt number, starting at `1`. |
| `qym_runs[].status` | Status of that attempt. |
| `qym_runs[].qym_run_id` | Qym run ID for that attempt, or `null` until created. |
| `qym_runs[].qym_run_url` | URL for that attempt's Qym run, or `null` until created. |
| `qym_compare_url` | Compare URL for created attempts. On completion, this is the main result URL for pass@3, avg@3, consistency, reliability, and average latency. |
| `group_analysis` | Final grouped metrics. Present only after `status` is `COMPLETED`. |
| `group_analysis.metric` | Metric used for the grouped summary. For Insightor this is `accuracy`. |
| `group_analysis.threshold` | Score threshold used to count a passing attempt. |
| `group_analysis.k` | Number of attempts included in the group. For Insightor this is `3`. |
| `group_analysis.total_items` | Number of dataset items included in grouped analysis. |
| `group_analysis.total_score_count` | Number of item scores included across all attempts. |
| `group_analysis.failed_count` | Number of failed scored attempts included in grouped analysis. |
| `group_analysis.pass_at_3` | Share of items where at least one of the three attempts passed. |
| `group_analysis.avg_at_3` | Average score across all item attempts. |
| `group_analysis.consistency` | Average pass/fail agreement across attempts. |
| `group_analysis.reliability` | Average pass rate on items where at least one attempt passed. |
| `group_analysis.avg_latency_ms` | Average item latency across attempts, in milliseconds. |
| `poll_url` | Relative URL to poll next. Always use this value instead of constructing your own URL. |
| `created_at` | UTC timestamp when the Insightor eval job was accepted. |
| `updated_at` | UTC timestamp when the Insightor eval job last changed. |
| `error` | Present only when `status` is `FAILED`. |

## Status Values

Top-level `data.status` values:

| Status | Meaning | Terminal |
| --- | --- | --- |
| `STARTING` | Request accepted, but no Qym run has been created yet. | No |
| `RUNNING` | One or more Insightor attempts are active. | No |
| `COMPLETED` | All Insightor attempts completed successfully. | Yes |
| `FAILED` | The Insightor eval failed. See `data.error`. | Yes |

Each row in `qym_runs` can have:

| Status | Meaning |
| --- | --- |
| `STARTING` | This attempt has not created a Qym run yet. |
| `RUNNING` | This attempt has an active Qym run. |
| `COMPLETED` | This attempt completed. |

## Optional Single-Run Aggregate Details

The normal Insightor flow should poll the job URL and use `qym_compare_url`.

If you need aggregate details for one specific Qym run, call:

```http
GET /v1/product-evals/{qym_run_id}
Authorization: Bearer <QYM_API_KEY>
```

Example response:

```json
{
  "ok": true,
  "data": {
    "qym_run_id": "run-attempt-1",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "qym_run_url": "https://qym.example.com/run/run-attempt-1",
    "external_run_id": "insightor-api-smoke-001",
    "status": "RUNNING",
    "task": "insightor_api",
    "dataset": "customer-langfuse-dataset",
    "model": "gpt-4.1",
    "metrics": ["accuracy"],
    "total": 100,
    "completed": 42,
    "failed": 1,
    "in_progress": 2,
    "pending": 55,
    "metric_stats": {
      "accuracy": {
        "count": 42,
        "mean": 0.81,
        "min": 0.0,
        "max": 1.0
      }
    },
    "latency_ms": {
      "count": 42,
      "mean": 1842.5,
      "min": 900.2,
      "max": 5200.9
    },
    "started_at": "2026-05-13T12:05:35Z",
    "ended_at": null,
    "created_at": "2026-05-13T12:05:34Z",
    "metadata": {
      "source": "external-app",
      "request_id": "req-123"
    },
    "config": {
      "max_concurrency": 10,
      "timeout": 900,
      "max_retries": 0,
      "max_parallel_runs": 1
    }
  },
  "error": null
}
```

This endpoint is aggregate-only by default. For debugging only, add `?include_items=true` to include item rows. Do not use `include_items=true` for frequent production polling.

## Recommended Client Flow

1. Submit `POST /v1/product-evals` with `preset: "insightor"`.
2. Confirm the HTTP status is `202`.
3. Save `data.poll_url`.
4. Poll `data.poll_url` every 2 to 5 seconds with the same bearer token.
5. Stop when `data.status` is `COMPLETED` or `FAILED`.
6. On `COMPLETED`, read `data.group_analysis` and use `data.qym_compare_url` as the main result URL.
7. On `FAILED`, show or log `data.error`.

## Minimal JavaScript Example

```js
async function startInsightorEval() {
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
      dataset: "customer-langfuse-dataset",
      insightor_url: "https://insightor.example.com",
      refresh_token: process.env.INSIGHTOR_REFRESH_TOKEN,
      agent_version: "agent-v1",
      image_version: "image-v1",
      kb_version: "kb-v1",
      run_name: "insightor-api-smoke-001",
      metadata: { source: "external-app" },
    }),
  });

  const submitBody = await submitRes.json();
  if (!submitRes.ok) {
    throw new Error(submitBody.error?.message || "Failed to start Insightor eval");
  }

  let pollUrl = submitBody.data.poll_url;

  while (true) {
    await new Promise((resolve) => setTimeout(resolve, 3000));

    const pollRes = await fetch(`${baseUrl}${pollUrl}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    const pollBody = await pollRes.json();
    if (!pollRes.ok) {
      throw new Error(pollBody.error?.message || "Failed to poll Insightor eval");
    }

    const data = pollBody.data;
    pollUrl = data.poll_url;

    if (data.status === "COMPLETED") {
      return {
        qymCompareUrl: data.qym_compare_url,
        groupAnalysis: data.group_analysis,
        qymRuns: data.qym_runs,
      };
    }

    if (data.status === "FAILED") {
      throw new Error(data.error || "Insightor eval failed");
    }
  }
}
```

## Error Responses

### Validation Error Responses

Validation errors return `400 Bad Request`. No eval is created when validation fails.

Missing required input example:

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

Out-of-range config example:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "invalid_request",
    "message": "config.max_concurrency must be between 1 and 20"
  }
}
```

### Common HTTP Statuses

| Status | Meaning |
| --- | --- |
| `400 Bad Request` | Missing required input, unknown preset, empty `dataset`, or unsupported config key. |
| `401 Unauthorized` | Missing or invalid bearer token. |
| `403 Forbidden` | API key does not have the required scope or project access. |
| `429 Too Many Requests` | All product eval worker slots are busy. Wait and retry after the `Retry-After` header. |
| `404 Not Found` | Poll URL does not exist or is not visible to the caller. |
| `500 Internal Server Error` | Server-side preset setup problem. |

### Capacity Full Response

When all Insightor eval worker slots are busy, the submit endpoint returns:

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

No eval is created for a `429` response. The client should wait and submit again later.

## Security Notes

- Use HTTPS.
- Treat `QYM_API_KEY` and `refresh_token` as secrets.
- Do not send secrets in `metadata`.
- `refresh_token` is not returned in Product Eval API responses.
- Store `qym_compare_url` if you want users or operators to open the final Qym result later.
