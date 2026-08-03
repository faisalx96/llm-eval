<p align="center">
  <img src="https://raw.githubusercontent.com/faisalx96/qym/main/docs/images/qym_logo.png" alt="qym logo" width="320" />
</p>

# qym-platform

`qym-platform` is qym's shared evaluation service and web application. It stores project-scoped runs and datasets, receives live SDK events, and provides dashboards for comparison, review, approval, and analysis.

## What It Provides

- project dashboards for runs, charts, models, reviews, and datasets
- live and historical run details, traces, repeat-pass analysis, and exports
- human review, approval workflows, corrections, and AI-assisted analysis
- versioned datasets with aliases, lineage, comparisons, and item history
- project API keys and encrypted project LLM connections
- SDK ingestion and a product-evaluation API

## Quick Start

Run commands from the repository root.

### Docker

Create a root `.env` for local development:

```dotenv
POSTGRES_USER=qym
POSTGRES_PASSWORD=qym
POSTGRES_DB=qym

QYM_ENVIRONMENT=dev
QYM_BASE_URL=http://localhost:8000
QYM_DATABASE_URL=postgresql+psycopg2://qym:qym@db:5432/qym
QYM_AUTH_MODE=none
QYM_AUTH_LOCAL_ENABLED=false
QYM_ADMIN_BOOTSTRAP_TOKEN=
QYM_AUTH_SESSION_SECRET=
QYM_AUTH_GOOGLE_CLIENT_ID=
QYM_AUTH_GOOGLE_CLIENT_SECRET=
QYM_AUTH_GITHUB_CLIENT_ID=
QYM_AUTH_GITHUB_CLIENT_SECRET=
QYM_LLM_CONFIG_ENCRYPTION_KEY=
```

Start the production-style stack:

```bash
docker compose -f docker/docker-compose.yml up --build
```

For hot reload and source bind mounts:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build
```

The container waits for PostgreSQL, applies Alembic migrations, then starts the API. Open [http://localhost:8000](http://localhost:8000).

### Without Docker

Use Python 3.9+ and a running PostgreSQL server:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e packages/sdk -e packages/platform

export QYM_DATABASE_URL=postgresql+psycopg2://qym:qym@localhost:5432/qym
export QYM_BASE_URL=http://localhost:8000
export QYM_AUTH_MODE=none

alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head
qym-platform
```

`qym-platform` listens on `0.0.0.0:8000` by default. Override this with `QYM_PLATFORM_HOST` and `QYM_PLATFORM_PORT`.

## Database, Migrations, and Backups

PostgreSQL is required; there is no SQLite fallback. Apply migrations before every deployment:

```bash
alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head
```

The Docker entrypoint runs this command automatically. The Compose stack also runs a backup service that writes compressed `pg_dump` files to `QYM_BACKUP_PATH` (default `docker/backups`), every `BACKUP_INTERVAL_HOURS` (default `24`), and removes files older than `BACKUP_KEEP_DAYS` (default `14`). Back up that directory outside the host before treating it as durable disaster recovery.

## Configuration

Settings are read from environment variables or `.env`.

### Core

| Variable | Default | Purpose |
|---|---:|---|
| `QYM_DATABASE_URL` | required | PostgreSQL SQLAlchemy URL. |
| `QYM_ENVIRONMENT` | `dev` | Runtime label; session cookies are secure outside `dev`, `test`, and `local`. |
| `QYM_BASE_URL` | `http://localhost:8000` | Public origin used for generated links, OIDC callbacks, and same-origin checks. |
| `QYM_ROOT_PATH` | empty | Mount prefix when served below a reverse-proxy path, such as `/qym`. |
| `QYM_HIDDEN_TASKS` | empty | Comma-separated task names hidden from run listings. |
| `QYM_RUN_STALE_TIMEOUT_SECONDS` | `60` | Seconds without events before a viewed `RUNNING` run becomes `STOPPED` with reason `lease_timeout`; minimum `5`. |
| `QYM_LLM_CONFIG_ENCRYPTION_KEY` | empty | Fernet key required before storing project LLM credentials. |
| `QYM_PLATFORM_HOST` | `0.0.0.0` | Bind host used by the `qym-platform` command. |
| `QYM_PLATFORM_PORT` | `8000` | Bind port used by the `qym-platform` command. |

Generate a Fernet key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

For SDK streaming and platform-launched SDK work against a private HTTPS origin, set `QYM_PLATFORM_CA_BUNDLE` to a CA bundle. `QYM_PLATFORM_SSL_VERIFY=false` disables verification and should only be used for local troubleshooting. `QYM_CA_BUNDLE` and `QYM_SSL_VERIFY` are fallback aliases. Current platform-dataset downloads use Python's default URL trust store and do not apply the custom CA-bundle setting; install the CA into the process trust store when those downloads also target a private certificate.

### Authentication

| Variable | Default | Purpose |
|---|---:|---|
| `QYM_AUTH_MODE` | `none` | `none`, `proxy_headers`, or `oidc`. |
| `QYM_ADMIN_BOOTSTRAP_TOKEN` | empty | One-time token for promoting the first admin. |
| `QYM_AUTO_PROVISION_USERS` | `true` | Create unknown users received from trusted proxy headers. |
| `QYM_AUTH_SESSION_SECRET` | empty | Required whenever OIDC or local password auth enables browser sessions. |
| `QYM_AUTH_LOCAL_ENABLED` | `false` | Enable email/password sign-up and login when auth mode is not `none`. |
| `QYM_AUTH_GOOGLE_CLIENT_ID` / `QYM_AUTH_GOOGLE_CLIENT_SECRET` | empty | Enable Google login in `oidc` mode. |
| `QYM_AUTH_GITHUB_CLIENT_ID` / `QYM_AUTH_GITHUB_CLIENT_SECRET` | empty | Enable GitHub login in `oidc` mode. |

Auth modes:

- `none` is for local development. It creates or reuses `dev@local` as an `ADMIN` and accepts no identity headers.
- `proxy_headers` trusts `X-User-Email` or `X-Email` from an identity-aware reverse proxy. Block direct access to the application so clients cannot spoof these headers.
- `oidc` provides native Google and/or GitHub login. Register `${QYM_BASE_URL}/v1/auth/callback/google` or `${QYM_BASE_URL}/v1/auth/callback/github` with the provider. Enterprise SSO/SAML is not implemented.
- `QYM_AUTH_LOCAL_ENABLED=true` adds local email/password sessions alongside `proxy_headers` or `oidc`.

In session-based modes, `QYM_BASE_URL` must match the browser origin. Browser writes without Bearer authentication are restricted to that origin.

To bootstrap the first admin, set `QYM_ADMIN_BOOTSTRAP_TOKEN`, sign in, and use the bootstrap prompt or call `POST /v1/auth/bootstrap-admin` with `{"bootstrap_token":"..."}`. In `proxy_headers` mode, when no user exists, a request containing `X-User-Email` and matching `X-Admin-Bootstrap` headers can create the first admin directly.

## Projects and Access

The platform has two role layers:

| Layer | Roles | Access |
|---|---|---|
| Platform | `MEMBER`, `ADMIN` | Admins manage users and projects, access every project, and restore deleted runs. |
| Project | `MEMBER`, `MANAGER` | Members work with project runs, reviews, datasets, API keys, and LLM connections. Managers also manage membership and approve or reject submitted runs. |

An admin or an existing project manager can create a project; its creator becomes a manager. A project must always retain at least one manager. Projects containing runs are archived instead of physically deleted.

### Project API Keys

Create keys under **Project Settings → API Keys** or `POST /v1/projects/{project_id}/api-keys`. The plaintext token is shown once; only a PBKDF2 hash and display prefix are stored. Use it as a Bearer token:

```bash
export QYM_BASE_URL=https://qym.example.com
export QYM_API_KEY=<project-api-key>
qym config check --json
```

Keys are bound to one project. The stored `scopes` field is descriptive metadata only: scope enforcement is currently disabled, so every valid non-revoked key has the same API-key permissions within its project.

### Project LLM Connections

Project members configure OpenAI-compatible connections under **Project Settings → LLM Connections**. Connections can be tested and one is selected as the project default for AI analysis. `QYM_LLM_CONFIG_ENCRYPTION_KEY` must be configured before an API key can be stored; secrets are encrypted and never returned by the API.

## Runs and Reviews

SDK clients stream runs when `QYM_BASE_URL` and a project `QYM_API_KEY` are set. Runs can be `DRAFT`, `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `STOPPED`, `SUBMITTED`, `APPROVED`, or `REJECTED`.

- The run owner can submit a completed, failed, or previously rejected run.
- A project manager or platform admin can approve, reject, unapprove, or unreject it.
- `samples=k` creates one logical run with `k` sequential passes, per-pass results, Pass@k/Pass^k analysis, uncertainty, and consistency data.
- A stale live run is reconciled to `STOPPED` with reason `lease_timeout`; a later live event can reopen it.
- Deletion is soft. The owner, a project manager, or an admin can delete a run; only an admin can restore it from **Deleted Runs**. Actions are audit logged.

Reviews support filtering, human corrections, root-cause revisions, approval decisions, bulk operations, and AI-assisted analysis. AI analysis uses the project's default LLM connection and browser/session authentication.

## Datasets

Datasets are project-scoped and versioned:

- draft versions are mutable; publishing requires at least one item
- aliases can point only to published versions; `QymDataset("name")` resolves the `production` alias by default
- uploads accept CSV or JSONL, and downloads use JSONL
- versions support cloning, lineage, metadata updates, comparison, and human-friendly immutable `vN` names
- items support CRUD, bulk edits, revisions, neighbors, lineage, and run history

Use the dashboard's **Datasets** page or the `/v1/datasets` API. SDK dataset access uses the same `QYM_BASE_URL` and project API key.

## Product Evaluation API

`POST /v1/product-evals` starts an asynchronous preset evaluation using a project Bearer key. Poll `GET /v1/product-evals/{eval_id}` and stop it with `POST /v1/product-evals/{eval_id}/stop`. The legacy `/v1/product-evals/jobs/{job_id}` status and stop routes remain available.

The `insightor` preset is the default. `run_count` may be `1`–`100`; values above one create a single native `samples=run_count` run, not separate dashboard runs.

| Variable | Default | Purpose |
|---|---:|---|
| `QYM_PRODUCT_EVAL_MAX_WORKERS` | `3` | Maximum in-flight product-evaluation jobs. |
| `QYM_PRODUCT_EVAL_MAX_CONCURRENCY` | `10` | Per-evaluation task concurrency, maximum `20`. |
| `QYM_PRODUCT_EVAL_TIMEOUT` | `900` | Task timeout in seconds, maximum `900`. |
| `QYM_PRODUCT_EVAL_MAX_RETRIES` | `1` | Task retries, range `0`–`2`. |
| `QYM_PRODUCT_EVAL_METRIC_TIMEOUT` | `300` | Metric timeout in seconds. |
| `QYM_PRODUCT_EVAL_RUN_COUNT` | `3` | Default sample/pass count, range `1`–`100`. |
| `QYM_PRODUCT_EVAL_DEFAULT_DATASET` | `playground_set_v2` | Default platform dataset for the `insightor` preset. |
| `QYM_PRODUCT_EVAL_MAX_PARALLEL_RUNS` | `1` | Compatibility multiplier used by the effective-concurrency safety limit; range `1`–`3`. |
| `QYM_INSIGHTOR_EVAL_SCRIPT` | repository `insightor_eval.py` | Optional path to an alternative preset script. |

`QYM_PRODUCT_EVAL_MAX_CONCURRENCY × QYM_PRODUCT_EVAL_MAX_PARALLEL_RUNS` cannot exceed `20`. Request fields select runtime inputs; clients cannot override server-controlled evaluator configuration.

## Service Endpoints

| Endpoint | Purpose |
|---|---|
| `/` | Project dashboard. |
| `/docs-guide` | In-app product and SDK documentation. |
| `/healthz` | Health response: `{"ok":true,"service":"qym-platform","env":"..."}`. |
| `/api-docs` | Interactive FastAPI documentation. |
| `/openapi.json` | OpenAPI schema. |

When deployed under a prefix, configure both the proxy and `QYM_ROOT_PATH`; set `QYM_BASE_URL` to the complete public URL including that prefix.

## Import Legacy Local Results

After setting `QYM_DATABASE_URL`, import local CSV or JSON results with:

```bash
python -m qym_platform.tools.import_local_results \
  --owner-email you@company.com \
  --results-dir qym_results
```

Parsed records are written to PostgreSQL; source files are not retained as permanent artifacts.

## Related Documentation

- [Platform User Guide](docs/USER_GUIDE.md)
- [Product Evaluation API Guide](docs/PRODUCT_EVAL_API_GUIDE.md)
- [Product Evaluation Client Guide](docs/PRODUCT_EVAL_API_CLIENT_GUIDE.md)
- [SDK README](../sdk/README.md)
