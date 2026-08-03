# Product Eval API Integration and Operations Guide

The Product Eval API lets an external application start a predefined qym evaluation, poll it, and stop it over HTTP. The caller needs only a project API key; the platform runs the qym SDK internally.

> `run_count=k` creates one logical qym run with `samples=k`. Each dataset item runs through `k` sequential passes inside that run. It does not create or compare `k` physical runs.

For client-only instructions, see the [Product Eval API Client Guide](PRODUCT_EVAL_API_CLIENT_GUIDE.md).

## Execution Model

1. `POST /v1/product-evals` authenticates the project key, validates the preset, and checks process capacity.
2. The platform creates an in-memory job with an `eval_...` ID.
3. A thread-pool worker loads the preset and calls the synchronous qym `Evaluator.run()` API. Synchronous preset tasks run through qym's task worker pool; the HTTP request does not wait for completion.
4. The SDK creates one platform run, streams normal run/pass/item events back to `QYM_BASE_URL`, and stores the caller metadata plus the `eval_id` on the run.
5. Submit waits at most five seconds for initial run creation, then returns `202 Accepted`. Clients poll by `eval_id`.

The product-eval job manager, stop flag, and final compact `group_analysis` are process-local. Platform run data is durable in PostgreSQL; transient job state is not.

## Endpoints

| Method and path | Purpose |
|---|---|
| `POST /v1/product-evals` | Submit an asynchronous eval. |
| `GET /v1/product-evals/{eval_id}` | Canonical eval polling; can recover persisted runs after job-state loss. |
| `POST /v1/product-evals/{eval_id}/stop` | Canonical cooperative stop. |
| `GET /v1/product-evals/{qym_run_id}` | Poll aggregate data for a physical run. |
| `GET /v1/product-evals/{qym_run_id}?include_items=true` | Poll a physical run with item rows. |
| `POST /v1/product-evals/{qym_run_id}/stop` | Stop by physical run ID. |
| `GET /v1/product-evals/jobs/{eval_id}` | Process-local compatibility polling. |
| `POST /v1/product-evals/jobs/{eval_id}/stop` | Process-local compatibility stop. |

There is no synchronous submit-and-wait endpoint.

## Authentication and Ownership

Every endpoint requires a project API key:

```http
Authorization: Bearer <QYM_API_KEY>
```

The submit key is forwarded to the SDK and binds the run to its project and key owner. Job/run reads are restricted to that owner and project. A different user's key in the same project cannot take over the eval.

API-key scopes are not enforced. Stored scope labels are metadata only; documentation and clients must not treat `runs:read` or `runs:write` as authorization boundaries.

Auth failures generally use FastAPI's `{"detail": ...}` shape rather than the product-eval response envelope.

## Submit Contract

```http
POST /v1/product-evals
Content-Type: application/json
Authorization: Bearer <QYM_API_KEY>
```

### Request Schema

| Field | Type | Default | Rules |
|---|---|---|---|
| `preset` | string | `insightor` | Supported values: `insightor`, `test`. |
| `dataset` | string/null | deployment default | Optional for `insightor`; forbidden for `test`; blank strings are invalid. |
| `insightor_url` | string/null | null | Required and nonblank for `insightor`. |
| `refresh_token` | string/null | null | Required and nonblank for `insightor`; secret input. |
| `agent_version` | string/null | null | Optional Insightor runtime input and run-name component. |
| `image_version` | string/null | null | Optional Insightor runtime input and run-name component. |
| `kb_version` | string/null | null | Optional Insightor runtime input and run-name component. |
| `run_name` | string/null | preset/version name | Dashboard run name. |
| `task_name` | string/null | preset task | Task display-name override. |
| `model` | string/null | `MODEL`/preset value | Model label/override. |
| `run_count` | integer/null | operator setting | Samples per item, `1`–`100`. |
| `metadata` | object | `{}` | Caller metadata stored on the platform run. |

The model initially permits extra JSON fields so the route can return a clear `400` identifying them. `config` is explicitly rejected because concurrency, timeouts, and retries are operator-controlled.

Example:

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
    "run_name": "insightor-smoke-001",
    "metadata": {"source": "external-app", "request_id": "req-123"}
  }'
```

## Presets

### `insightor`

- Task: `insightor_api`
- Metric: `accuracy`
- Dataset: request `dataset`, otherwise `QYM_PRODUCT_EVAL_DEFAULT_DATASET`
- Model precedence: request `model`, then server `MODEL`, then a script-level value if present
- Required request inputs: `insightor_url`, `refresh_token`
- Optional version inputs: `agent_version`, `image_version`, `kb_version`
- Script: repository `insightor_eval.py`, overridable with `QYM_INSIGHTOR_EVAL_SCRIPT`

The platform injects the request's Insightor inputs through the script's `configure_runtime()` hook; it does not write them to caller metadata or return them in API payloads.

The bundled script also uses server-side provider credentials. Configure these as needed for the deployed evaluation:

| Variable | Purpose |
|---|---|
| `DATAIKU_API_KEY` | Dataiku SQL access. |
| `DATAIKU_URL` | Dataiku host; the bundled script has a deployment-specific default. |
| `OPENAI_API_KEY` | Main judge credentials and fallback context-judge credentials. |
| `OPENAI_BASE_URL` | Optional OpenAI-compatible base URL. |
| `CONTEXT_JUDGE_API_KEY` | Optional context-judge override. |
| `CONTEXT_JUDGE_BASE_URL` | Optional context-judge base URL. |
| `MODEL` | Default model label when the request omits `model`. |

### `test`

The smoke-test preset is self-contained:

- 50 in-memory items
- synchronous task sleeping about five seconds per item
- deterministic uppercase output and `exact_match`
- fixed task concurrency `10` and task timeout `30` seconds
- no external dataset or provider credentials
- request `dataset` is rejected
- `run_count` still controls samples/passes

It intentionally exercises asynchronous submit, polling, summaries, stopping, and repeat-pass storage; it is not a fast health endpoint.

## Operator Configuration

`QYM_BASE_URL` must be the platform's reachable public/internal URL. The in-process SDK uses it to stream the run back to the platform. For private TLS, configure `QYM_PLATFORM_CA_BUNDLE`; use `QYM_PLATFORM_SSL_VERIFY=false` only for local troubleshooting.

Product-eval settings:

| Variable | Default | Validation | Effect |
|---|---:|---:|---|
| `QYM_PRODUCT_EVAL_MAX_WORKERS` | `3` | `>=1` | Maximum non-terminal jobs in this process. Excess submits receive `429`; there is no waiting queue. |
| `QYM_PRODUCT_EVAL_MAX_CONCURRENCY` | `10` | `1`–`20` | Insightor item concurrency within each pass. |
| `QYM_PRODUCT_EVAL_TIMEOUT` | `900` | `1`–`900` | Insightor timeout per task attempt, seconds. |
| `QYM_PRODUCT_EVAL_MAX_RETRIES` | `1` | `0`–`2` | Insightor task retries after failure/timeout. |
| `QYM_PRODUCT_EVAL_METRIC_TIMEOUT` | `300` | `>=1` | Insightor hard timeout per metric attempt, seconds. |
| `QYM_PRODUCT_EVAL_RUN_COUNT` | `3` | `1`–`100` | Default `samples` value for both presets. Request `run_count` overrides it. |
| `QYM_PRODUCT_EVAL_DEFAULT_DATASET` | `playground_set_v2` | nonempty | Insightor dataset used when the request omits one. |
| `QYM_PRODUCT_EVAL_MAX_PARALLEL_RUNS` | `1` | `1`–`3` | Legacy compatibility multiplier used only in the Insightor effective-concurrency safety check. It does not create parallel physical runs. |
| `QYM_INSIGHTOR_EVAL_SCRIPT` | repository script | existing path | Alternative Insightor preset module. |

Insightor validation requires:

```text
QYM_PRODUCT_EVAL_MAX_CONCURRENCY * QYM_PRODUCT_EVAL_MAX_PARALLEL_RUNS <= 20
```

The `test` preset keeps its fixed concurrency and timeout; it uses the shared worker and run-count settings.

Restart the platform after changing these variables. `QYM_PRODUCT_EVAL_MAX_WORKERS` is captured when the module-level job manager is created.

## Success and Error Envelopes

Product-eval successes use:

```json
{"ok": true, "data": {}, "error": null}
```

Route-level request/setup failures use:

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

Submit returns `202`; successful poll and stop return `200`.

| HTTP status | Source |
|---|---|
| `400` | Unknown preset, missing Insightor input, invalid dataset rule, `config`, or another unsupported field. |
| `401` | Missing, malformed, invalid, or revoked Bearer key. |
| `403` | Disabled owner, key without a project, or cross-owner/project access. |
| `404` | Unknown/inaccessible eval or physical run. |
| `422` | Pydantic body/type/range validation, including invalid `run_count`. Uses FastAPI `detail`. |
| `429` | All local job slots busy. Returns `Retry-After: 30` and code `queue_full`. |
| `500` | Preset setup error, such as a missing script. Returns code `preset_error`. |

A background exception does not turn a later poll into an HTTP error. Poll returns `200` with `data.status: "FAILED"` and a sanitized `data.error` string.

## Eval Polling Response

`GET /v1/product-evals/{eval_id}` returns:

| Field | Meaning |
|---|---|
| `eval_id` | Stable `eval_...` identifier. |
| `status` | `STARTING`, `RUNNING`, `COMPLETED`, `FAILED`, or `STOPPED`. |
| `qym_project_id` | Project bound to the submit key. |
| `run_count` | Effective sample/pass count. |
| `runs` | Legacy attempt-shaped compatibility rows; not a reliable physical-run count. |
| `qym_compare_url` | URL only when two or more physical run IDs exist; normally null for new native evals. |
| `group_analysis` | Compact sampled-run analysis, exposed only after successful completion when calculation succeeds. |
| `created_at`, `updated_at` | UTC job/run timestamps. |
| `error` | Sanitized background error when failed. |

The `runs` rows contain `attempt`, `status`, `qym_run_id`, `qym_run_url`, `task`, `dataset`, `model`, and `summary`. Important compatibility rules:

- Native execution creates one physical qym run even when `run_count > 1`.
- Planned placeholder rows may remain in `runs`; the physical run is identified by a non-null `qym_run_id`.
- Trust the top-level eval `status`, not individual compatibility-row statuses or array length.
- Top-level `qym_run_id`, `qym_run_url`, `qym_runs`, `poll_url`, and `job_id` are intentionally absent.
- The result UI link is the non-null `runs[].qym_run_url`, not `qym_compare_url`.

When available, `summary` contains item progress, metric aggregates, latency aggregates, and start/end timestamps. It summarizes the run's compatibility/reduced item view; pass details live on the platform run.

### Group Analysis Shape

For `samples=k`, the in-memory job derives:

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

`pass_at_<k>` and `avg_at_<k>` are dynamic keys. `group_analysis` is null for active/stopped/failed jobs, normally null for `run_count=1`, and may be null if calculation or transient-state recovery is unavailable. The platform's Samples analysis is authoritative.

## Physical-Run Polling

Once a compatibility row exposes a `qym_run_id`:

```http
GET /v1/product-evals/{qym_run_id}
```

The response contains `qym_run_id`, project/run URL, external run ID, run status, task, dataset, model, metrics, progress counts, metric statistics, latency statistics, timestamps, and public caller metadata. Internal `metadata.product_eval` bookkeeping is removed.

`?include_items=true` adds item input/expected/output/error, latency, retries, trace fields, scores, and metric metadata. It is ignored for an `eval_id`, so use a physical run ID. Avoid it for high-frequency polling.

## Stop Semantics

Prefer:

```http
POST /v1/product-evals/{eval_id}/stop
```

The job stop flag is visible to the qym evaluator through `should_stop`. The route immediately marks the process-local job and planned compatibility rows `STOPPED`, then marks non-terminal persisted runs `STOPPED` with reason `product_eval_stopped`. The response adds `stopped_qym_runs`.

Stopping is cooperative: a blocking synchronous task call may finish before control returns to qym. Completed/failed/stopped runs are not changed, and explicitly stopped runs are not reopened by late SDK events.

Stop by physical run ID is supported. The `/jobs/{eval_id}/stop` route is retained only for compatibility and requires the original process-local job to exist.

## Persistence and Compatibility

- The canonical `/{eval_id}` poll route checks the in-memory job first. If it is absent, it searches active platform runs whose internal metadata contains that `eval_id`, owner, and project.
- A restart before the physical run is persisted loses the eval ID completely; polling returns `404`.
- After persistence, the route can recover status and run summaries. Process-local planning rows, stop flag, and computed group analysis are not guaranteed to survive.
- New native sampled evals normally have one run and a null compare URL. Multiple run rows and a compare URL can appear when reading data created by the former physical multi-run implementation.
- `/jobs/{eval_id}` never performs database recovery and is unsuitable as a durable client contract.

## Deployment Checklist

- Run PostgreSQL migrations before startup.
- Set `QYM_BASE_URL` to an address the platform process can call back through the SDK.
- Create the default qym dataset and a usable published version/alias before submitting Insightor without a dataset override.
- Configure Insightor/Dataiku/judge credentials on the server, never in caller metadata.
- Use one application process for reliable live polling and stopping. Job state is not shared between Uvicorn workers; if multiple processes are unavoidable, use sticky routing and understand that only persisted run recovery is durable.
- Size `QYM_PRODUCT_EVAL_MAX_WORKERS` and per-pass item concurrency for the host. Capacity is per process and excess work receives `429` rather than queuing.
- Treat stop as cooperative and design synchronous preset calls with bounded timeouts.
- Monitor `/healthz`, worker-capacity errors, and background `FAILED` statuses separately.
