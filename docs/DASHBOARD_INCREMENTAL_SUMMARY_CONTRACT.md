# Incremental Dashboard Summary Contract

Status: design contract. This document defines the smallest durable state
needed to keep dashboard reads independent of lifetime history. It does not
authorize a runtime implementation by itself.

## Goals

- Normal dashboard reads touch only run summaries, time buckets, and small
  numeric dictionaries.
- Source mutations become visible within the configured freshness target
  (normally a few seconds).
- Retries, corrections, deletes, restores, duplicate events, and out-of-order
  delivery cannot silently drift totals.
- Raw payloads are never copied into the dashboard read path.
- A one-time backfill can seed existing history while new writes continue.

## Terms and identity

- `project_key`, `run_key`, `record_key`, `metric_key`, and `slice_key` are
  numeric or stable surrogate keys. Labels remain in source/dimension tables.
- A time bucket is UTC and has an explicit start and duration. The initial
  supported granularities are `hour` for live activity and `day` for history.
- A slice is an explicitly supported dashboard grouping. The implementation
  must not create an unbounded cross-product of every possible dimension.
- `source_version` is a durable database sequence allocated by the source
  transaction. It is not a wall-clock timestamp. Events are published only
  after their source transaction commits. Gaps are valid; ordering is by the
  numeric version.

## Durable tables

The exact SQL types may vary by database, but the keys and invariants are
mandatory.

### `dashboard_change_events`

One row is written in the same transaction as the source mutation.

```text
event_id              unique identifier, primary key
project_key           numeric
partition_key         numeric, run or time-bucket partition
record_key            numeric/stable identifier
metric_key            numeric or null for execution facts
pass_number           integer
source_version        bigint, allocated source sequence
operation             UPSERT or DELETE
numeric_contribution  fixed numeric columns; no raw JSON/text payload
created_at            timestamp
published_at          timestamp nullable
attempt_count         integer
```

`event_id` is unique. The event is a durable outbox record, not an in-memory
notification.

### `dashboard_record_state`

This is worker bookkeeping, not a dashboard response. It stores the last
accepted numeric snapshot for each mutable execution contribution.

```text
project_key           numeric
record_key            numeric/stable identifier
metric_key            numeric or null
pass_number           integer
run_key               numeric
bucket_key            numeric
applied_source_version bigint
present               boolean
observed              integer
terminal              integer
success               integer
error                 integer
retry_count           bigint
latency_ms            numeric nullable
score                 numeric nullable
score_bucket          integer nullable
updated_at            timestamp
```

The primary key covers project, record, metric, and pass. A delete is a
tombstoned snapshot (`present=false`), not an event that removes the state
needed to reject late delivery. Tombstones remain through the late-event
horizon.

### `dashboard_run_summaries`

One row per run for live status, recent runs, and run detail headers. It stores
only numeric counters, sums, extrema state, histogram references, and the
latest applied revision.

### `dashboard_bucket_rollups`

One row per supported project/slice/time-bucket combination. It contains:

```text
count, terminal_count, success_count, error_count, retry_sum
latency_count, latency_sum, latency_sum_squares
score_count, score_sum, score_sum_squares
latency_min, latency_max, score_min, score_max
extrema_state, extrema_verified_version, dirty_since_version
applied_source_version, updated_at
```

Histograms are child rows keyed by rollup and fixed `bucket_index`, with a
numeric count. Histogram definitions are versioned and immutable. A histogram
change is a new definition, never a silent reinterpretation of old buckets.

### `dashboard_partition_state`

One row per project/run or project/time-bucket partition:

```text
partition_key, last_enqueued_version, last_applied_version
oldest_pending_event, queue_state, lease_owner, lease_until
last_error, retry_count, updated_at
```

This is the freshness boundary. A noisy run must not block unrelated buckets.

### `dashboard_dead_letters`

Events that exceed retry limits, violate the late-event policy, or fail schema
validation are retained with the error and source version. They are visible to
operations and never silently discarded.

## Event application contract

The worker processes one partition lease at a time. Within a database
transaction it:

1. Locks the record-state row and reads its last accepted version.
2. Ignores the event when `source_version <= applied_source_version`.
3. Otherwise computes `new_contribution - old_contribution` from the two
   numeric snapshots.
4. Applies the delta to the run and bucket rows using database-level atomic
   expressions (`value = value + delta`), or serializes the partition so no
   read-modify-write race is possible.
5. Stores the new record snapshot and source version.
6. Advances the partition watermark and commits all changes together.

An event can therefore be retried or delivered out of order without changing
the final state. A unique event ID is a secondary duplicate guard; version
comparison is the correctness mechanism.

## Extrema contract

Counts, sums, status totals, and histogram bins are delta-safe. Scalar
min/max values are not.

Each extrema pair has one of these states:

- `valid`: the value is exact at `extrema_verified_version`.
- `dirty_known`: a mutation invalidated a known candidate.
- `rebuilding`: a worker has claimed the repair.
- `unknown`: the bucket has not yet completed backfill or validation.

When the state is not `valid`, the API returns `value: null` and the state and
revision metadata. The UI must display an explicit updating/unavailable state;
it must never present the previous value as current truth.

Extrema repair runs only for the affected bucket. It uses the indexed numeric
record-state rows (`ORDER BY value LIMIT 1` in each direction), never a normal
dashboard request. A successful repair writes both extrema and the verified
source version atomically.

`dirty_known` means a specific mutation invalidated a candidate. `unknown`
means the projection has not established truth yet; the two states must not be
collapsed into one generic dirty flag.

## Retention and late events

Record state and tombstones are retained through `MAX_LATE_EVENT_AGE`, a
configured deployment value (recommended initial value: 30 days). Pruning is
partitioned and checkpointed.

An event older than the horizon is not best-effort applied. It is placed in the
dead-letter table and the affected run/bucket is marked for an explicit
backfill or operator-approved repair. Pruning never runs ahead of the source
watermark or an active repair.

## Reconciliation and backfill

Reconciliation consumes only dirty partitions, retry queues, and dead letters.
It does not periodically compare every source row with every rollup.

Backfill takes a source-version snapshot, seeds bounded partitions from that
snapshot, then drains events newer than the snapshot. It can pause and resume
from partition checkpoints and does not block live writes.

## Read and cache contract

Normal dashboard endpoints read summaries and at most a bounded number of
recent rows. They never scan raw history. Every response includes the block
revision and whether any requested block is updating or stale.

Cache keys include project, filter/slice, time window, and block revision.
Changes invalidate affected run and bucket blocks. A small project-total block
may also be invalidated when its dependent bucket changes; a global cache flush
is not required for every source mutation.

## Required tests before implementation is enabled

- duplicate and out-of-order versions converge to one result;
- concurrent events for one bucket cannot lose increments;
- deleting or raising the current min/max marks only that bucket dirty and
  repairs it from numeric state;
- tombstones reject late events after deletion;
- events beyond the lateness horizon enter the dead-letter table;
- partition watermarks isolate a hot run;
- cache invalidation does not evict unrelated run/bucket blocks;
- normal dashboard SQL does not read raw payload or history tables;
- backfill plus live events produces the same result as a clean rebuild on a
  bounded fixture.
