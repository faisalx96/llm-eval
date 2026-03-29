# Deployment Guide (qym platform)

This guide covers deploying the **deployed web platform** (FastAPI + Postgres) that hosts:
- the historical runs dashboard
- the live run UI (remote streaming)

## Docker Compose

From repo root:

Production-style baseline:

```bash
docker compose -f docker/docker-compose.yml up --build
```

The platform will be available at `http://localhost:8000`.

Development with hot reload and bind mounts:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build
```

## Required environment variables

Set these on the platform service (`api`):
- `QYM_DATABASE_URL`: SQLAlchemy URL (Postgres required)
- `QYM_BASE_URL`: public base URL used to generate `live_url`
- `QYM_ADMIN_BOOTSTRAP_TOKEN`: one-time bootstrap token for first admin user
- `QYM_AUTH_MODE`: use `proxy_headers` in deployed environments
- `QYM_LLM_CONFIG_ENCRYPTION_KEY`: Fernet key used to encrypt stored user LLM API keys

## Health check

- `GET /healthz` should return `{ "ok": true, ... }`

## Migrations

The container entrypoint runs:

```bash
alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head
```

It then starts plain Uvicorn without reload flags. Reload is only enabled by the development Compose override.

If you run migrations manually:

```bash
alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head
```

## Windows / WSL note

If the `api` container exits with `exec /entrypoint.sh: no such file or directory`, the entrypoint script likely has Windows-style line endings (CRLF). Fix with:

```bash
sed -i 's/\r$//' docker/entrypoint.sh
```

Then rebuild:

- production-style: `docker compose -f docker/docker-compose.yml up --build`
- development: `docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build`

