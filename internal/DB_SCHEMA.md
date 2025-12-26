# DB Schema (MVP)

Defined in:
- `llm_eval_platform/db/models.py`
- migrations: `llm_eval_platform/migrations/versions/0001_initial.py`

## Core tables

- `users`: user identity + role
- `user_identities`: SSO-ready mapping (provider + subject)
- `org_edges`, `org_closure`: org hierarchy (closure is used for subtree checks once populated)
- `api_keys`: per-user hashed API keys

## Run tables

- `runs`: run metadata, workflow state
- `run_items`: per-item input/output/expected/errors and latency
- `run_item_scores`: per-metric scores
- `approvals`: submit/approve/reject record (1 per run)
- `audit_logs`: append-only audit events (wired in later iteration)
- `run_events`: optional append-only event log (RunEventV1)


