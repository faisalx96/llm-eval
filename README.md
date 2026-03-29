<p align="center">
  <img src="docs/images/qym_logo.png" alt="qym logo" width="400" />
</p>

---

<h3 align="center">A Fast, Async Framework for LLM Evaluation</h3>

<p align="center">
  <img src="docs/images/qym_icon.png" alt="" height="20" />
  &nbsp;
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.9+-3776AB.svg" alt="Python 3.9+" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT" /></a>
</p>

## Project Structure

This is a monorepo with two packages:

```
packages/
  sdk/        # qym — the Python SDK (pip install qym)
  platform/   # qym_platform — the web dashboard (FastAPI + Postgres)
docker/       # Docker Compose setup for the platform
docs/         # Guides and documentation
examples/     # Runnable example scripts
```

| Package | Description | Install |
|---------|-------------|---------|
| **SDK** (`packages/sdk`) | Evaluation framework — task runner, metrics, CLI | `pip install qym` |
| **Platform** (`packages/platform`) | Web dashboard — run history, comparison, admin | Docker Compose or `pip install -e packages/platform` |

**End users:** See the [SDK README](packages/sdk/README.md) for installation and usage.

## Development Setup

### SDK

```bash
pip install -e packages/sdk
```

### Platform

**With Docker (development, hot reload):**

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build
```

Platform available at http://localhost:8000.

**With Docker (production-style baseline):**

```bash
docker compose -f docker/docker-compose.yml up --build
```

**Without Docker:**

```bash
pip install -e packages/platform
```

Set environment variables:

```bash
QYM_DATABASE_URL=postgresql+psycopg2://qym:qym@localhost:5432/qym
QYM_ADMIN_BOOTSTRAP_TOKEN=test
QYM_AUTH_MODE=none
QYM_LLM_CONFIG_ENCRYPTION_KEY=<fernet-key>
```

Run migrations and start:

```bash
alembic -c packages/platform/qym_platform/migrations/alembic.ini upgrade head
qym-platform
```

### Environment Variables

Copy the template and fill in your values:

```bash
cp .env.template .env
```

| Variable | Used By | Description |
|----------|---------|-------------|
| `LANGFUSE_PUBLIC_KEY` | SDK | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | SDK | Langfuse secret key |
| `LANGFUSE_HOST` | SDK | Langfuse host URL |
| `QYM_API_KEY` | SDK | API key for platform streaming |
| `QYM_PLATFORM_URL` | SDK | Platform URL (default: `http://localhost:8000`) |
| `QYM_JUDGE_MODEL` | SDK | Model name for LLM judge metrics (or pass `judge_model` per judge) |
| `QYM_JUDGE_API_KEY` | SDK | API key for LLM judge metrics (or pass `judge_api_key` per judge) |
| `QYM_JUDGE_BASE_URL` | SDK | Base URL for LLM judge metrics (optional, or pass `judge_base_url` per judge) |
| `QYM_DATABASE_URL` | Platform | PostgreSQL connection string |
| `QYM_ADMIN_BOOTSTRAP_TOKEN` | Platform | One-time token for first admin user |
| `QYM_AUTH_MODE` | Platform | `none` (local dev) or `proxy_headers` |
| `QYM_LLM_CONFIG_ENCRYPTION_KEY` | Platform | Fernet key used to encrypt stored user LLM API keys |

## Documentation

**SDK (end users):**
- [SDK README](packages/sdk/README.md) - Installation and usage
- [User Guide](packages/sdk/docs/USER_GUIDE.md) - Tasks, metrics, datasets, CLI, configuration
- [Metrics Guide](packages/sdk/docs/METRICS_GUIDE.md) - 40+ metrics by use case, including LLM-as-judge
- [Auto-Instrumentation Guide](packages/sdk/docs/AUTO_INSTRUMENTATION_GUIDE.md) - Automatic LLM call tracing

**Platform (operators):**
- [Platform User Guide](docs/PLATFORM_USER_GUIDE.md) - Dashboard, trace viewer, AI analysis, corrections review, roles, approval workflows
- [Deployment Guide](docs/DEPLOYMENT_GUIDE.md) - Production deployment
- [Admin Guide](docs/ADMIN_GUIDE.md) - User management, org structure, settings

## License

MIT
