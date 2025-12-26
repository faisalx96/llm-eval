# RunEventV1 (SDK → Platform streaming schema)

This document defines the versioned event contract used by the **SDK** to stream live evaluation runs to the **platform**.

## Goals
- **Real-time UI**: platform can render the live run dashboard while the SDK is executing.
- **Idempotent ingestion**: retries must not duplicate data.
- **Ordered updates**: platform can apply incremental updates deterministically.
- **Backward compatibility**: new SDK versions should not break older platforms and vice versa (within policy).

## Transport
One of the following (platform may support both):
- **NDJSON over HTTP**: `POST /v1/runs/{run_id}/events` with newline-delimited JSON objects.
- **WebSocket**: `WS /v1/runs/{run_id}/ws` sending one JSON per message.

## Envelope (common fields)
Every event is a JSON object with these top-level fields:

- `schema_version`: integer, must be `1` for this spec.
- `event_id`: uuid string, globally unique (idempotency key).
- `sequence`: integer, strictly increasing **per run** starting from 1.
- `sent_at`: RFC3339 timestamp (client time), informational.
- `type`: string enum (see event types below).
- `run_id`: platform `run_id` (uuid string).
- `payload`: object, type-specific payload.

### Idempotency rules
- Platform must dedupe on `(run_id, event_id)`.\n+- Platform should also enforce monotonic `sequence` (accept out-of-order but apply in order, or reject if too old).\n+- SDK may retry sending the same event (same `event_id`) on network errors.

### Ordering rules
- SDK must send events with increasing `sequence`.
- Platform may receive out-of-order; it should either:
  - buffer and re-order until contiguous sequences arrive, or
  - apply best-effort and tolerate minor reordering (acceptable for live UI), but **must** preserve final stored results.

## Event types (minimum set)

### `run_started`
Sent once at run start.

Payload:
- `external_run_id`: optional string (client-chosen stable identifier).
- `task`: string
- `dataset`: string
- `model`: optional string
- `metrics`: string[]
- `run_metadata`: object (JSON)
- `run_config`: object (JSON)
- `started_at`: RFC3339 timestamp

### `item_started`
Sent when processing begins for an item.

Payload:
- `item_id`: string
- `index`: integer (0-based)
- `input`: any JSON
- `expected`: any JSON (nullable)
- `item_metadata`: object (JSON)

### `metric_scored`
Sent when a metric is computed for an item. May be repeated (one per metric).

Payload:
- `item_id`: string
- `metric_name`: string
- `score_numeric`: number|null (if meaningful numeric score)
- `score_raw`: any JSON (preserve original)
- `meta`: object (JSON) optional (metric metadata)

### `item_completed`
Sent when item completes successfully.

Payload:
- `item_id`: string
- `output`: any JSON
- `latency_ms`: number
- `trace_id`: string|null
- `trace_url`: string|null

### `item_failed`
Sent when item fails.

Payload:
- `item_id`: string
- `error`: string
- `trace_id`: string|null
- `trace_url`: string|null

### `run_completed`
Sent once at end.

Payload:
- `ended_at`: RFC3339 timestamp
- `summary`: object (JSON) optional (success counts, etc.)
- `final_status`: string enum: `COMPLETED` or `FAILED`

## Compatibility policy
- The platform must accept `schema_version=1` long-term.
- The SDK may add new optional fields to payloads without breaking v1.
- Breaking changes require bumping `schema_version` and providing a new `RUN_EVENT_SCHEMA.md`.

## NDJSON example

```json
{"schema_version":1,"event_id":"5d8f7d2e-7a9f-4e3a-8b15-0b4f9c2b4c0e","sequence":1,"sent_at":"2025-12-26T12:00:00Z","type":"run_started","run_id":"2c2a0c9d-1c66-4e7f-9c03-2f04c9d1a0a3","payload":{"task":"my_task","dataset":"qa.csv","model":"gpt-4o-mini","metrics":["exact_match"],"run_metadata":{"team":"rag"},"run_config":{"max_concurrency":10,"timeout":30},"started_at":"2025-12-26T12:00:00Z"}}
{"schema_version":1,"event_id":"b8c2f55a-1a62-4ef1-a91e-5f5c7b2d0b3f","sequence":2,"sent_at":"2025-12-26T12:00:01Z","type":"item_started","run_id":"2c2a0c9d-1c66-4e7f-9c03-2f04c9d1a0a3","payload":{"item_id":"row_000001","index":0,"input":"What is X?","expected":"X is ...","item_metadata":{"difficulty":"easy"}}}
{"schema_version":1,"event_id":"2f83f9a4-8f2c-4bde-9c2e-0c2a6e1f1e2a","sequence":3,"sent_at":"2025-12-26T12:00:02Z","type":"metric_scored","run_id":"2c2a0c9d-1c66-4e7f-9c03-2f04c9d1a0a3","payload":{"item_id":"row_000001","metric_name":"exact_match","score_numeric":1,"score_raw":true,"meta":{}}}
{"schema_version":1,"event_id":"d7c8b1d0-3f4a-4e5f-9a0b-1c2d3e4f5a6b","sequence":4,"sent_at":"2025-12-26T12:00:02Z","type":"item_completed","run_id":"2c2a0c9d-1c66-4e7f-9c03-2f04c9d1a0a3","payload":{"item_id":"row_000001","output":"X is ...","latency_ms":412,"trace_id":null,"trace_url":null}}
{"schema_version":1,"event_id":"a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d","sequence":5,"sent_at":"2025-12-26T12:00:03Z","type":"run_completed","run_id":"2c2a0c9d-1c66-4e7f-9c03-2f04c9d1a0a3","payload":{"ended_at":"2025-12-26T12:00:03Z","final_status":"COMPLETED","summary":{"total_items":1,"success_count":1,"error_count":0}}}
```


