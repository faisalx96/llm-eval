# Robust Runner Liveness And Stale-Run Recovery

## Summary
Add explicit per-run heartbeats from the SDK, persist runner liveness on the platform, and add an embedded platform sweeper that marks abandoned `RUNNING` runs as `LOST`. Keep explicit SDK terminal events authoritative: a later `run_completed` from the SDK must overwrite an inferred `LOST`.

Chosen defaults:
- New inferred terminal status: `LOST`
- Heartbeat transport: new `run_heartbeat` event on the existing platform event stream
- Heartbeat cadence: every 15s while a run is active
- Stale threshold: 90s since last heartbeat
- Sweeper cadence: every 30s
- Sweeper host: FastAPI lifespan background loop inside the platform app
- Explicit final status wins over inferred `LOST`

## Implementation Changes
### SDK runner
- Add a dedicated heartbeat loop per active run in `qym.core.evaluator`.
- Implement it as a daemon thread, not an asyncio task, so it continues through long LLM calls and does not depend on item progress.
- Start the heartbeat only after platform streaming is initialized and the run has a platform `run_id`.
- Send heartbeat events through the existing `PlatformEventStream`; do not add a second transport.
- Stop the heartbeat on every terminal path:
  - normal completion
  - explicit stop / interrupt
  - async cancellation
  - signal-driven shutdown already routed through graceful interrupt handling
- Guarantee heartbeat shutdown happens before process exit but after final `run_completed` is attempted.
- In multi-run mode, each evaluator/run owns its own heartbeat loop; no shared process heartbeat.

### Event/schema/platform model
- Add a new event type `run_heartbeat` in platform event schemas.
- Add `last_heartbeat_at` to `Run`.
- Add new workflow status `LOST` to `RunWorkflowStatus`.
- On ingest of `run_started`, initialize `last_heartbeat_at = started_at`.
- On ingest of `run_heartbeat`, update only `last_heartbeat_at`; do not mutate progress or status unless the run is still `RUNNING`.
- On ingest of `run_completed`, allow overwrite from `LOST` to the explicit final status (`COMPLETED`, `FAILED`, `STOPPED`).
- Do not resurrect `LOST` back to `RUNNING` from late heartbeat traffic; only an explicit terminal event may replace `LOST`.

### Platform sweeper
- Add a background sweeper loop in `qym_platform.app` lifespan.
- Every 30s, query indexed `RUNNING` runs whose `last_heartbeat_at` is older than 90s.
- Mark them:
  - `status = LOST`
  - `ended_at = now`
  - merge a small marker into `run_metadata` such as `{"inferred_terminal_status":"LOST","lost_at":...,"lost_reason":"heartbeat_timeout"}`
- Keep the sweeper idempotent and batch-safe.
- Ensure only one sweeper instance runs per app process; document that multiple app replicas may race and must rely on idempotent `UPDATE ... WHERE status='RUNNING'`.
- If a later SDK `run_completed` arrives, let it replace `LOST` and refresh `ended_at`/summary.

### UI/API behavior
- Surface `LOST` as a distinct terminal badge in dashboard/list views.
- Treat `LOST` as non-active everywhere the UI currently special-cases `RUNNING`/`PENDING`.
- Keep submit-for-approval behavior unchanged: only `COMPLETED`/`FAILED` remain submittable.
- No browser-side heartbeat changes; this is runner liveness only.

## Public Interfaces And Schema Additions
- Add `RunWorkflowStatus.LOST`.
- Add `Run.last_heartbeat_at: datetime | null`.
- Add `run_heartbeat` to platform event types.
- Add `RunHeartbeatPayload` with a single authoritative timestamp field, `heartbeat_at`.
- Migration requirements:
  - enum expansion for `LOST`
  - nullable `last_heartbeat_at` column
  - index on `(status, last_heartbeat_at)` for sweeper queries

## Test Plan
- SDK unit test: heartbeat thread starts when platform streaming is enabled and stops on normal completion.
- SDK unit test: long-running async task still emits heartbeats during a 60s-equivalent wait.
- SDK unit test: interrupt / cancellation / SIGTERM path emits `STOPPED` and shuts down heartbeat.
- Platform ingest test: `run_heartbeat` updates `last_heartbeat_at` without changing a healthy `RUNNING` run.
- Sweeper test: stale `RUNNING` run becomes `LOST` after threshold.
- Race test: run marked `LOST`, then later `run_completed(COMPLETED|FAILED|STOPPED)` arrives and overrides `LOST`.
- UI/API test: `LOST` appears as terminal, not active, and is not submittable.
- Acceptance scenario: kill a live runner with `pkill`; after threshold the platform shows `LOST` if no explicit final event arrives.
- Acceptance scenario: network blip shorter than threshold does not mark the run stale.

## Assumptions
- `SIGKILL` / `kill -9` remains uncatchable; heartbeat + sweeper is the recovery mechanism for that case.
- “Proper and robust” means inferred abandonment should be distinguishable from explicit user stop, hence `LOST` instead of reusing `STOPPED`.
- The platform will initially run the sweeper in-process via FastAPI lifespan; if deployment later moves to multiple replicas, this design remains correct because stale updates are idempotent and explicit final events remain authoritative.
