from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from dotenv import load_dotenv
load_dotenv()  # Load .env file

from alembic import context
from sqlalchemy import engine_from_config, pool

from llm_eval_platform.db.base import Base
from llm_eval_platform.db import models  # noqa: F401  (import models for metadata)
from llm_eval_platform.settings import PlatformSettings


config = context.config
if config.config_file_name is not None:
    # Provide `sys` so alembic.ini handler args like `(sys.stderr,)` evaluate correctly.
    fileConfig(config.config_file_name, defaults={"sys": sys})

target_metadata = Base.metadata


def get_url() -> str:
    return PlatformSettings().database_url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()


