# Repository Guidelines

This guide explains how to develop, test, and contribute to `qym` (قيِّم).

## Project Structure & Module Organization
- `qym/`: Python package
  - `core/`: evaluator orchestration (`Evaluator`, datasets, results)
  - `metrics/`: built-ins and registry for custom metrics
  - `adapters/`: task adapters (functions, LangChain/OpenAI)
  - `utils/`: errors and HTML/HTTP frontend helpers
  - `cli.py`: `qym` entry point
- `docs/`: user guides (`USER_GUIDE.md`, `METRICS_GUIDE.md`)
- `examples/`: runnable examples and notebooks
- `internal/`: developer docs (error handling, requirements)
- Generated: `build/`, `qym.egg-info/` (do not edit)

## Build, Test, and Development Commands
- Setup (editable + dev tools): `pip install -e .[dev]`
- Run CLI: `qym --help`
- Format: `black . && isort .`
- Type check: `mypy qym`
- Tests: `pytest -q` (supports `pytest-asyncio`)

Example local run:
```
qym --task-file examples/example.py \
  --task-function my_task --dataset my-set \
  --metrics exact_match,fuzzy_match
```

## Coding Style & Naming Conventions
- Python 3.9+, PEP 8, 4-space indentation.
- Use type hints and concise docstrings.
- Modules/files: `snake_case.py`; classes: `PascalCase`; functions/vars: `snake_case`.
- Keep public APIs minimal; avoid editing generated folders.

## Testing Guidelines
- Framework: `pytest` with `pytest-asyncio` for async paths.
- Place tests in `tests/` named `test_*.py`; mirror package layout (e.g., `tests/core/test_evaluator.py`).
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
- Metrics: add to `qym/metrics/builtin.py` or register dynamically via `metrics.registry.register_metric(name, func)`.
- Adapters: add under `qym/adapters/` and wire into `auto_detect_task`.
