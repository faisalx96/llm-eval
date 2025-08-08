"""Database connection and session management."""

import logging
import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ..models.run_models import Base, create_tables

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and sessions for LLM-Eval."""

    def __init__(self, database_url: Optional[str] = None, **engine_kwargs):
        """
        Initialize database manager.

        Args:
            database_url: Database connection URL. If None, uses environment variable
                         LLM_EVAL_DATABASE_URL or defaults to SQLite
            **engine_kwargs: Additional arguments passed to create_engine
        """
        self.database_url = database_url or self._get_database_url()
        self.engine = self._create_engine(**engine_kwargs)
        self.SessionLocal = sessionmaker(bind=self.engine)

        # Initialize tables
        self._ensure_tables_exist()

    def _get_database_url(self) -> str:
        """Get database URL from environment or use default SQLite."""
        default_url = "sqlite:///./llm_eval_runs.db"
        return os.getenv("LLM_EVAL_DATABASE_URL", default_url)

    def _create_engine(self, **kwargs):
        """Create SQLAlchemy engine with appropriate configuration."""
        default_kwargs = {
            "echo": os.getenv("LLM_EVAL_DEBUG", "false").lower() == "true",
            "future": True,
        }

        # SQLite-specific configurations
        if self.database_url.startswith("sqlite"):
            default_kwargs.update(
                {
                    "poolclass": StaticPool,
                    "connect_args": {"check_same_thread": False, "timeout": 30},
                }
            )

        # PostgreSQL-specific configurations
        elif "postgresql" in self.database_url:
            default_kwargs.update(
                {
                    "pool_size": 10,
                    "max_overflow": 20,
                    "pool_recycle": 3600,
                    "pool_pre_ping": True,
                }
            )

        # Merge with user-provided kwargs
        default_kwargs.update(kwargs)

        engine = create_engine(self.database_url, **default_kwargs)

        # Add event listeners for better performance
        self._setup_engine_events(engine)

        return engine

    def _setup_engine_events(self, engine):
        """Set up database engine event listeners."""

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            """Optimize SQLite for better performance."""
            if "sqlite" in str(engine.url):
                cursor = dbapi_connection.cursor()
                # Enable WAL mode for better concurrency
                cursor.execute("PRAGMA journal_mode=WAL")
                # Increase cache size
                cursor.execute("PRAGMA cache_size=10000")
                # Enable foreign key constraints
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        @event.listens_for(engine, "connect")
        def set_postgresql_search_path(dbapi_connection, connection_record):
            """Set PostgreSQL search path and optimizations."""
            if "postgresql" in str(engine.url):
                cursor = dbapi_connection.cursor()
                # Set search path if needed
                cursor.execute("SET search_path TO public")
                # Set reasonable work_mem for complex queries
                cursor.execute("SET work_mem = '16MB'")
                cursor.close()

    def _ensure_tables_exist(self):
        """Create database tables if they don't exist."""
        try:
            create_tables(self.engine)
            logger.info("Database tables initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database tables: {e}")
            raise

    @contextmanager
    def get_session(self):
        """
        Context manager for database sessions.

        Yields:
            SQLAlchemy session with automatic transaction management
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            session.close()

    def get_sync_session(self) -> Session:
        """
        Get a synchronous database session.

        Note: Caller is responsible for closing the session.

        Returns:
            SQLAlchemy session
        """
        return self.SessionLocal()

    def health_check(self) -> Dict[str, Any]:
        """
        Perform database health check.

        Returns:
            Dictionary with health check results
        """
        try:
            with self.get_session() as session:
                # Simple query to test connectivity
                result = session.execute(text("SELECT 1")).scalar()

                # Get database statistics
                stats = self._get_database_stats(session)

                return {
                    "status": "healthy",
                    "database_url": (
                        self.database_url.split("@")[-1]
                        if "@" in self.database_url
                        else self.database_url
                    ),
                    "connection_test": result == 1,
                    "statistics": stats,
                }

        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "database_url": (
                    self.database_url.split("@")[-1]
                    if "@" in self.database_url
                    else self.database_url
                ),
            }

    def _get_database_stats(self, session: Session) -> Dict[str, Any]:
        """Get basic database statistics."""
        stats = {}

        try:
            # Count records in main tables
            from ..models.run_models import EvaluationItem, EvaluationRun, RunMetric

            stats["run_count"] = session.query(EvaluationRun).count()
            stats["item_count"] = session.query(EvaluationItem).count()
            stats["metric_count"] = session.query(RunMetric).count()

            # Get recent activity
            latest_run = (
                session.query(EvaluationRun)
                .order_by(EvaluationRun.created_at.desc())
                .first()
            )

            if latest_run:
                stats["latest_run_date"] = latest_run.created_at.isoformat()
                stats["latest_run_name"] = latest_run.name

        except Exception as e:
            logger.warning(f"Could not retrieve database statistics: {e}")
            stats["error"] = "Could not retrieve statistics"

        return stats

    def close(self):
        """Close database engine and connections."""
        if hasattr(self, "engine"):
            self.engine.dispose()
            logger.info("Database connections closed")


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def get_database_manager(
    database_url: Optional[str] = None, **kwargs
) -> DatabaseManager:
    """
    Get or create global database manager instance.

    Args:
        database_url: Database connection URL
        **kwargs: Additional engine arguments

    Returns:
        DatabaseManager instance
    """
    global _db_manager

    if _db_manager is None:
        _db_manager = DatabaseManager(database_url, **kwargs)

    return _db_manager


def reset_database_manager():
    """Reset global database manager (useful for testing)."""
    global _db_manager
    if _db_manager:
        _db_manager.close()
    _db_manager = None
