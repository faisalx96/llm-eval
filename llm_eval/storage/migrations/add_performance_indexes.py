#!/usr/bin/env python3
"""
Migration script to add performance indexes to existing databases.

This script adds the new indexes introduced in SPRINT25-005 to improve
query performance for the storage layer.

Usage:
    python add_performance_indexes.py --database-url <url>
    python add_performance_indexes.py --help

Example:
    python add_performance_indexes.py --database-url sqlite:///./eval_runs.db
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from sqlalchemy import Index, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

# Add the project root directory to the Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from llm_eval.models.run_models import Base

logger = logging.getLogger(__name__)


class IndexMigration:
    """Handles database index migrations for performance improvements."""

    def __init__(self, database_url: str):
        """Initialize migration with database URL."""
        self.database_url = database_url
        self.engine = create_engine(database_url)

    def get_existing_indexes(self, table_name: str) -> List[str]:
        """Get list of existing indexes for a table."""
        inspector = inspect(self.engine)
        try:
            indexes = inspector.get_indexes(table_name)
            return [idx["name"] for idx in indexes if idx["name"]]
        except Exception as e:
            logger.warning(f"Could not get indexes for {table_name}: {e}")
            return []

    def index_exists(self, table_name: str, index_name: str) -> bool:
        """Check if an index already exists."""
        existing_indexes = self.get_existing_indexes(table_name)
        return index_name in existing_indexes

    def create_index_safely(
        self, table_name: str, index_name: str, index_sql: str
    ) -> bool:
        """Create an index if it doesn't already exist."""
        if self.index_exists(table_name, index_name):
            logger.info(f"Index {index_name} already exists on {table_name}, skipping")
            return True

        try:
            with self.engine.connect() as conn:
                logger.info(f"Creating index {index_name} on {table_name}")
                conn.execute(text(index_sql))
                conn.commit()
            return True
        except SQLAlchemyError as e:
            logger.error(f"Failed to create index {index_name}: {e}")
            return False

    def add_updated_at_column(self) -> bool:
        """Add updated_at column to evaluation_runs if it doesn't exist."""
        try:
            inspector = inspect(self.engine)
            columns = inspector.get_columns("evaluation_runs")
            column_names = [col["name"] for col in columns]

            if "updated_at" not in column_names:
                logger.info("Adding updated_at column to evaluation_runs")
                with self.engine.connect() as conn:
                    # Add the column with default value
                    conn.execute(
                        text(
                            """
                        ALTER TABLE evaluation_runs
                        ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    """
                        )
                    )
                    conn.commit()
                logger.info("Added updated_at column successfully")
            else:
                logger.info("updated_at column already exists, skipping")
            return True
        except SQLAlchemyError as e:
            logger.error(f"Failed to add updated_at column: {e}")
            return False

    def run_migration(self) -> bool:
        """Run the complete migration."""
        logger.info(f"Starting index migration on database: {self.database_url}")

        success = True

        # Step 1: Add updated_at column if needed
        if not self.add_updated_at_column():
            success = False

        # Step 2: Define new indexes to create
        new_indexes = [
            # EvaluationRun indexes
            (
                "evaluation_runs",
                "idx_runs_project_status",
                "CREATE INDEX IF NOT EXISTS idx_runs_project_status ON evaluation_runs (project_id, status)",
            ),
            (
                "evaluation_runs",
                "idx_runs_updated_at",
                "CREATE INDEX IF NOT EXISTS idx_runs_updated_at ON evaluation_runs (updated_at)",
            ),
            (
                "evaluation_runs",
                "idx_runs_status_created",
                "CREATE INDEX IF NOT EXISTS idx_runs_status_created ON evaluation_runs (status, created_at)",
            ),
            # EvaluationItem indexes
            (
                "evaluation_items",
                "idx_items_run_created",
                "CREATE INDEX IF NOT EXISTS idx_items_run_created ON evaluation_items (run_id, started_at)",
            ),
            (
                "evaluation_items",
                "idx_items_run_completed",
                "CREATE INDEX IF NOT EXISTS idx_items_run_completed ON evaluation_items (run_id, completed_at)",
            ),
            (
                "evaluation_items",
                "idx_items_tokens_cost",
                "CREATE INDEX IF NOT EXISTS idx_items_tokens_cost ON evaluation_items (tokens_used, cost)",
            ),
            (
                "evaluation_items",
                "idx_items_error_type",
                "CREATE INDEX IF NOT EXISTS idx_items_error_type ON evaluation_items (error_type)",
            ),
        ]

        # Step 3: Create new indexes
        for table_name, index_name, index_sql in new_indexes:
            if not self.create_index_safely(table_name, index_name, index_sql):
                success = False

        # Step 4: Verify existing critical indexes
        critical_indexes = [
            ("evaluation_runs", "idx_runs_project_id"),
            ("evaluation_runs", "idx_runs_status"),
            ("evaluation_runs", "idx_runs_created_at"),
            ("evaluation_items", "idx_items_run_id"),
            ("evaluation_items", "idx_items_run_status"),
            ("run_metrics", "idx_metrics_run_name"),
            ("run_comparisons", "idx_comparisons_runs"),
        ]

        missing_indexes = []
        for table_name, index_name in critical_indexes:
            if not self.index_exists(table_name, index_name):
                missing_indexes.append(f"{table_name}.{index_name}")

        if missing_indexes:
            logger.warning(f"Missing critical indexes: {missing_indexes}")
            logger.warning(
                "Consider running full table creation to ensure all indexes exist"
            )

        if success:
            logger.info("Migration completed successfully")
        else:
            logger.error("Migration completed with errors")

        return success

    def rollback_migration(self) -> bool:
        """Rollback the migration by dropping new indexes."""
        logger.info("Rolling back index migration")

        indexes_to_drop = [
            ("evaluation_runs", "idx_runs_project_status"),
            ("evaluation_runs", "idx_runs_updated_at"),
            ("evaluation_runs", "idx_runs_status_created"),
            ("evaluation_items", "idx_items_run_created"),
            ("evaluation_items", "idx_items_run_completed"),
            ("evaluation_items", "idx_items_tokens_cost"),
            ("evaluation_items", "idx_items_error_type"),
        ]

        success = True
        for table_name, index_name in indexes_to_drop:
            try:
                with self.engine.connect() as conn:
                    logger.info(f"Dropping index {index_name} from {table_name}")
                    conn.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
                    conn.commit()
            except SQLAlchemyError as e:
                logger.error(f"Failed to drop index {index_name}: {e}")
                success = False

        return success

    def analyze_performance(self) -> dict:
        """Analyze database performance and index usage."""
        logger.info("Analyzing database performance")

        analysis = {
            "total_tables": 0,
            "total_indexes": 0,
            "table_stats": {},
            "recommendations": [],
        }

        try:
            inspector = inspect(self.engine)
            tables = inspector.get_table_names()
            analysis["total_tables"] = len(tables)

            for table in tables:
                indexes = inspector.get_indexes(table)
                analysis["total_indexes"] += len(indexes)

                # Get table row count if possible
                try:
                    with self.engine.connect() as conn:
                        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        row_count = result.scalar()

                    analysis["table_stats"][table] = {
                        "rows": row_count,
                        "indexes": len(indexes),
                        "index_names": [idx["name"] for idx in indexes if idx["name"]],
                    }

                    # Add recommendations for large tables
                    if row_count > 10000:
                        analysis["recommendations"].append(
                            f"Table {table} has {row_count} rows - ensure proper indexing for queries"
                        )

                except Exception as e:
                    logger.warning(f"Could not analyze table {table}: {e}")

        except Exception as e:
            logger.error(f"Performance analysis failed: {e}")

        return analysis


def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    """Main migration script."""
    parser = argparse.ArgumentParser(
        description="Add performance indexes to LLM-Eval database"
    )
    parser.add_argument("--database-url", required=True, help="Database URL")
    parser.add_argument(
        "--rollback", action="store_true", help="Rollback the migration"
    )
    parser.add_argument(
        "--analyze", action="store_true", help="Analyze database performance"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    migration = IndexMigration(args.database_url)

    if args.analyze:
        logger.info("Running performance analysis")
        analysis = migration.analyze_performance()

        print("\n=== Database Performance Analysis ===")
        print(f"Total tables: {analysis['total_tables']}")
        print(f"Total indexes: {analysis['total_indexes']}")

        print("\n=== Table Statistics ===")
        for table, stats in analysis["table_stats"].items():
            print(f"{table}: {stats['rows']} rows, {stats['indexes']} indexes")
            if args.verbose:
                print(f"  Indexes: {', '.join(stats['index_names'])}")

        if analysis["recommendations"]:
            print("\n=== Recommendations ===")
            for rec in analysis["recommendations"]:
                print(f"- {rec}")

        return

    if args.rollback:
        success = migration.rollback_migration()
    else:
        success = migration.run_migration()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
