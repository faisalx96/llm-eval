# Deployment Guide (qym platform)

This guide covers deploying the **deployed web platform** (FastAPI + Postgres) that hosts:
- the historical runs dashboard
- the live run UI (remote streaming)

## Docker Compose (recommended for internal dev)

From repo root:

```bash
docker compose -f docker/docker-compose.yml up --build
```

The platform will be available at `http://localhost:8000`.

## Required environment variables

Set these on the platform service (`api`):
- `QYM_DATABASE_URL`: SQLAlchemy URL (Postgres required)
- `QYM_BASE_URL`: public base URL used to generate `live_url`
- `QYM_ADMIN_BOOTSTRAP_TOKEN`: one-time bootstrap token for first admin user
- `QYM_AUTH_MODE`: `none` (default) or `proxy` (reverse-proxy headers)

## Health check

- `GET /healthz` should return `{ "ok": true, ... }`

## Migrations

The container entrypoint runs:

```bash
alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head
```

If you run migrations manually:

```bash
alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head
```

## Windows / WSL note

If the `api` container exits with `exec /entrypoint.sh: no such file or directory`, the entrypoint script likely has Windows-style line endings (CRLF). Fix with:

```bash
sed -i 's/\r$//' docker/entrypoint.sh
```

Then rebuild: `docker compose -f docker/docker-compose.yml up --build`


