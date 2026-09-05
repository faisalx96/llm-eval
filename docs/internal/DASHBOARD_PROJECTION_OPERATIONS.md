# Durable dashboard projections

The browser dashboard reads numerical projections through `/api/dashboard/*`.
The legacy `/api/runs` endpoint remains immediately source-backed for API and CLI
compatibility. Inputs, outputs, trace bodies, score explanations, and analysis
text are not copied into the projection read path.

Migration `0048` creates the durable outbox, numerical record state, run
summaries, hour/day rollups, fixed histogram definitions, partition checkpoints,
and dead-letter tables. It seeds existing run identifiers for asynchronous
backfill. The migration schema is frozen and does not import current ORM models.
PostgreSQL source versions use `BIGINT`; SQLite uses its non-reusing integer
sequence. Event UUIDs independently identify records returned from batched
inserts.

The application starts one `DashboardSummaryWorker` per process and stops it on
shutdown. Each worker owns its sessions. A tick processes at most 20 partitions,
500 events per partition, then bounded dirty-bucket repair and retention. The
poll interval defaults to one second. These constructor limits may be adjusted
when embedding the worker. Database row locks coordinate multiple workers;
shared buckets are locked in the same order, including timestamp corrections.
Backfill locks source rows before its partition, matching the write path.

Each source mutation and its numeric snapshot commit together. Record versions
reject duplicate and older delivery; deletes retain tombstones. Counters and
histograms apply old-to-new deltas in batches. Exact medians and extrema use
numeric state, without reopening source item or trace bodies. Owner names,
approvals, metric specs, and dataset-alias changes enqueue dimension refreshes.
Expired live runs are reconciled in bounded background work using the existing
run-lifecycle rules.

A response includes freshness and publication revision. A source sequence alone
cannot identify a published snapshot because transactions can commit out of
sequence. Run publication counters therefore advance separately, and filtered
view revisions derive from the relevant run counters. A terminal run's previous
published descriptor and numerical values remain visible until its pending
outbox and all backfill source kinds have completed. New terminal historical
runs are published only when their complete numerical snapshot is ready.

The initial late-event horizon is 30 days (`MAX_LATE_EVENT_AGE`). Older events
and invalid schemas enter `dashboard_dead_letters`; persistent processing
failures do so after five attempts. The partition remains `repair_required`, so
freshness never claims it is current. Dead letters retain source identity,
version, and failure details. Normal maintenance prunes only old tombstones and
published outbox records behind settled, unleased partition watermarks. It does
not prune unresolved repair evidence.

After inspecting a failed partition, an operator can request a source rebuild:

```python
from qym_platform.db.session import SessionLocal
from qym_platform.services.dashboard_summaries import request_dashboard_repair

with SessionLocal() as db:
    request_dashboard_repair(db, run_id)
    db.commit()
```

This explicit repair retires snapshots through its durable source-version
boundary, preserves tombstone versions, and resumes bounded source backfill.
Pending old updates cannot resurrect a source-deleted record. The dead-letter
rows remain as evidence. Live writes continue through the transactional outbox.

Validation evidence is in `artifacts/p1-validation/dashboard-durability-final.xml`,
and `artifacts/p1-validation/dashboard-worker-benchmark.json`. The core
suite covers SQLite and PostgreSQL, differential numerical parity with the
legacy endpoint, source rollback, retries, out-of-order commits, root causes,
repeat deletion, alias changes, leases, retention, liveness, migration,
backfill with live updates, concurrent shared buckets, and terminal publication.
