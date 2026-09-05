# P1 performance implementation plan

Authorized on 5 September 2026. Worktree `/Users/faisalbh/qym-p1-performance`, branch `codex/p1-performance`, base `b1d1d00587df4fcf0e70875c29b0bb0cbc20172c`.

Integrated main `9325874` before publication. Its structured root-cause issues and migrations are preserved; the P1 migrations follow as `0047` and `0048`. See [validation](P1_VALIDATION.md) for measured results and compatibility limits.

The release must preserve platform behavior and logical content. Faster responses must not change scores, estimators, denominators, counts, repeat-pass identity, filtering, permissions, edits, exports, or the user's navigation context. Existing full-data API consumers remain compatible while browser clients adopt bounded APIs.

## Work order

1. **Baseline and isolated validation.** Capture the base source, dependency versions, complete test results, PostgreSQL migration results and browser behavior. Use a dedicated Python environment and PostgreSQL container. Never use the production database or repository `.env`.
2. **Independent P1 changes.** Implement indexed Models/Compare lookups, owned reusable judge clients, asynchronous SDK upload finalization with bounded memory, off-loop ingestion and batched identity queries, and incremental live trace updates. Validate each against the original behavior before integration.
3. **Run-detail data contract.** Introduce bounded item pages and on-demand text/pass detail. Preserve global search/filter/sort, score distributions, repeat summaries, group estimators, selection, review actions, trace links, deep links and exports. Keep existing full responses available for established SDK/API consumers. Compare must use aligned IDs across pages, never row positions.
4. **Dashboard data contract.** Implement durable summaries and source-mutation updates, bounded history queries and server-side filtering/aggregation. Follow [the summary contract](../DASHBOARD_INCREMENTAL_SUMMARY_CONTRACT.md); duplicate events, corrections, soft deletion, restoration and backfill must converge. Global charts/models and filter options must remain independent of the visible Runs page.
5. **Integration and adversarial testing.** Run all tests, browser workflows, PostgreSQL concurrency/migrations, SDK-to-platform end-to-end ingestion, payload/query scaling checks and before/after benchmarks. Inspect source changes independently and rerun affected checks after corrections.
6. **PR.** Commit coherent changes, push the isolated branch and submit a PR with test evidence, measured improvements, deployment/backfill notes and any remaining limitations. A failing or untested requirement is documented as unfinished, never described as passed.

## Non-negotiable invariants

- Error scores, unscored/in-flight items, missing metrics, boolean/count/percentage metrics, minimizing metrics and metric thresholds retain their current meaning.
- Repeat-pass reduction, per-pass output, retries, late events, duplicate event IDs/sequences and comparison alignment remain correct.
- A full export contains the full filtered dataset, regardless of current page.
- Search, filtering and sort operate over the full intended population. Chart totals and model statistics cannot silently become page-local.
- Review/metric/root-cause edits, deletion/restoration and approvals become visible without stale totals or lost provenance.
- Access checks remain applied before all new summary/page/detail APIs. Cross-project and disabled/revoked credentials cannot gain access through caches.
- Cancellation and upload shutdown do not lose terminal events, allow silent queue overflow or leave owned clients/threads running indefinitely.
- Old API shapes continue to work. New fields explicitly distinguish totals, page counts, revisions and freshness.
- Design tokens, keyboard behavior, focus, scroll position, accessible controls and empty/loading/error states follow `DESIGN_LANGUAGE.md`.

## Validation matrix

| Layer | Required checks |
|---|---|
| Full baseline | Entire SDK and platform suites, including browser tests; record existing failures separately. |
| Differential data tests | Compare old/new summary, row and metric outputs for randomized fixtures, ties, nulls, errors, metric types, multiple projects, repeat passes and corrections. |
| Event ingestion | Duplicate IDs/sequences, reordered events, partial batches, malformed/poison data, concurrent requests, rollback/retry, late spans, pass deletion and restored runs. |
| PostgreSQL | Empty-to-head migration, populated migration, rollback where supported, concurrent ingest/update, query plans and bounded SQL/row loading. SQLite remains a fast unit-test backend, not the only database check. |
| SDK | Concurrent runs, cancellation at each teardown phase, stalled/unavailable platform, byte pressure, large events, spool failure/capacity, retry recovery, owned/injected clients and separate event loops. |
| Browser workflows | Runs/chart/model global totals and filters, page switching, search and sort, compare selection/alignment, run tabs, repeat views, item details, score/root-cause edits, trace navigation, approvals, export and empty/error states. Fail on unexpected console/network errors. |
| Browser interaction | Keyboard/focus, nested scroll restoration, deep links, refresh while editing, navigation away/back, narrow viewport and standard desktop viewport. |
| Performance | SDK overhead and shutdown heartbeat; trace-refresh cost with fixed touched items and growing run; ingestion statements and event-loop delay; initial/detail bytes; comparison scaling; summary reads independent of raw history. |
| Packaging | SDK/platform wheel builds, Docker build, relevant formatting/type checks, design-language enforcement and final clean diff review. |

## Progress

- [x] Isolated branch and worktree created.
- [x] Base source snapshot saved outside the worktree for differential tests.
- [x] Dedicated PostgreSQL container started on localhost port 15439.
- [x] Dedicated Python 3.12 environment installed.
- [x] Baseline suites and migration/browser results recorded.
- [x] Indexed item lookups and regression tests complete.
- [x] SDK upload/client changes and adversarial tests complete.
- [x] Ingestion/trace changes and PostgreSQL tests complete.
- [x] Paged run-detail API and browser integration complete.
- [x] Durable dashboard summaries and bounded browser reads complete.
- [x] Full integration, browser and performance evidence complete; existing external-fixture/type-check/responsive limitations documented.
- [x] Independent review complete.
- [x] [PR #35 submitted](https://github.com/faisalx96/qym/pull/35).
