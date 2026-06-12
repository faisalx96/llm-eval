# Phase 0 Handoff — from the stood-down session (2026-06-11, ~23:50)

A second Claude session (this one) implemented OVERHAUL_PLAN.md **Phase 0** before discovering another session owns the plan. It has now **stood down**. This file lists exactly what it changed so the owning session can absorb, keep, or redo it. Delete this file once absorbed.

## What this session changed (all uncommitted, in the working tree)

### Direct edits (main loop)
- `packages/platform/qym_platform/docs_site.py` — added leading-`/` (absolute path) rejection in `_is_unsafe_request_path` (the pre-existing SEC-1 fix missed `/etc/passwd`-style paths because it stripped slashes before checking). All 18 tests in `tests/platform/test_docs_security.py` passed after this.
- `tests/conftest.py` — replaced unconditional `sys.modules` mocking of installed packages (`rich` broke `httpx`/TestClient imports suite-wide) with mock-only-if-missing. NOTE: the owning session has since layered env-isolation (`pytest_configure` pinning `QYM_DATABASE_URL`/`QYM_ENVIRONMENT`/`QYM_AUTH_MODE`) on top — current file is the merged version, keep it.
- venv: installed `pytest`, `pytest-asyncio`, `typer` (was missing, broke `tests/sdk/test_docs_generation.py` collection).

### Workflow agents (Phase 0 scope, per OVERHAUL_PLAN Phase 0 table)
- **SEC-3 / SEC-4** — `qym_platform/settings.py`, `auth.py`, `app.py`, `api/auth.py`, `docker/docker-compose.yml`, `docker/docker-compose.dev.yml`:
  startup fail-fast on `auth_mode` ∈ {none/empty/unknown} outside dev-like `QYM_ENVIRONMENT` (reuses `url_guard.is_dev_environment`); `X-Qym-Proxy-Secret` required (hmac.compare_digest) in proxy_headers mode; identity headers no longer honored in other modes; `auto_provision_users` default False; compose: `${QYM_AUTH_MODE:-proxy_headers}` restored, Postgres bound to `127.0.0.1:5432`, proxy-secret/environment passthrough; constant-time bootstrap-token compare. Tests: `tests/platform/test_auth_hardening.py`. Side effect: many `tests/platform/*` files updated to pin `QYM_ENVIRONMENT=test` where they use `QYM_AUTH_MODE=none`.
- **HP-1 / HP-2** — `packages/sdk/qym/cli/run.py` (`show_table`→`show_tui`, dropped `show_progress`), `cli/_platform_api.py` + `cli/analyze.py` (route + response keys), `qym_platform/api/analysis.py` (bearer-or-session auth on analyze endpoints). Tests: `tests/sdk/test_cli_run_create.py`, `tests/sdk/test_cli_analyze.py`, `tests/platform/test_analyze_auth.py`.
- **HP-3** — `.env.template` rewritten → moved to `docker/.env.template` (LANGFUSE block dropped); references updated in `README.md`, `packages/platform/README.md`, `docs_portal/docs/contributors/local-development.mdx`, `docs_portal/docs/deploy-operate/docker-deployment.mdx`. Guard test: `tests/platform/test_env_template.py` (asserts every `${VAR}` in both compose files is documented in the template).
- **HYG + SEC-1b** — deleted: `api/org.py` (verified unmounted), `_static/dashboard/mock_navigation*.html`, `_static/dashboard/mocks/`, tracked `outputs/` decks (~23MB). `.dockerignore`: ensured `.git`, `outputs`, `tmp` excluded. Guard test: `tests/platform/test_repo_hygiene.py`.
- **SEC-2 tests** — `tests/platform/test_llm_connections_security.py` (url_guard unit tests + manager-only + `__KEEP__`-on-URL-change endpoint tests). ⚠️ OVERLAP: the owning session created `tests/platform/test_llm_connections.py` minutes later — **two parallel suites cover the same thing; keep one, delete the other.**
- **HP-4/HP-5 regression tests** — `tests/sdk/test_run_started_event.py`, `tests/sdk/test_executor_cleanup.py`; small follow-up in `packages/sdk/qym/core/multi_runner.py` (executor shutdown symmetry).

### Not finished / unknown state
- The workflow's final verify+review stage may not have completed when work stopped (last agent activity 23:39). Treat the above as **implemented but not fully re-verified**: run `tests/platform/test_auth_hardening.py test_analyze_auth.py test_env_template.py test_repo_hygiene.py test_llm_connections_security.py tests/sdk/test_cli_*.py test_run_started_event.py test_executor_cleanup.py` and the previously-green platform suites to confirm.
- SEC-1b secret rotation in `.env` was NOT done (touches live local DB/OAuth creds — left to the owner).

### Useful intel gathered (read-only, no files)
- Full-suite baseline pre-changes: 368 passed / 64 failed / 5 errors — failures are stale Langfuse/org-era tests per CI-2.
- Verified at HEAD vs working tree: the pre-session SEC-1/SEC-2/HP-4/HP-5 edits introduced zero regressions.
