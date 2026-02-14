from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from qym_platform.settings import PlatformSettings


def _build_engine():
    settings = PlatformSettings()
    # future=True by default in SQLAlchemy 2.x
    return create_engine(settings.database_url, pool_pre_ping=True)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


