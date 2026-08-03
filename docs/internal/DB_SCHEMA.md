# Platform Database Schema

The canonical models are in `packages/platform/qym_platform/db/models.py`; Alembic migrations are in `packages/platform/qym_platform/migrations/versions/`. PostgreSQL is required.

## Identity and projects

- `users`: global identity, active flag, and `MEMBER` / `ADMIN` role.
- `user_identities`: provider/subject mappings for OIDC and local identities.
- `local_auth_credentials`: password hashes and local-login timestamps.
- `projects`: project access boundary and active/archive state.
- `project_memberships`: one `MEMBER` / `MANAGER` role per user and project.
- `api_keys`: project-bound key prefix, PBKDF2 hash, creator, recorded scopes, and revocation time. Scopes are stored but are not currently enforced.
- `project_llm_connections`: encrypted OpenAI-compatible connection settings and the project default.
- `platform_settings`: retained settings storage; current operator configuration primarily comes from environment variables.

## Runs and repeat executions

- `runs`: project, owner, task/dataset/model, workflow state, metadata/config, progress, soft deletion, and `samples` (default `1`).
- `run_items`: one representative row per `(run, item)` with input, expected, latest output/error, metadata, latency, and trace links.
- `run_metric_specs`: immutable score semantics and display order per run/metric.
- `run_item_scores`: one reduced row per `(run, item, metric)`. For repeat runs, the numeric value is the mean across stored passes.
- `run_item_attempts`: retry attempts keyed by `(run, item, pass, attempt)`; the final attempt in each pass stores that pass's output and trace data.
- `run_item_pass_scores`: lossless score per `(run, item, metric, pass)`. Migration `0027_pass_score_meta` adds the per-pass `label`, `meta`, and `explanation` used for judge and metric detail.
- `run_metric_analyses`: cached repeat-analysis payloads keyed by run, metric, threshold, and method version. Score edits invalidate affected cache entries.
- `run_events`: idempotent `RunEventV1` log, unique by both `(run, event_id)` and `(run, sequence)`.
- `approvals` and `audit_logs`: run workflow decisions and mutation audit history.

## Datasets

- `datasets`: project-scoped dataset identity, description/tags, and soft deletion.
- `dataset_versions`: immutable `vN` identifier, optional display name, draft/published state, parent version, item count, and content hash.
- `dataset_aliases`: project-dataset aliases such as `production`, restricted to published versions.
- `dataset_items`: items keyed by `(version, item_id)` with input, expected output, metadata, labels, and fingerprint.
- `dataset_item_revisions`: append-only before/after item edits.
- `dataset_version_changes`: version creation, publishing, upload, clone, and alias history.

## Traces and review

- `spans`: normalized OpenTelemetry spans, unique per `(run, span_id)`.
- `run_trace_aggregates`: cached per-trace timing, token, cost, type, and error summaries.
- `root_cause_revisions`: append-only item-level root-cause/solution revisions.
- `review_corrections`: active review candidates, snapshots, confidence, source, review status/comment, and supersession links.

Published dataset versions and historical review revisions are immutable. Runs, datasets, projects, and API keys use archive, soft-delete, or revocation fields where recovery/auditability matters.
