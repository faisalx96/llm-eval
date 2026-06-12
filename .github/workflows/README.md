# CI workflows

`ci.yml` runs on every push and pull request targeting `main`.

## Jobs

### `python-tests` — Python tests (3.11)

The main gate. Installs both packages editable (`packages/sdk`,
`packages/platform`) plus the test deps (`pytest`, `pytest-asyncio` — the
test-relevant subset of the SDK's `[dev]` extra; jupyter/black/mypy are not
needed to run the suite) and runs the **full** suite:

```
pytest tests -q
```

Environment (mirrors what the suite expects; tests must still pin
auth-relevant vars via `monkeypatch`):

| Variable | Value |
| --- | --- |
| `QYM_DATABASE_URL` | `sqlite:///:memory:` |
| `QYM_AUTH_MODE` | `none` |
| `QYM_ENVIRONMENT` | `test` |
| `QYM_AUTO_PROVISION_USERS` | `true` |

There is no escape hatch (`continue-on-error: false` is set explicitly): a red
suite blocks the merge.

### `python-39-floor` — Python 3.9 import floor

Both packages declare `requires-python = ">=3.9"`. This job installs them on
3.9 and does an import-only smoke (`python -c "import qym; import
qym_platform"`) to keep that floor honest without running the full suite twice.

### `migrations-postgres` — Migrations + Postgres tests

Spins up a `postgres:16` service container (`qym`/`qym`/`qym`, health-checked
with `pg_isready`), then:

1. Runs `alembic -c packages/platform/qym_platform/migrations/alembic.ini
   upgrade head` against an **empty** database
   (`postgresql+psycopg2://qym:qym@localhost:5432/qym`) — proving the
   migration chain applies cleanly from scratch.
2. Runs the Postgres-backed test subset via `tools/ci/run_postgres_tests.sh`.

#### Postgres test-marking convention

Tests that need a real PostgreSQL server (not SQLite) are marked:

```python
import pytest

@pytest.mark.postgres
def test_something_pg_specific(...):
    ...
```

The marker is registered in the repo-root `pytest.ini`. CI selects them with
`pytest tests/platform -m postgres`. The helper script treats pytest exit code
5 ("no tests collected") as success, so the job stays green until the first
marked test lands.

### `examples-smoke` — Examples smoke (non-blocking)

Runs `tools/ci/examples_smoke.py`, which for every `examples/**/*.py`:

- byte-compiles the file (syntax check) — **examples are never executed**;
- AST-checks that top-level, unguarded imports resolve against the installed
  packages;
- asserts no top-level `langfuse` import without a `try`/`except` (or
  `if TYPE_CHECKING`) guard;
- asserts no `llm_eval` (legacy package name) import anywhere.

The script exits nonzero on findings. **This is the one allowed soft job**: it
currently runs with `continue-on-error: true` because the examples are known
broken and are being fixed in DOC-5.

> **Planned flip:** once DOC-5 lands, set `continue-on-error: false` on the
> `examples-smoke` job in `ci.yml` to make it blocking.

### `frontend` — Frontend (scaffold)

Scaffold for CI-3. Every step after checkout is guarded with
`if: hashFiles('packages/platform/frontend/package.json') != ''`, so the job
no-ops gracefully until the frontend lands. (The guard must be at step level:
`hashFiles()` evaluates against the runner workspace, which is empty before
checkout.)

Once `packages/platform/frontend/package.json` exists the job runs Node 22
with npm caching: `npm ci`, then `npm run lint` / `test` / `build`
(`--if-present`, so missing scripts no-op until CI-3 defines them — remove
`--if-present` when they exist). Note: `npm ci` and the npm cache require a
committed `package-lock.json`.

## Helper scripts

| Script | Purpose |
| --- | --- |
| `tools/ci/examples_smoke.py` | Static smoke checks for `examples/` (see above). |
| `tools/ci/run_postgres_tests.sh` | Runs `pytest tests/platform -m postgres`, tolerating "no tests collected". |
