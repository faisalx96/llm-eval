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
- `QYM_DATABASE_URL`: SQLAlchemy URL (Postgres recommended)
- `QYM_BASE_URL`: public base URL used to generate `live_url`
- `QYM_ADMIN_BOOTSTRAP_TOKEN`: one-time bootstrap token for first admin user

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


