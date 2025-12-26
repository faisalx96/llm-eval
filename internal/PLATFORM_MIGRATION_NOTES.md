# Platform migration notes (SDK → DB-backed platform)

This document maps the current **local SDK/CLI** run lifecycle and file formats to the new **platform** data model.

## Current lifecycle (today)

### Execution
- Runs are executed locally via `llm_eval/cli.py` which constructs an `Evaluator` (`llm_eval/core/evaluator.py`) and runs it.
- The evaluator:
  - Uses a `ProgressTracker` to track per-item progress.
  - Writes a live snapshot to a local UI server (`llm_eval/server/app.py`) via `/api/snapshot` and SSE (`/api/rows/stream`).

### Persistence
- After completion, `EvaluationResult.save()` persists to disk under `llm-eval_results/` (`llm_eval/core/results.py`).
- The historical dashboard (`llm_eval/server/dashboard_server.py`) discovers runs by scanning that directory (`llm_eval/core/run_discovery.py`) and serves:
  - `GET /api/runs` (index)
  - `GET /api/runs/{file_path}` (full run view)
  - `GET /run/{file_path}` (run UI in “dashboard mode”)

## Current file formats (source of truth)

### CSV (primary)
Produced by `EvaluationResult.save_csv()` in `llm_eval/core/results.py`.

**Base columns**
- `dataset_name`
- `run_name`
- `run_metadata` (JSON string)
- `run_config` (JSON string)
- `trace_id`
- `item_id`
- `input`
- `item_metadata` (JSON string)
- `output` (or `ERROR: ...`)
- `expected_output`
- `time` (seconds)

**Metric columns**
- For each metric `m`:
  - `m_score`
  - `m__meta__{k}` for each metadata key (flattened)

### JSON (secondary)
`EvaluationResult.to_dict()` provides run-wide + per-item payloads.

### XLSX
Same schema as CSV; just stored in Excel format.

## Platform data model mapping (target)

### runs
From the CSV first row / run-level metadata:
- `runs.external_run_id`: optional client-provided stable id (new)
- `runs.task`: derived from run name conventions or explicit config (new)
- `runs.dataset`: `dataset_name`
- `runs.model`: from `run_metadata.model` (if present) else from config
- `runs.metrics[]`: list of metric names inferred from `{m}_score` columns
- `runs.run_metadata`: parsed JSON from `run_metadata`
- `runs.run_config`: parsed JSON from `run_config`
- `runs.status`: platform workflow state (new; not present in CSV)

### run_items
One row per item:
- `run_items.item_id`: `item_id`
- `run_items.input`: `input`
- `run_items.expected`: `expected_output`
- `run_items.output`: `output` (or null if error)
- `run_items.error`: parse when output begins with `ERROR:` (same heuristic as `RunDiscovery.is_error_row()`)
- `run_items.trace_id`: `trace_id`
- `run_items.latency_ms`: `time * 1000`
- `run_items.item_metadata`: parsed from `item_metadata` (new column in DB; in CSV it’s a string)

### run_item_scores
For each metric `m`:
- `run_item_scores.metric_name`: `m`
- `run_item_scores.score_numeric`: numeric score parsed from `m_score` when possible
- `run_item_scores.score_raw`: preserve original raw value for non-numeric scores (boolean, categorical)
- `run_item_scores.meta`: collected from `m__meta__*` columns

### approvals / audit logs
Not present today; derived from platform actions:
- Employee submits (`DRAFT` → `SUBMITTED`)
- Manager approves/rejects
- GM/VP visibility constrained to approved runs

## Missing data we must introduce (platform-only)

- **User identity**: which user “owns” a run (`owner_user_id`) and which API key created it.
- **Org structure**: manager relationships to enforce visibility (subtree authorization).
- **Workflow state**: `DRAFT/SUBMITTED/APPROVED/REJECTED`.
- **Event stream** for live runs (RunEventV1) so the platform can render live UI without local `UIServer`.


