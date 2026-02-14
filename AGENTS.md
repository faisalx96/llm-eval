# Repository Guidelines

This guide explains how to develop, test, and contribute to `qym` (قيِّم).

## Project Structure & Module Organization

This is a monorepo with two independently-buildable packages under `packages/`:

- `packages/sdk/qym/`: SDK Python package (`pip install qym`)
  - `core/`: evaluator orchestration (`Evaluator`, datasets, results)
  - `metrics/`: built-ins and registry for custom metrics
  - `adapters/`: task adapters (functions, LangChain/OpenAI)
  - `platform/`: platform client and defaults
  - `utils/`: errors and HTML/HTTP frontend helpers
  - `server/`: local UIServer + DashboardServer
  - `cli.py`: `qym` entry point
  - `_static/`: UI and dashboard assets
- `packages/platform/qym_platform/`: Platform Python package (`pip install qym-platform`)
  - `api/`: FastAPI route modules (ingest, runs, org, web)
  - `db/`: SQLAlchemy models and session
  - `migrations/`: Alembic migrations
  - `tools/`: import scripts
  - `_static/`: platform-specific UI assets
- `docker/`: Dockerfile, docker-compose, entrypoint
- `tests/`: test suites
  - `sdk/`: SDK unit tests
  - `platform/`: platform unit tests
- `docs/`: user guides (`USER_GUIDE.md`, `METRICS_GUIDE.md`)
- `examples/`: runnable examples and notebooks
- `internal/`: developer docs (error handling, requirements)

## Build, Test, and Development Commands
- Setup (editable + dev tools): `pip install -e packages/sdk[dev] -e packages/platform`
- Run CLI: `qym --help`
- Format: `black . && isort .`
- Type check: `mypy packages/sdk/qym`
- Tests: `pytest -q` (supports `pytest-asyncio`)
- Build SDK wheel: `pip wheel packages/sdk/ --no-deps -w dist/`
- Build platform Docker: `docker compose -f docker/docker-compose.yml build`

Example local run:
```
qym --task-file examples/example.py \
  --task-function my_task --dataset my-set \
  --metrics exact_match,fuzzy_match
```

## Environment Variables
- SDK: `QYM_PLATFORM_URL`, `QYM_API_KEY`, `QYM_PLATFORM_DEBUG`
- Platform: `QYM_ENVIRONMENT`, `QYM_DATABASE_URL`, `QYM_AUTH_MODE`, `QYM_ADMIN_BOOTSTRAP_TOKEN`, `QYM_BASE_URL`
- Langfuse: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`

## Coding Style & Naming Conventions
- Python 3.9+, PEP 8, 4-space indentation.
- Use type hints and concise docstrings.
- Modules/files: `snake_case.py`; classes: `PascalCase`; functions/vars: `snake_case`.
- Keep public APIs minimal; avoid editing generated folders.

## Testing Guidelines
- Framework: `pytest` with `pytest-asyncio` for async paths.
- Place SDK tests in `tests/sdk/` and platform tests in `tests/platform/`.
- Include fast unit tests for metrics and adapters; add an integration test for CLI when practical.

## Commit & Pull Request Guidelines
- Commits: imperative mood, scoped and small; Conventional Commits welcome (e.g., `feat:`, `fix:`).
- PRs: clear description, linked issue (`#123`), before/after notes, and any docs updates.
- Include evidence of testing (command output or saved results JSON/CSV). Do not commit `.env`, `build/`, or `*.egg-info` changes.

## Security & Configuration Tips
- Credentials: set via env vars or `.env` (auto-loaded).
```
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com
```
- `.env` is gitignored; never commit secrets.

## Extending the Framework
- Metrics: add to `packages/sdk/qym/metrics/builtin.py` or register dynamically via `metrics.registry.register_metric(name, func)`.
- Adapters: add under `packages/sdk/qym/adapters/` and wire into `auto_detect_task`.
