import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
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

    assert heads == ["0048"]


def test_subcategory_taxonomy_migration_preserves_rows_and_defaults_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration("0045_subcategory_taxonomy.py")
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    catalog = sa.Table(
        "project_analysis_category_catalog_versions",
        metadata,
        sa.Column("id", sa.String(length=36), primary_key=True),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(catalog.insert().values(id="existing"))
        monkeypatch.setattr(
            migration,
            "op",
            Operations(MigrationContext.configure(connection)),
        )

        migration.upgrade()

        columns = {
            column["name"]: column
            for column in sa.inspect(connection).get_columns(catalog.name)
        }
        taxonomy_column = columns["subcategory_taxonomy"]
        assert isinstance(taxonomy_column["type"], sa.JSON)
        assert taxonomy_column["nullable"] is False
        stored = connection.execute(
            sa.text(
                "SELECT subcategory_taxonomy "
                "FROM project_analysis_category_catalog_versions "
                "WHERE id = 'existing'"
            )
        ).scalar_one()
        assert stored == "{}"

        migration.downgrade()
        column_names = {
            column["name"]
            for column in sa.inspect(connection).get_columns(catalog.name)
        }
        assert "subcategory_taxonomy" not in column_names

    engine.dispose()


def test_root_cause_issue_migration_preserves_rows_and_nullable_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration("0046_root_cause_issues.py")
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    corrections = sa.Table(
        "review_corrections",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(corrections.insert().values(id=1))
        monkeypatch.setattr(
            migration,
            "op",
            Operations(MigrationContext.configure(connection)),
        )

        migration.upgrade()

        columns = {
            column["name"]: column
            for column in sa.inspect(connection).get_columns(corrections.name)
        }
        for name in ("ai_root_cause_issues", "human_root_cause_issues"):
            assert isinstance(columns[name]["type"], sa.JSON)
            assert columns[name]["nullable"] is True
        stored = connection.execute(
            sa.text(
                "SELECT ai_root_cause_issues, human_root_cause_issues "
                "FROM review_corrections WHERE id = 1"
            )
        ).one()
        assert tuple(stored) == (None, None)

        migration.downgrade()
        column_names = {
            column["name"]
            for column in sa.inspect(connection).get_columns(corrections.name)
        }
        assert "ai_root_cause_issues" not in column_names
        assert "human_root_cause_issues" not in column_names

    engine.dispose()


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
            self.execute_options: list[Optional[dict[str, Any]]] = []

        def execution_options(self, **_options: Any) -> Any:
            raise AssertionError("streaming must not mutate the Alembic connection")

        def execute(
            self,
            _statement: Any,
            _parameters: Any = None,
            *,
            execution_options: Optional[dict[str, Any]] = None,
        ) -> EmptyResult:
            self.execute_options.append(execution_options)
            return EmptyResult()

    connection = FakeConnection()
    migration._legacy_project_catalog(connection, "project-1")

    assert connection.execute_options == [{"stream_results": True}]
