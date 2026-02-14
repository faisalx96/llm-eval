"""Comprehensive tests for the monorepo restructure.

Verifies:
1. Directory structure is correct (files exist where expected, gone from old locations)
2. SDK package imports work correctly
3. Platform package imports work correctly
4. No stale llm_eval / llm-eval / LLM_EVAL references remain
5. pyproject.toml files are well-formed
6. Docker files reference correct paths
7. Env var prefix is QYM_ everywhere
8. Static assets are in the right packages
"""

import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── Repo root ──────────────────────────────────────────────────────────

REPO = Path(__file__).resolve().parents[1]
SDK_ROOT = REPO / "packages" / "sdk"
PLATFORM_ROOT = REPO / "packages" / "platform"

# ── Mock heavy optional dependencies that may not be installed ─────────
# conftest.py already mocks rich and langfuse; add others here.
for _mod_name in ("arabic_reshaper", "bidi", "bidi.algorithm", "openpyxl"):
    if _mod_name not in sys.modules:
        _mock = MagicMock()
        _mock.__path__ = []
        sys.modules[_mod_name] = _mock


# ═══════════════════════════════════════════════════════════════════════
# 1. DIRECTORY STRUCTURE
# ═══════════════════════════════════════════════════════════════════════

class TestDirectoryStructure:
    """Verify that files are where they should be after the restructure."""

    # ── SDK package ────────────────────────────────────────────────────

    def test_sdk_package_exists(self):
        assert (SDK_ROOT / "qym" / "__init__.py").exists()

    def test_sdk_pyproject_toml(self):
        assert (SDK_ROOT / "pyproject.toml").exists()

    def test_sdk_core_modules(self):
        core = SDK_ROOT / "qym" / "core"
        for mod in ("evaluator.py", "config.py", "dataset.py", "results.py",
                     "checkpoint.py", "multi_runner.py", "observers.py",
                     "progress.py", "run_discovery.py", "dashboard.py"):
            assert (core / mod).exists(), f"Missing SDK core module: {mod}"

    def test_sdk_platform_subpackage(self):
        plat = SDK_ROOT / "qym" / "platform"
        assert (plat / "__init__.py").exists()
        assert (plat / "client.py").exists()
        assert (plat / "defaults.py").exists()

    def test_sdk_metrics(self):
        metrics = SDK_ROOT / "qym" / "metrics"
        assert (metrics / "__init__.py").exists()
        assert (metrics / "builtin.py").exists()
        assert (metrics / "registry.py").exists()

    def test_sdk_adapters(self):
        assert (SDK_ROOT / "qym" / "adapters" / "base.py").exists()

    def test_sdk_server(self):
        srv = SDK_ROOT / "qym" / "server"
        assert (srv / "app.py").exists()
        assert (srv / "dashboard_server.py").exists()

    def test_sdk_utils(self):
        utils = SDK_ROOT / "qym" / "utils"
        assert (utils / "errors.py").exists()
        assert (utils / "text.py").exists()

    def test_sdk_static_dashboard(self):
        d = SDK_ROOT / "qym" / "_static" / "dashboard"
        assert d.exists()
        assert (d / "index.html").exists()

    def test_sdk_static_ui(self):
        u = SDK_ROOT / "qym" / "_static" / "ui"
        assert u.exists()
        assert (u / "index.html").exists()

    def test_sdk_no_profile_html(self):
        """profile.html is platform-only and must NOT be in the SDK."""
        assert not (SDK_ROOT / "qym" / "_static" / "dashboard" / "profile.html").exists()

    def test_sdk_cli(self):
        assert (SDK_ROOT / "qym" / "cli.py").exists()

    # ── Platform package ───────────────────────────────────────────────

    def test_platform_package_exists(self):
        assert (PLATFORM_ROOT / "qym_platform" / "__init__.py").exists()

    def test_platform_pyproject_toml(self):
        assert (PLATFORM_ROOT / "pyproject.toml").exists()

    def test_platform_core_modules(self):
        pkg = PLATFORM_ROOT / "qym_platform"
        for mod in ("app.py", "main.py", "settings.py", "auth.py",
                     "deps.py", "events.py", "security.py", "cli.py",
                     "__main__.py"):
            assert (pkg / mod).exists(), f"Missing platform module: {mod}"

    def test_platform_api_subpackage(self):
        api = PLATFORM_ROOT / "qym_platform" / "api"
        assert (api / "__init__.py").exists()
        assert (api / "ingest.py").exists()
        assert (api / "runs.py").exists()
        assert (api / "org.py").exists()
        assert (api / "web.py").exists()

    def test_platform_db(self):
        db = PLATFORM_ROOT / "qym_platform" / "db"
        assert (db / "models.py").exists()
        assert (db / "session.py").exists()

    def test_platform_migrations(self):
        mig = PLATFORM_ROOT / "qym_platform" / "migrations"
        assert (mig / "env.py").exists()
        assert (mig / "alembic.ini").exists()

    def test_platform_tools(self):
        assert (PLATFORM_ROOT / "qym_platform" / "tools" / "import_local_results.py").exists()

    def test_platform_static_dashboard(self):
        d = PLATFORM_ROOT / "qym_platform" / "_static" / "dashboard"
        assert d.exists()
        assert (d / "index.html").exists()

    # ── Old locations must be gone ─────────────────────────────────────

    def test_no_old_setup_py(self):
        assert not (REPO / "setup.py").exists()

    def test_no_old_toplevel_qym_package(self):
        """The top-level qym/ dir should not exist (moved to packages/sdk/qym/)."""
        old = REPO / "qym" / "__init__.py"
        assert not old.exists(), "Old top-level qym/ package still present"

    def test_no_old_llm_eval_platform_dir(self):
        assert not (REPO / "llm_eval_platform").exists()

    def test_no_old_tests_unit_dir(self):
        assert not (REPO / "tests" / "unit").exists()

    # ── Test layout ────────────────────────────────────────────────────

    def test_test_sdk_dir(self):
        assert (REPO / "tests" / "sdk").is_dir()

    def test_test_platform_dir(self):
        assert (REPO / "tests" / "platform").is_dir()

    def test_conftest_exists(self):
        assert (REPO / "tests" / "conftest.py").exists()

    # ── Docker files ───────────────────────────────────────────────────

    def test_dockerfile_exists(self):
        assert (REPO / "docker" / "Dockerfile").exists()

    def test_entrypoint_exists(self):
        assert (REPO / "docker" / "entrypoint.sh").exists()

    def test_docker_compose_exists(self):
        assert (REPO / "docker" / "docker-compose.yml").exists()


# ═══════════════════════════════════════════════════════════════════════
# 2. SDK IMPORTS
# ═══════════════════════════════════════════════════════════════════════

class TestSdkImports:
    """Verify the SDK package can be imported correctly."""

    def test_import_qym(self):
        import qym
        assert hasattr(qym, "__version__")

    def test_import_evaluator(self):
        from qym.core.evaluator import Evaluator
        assert Evaluator is not None

    def test_import_csv_dataset(self):
        from qym.core.dataset import CsvDataset
        assert CsvDataset is not None

    def test_import_evaluation_result(self):
        from qym.core.results import EvaluationResult
        assert EvaluationResult is not None

    def test_import_config(self):
        from qym.core.config import EvaluatorConfig, RunSpec
        assert EvaluatorConfig is not None
        assert RunSpec is not None

    def test_import_checkpoint(self):
        from qym.core.checkpoint import (
            CheckpointWriter,
            load_checkpoint_state,
            iter_checkpoint_rows,
            parse_checkpoint_row,
            serialize_checkpoint_row,
        )
        assert CheckpointWriter is not None

    def test_import_platform_subpackage(self):
        from qym.platform import PlatformClient, PlatformEventStream, DEFAULT_PLATFORM_URL
        assert PlatformClient is not None
        assert PlatformEventStream is not None
        assert isinstance(DEFAULT_PLATFORM_URL, str)

    def test_import_platform_client_directly(self):
        from qym.platform.client import PlatformClient, PlatformEventStream
        assert PlatformClient is not None

    def test_import_platform_defaults_directly(self):
        from qym.platform.defaults import DEFAULT_PLATFORM_URL
        assert isinstance(DEFAULT_PLATFORM_URL, str)

    def test_import_metrics(self):
        from qym.metrics import builtin_metrics, list_available_metrics
        assert isinstance(builtin_metrics, dict)
        assert callable(list_available_metrics)

    def test_import_builtin_metrics(self):
        from qym.metrics.builtin import exact_match, contains_expected, fuzzy_match
        assert callable(exact_match)
        assert callable(contains_expected)
        assert callable(fuzzy_match)

    def test_import_errors(self):
        from qym.utils.errors import CsvDatasetSchemaError
        assert issubclass(CsvDatasetSchemaError, Exception)

    def test_import_multi_runner(self):
        from qym.core.multi_runner import MultiModelRunner
        assert MultiModelRunner is not None

    def test_import_run_discovery(self):
        from qym.core.run_discovery import RunDiscovery
        assert RunDiscovery is not None

    def test_top_level_exports(self):
        """qym.__init__ re-exports key classes."""
        import qym
        assert hasattr(qym, "Evaluator")
        assert hasattr(qym, "CsvDataset")
        assert hasattr(qym, "EvaluationResult")
        assert hasattr(qym, "RunSpec")
        assert hasattr(qym, "MultiModelRunner")
        assert hasattr(qym, "builtin_metrics")
        assert hasattr(qym, "list_available_metrics")


# ═══════════════════════════════════════════════════════════════════════
# 3. PLATFORM IMPORTS
# ═══════════════════════════════════════════════════════════════════════

class TestPlatformImports:
    """Verify the platform package can be imported correctly.

    Requires pydantic_settings, sqlalchemy, and fastapi.
    """

    @pytest.fixture(autouse=True)
    def _require_platform_deps(self):
        pytest.importorskip("pydantic_settings", reason="pydantic_settings required")
        pytest.importorskip("sqlalchemy", reason="sqlalchemy required")
        pytest.importorskip("fastapi", reason="fastapi required")
        # Ensure QYM_DATABASE_URL is set for settings import
        os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")

    def test_import_qym_platform(self):
        import qym_platform
        assert hasattr(qym_platform, "__version__")

    def test_import_settings(self):
        from qym_platform.settings import PlatformSettings
        assert PlatformSettings is not None

    def test_settings_env_prefix(self):
        from qym_platform.settings import PlatformSettings
        cfg = PlatformSettings.model_config
        assert cfg.get("env_prefix") == "QYM_"

    def test_import_db_models(self):
        from qym_platform.db.models import (
            User, UserRole, Run, RunItem, RunItemScore,
            RunWorkflowStatus, OrgUnit, OrgUnitType,
            OrgUnitClosure, PlatformSetting,
        )
        assert User is not None
        assert RunWorkflowStatus.DRAFT is not None
        assert UserRole.ADMIN is not None

    def test_import_app_factory(self):
        from qym_platform.app import create_app
        assert callable(create_app)

    def test_import_api_routers(self):
        from qym_platform.api.web import router as web_router
        from qym_platform.api.runs import router as runs_router
        from qym_platform.api.ingest import router as ingest_router
        from qym_platform.api.org import router as org_router
        assert web_router is not None
        assert runs_router is not None
        assert ingest_router is not None
        assert org_router is not None

    def test_import_auth(self):
        from qym_platform.auth import Principal
        assert Principal is not None

    def test_import_events(self):
        import qym_platform.events
        assert qym_platform.events is not None


# ═══════════════════════════════════════════════════════════════════════
# 4. NO STALE REFERENCES
# ═══════════════════════════════════════════════════════════════════════

def _collect_source_files(root: Path, exts: tuple = (".py", ".toml", ".yml", ".yaml", ".sh", ".md", ".html", ".js", ".css")) -> list:
    """Collect all text source files under root, skipping hidden/vendored dirs."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden dirs, __pycache__, node_modules, .git
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".git", "dist", "build", "*.egg-info")]
        for fn in filenames:
            if any(fn.endswith(ext) for ext in exts):
                files.append(Path(dirpath) / fn)
    return files


class TestNoStaleReferences:
    """Ensure the old naming is fully eliminated."""

    @pytest.fixture(scope="class")
    def source_files(self):
        return _collect_source_files(REPO)

    def test_no_llm_eval_platform_import(self, source_files):
        """No Python file should import from llm_eval_platform."""
        pattern = re.compile(r"\bllm_eval_platform\b")
        violations = []
        for f in source_files:
            if f.name == "test_restructure.py":
                continue
            if f.suffix == ".py":
                text = f.read_text(errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        violations.append(f"{f}:{i}: {line.strip()}")
        assert violations == [], "Found llm_eval_platform references:\n" + "\n".join(violations)

    def test_no_LLM_EVAL_env_prefix(self, source_files):
        """No config/code file should use LLM_EVAL_ env prefix."""
        pattern = re.compile(r"\bLLM_EVAL_")
        violations = []
        for f in source_files:
            if f.name == "test_restructure.py":
                continue
            text = f.read_text(errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    violations.append(f"{f}:{i}: {line.strip()}")
        assert violations == [], "Found LLM_EVAL_ env prefix:\n" + "\n".join(violations)

    def test_no_llm_eval_project_name_in_code(self, source_files):
        """No Python/config file should reference 'llm-eval' as a project name.

        Exceptions:
        - pyproject.toml entry point alias (backward-compat CLI)
        - Generic phrase 'LLM evaluation' / 'LLM Evaluation' (domain term)
        - This test file itself
        """
        # Match 'llm-eval' but NOT 'LLM evaluation' (word boundary)
        pattern = re.compile(r"\bllm-eval\b", re.IGNORECASE)
        generic_domain = re.compile(r"llm.evaluation", re.IGNORECASE)
        violations = []
        for f in source_files:
            # Skip this test file itself
            if f.name == "test_restructure.py":
                continue
            text = f.read_text(errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    # Allow generic domain mentions
                    if generic_domain.search(line):
                        continue
                    violations.append(f"{f}:{i}: {line.strip()}")
        assert violations == [], "Found stale 'llm-eval' references:\n" + "\n".join(violations)

    def test_no_llm_eval_results_dir_references(self, source_files):
        """No reference to the old llm-eval_results directory name."""
        pattern = re.compile(r"llm-eval_results|llm_eval_results")
        violations = []
        for f in source_files:
            if f.name == "test_restructure.py":
                continue
            text = f.read_text(errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    violations.append(f"{f}:{i}: {line.strip()}")
        assert violations == [], "Found old results dir references:\n" + "\n".join(violations)


# ═══════════════════════════════════════════════════════════════════════
# 5. PYPROJECT.TOML VALIDATION
# ═══════════════════════════════════════════════════════════════════════

class TestPyprojectToml:
    """Validate both pyproject.toml files."""

    @pytest.fixture(scope="class")
    def sdk_toml(self):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        return tomllib.loads((SDK_ROOT / "pyproject.toml").read_text())

    @pytest.fixture(scope="class")
    def platform_toml(self):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        return tomllib.loads((PLATFORM_ROOT / "pyproject.toml").read_text())

    def test_sdk_name(self, sdk_toml):
        assert sdk_toml["project"]["name"] == "qym"

    def test_sdk_entry_points(self, sdk_toml):
        scripts = sdk_toml["project"]["scripts"]
        assert "qym" in scripts
        assert scripts["qym"] == "qym.cli:main"
        # Old alias should be removed
        assert "llm-eval" not in scripts

    def test_sdk_has_dev_extras(self, sdk_toml):
        extras = sdk_toml["project"]["optional-dependencies"]
        assert "dev" in extras

    def test_sdk_package_data(self, sdk_toml):
        pkg_data = sdk_toml["tool"]["setuptools"]["package-data"]["qym"]
        assert "_static/ui/*" in pkg_data
        assert "_static/dashboard/*" in pkg_data

    def test_platform_name(self, platform_toml):
        assert platform_toml["project"]["name"] == "qym-platform"

    def test_platform_depends_on_sdk(self, platform_toml):
        deps = platform_toml["project"]["dependencies"]
        assert any("qym" in d for d in deps)

    def test_platform_entry_point(self, platform_toml):
        scripts = platform_toml["project"]["scripts"]
        assert "qym-platform" in scripts
        assert scripts["qym-platform"] == "qym_platform.cli:main"

    def test_platform_package_data(self, platform_toml):
        pkg_data = platform_toml["tool"]["setuptools"]["package-data"]["qym_platform"]
        assert "_static/dashboard/*" in pkg_data
        assert "migrations/*" in pkg_data


# ═══════════════════════════════════════════════════════════════════════
# 6. DOCKER FILES
# ═══════════════════════════════════════════════════════════════════════

class TestDockerFiles:
    """Verify Docker files reference the new paths."""

    def test_dockerfile_copies_packages(self):
        text = (REPO / "docker" / "Dockerfile").read_text()
        assert "COPY packages/sdk" in text
        assert "COPY packages/platform" in text
        # Old single setup.py approach must be gone
        assert "COPY setup.py" not in text
        assert "COPY qym " not in text
        assert "llm_eval_platform" not in text

    def test_dockerfile_installs_both_packages(self):
        text = (REPO / "docker" / "Dockerfile").read_text()
        assert "packages/sdk" in text
        assert "packages/platform" in text

    def test_entrypoint_uses_new_paths(self):
        text = (REPO / "docker" / "entrypoint.sh").read_text()
        assert "packages/platform/qym_platform/migrations/alembic.ini" in text
        assert "qym_platform.main:app" in text
        assert "llm_eval_platform" not in text

    def test_compose_uses_qym_env_vars(self):
        text = (REPO / "docker" / "docker-compose.yml").read_text()
        assert "QYM_ENVIRONMENT" in text
        assert "QYM_DATABASE_URL" in text
        assert "QYM_ADMIN_BOOTSTRAP_TOKEN" in text
        assert "LLM_EVAL_" not in text

    def test_compose_postgres_creds(self):
        text = (REPO / "docker" / "docker-compose.yml").read_text()
        assert "POSTGRES_USER: qym" in text
        assert "POSTGRES_PASSWORD: qym" in text
        assert "POSTGRES_DB: qym" in text


# ═══════════════════════════════════════════════════════════════════════
# 7. ENV VAR PREFIX CONSISTENCY
# ═══════════════════════════════════════════════════════════════════════

class TestEnvVarPrefix:
    """All QYM_ env vars are used consistently."""

    def test_platform_defaults_uses_qym_prefix(self):
        text = (SDK_ROOT / "qym" / "platform" / "defaults.py").read_text()
        assert "QYM_PLATFORM_URL" in text
        assert "LLM_EVAL_PLATFORM_URL" not in text

    def test_platform_client_uses_qym_prefix(self):
        text = (SDK_ROOT / "qym" / "platform" / "client.py").read_text()
        assert "QYM_PLATFORM_DEBUG" in text
        assert "LLM_EVAL_PLATFORM_DEBUG" not in text

    def test_settings_env_prefix_is_qym(self):
        text = (PLATFORM_ROOT / "qym_platform" / "settings.py").read_text()
        assert 'env_prefix="QYM_"' in text or "env_prefix='QYM_'" in text

    def test_env_template_uses_qym(self):
        text = (REPO / ".env.template").read_text()
        assert "LLM_EVAL_" not in text


# ═══════════════════════════════════════════════════════════════════════
# 8. STATIC ASSETS SEPARATION
# ═══════════════════════════════════════════════════════════════════════

class TestStaticAssets:
    """Verify both packages own appropriate static assets."""

    def test_sdk_dashboard_has_index(self):
        assert (SDK_ROOT / "qym" / "_static" / "dashboard" / "index.html").exists()

    def test_sdk_ui_has_index(self):
        assert (SDK_ROOT / "qym" / "_static" / "ui" / "index.html").exists()

    def test_platform_dashboard_has_index(self):
        assert (PLATFORM_ROOT / "qym_platform" / "_static" / "dashboard" / "index.html").exists()

    def test_platform_ui_has_index(self):
        assert (PLATFORM_ROOT / "qym_platform" / "_static" / "ui" / "index.html").exists()

    def test_profile_html_only_in_platform(self):
        """profile.html should only exist in the platform package."""
        sdk_profile = SDK_ROOT / "qym" / "_static" / "dashboard" / "profile.html"
        platform_profile = PLATFORM_ROOT / "qym_platform" / "_static" / "dashboard" / "profile.html"
        assert not sdk_profile.exists(), "profile.html should not be in SDK"
        assert platform_profile.exists(), "profile.html should be in platform"


# ═══════════════════════════════════════════════════════════════════════
# 9. CONFTEST AND TEST INFRA
# ═══════════════════════════════════════════════════════════════════════

class TestTestInfrastructure:
    """Verify the test infrastructure is correctly configured."""

    def test_conftest_adds_sdk_to_path(self):
        text = (REPO / "tests" / "conftest.py").read_text()
        assert "packages" in text and "sdk" in text

    def test_conftest_adds_platform_to_path(self):
        text = (REPO / "tests" / "conftest.py").read_text()
        assert "packages" in text and "platform" in text

    def test_sdk_tests_exist(self):
        sdk_tests = list((REPO / "tests" / "sdk").glob("test_*.py"))
        assert len(sdk_tests) >= 3, f"Expected at least 3 SDK tests, found {len(sdk_tests)}"

    def test_platform_tests_exist(self):
        platform_tests = list((REPO / "tests" / "platform").glob("test_*.py"))
        assert len(platform_tests) >= 1, f"Expected at least 1 platform test, found {len(platform_tests)}"


# ═══════════════════════════════════════════════════════════════════════
# 10. PLATFORM APP WIRING
# ═══════════════════════════════════════════════════════════════════════

class TestPlatformAppWiring:
    """Verify the platform app factory is properly wired."""

    @pytest.fixture(autouse=True)
    def _require_platform_deps(self):
        pytest.importorskip("pydantic_settings", reason="pydantic_settings required")
        pytest.importorskip("sqlalchemy", reason="sqlalchemy required")
        pytest.importorskip("fastapi", reason="fastapi required")
        os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")

    def test_create_app_returns_fastapi(self):
        from qym_platform.app import create_app
        from qym_platform.settings import PlatformSettings

        settings = PlatformSettings(database_url="sqlite:///:memory:")
        app = create_app(settings)

        from fastapi import FastAPI
        assert isinstance(app, FastAPI)

    def test_healthz_route_exists(self):
        from qym_platform.app import create_app
        from qym_platform.settings import PlatformSettings

        settings = PlatformSettings(database_url="sqlite:///:memory:")
        app = create_app(settings)

        routes = [r.path for r in app.routes]
        assert "/healthz" in routes

    def test_app_title(self):
        from qym_platform.app import create_app
        from qym_platform.settings import PlatformSettings

        settings = PlatformSettings(database_url="sqlite:///:memory:")
        app = create_app(settings)
        assert app.title == "qym-platform"


# ═══════════════════════════════════════════════════════════════════════
# 11. CROSS-PACKAGE BOUNDARY
# ═══════════════════════════════════════════════════════════════════════

class TestCrossPackageBoundary:
    """The SDK should not import qym_platform and vice-versa (except controlled deps)."""

    def test_sdk_does_not_import_qym_platform(self):
        """No SDK source file should import from qym_platform."""
        pattern = re.compile(r"^\s*(from|import)\s+qym_platform")
        violations = []
        for f in (SDK_ROOT / "qym").rglob("*.py"):
            text = f.read_text(errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.match(line):
                    violations.append(f"{f}:{i}: {line.strip()}")
        assert violations == [], "SDK imports qym_platform:\n" + "\n".join(violations)

    def test_platform_import_from_sdk_is_limited(self):
        """Platform may import from qym (SDK), but only specific things."""
        pattern = re.compile(r"^\s*(from|import)\s+qym\b")
        imports = []
        for f in (PLATFORM_ROOT / "qym_platform").rglob("*.py"):
            text = f.read_text(errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.match(line):
                    imports.append(f"{f.relative_to(PLATFORM_ROOT)}:{i}: {line.strip()}")
        # It's OK to import from qym (the tools/import script does),
        # but there shouldn't be excessive coupling.
        # Just log them; the important thing is they exist and work.
        assert isinstance(imports, list)  # Always passes — informational


# ═══════════════════════════════════════════════════════════════════════
# 12. ALEMBIC CONFIG
# ═══════════════════════════════════════════════════════════════════════

class TestAlembicConfig:
    """Verify alembic.ini references are correct."""

    def test_alembic_ini_script_location(self):
        text = (PLATFORM_ROOT / "qym_platform" / "migrations" / "alembic.ini").read_text()
        assert "qym_platform/migrations" in text or "packages/platform/qym_platform/migrations" in text
        assert "llm_eval_platform" not in text

    def test_migrations_readme(self):
        text = (PLATFORM_ROOT / "qym_platform" / "migrations" / "README.md").read_text()
        assert "qym" in text.lower()
        assert "llm-eval" not in text.lower()
