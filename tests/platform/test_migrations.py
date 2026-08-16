import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "packages" / "platform" / "qym_platform" / "migrations"


def _load_migration(filename: str) -> ModuleType:
    path = MIGRATIONS_DIR / "versions" / filename
    spec = importlib.util.spec_from_file_location(f"test_migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alembic_revision_ids_fit_default_version_column() -> None:
    """Alembic stores revision IDs in VARCHAR(32) unless configured otherwise."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    revisions = list(ScriptDirectory.from_config(config).walk_revisions())

    oversized = [
        revision.revision for revision in revisions if len(revision.revision) > 32
    ]

    assert oversized == []


def test_alembic_has_one_upgrade_head() -> None:
    """The deployment entrypoint uses ``upgrade head``, which requires one head."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    heads = ScriptDirectory.from_config(config).get_heads()

    assert heads == ["0044"]


def test_catalog_backfill_scopes_streaming_to_select_statements() -> None:
    """PostgreSQL cannot execute INSERT through a server-side SELECT cursor."""
    migration = _load_migration("0043_backfill_analysis_category_catalogs.py")

    class EmptyResult:
        def fetchmany(self, _size: int) -> list[Any]:
            return []

        def close(self) -> None:
            pass

    class FakeConnection:
        def __init__(self) -> None:
            self.execute_options: list[dict[str, Any] | None] = []

        def execution_options(self, **_options: Any) -> Any:
            raise AssertionError("streaming must not mutate the Alembic connection")

        def execute(
            self,
            _statement: Any,
            _parameters: Any = None,
            *,
            execution_options: dict[str, Any] | None = None,
        ) -> EmptyResult:
            self.execute_options.append(execution_options)
            return EmptyResult()

    connection = FakeConnection()
    migration._legacy_project_catalog(connection, "project-1")

    assert connection.execute_options == [{"stream_results": True}]
