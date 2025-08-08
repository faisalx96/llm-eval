"""Repository pattern for evaluation run data access."""

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from sqlalchemy import and_, asc, desc, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.run_models import EvaluationItem, EvaluationRun, RunComparison, RunMetric
from .database import get_database_manager

logger = logging.getLogger(__name__)


class RunRepository:
    """Repository for evaluation run data access and management."""

    def __init__(self, session: Optional[Session] = None):
        """
        Initialize repository.

        Args:
            session: Optional SQLAlchemy session. If None, uses database manager.
        """
        self.session = session
        self._db_manager = get_database_manager() if session is None else None

    def _get_session(self):
        """Get database session context manager or direct session."""
        if self.session:
            # For direct session, return it directly
            return self.session
        else:
            # For database manager, return the context manager
            return self._db_manager.get_session()

    def _get_session_context(self):
        """Get database session context manager."""
        if self.session:
            # For direct session, create a context manager that handles rollback
            @contextmanager
            def session_context():
                try:
                    yield self.session
                    # Don't commit for provided sessions - let the caller handle it
                except Exception:
                    # Rollback on error and re-raise
                    self.session.rollback()
                    raise

            return session_context()
        else:
            # For database manager, return the context manager
            return self._db_manager.get_session()

    # CRUD Operations for Evaluation Runs

    def create_run(self, run_data: Dict[str, Any]) -> EvaluationRun:
        """
        Create a new evaluation run.

        Args:
            run_data: Dictionary containing run metadata

        Returns:
            Created EvaluationRun instance

        Raises:
            IntegrityError: If run creation fails due to constraint violations
        """
        try:
            with self._get_session_context() as session:
                run = EvaluationRun(**run_data)
                session.add(run)
                session.flush()  # Get the ID without committing

                # Create a detached copy with all needed attributes
                run_dict = {
                    "id": run.id,
                    "name": run.name,
                    "description": run.description,
                    "status": run.status,
                    "dataset_name": run.dataset_name,
                    "model_name": run.model_name,
                    "task_type": run.task_type,
                    "created_at": run.created_at,
                    "completed_at": run.completed_at,
                    "duration_seconds": run.duration_seconds,
                    "total_items": run.total_items,
                    "successful_items": run.successful_items,
                    "success_rate": run.success_rate,
                    "tags": run.tags,
                    "project_id": getattr(run, "project_id", None),
                    "created_by": getattr(run, "created_by", None),
                }

                session.commit()  # Commit the changes

                # Return a simple object that can be accessed safely
                class SimpleRun:
                    def __init__(self, data):
                        for key, value in data.items():
                            setattr(self, key, value)

                return SimpleRun(run_dict)

        except IntegrityError as e:
            logger.error(f"Failed to create run: {e}")
            raise

    def get_run(self, run_id: Union[str, UUID]) -> Optional[EvaluationRun]:
        """
        Get evaluation run by ID.

        Args:
            run_id: Run UUID or string representation

        Returns:
            EvaluationRun instance or None if not found
        """
        if run_id is None:
            return None

        try:
            # Convert to UUID if string
            if isinstance(run_id, str):
                uuid_obj = UUID(run_id)
            else:
                uuid_obj = run_id
        except (ValueError, TypeError):
            return None

        with self._get_session_context() as session:
            return (
                session.query(EvaluationRun)
                .filter(EvaluationRun.id == uuid_obj)
                .first()
            )

    def update_run(
        self, run_id: Union[str, UUID], updates: Dict[str, Any]
    ) -> Optional[EvaluationRun]:
        """
        Update evaluation run.

        Args:
            run_id: Run UUID or string representation
            updates: Dictionary of fields to update

        Returns:
            Updated EvaluationRun instance or None if not found
        """
        if run_id is None:
            return None

        try:
            # Convert to UUID if string
            if isinstance(run_id, str):
                uuid_obj = UUID(run_id)
            else:
                uuid_obj = run_id
        except (ValueError, TypeError):
            return None

        with self._get_session_context() as session:
            run = (
                session.query(EvaluationRun)
                .filter(EvaluationRun.id == uuid_obj)
                .first()
            )

            if run:
                for key, value in updates.items():
                    if hasattr(run, key):
                        setattr(run, key, value)
                session.flush()
                return session.merge(run)

            return None

    def delete_run(self, run_id: Union[str, UUID]) -> bool:
        """
        Delete evaluation run and all associated data.

        Args:
            run_id: Run UUID or string representation

        Returns:
            True if run was deleted, False if not found
        """
        if run_id is None:
            return False

        try:
            # Convert to UUID if string
            if isinstance(run_id, str):
                uuid_obj = UUID(run_id)
            else:
                uuid_obj = run_id
        except (ValueError, TypeError):
            return False

        with self._get_session_context() as session:
            run = (
                session.query(EvaluationRun)
                .filter(EvaluationRun.id == uuid_obj)
                .first()
            )

            if run:
                session.delete(run)  # Cascade will handle related records
                return True

            return False

    # Query Operations

    def list_runs(
        self,
        project_id: Optional[str] = None,
        dataset_name: Optional[str] = None,
        model_name: Optional[str] = None,
        status: Optional[str] = None,
        created_by: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_success_rate: Optional[float] = None,
        max_duration: Optional[float] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        order_by: str = "created_at",
        descending: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> List[EvaluationRun]:
        """
        List evaluation runs with filtering and pagination.

        Args:
            project_id: Filter by project ID
            dataset_name: Filter by dataset name
            model_name: Filter by model name
            status: Filter by run status
            created_by: Filter by creator
            tags: Filter by tags (must contain all specified tags)
            min_success_rate: Minimum success rate threshold
            max_duration: Maximum duration in seconds
            created_after: Filter runs created after this date
            created_before: Filter runs created before this date
            order_by: Field to order by
            descending: Whether to sort in descending order
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of EvaluationRun instances
        """
        with self._get_session_context() as session:
            query = session.query(EvaluationRun)

            # Apply filters
            if project_id:
                query = query.filter(EvaluationRun.project_id == project_id)

            if dataset_name:
                query = query.filter(EvaluationRun.dataset_name == dataset_name)

            if model_name:
                query = query.filter(EvaluationRun.model_name == model_name)

            if status:
                query = query.filter(EvaluationRun.status == status)

            if created_by:
                query = query.filter(EvaluationRun.created_by == created_by)

            if min_success_rate is not None:
                query = query.filter(EvaluationRun.success_rate >= min_success_rate)

            if max_duration is not None:
                query = query.filter(EvaluationRun.duration_seconds <= max_duration)

            if created_after:
                query = query.filter(EvaluationRun.created_at >= created_after)

            if created_before:
                query = query.filter(EvaluationRun.created_at <= created_before)

            if tags:
                # Filter by tags (PostgreSQL JSON contains operations)
                for tag in tags:
                    query = query.filter(EvaluationRun.tags.contains([tag]))

            # Apply ordering
            order_field = getattr(EvaluationRun, order_by, EvaluationRun.created_at)
            if descending:
                query = query.order_by(desc(order_field))
            else:
                query = query.order_by(asc(order_field))

            # Apply pagination
            query = query.offset(offset).limit(limit)

            # Fetch runs and convert to dictionaries to avoid DetachedInstanceError
            runs = query.all()

            # Convert to dictionaries within session context
            run_dicts = []
            for run in runs:
                run_dict = {
                    "id": str(run.id),
                    "name": run.name,
                    "description": run.description,
                    "status": run.status,
                    "dataset_name": run.dataset_name,
                    "model_name": run.model_name,
                    "task_type": run.task_type,
                    "created_at": run.created_at,
                    "completed_at": run.completed_at,
                    "duration_seconds": run.duration_seconds,
                    "total_items": run.total_items,
                    "successful_items": run.successful_items,
                    "success_rate": run.success_rate,
                    "tags": run.tags,
                    "project_id": getattr(run, "project_id", None),
                    "created_by": getattr(run, "created_by", None),
                }
                run_dicts.append(run_dict)

            return run_dicts

    def count_runs(self, **filters) -> int:
        """Count evaluation runs matching filters."""
        # Use same filtering logic as list_runs but count instead
        with self._get_session_context() as session:
            query = session.query(func.count(EvaluationRun.id))

            # Apply same filters as list_runs (simplified)
            for key, value in filters.items():
                if value is not None and hasattr(EvaluationRun, key):
                    query = query.filter(getattr(EvaluationRun, key) == value)

            return query.scalar() or 0

    def search_runs(self, search_term: str, limit: int = 20) -> List[EvaluationRun]:
        """
        Search runs by name, description, or dataset name.

        Args:
            search_term: Text to search for
            limit: Maximum number of results

        Returns:
            List of matching EvaluationRun instances
        """
        with self._get_session_context() as session:
            search_pattern = f"%{search_term}%"

            query = (
                session.query(EvaluationRun)
                .filter(
                    or_(
                        EvaluationRun.name.ilike(search_pattern),
                        EvaluationRun.description.ilike(search_pattern),
                        EvaluationRun.dataset_name.ilike(search_pattern),
                    )
                )
                .order_by(desc(EvaluationRun.created_at))
                .limit(limit)
            )

            return query.all()

    # Metrics Operations

    def get_run_metrics(self, run_id: Union[str, UUID]) -> List[RunMetric]:
        """
        Get all metrics for a specific run.

        Args:
            run_id: Run UUID or string representation

        Returns:
            List of RunMetric instances
        """
        if run_id is None:
            return []

        try:
            # Convert to UUID if string
            if isinstance(run_id, str):
                uuid_obj = UUID(run_id)
            else:
                uuid_obj = run_id
        except (ValueError, TypeError):
            return []

        with self._get_session_context() as session:
            return session.query(RunMetric).filter(RunMetric.run_id == uuid_obj).all()

    def get_metric_stats(
        self, metric_name: str, project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get aggregate statistics for a metric across runs.

        Args:
            metric_name: Name of the metric
            project_id: Optional project filter

        Returns:
            Dictionary with aggregate statistics
        """
        with self._get_session_context() as session:
            # Check if we're using SQLite (which doesn't have stddev function)
            engine_name = session.bind.dialect.name

            if engine_name == "sqlite":
                # For SQLite, calculate std_dev manually or skip it
                query = session.query(
                    func.count(RunMetric.id).label("run_count"),
                    func.avg(RunMetric.mean_score).label("overall_mean"),
                    func.min(RunMetric.mean_score).label("min_mean"),
                    func.max(RunMetric.mean_score).label("max_mean"),
                ).filter(RunMetric.metric_name == metric_name)
            else:
                # For PostgreSQL and other databases with stddev function
                query = session.query(
                    func.count(RunMetric.id).label("run_count"),
                    func.avg(RunMetric.mean_score).label("overall_mean"),
                    func.min(RunMetric.mean_score).label("min_mean"),
                    func.max(RunMetric.mean_score).label("max_mean"),
                    func.stddev(RunMetric.mean_score).label("std_dev"),
                ).filter(RunMetric.metric_name == metric_name)

            if project_id:
                query = query.join(EvaluationRun).filter(
                    EvaluationRun.project_id == project_id
                )

            result = query.first()

            # For SQLite, calculate standard deviation manually if we have data
            std_dev = 0.0
            if engine_name == "sqlite" and result and result.run_count > 1:
                # Get all values for manual std_dev calculation
                values_query = session.query(RunMetric.mean_score).filter(
                    RunMetric.metric_name == metric_name
                )
                if project_id:
                    values_query = values_query.join(EvaluationRun).filter(
                        EvaluationRun.project_id == project_id
                    )

                values = [row[0] for row in values_query.all() if row[0] is not None]
                if len(values) > 1:
                    mean = sum(values) / len(values)
                    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
                    std_dev = variance**0.5
            elif engine_name != "sqlite" and result:
                std_dev = (
                    float(result.std_dev)
                    if hasattr(result, "std_dev") and result.std_dev
                    else 0.0
                )

            return {
                "metric_name": metric_name,
                "run_count": result.run_count or 0,
                "overall_mean": (
                    float(result.overall_mean) if result.overall_mean else 0.0
                ),
                "min_mean": float(result.min_mean) if result.min_mean else 0.0,
                "max_mean": float(result.max_mean) if result.max_mean else 0.0,
                "std_dev": std_dev,
            }

    # Comparison Operations

    def get_comparison(
        self, run1_id: Union[str, UUID], run2_id: Union[str, UUID]
    ) -> Optional[RunComparison]:
        """
        Get cached comparison between two runs.

        Args:
            run1_id: First run UUID
            run2_id: Second run UUID

        Returns:
            RunComparison instance or None if not found
        """
        if run1_id is None or run2_id is None:
            return None

        try:
            # Convert to UUIDs if strings
            if isinstance(run1_id, str):
                uuid1_obj = UUID(run1_id)
            else:
                uuid1_obj = run1_id

            if isinstance(run2_id, str):
                uuid2_obj = UUID(run2_id)
            else:
                uuid2_obj = run2_id
        except (ValueError, TypeError):
            return None

        with self._get_session_context() as session:
            # Check both directions (run1,run2) and (run2,run1)
            comparison = (
                session.query(RunComparison)
                .filter(
                    or_(
                        and_(
                            RunComparison.run1_id == uuid1_obj,
                            RunComparison.run2_id == uuid2_obj,
                        ),
                        and_(
                            RunComparison.run1_id == uuid2_obj,
                            RunComparison.run2_id == uuid1_obj,
                        ),
                    )
                )
                .first()
            )

            return comparison

    def save_comparison(self, comparison_data: Dict[str, Any]) -> RunComparison:
        """
        Save run comparison results.

        Args:
            comparison_data: Dictionary containing comparison data

        Returns:
            Created RunComparison instance
        """
        with self._get_session_context() as session:
            comparison = RunComparison(**comparison_data)
            session.add(comparison)
            session.flush()

            return session.merge(comparison)
