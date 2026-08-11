# Product Eval API Client Guide

This guide is for HTTP clients that trigger qym product evaluations without installing Python or the qym SDK.

> `run_count=k` means one qym run with `samples=k`: every dataset item is evaluated `k` times inside that run. It does not create `k` dashboard runs.

## Contract at a Glance

| Action | Endpoint | Result |
|---|---|---|
| Start | `POST /v1/product-evals` | `202 Accepted` with a stable `eval_id`. |
| Poll | `GET /v1/product-evals/{eval_id}` | Eval status, physical run links, summaries, and final group analysis when available. |
| Stop | `POST /v1/product-evals/{eval_id}/stop` | Cooperative stop request. |
| Inspect a run | `GET /v1/product-evals/{qym_run_id}` | Aggregate progress for one physical qym run. |
| Inspect run items | `GET /v1/product-evals/{qym_run_id}?include_items=true` | Aggregate progress plus item rows. |

Submit is asynchronous. The server may wait up to five seconds for the physical qym run to appear, but it never waits for evaluation completion. There is no synchronous product-eval endpoint.

## Base URL and Authentication

All paths are relative to the platform URL, for example:

```text
https://qym.example.com
```

Send a project API key on every request:

```http
Authorization: Bearer <QYM_API_KEY>
```

The key determines the project and owner. Poll and stop with a key owned by the same user and bound to the same project as the submit key.

API-key scope labels are currently metadata only; the platform does not enforce per-key scopes. A valid, non-revoked project key is still required.

## Start an Eval

```http
POST /v1/product-evals
Content-Type: application/json
Authorization: Bearer <QYM_API_KEY>
```

### Request Fields

| Field | Type | Required | Description |
|---|---|---:|---|
| `preset` | string | No | `insightor` (default) or `test`. |
| `dataset` | string | No | qym dataset for `insightor`; otherwise the deployment default. Rejected by `test`. |
| `insightor_url` | string | Insightor only | Insightor base URL. |
| `refresh_token` | string | Insightor only | Secret used to authenticate to Insightor. |
| `agent_version` | string | No | Insightor agent label/runtime input. |
| `image_version` | string | No | Insightor image label/runtime input. |
| `kb_version` | string | No | Insightor knowledge-base label/runtime input. |
| `run_name` | string | No | Dashboard run name. |
| `task_name` | string | No | Task display label override. |
| `model` | string | No | Model label/override. |
| `run_count` | integer | No | Samples per item, `1`–`100`; deployment default is normally `3`. |
| `metadata` | object | No | Caller metadata stored on the run. Never include secrets. |

Clients cannot set evaluator `config`. `config` and every other unsupported field return `400` without creating an eval.

### Presets

| Preset | Inputs | Behavior |
|---|---|---|
| `insightor` | Requires `insightor_url` and `refresh_token`; `dataset` is optional. | Uses the deployment's Insightor task, qym dataset, and `accuracy` metric. |
| `test` | No external inputs; do not send `dataset`. | Runs 50 deterministic items with a five-second synchronous task and `exact_match`. Intended for integration smoke tests. |

Both presets create one physical qym run. If `run_count` is greater than one, that run contains sequential repeat passes.

### Curl Example

```bash
curl -X POST "$QYM_BASE_URL/v1/product-evals" \
  -H "Authorization: Bearer $QYM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "preset": "insightor",
    "dataset": "customer-eval-set",
    "insightor_url": "https://insightor.example.com",
    "refresh_token": "'"$INSIGHTOR_REFRESH_TOKEN"'",
    "run_count": 5,
    "agent_version": "agent-v1",
    "image_version": "image-v1",
    "kb_version": "kb-v1",
    "run_name": "insightor-smoke-001",
    "metadata": {
      "source": "external-app",
      "request_id": "req-123"
    }
  }'
```

## Submit Response

A valid request returns `202 Accepted`:

```json
{
  "ok": true,
  "data": {
    "eval_id": "eval_3b8df7a5e0f74cf8988ab4b3ad2d7f40",
    "status": "STARTING",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "run_count": 3,
    "runs": [
      {
        "attempt": 1,
        "status": "PENDING",
        "qym_run_id": null,
        "qym_run_url": null,
        "task": null,
        "dataset": null,
        "model": null,
        "summary": null
      },
      {
        "attempt": 2,
        "status": "PENDING",
        "qym_run_id": null,
        "qym_run_url": null,
        "task": null,
        "dataset": null,
        "model": null,
        "summary": null
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
    "qym_compare_url": null,
    "group_analysis": null,
    "created_at": "2026-08-03T09:00:00Z",
    "updated_at": "2026-08-03T09:00:00Z"
  },
  "error": null
}
```

Save `data.eval_id`. Top-level `qym_run_id`, `qym_run_url`, `poll_url`, and `job_id` are not part of this response contract.

## Poll an Eval

```http
GET /v1/product-evals/{eval_id}
Authorization: Bearer <QYM_API_KEY>
```

```bash
curl "$QYM_BASE_URL/v1/product-evals/$EVAL_ID" \
  -H "Authorization: Bearer $QYM_API_KEY"
```

Poll every two to five seconds, then back off for long evaluations. Treat these top-level statuses as authoritative:

| Status | Meaning |
|---|---|
| `STARTING` | Accepted, but no physical qym run is visible yet. |
| `RUNNING` | Background execution is active. |
| `COMPLETED` | Execution finished normally. |
| `FAILED` | Background execution failed; `data.error` contains a sanitized message. |
| `STOPPED` | A stop was requested or the run ended stopped. |

`COMPLETED`, `FAILED`, and `STOPPED` are terminal.

### Compatibility Fields

The response retains fields from the former multi-run implementation:

- `run_count` is the sample/pass count, not a physical-run count.
- `runs` is a legacy attempt-shaped view. It may contain planned placeholder rows as well as the row carrying the physical `qym_run_id`. Do not rely on its length, attempt numbers, or row statuses to determine eval completion; use the top-level `status`.
- Collect distinct non-null `runs[].qym_run_id` and `runs[].qym_run_url` values to find physical runs. A new native evaluation normally has one.
- `qym_compare_url` is normally `null` for new evaluations because one physical run does not need comparison. It may be populated when recovering an older eval that genuinely created multiple runs; do not use it as the primary result link.

When database details are available, the physical-run row includes `task`, `dataset`, `model`, and `summary`. Summary fields are `total`, `completed`, `failed`, `in_progress`, `pending`, `metrics`, `metric_stats`, `latency_ms`, `started_at`, and `ended_at`.

### Group Analysis

For a successfully completed sampled run, `group_analysis` may contain:

```json
{
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
}
```

The key suffix matches `k`, such as `pass_at_5` and `avg_at_5`. `group_analysis` can be `null` for `run_count=1`, stopped/failed runs, calculation failure, or after transient job state is lost. The physical run's Samples analysis page remains the authoritative per-pass view.

## Inspect the Physical Run

After a non-null `qym_run_id` appears:

```http
GET /v1/product-evals/{qym_run_id}
Authorization: Bearer <QYM_API_KEY>
```

This returns aggregate run progress without the legacy eval wrapper:

```json
{
  "ok": true,
  "data": {
    "qym_run_id": "2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "qym_project_id": "1805a314-0fea-427c-9b14-c4c27c820d72",
    "qym_run_url": "https://qym.example.com/run/2c93f1bc-76a9-48e7-aaf1-5ec8ea1c6e30",
    "external_run_id": "insightor-smoke-001",
    "status": "RUNNING",
    "task": "insightor_api",
    "dataset": "customer-eval-set",
    "model": "model-label",
    "metrics": ["accuracy"],
    "total": 100,
    "completed": 42,
    "failed": 1,
    "in_progress": 2,
    "pending": 55,
    "metric_stats": {
      "accuracy": {"count": 42, "mean": 0.81, "min": 0.0, "max": 1.0}
    },
    "latency_ms": {"count": 43, "mean": 1440.2, "min": 700.0, "max": 5100.0},
    "started_at": "2026-08-03T09:00:01Z",
    "ended_at": null,
    "created_at": "2026-08-03T09:00:01Z",
    "metadata": {"source": "external-app", "request_id": "req-123"}
  },
  "error": null
}
```

Add `?include_items=true` only for debugging. Each item adds input, expected output, output/error, latency, retry count, trace fields, scores, and metric metadata. The option applies to a physical run ID, not an `eval_id`.

## Stop an Eval

```http
POST /v1/product-evals/{eval_id}/stop
Authorization: Bearer <QYM_API_KEY>
```

The response uses the success envelope, changes the job to `STOPPED`, and adds `stopped_qym_runs`, the number of non-terminal physical runs marked stopped.

Stopping is cooperative. qym checks between items and passes; a blocking synchronous task call may finish before the worker exits. Late events do not reopen a run explicitly stopped with reason `product_eval_stopped`.

Stopping by physical run ID is supported as an operational fallback:

```http
POST /v1/product-evals/{qym_run_id}/stop
```

## Compatibility Job Routes

These routes remain for older clients:

```http
GET  /v1/product-evals/jobs/{eval_id}
POST /v1/product-evals/jobs/{eval_id}/stop
```

They use process-local job state and are unavailable after a restart. Their polling response is not enriched with database summaries. New clients should use the canonical `/{eval_id}` routes.

## Errors

Product-eval validation/setup errors use:

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

| HTTP status | Meaning |
|---|---|
| `400` | Unknown preset, missing Insightor input, blank/forbidden dataset, `config`, or unsupported field. |
| `401` | Missing, invalid, or revoked Bearer key. |
| `403` | Disabled owner, unbound key, or eval/run owned by another user/project. |
| `404` | Eval or run not found. |
| `422` | JSON schema/type/range failure, including `run_count` outside `1`–`100`. |
| `429` | All in-process product-eval workers are busy; retry after the `Retry-After: 30` header. |
| `500` | Server preset setup failure, such as a missing preset script. |

FastAPI auth and schema errors may use `{"detail": ...}` instead of the product-eval envelope. A background failure is different: polling succeeds with HTTP `200`, while `data.status` is `FAILED` and `data.error` is present.

## Minimal JavaScript Client

```js
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function productEval({ baseUrl, apiKey, request }) {
  const headers = {
    Authorization: `Bearer ${apiKey}`,
    "Content-Type": "application/json",
  };

  const submit = await fetch(`${baseUrl}/v1/product-evals`, {
    method: "POST",
    headers,
    body: JSON.stringify(request),
  });
  const submitted = await submit.json();
  if (!submit.ok) {
    throw new Error(submitted.error?.message || JSON.stringify(submitted.detail));
  }

  const evalId = submitted.data.eval_id;
  while (true) {
    await sleep(3000);
    const response = await fetch(`${baseUrl}/v1/product-evals/${evalId}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.error?.message || JSON.stringify(body.detail));
    }

    const data = body.data;
    const runUrls = [...new Set(
      (data.runs || []).map((run) => run.qym_run_url).filter(Boolean)
    )];

    if (data.status === "COMPLETED") {
      return { evalId, runUrls, groupAnalysis: data.group_analysis };
    }
    if (data.status === "FAILED" || data.status === "STOPPED") {
      throw new Error(data.error || `Eval ${data.status.toLowerCase()}`);
    }
  }
}
```

## Security and Durability

- Use HTTPS and treat both `QYM_API_KEY` and `refresh_token` as secrets.
- Do not put credentials in `metadata`; caller metadata is returned by the run endpoint.
- Background jobs live in the platform process. After restart, the canonical `eval_id` route can recover a run that was already persisted, but startup-only state and transient group analysis may be unavailable.
- Save `eval_id` and the non-null physical run URL. Do not depend on the compatibility compare URL.
