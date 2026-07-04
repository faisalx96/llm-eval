# DB Schema (MVP)

Defined in:
- `packages/platform/qym_platform/db/models.py`
- migrations: `packages/platform/qym_platform/migrations/versions/0001_initial.py`

## Core tables

- `users`: user identity + role
- `user_identities`: SSO-ready mapping (provider + subject)
- `org_edges`, `org_closure`: org hierarchy (closure is used for subtree checks once populated)
- `api_keys`: per-user hashed API keys

## Run tables

- `runs`: run metadata, workflow state. `samples` (int, default 1) = repeat
  runs: how many passes evaluate each item (migration `0023_repeat_runs`).
- `run_items`: per-item input/output/expected/errors and latency. Always ONE
  row per (run, item); for repeat runs it holds the latest pass as the
  representative row.
- `run_item_scores`: per-metric scores — ONE row per (run, item, metric).
  For repeat runs the value is the REDUCED mean over passes, so every
  existing view/query keeps working.
- `run_item_attempts`: attempt/retry rows (migration `0015`), extended by
  `0023` with `pass_number` (which pass the attempt belongs to; unique key
  is run/item/pass/attempt) and `output` (the pass's output, stored on each
  pass's final attempt for the per-pass drill-down).
- `run_item_pass_scores` (new in `0023`): one numeric score per
  (run, item, metric, pass) — the per-pass detail powering accuracy-vs-k,
  the runs-list pass expansion, and attempt pooling in the models view.
- `approvals`: submit/approve/reject record (1 per run)
- `audit_logs`: append-only audit events (wired in later iteration)
- `run_events`: optional append-only event log (RunEventV1)


