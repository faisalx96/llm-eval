<p align="center">
  <img src="https://raw.githubusercontent.com/faisalx96/qym/main/docs/images/qym_logo.png" alt="qym logo" width="320" />
</p>

# qym-platform

`qym-platform` is the web application behind qym's shared evaluation dashboard. It stores run history, exposes APIs for ingest and analysis, and provides the UI for reviewing metrics, traces, and model comparisons.

## What It Provides

- run history and task/model comparisons
- trace viewing and per-item drill-down
- AI-assisted analysis and corrections review
- org, role, and admin workflows
- APIs for streamed SDK ingestion and local uploads

## Quick Start

### Docker

Development with hot reload:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build
```

Production-style baseline:

```bash
docker compose -f docker/docker-compose.yml up --build
```

### Without Docker

Install the package:

```bash
pip install -e packages/platform
```

Set the required environment variables:

```bash
QYM_DATABASE_URL=postgresql+psycopg2://qym:qym@localhost:5432/qym
QYM_BASE_URL=http://localhost:8000
QYM_ADMIN_BOOTSTRAP_TOKEN=test
QYM_AUTH_MODE=none
QYM_LLM_CONFIG_ENCRYPTION_KEY=<fernet-key>
```

Generate a Fernet key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Run migrations and start the app:

```bash
alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head
qym-platform
```

The local app is typically available at [http://localhost:8000](http://localhost:8000).

## Deployment

The platform is a FastAPI + Postgres application that serves:

- the historical runs dashboard
- the live run UI for streamed evaluations
- ingestion and analysis APIs

### Recommended Local Commands

From the repo root:

```bash
# Production-style baseline
docker compose -f docker/docker-compose.yml up --build

# Development with hot reload and bind mounts
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build
```

### Required Environment Variables

Set these on the platform service:

| Variable | Purpose |
|----------|---------|
| `QYM_DATABASE_URL` | SQLAlchemy database URL. Postgres is required. |
| `QYM_BASE_URL` | Public base URL used to generate `live_url` links. |
| `QYM_ADMIN_BOOTSTRAP_TOKEN` | One-time bootstrap token for the first admin user. |
| `QYM_AUTH_MODE` | Use `none` for local dev or `proxy_headers` in deployed environments. |
| `QYM_LLM_CONFIG_ENCRYPTION_KEY` | Fernet key used to encrypt stored user LLM API keys. |

### Migrations

The container entrypoint runs migrations automatically:

```bash
alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head
```

If you run the app manually, run the same command before starting `qym-platform`.

### Health Check

- `GET /healthz` should return `{ "ok": true, ... }`

### Windows / WSL Note

If the `api` container exits with `exec /entrypoint.sh: no such file or directory`, the entrypoint script likely has Windows-style line endings. Fix with:

```bash
sed -i 's/\r$//' docker/entrypoint.sh
```

Then rebuild the container.

## Admin Operations

### Bootstrap the First Admin

1. Set `QYM_ADMIN_BOOTSTRAP_TOKEN` on the platform.
2. Make a request with:
   - `X-Admin-Bootstrap: <token>`
   - `X-User-Email: <your email>`

This creates the first user with role `ADMIN`.

### Admin UI

Navigate to `/admin` to manage the platform. Admins can:

- view, create, and update users
- manage the organization tree as `Sector -> Department -> Team`
- assign team managers
- update platform visibility settings
- rebuild the org closure table when authorization data needs repair

### Organization Model

The platform uses a three-level hierarchy:

- **Sector**: top-level organizational unit
- **Department**: belongs to a sector
- **Team**: belongs to a department

Each user belongs to exactly one team. Team managers can approve or reject runs from their managed teams.

### Platform Settings

Admins can configure:

- **GM/VP Approved-Only Visibility**: GM and VP users only see approved runs
- **Manager Visibility Scope**: managers see either their full subtree or only their direct team

### API Keys

API keys are created per user. In the UI auth context, call:

```bash
POST /v1/me/api-keys
```

The token is returned once and should be stored securely.

### Useful Admin Endpoints

- `GET /v1/admin/users`
- `POST /v1/admin/users`
- `PUT /v1/admin/users/{user_id}`
- `GET /v1/admin/org/tree`
- `GET /v1/admin/org/teams`
- `POST /v1/admin/org/units`
- `PATCH /v1/admin/org/units/{id}`
- `DELETE /v1/admin/org/units/{id}`
- `PUT /v1/admin/org/teams/{id}/manager`
- `POST /v1/admin/org/rebuild-closure`
- `GET /v1/admin/settings`
- `PUT /v1/admin/settings`

### Import Legacy Local Results

From the repo root, after setting `QYM_DATABASE_URL`:

```bash
python -m qym_platform.tools.import_local_results --owner-email you@company.com --results-dir qym_results
```

This ingests local CSV or JSON results into the platform database. Raw artifacts are parsed and ingested, not stored as permanent source files.

## Related Docs

- [Platform User Guide](docs/USER_GUIDE.md)
