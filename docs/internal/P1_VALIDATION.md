# P1 performance validation

Work is isolated on `codex/p1-performance` in `/Users/faisalbh/qym-p1-performance`.
The performance baseline is `b1d1d00587df4fcf0e70875c29b0bb0cbc20172c`.
The branch also integrates `9325874` from main, including structured multi-issue
root-cause analysis. Its source fields, UI, review provenance and migrations
must remain intact alongside the performance changes.

## Behavior and deployment

- Ingestion runs database work outside the API event loop and batches identity,
  event and span operations. Incremental trace contributions replace repeated
  whole-run trace scans.
- The browser dashboard reads durable summaries. Runs retain 50 current rows
  plus explicit selections; Models load bounded candidates and selector pages.
  Charts preserve global totals and fetch complete numerical history only for
  opened task/dataset charts, in 500-row requests with two concurrent loads.
- Run and Compare retain a complete compact analytical index, then hydrate
  bodies/explanations in requests of at most 100 items. Search preserves global
  semantics, including repeated passes. The normal detail cache retains at most
  200 bodies per run; exports and unusual cross-field text searches deliberately
  load all required bodies before releasing off-page content.
- Analytical indexes still scale with item count. Opened chart histories scale
  with the analysis the user opens. These changes do not impose a fixed total
  memory ceiling on complete analysis or exports, and do not sample away data.
- SDK uploads use a 16 MiB memory budget and a 256 MiB private disk spool by
  default, with backpressure at capacity. Finalization stays off the event loop.
  Failed buffering or delivery cannot report successful completion. Judge
  clients are reused within their owning run/event loop and closed afterward.
- Existing full-data APIs and the immediately source-backed `/api/runs` remain
  available to established consumers. Dashboard freshness explicitly identifies
  pending work. A terminal historical run is not published with partial backfill.

Apply all migrations before starting the application. P1 migrations `0047` and
`0048` follow main's root-cause migrations. The app starts a durable summary worker per
process; database locks coordinate concurrent workers. Backfill is asynchronous,
resumable and bounded. See [the operations guide](DASHBOARD_PROJECTION_OPERATIONS.md)
for repair, late events, retention and worker behavior.

## Measurements

Synthetic measurements are local, not production latency guarantees. Ingestion
before/after uses the same Python 3.12.8 environment and fresh SQLite databases,
with three samples per case. It includes parsing and commit, including new
dashboard capture, but excludes HTTP authentication and thread dispatch.

| Workload | Before | After | Interpretation |
|---|---:|---:|---|
| 1,000 item-start events | 419 ms | 203 ms | About 2.1× faster processing |
| 1,000 span events | 775 ms | 105 ms | About 7.4× faster processing |
| 1,000 spans: SELECT statements | 2,006 | 14 | Fewer per-event reads |
| 10,000-item Run initial JSON | 71.44 MiB | 12.14 MiB | 83% fewer transferred bytes |
| 10,000-item Run Python peak | 163.13 MiB | 38.91 MiB | 76% lower measured peak |
| Dashboard: 1,000 runs × 50 items | 275 ms / 906 KB | 168 ms / 138 KB | Old full history vs first page with global overview |
| Models: 10,000 items × 5 runs | 3,055 ms | 19 ms | Indexed calculation only; excludes layout/network |
| Compare: 10,000 items × 2 runs | 859 ms | 4.3 ms | Lookup pass including index construction |
| 100 mocked judge calls | 227 ms / 100 clients | 80 ms / 1 client | Framework overhead; no model latency |

Raw samples and SQL counts are under `artifacts/p1-validation/`. Workstation
contention affected elapsed times; ingestion SQL counts were identical across
samples. The 1,000-item source-write probe measured 70.30 → 77.11 ms (+9.7%) for
durable capture. This added write cost is included in the faster ingestion
processor measurements above. The new worker itself projected 1,000 items in
171 ms / 159 statements; the original release had no worker, so this is not a
before/after release speedup.

## Verification

The full suite includes SDK, platform, real Chromium, accessibility, and
PostgreSQL cases. Separate tests verify database upgrade/downgrade with populated
data, actual app worker startup/shutdown/restart, real SDK-to-ASGI ingestion and
authenticated SDK-to-Docker HTTP ingestion through PostgreSQL.

Differential tests compare complete numerical outputs, metric types,
denominators, repeats, full-scope filters, text search, sorting, selection,
root-cause/review edits, trace links, deep links, and CSV/HTML export content.
Adversarial tests cover duplicate/reordered events, rollback, concurrency, lost
acknowledgements, cancellation, disk pressure/failure, deletion/restoration,
late events, repair, backfill with live writes and terminal publication.

Validation was repeated after integrating main: **1,200 passed, 8 skipped, and
one existing external SDK fixture failed**. All platform tests passed. Final counts and exact commands
are recorded in `artifacts/p1-validation/README.md` and the test XML reports.
CI runs the complete suite with PostgreSQL and Chromium on Python 3.9, 3.11 and
3.12, then builds both distributions twice and checks their contents. Package
discovery is restricted to each package's namespace: repeat builds cannot copy
nested build directories or stale migration files into a wheel. Local wheel
checks compare every Python module and the changed dashboard assets with source.

The first complete CI run passed all 1,200 cases on Python 3.11 and 3.12, with
nine skips in each clean checkout. Python 3.9 exposed test-helper compatibility
issues: evaluated union annotations, a FastAPI router-internal assertion, and
an asyncio event shared across worker and test loops. The fixtures now use
Python 3.9-compatible annotations, public OpenAPI paths, and explicit worker
synchronization. The PR checks record the full rerun after these corrections.

## Existing limitations

- A local SDK test imports the separate sibling `sql_eval` checkout and assumes
  its task module exports `AsyncOpenAI`. That external checkout no longer does.
  The same failure was reproduced before these changes; a clean checkout skips
  it when the optional sibling repository is absent.
- The existing SDK mypy run reports baseline errors. The integrated
  comparison found 113 on main and 111 here, with no new diagnostics. This is
  recorded separately from passing runtime tests.
- At 390px, the persistent sidebar squeezes Overview cards and clips tables.
  Baseline/current browser geometry is identical; desktop layouts were visually
  inspected at 1280px and 1440px. This pre-existing responsive limitation remains.
- Optional Traceloop tests skip when that integration is absent. Real OpenTelemetry
  span delivery is covered independently by the SDK/platform integration tests.
