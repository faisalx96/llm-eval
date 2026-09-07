# P1 validation evidence

See [the validation report](../../docs/internal/P1_VALIDATION.md) for behavior,
measurements, deployment and existing limitations. Work is isolated in
`codex/p1-performance`; main's `9325874` changes are integrated.

`test-results.json` summarizes the final XML files. Focused suites overlap the
full suite and must not be added together as a count of unique tests.

Final local result: **1,200 passed, 8 skipped, 1 existing external SDK fixture
failure** in 243.51 seconds. All platform tests passed. The frozen Run/Compare
file and full frontend suite also pass independently.

| Evidence | Scope |
|---|---|
| `integrated-full.xml` | Complete SDK/platform suite, real Chromium and PostgreSQL |
| `frontend.xml` | 178 frontend, design, accessibility and upstream issue-contract checks |
| `frontend-final-file.xml` | 17 frozen Run/Compare browser cases |
| `frontend-issue-integration.xml` | Actual source/API issue counts and pass-scope preservation |
| `integrated-migrations-lifecycle.xml` | 12 migration/lifecycle cases, including populated PostgreSQL roundtrips |
| `dashboard-structured-issues.xml` | 8 SQLite/PostgreSQL issue/provenance and summary-parity cases |
| `dashboard-durability-final.xml` | 60 passing durability cases; 3 SQLite concurrency cases skip |
| `python39-sdk.xml` | 283 passing SDK cases; the existing external fixture fails |
| `python39-integration.xml` | 223 passing API, ingestion, projection and delivery cases |
| `python39-integrated.xml` | 35 passing cases after integration with main |
| `container-sdk-smoke.jsonl` | Real authenticated SDK → Docker Python 3.11 → PostgreSQL → summary worker |
| `docker-runtime-manifest.json` | 43 changed runtime files match the built image byte for byte |
| `wheel-content.json` | Repeated wheel builds contain current modules/assets and no stale build namespaces |
| `type-check-comparison.json` | Main: 113 SDK mypy diagnostics; branch: 111; none newly introduced |
| `screenshots/` | Desktop visual inspection and unchanged 390px baseline clipping |

The complete local suite's external SDK fixture imports the sibling `sql_eval`
repository and assumes an `AsyncOpenAI` export that its current task module does
not have. The same failure occurs on the original checkout. Clean checkouts skip
that optional external test. Other skips are optional Traceloop integration and
SQLite cases whose concurrency/pool behavior is exercised on PostgreSQL.

Run the full suite against a disposable PostgreSQL database:

```sh
QYM_DATABASE_URL=sqlite:///:memory: QYM_ENVIRONMENT=test \
QYM_TEST_POSTGRES_URL="<disposable PostgreSQL SQLAlchemy URL>" CI=1 \
.venv/bin/pytest -q --junitxml=artifacts/p1-validation/integrated-full.xml
```

Test tools are installed separately from production dependencies:

```sh
python -m pip install -e packages/sdk -e packages/platform \
  pytest pytest-asyncio hypothesis playwright axe-playwright-python build
python -m playwright install chromium
```

CI installs Chromium's OS dependencies too, runs the suite on Python 3.9, 3.11
and 3.12 with PostgreSQL 16, builds both wheels twice, and checks their contents.

Benchmark scripts and JSON results are included. `ingest-sameenv-*` uses the
same Python 3.12.8 interpreter/dependencies for original and final sources,
fresh SQLite databases and three samples. The frontend benchmark uses the fixed
`b1d1d005` baseline and excludes DOM/layout/network. The compact payload probe
uses synthetic text. Judge requests are mocked, so its speedup describes client
overhead. Source-write results include the outbox's added cost. Initial-vs-final
worker measurements compare iterations of the new worker, not two releases.

`baseline-*.xml` and `pre-integration-full.xml` preserve earlier baseline and
integration evidence. Baseline environment/timing harness corrections are
separately recorded in `baseline-env-timing-recheck.xml`. Intermediate logs remain
local and ignored by Git; they are not passing release evidence.
