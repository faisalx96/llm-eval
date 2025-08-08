"""Run management endpoints for the LLM-Eval API.

This module provides REST endpoints for CRUD operations on evaluation runs,
including listing, filtering, searching, and detailed run management.
"""

import logging
import math
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from ...storage.database import get_database_manager
from ...storage.run_repository import RunRepository
from ..models import (
    APIResponse,
    CreateRunRequest,
    CreateRunResponse,
    GetRunResponse,
    ListRunsResponse,
    PaginationParams,
    RunDetail,
    RunFilters,
    RunMetricDetail,
    RunMetricsResponse,
    RunSorting,
    RunSummary,
    UpdateRunRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def get_run_repository() -> RunRepository:
    """Dependency to get run repository instance."""
    return RunRepository()


@router.post("/", response_model=CreateRunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    run_data: CreateRunRequest, repo: RunRepository = Depends(get_run_repository)
):
    """
    Create a new evaluation run.

    Args:
        run_data: Run creation data

    Returns:
        Created run details

    Raises:
        HTTPException: If run creation fails
    """
    try:
        # Convert Pydantic model to dict for repository
        run_dict = run_data.model_dump(exclude_unset=True)

        # Set default status if not provided
        if "status" not in run_dict:
            run_dict["status"] = "running"

        # Create the run
        created_run = repo.create_run(run_dict)

        # Convert to response model manually to avoid session issues
        run_detail = RunDetail(
            id=created_run.id,
            name=created_run.name,
            description=created_run.description,
            status=created_run.status,
            dataset_name=created_run.dataset_name,
            model_name=created_run.model_name,
            model_version=getattr(created_run, "model_version", None),
            task_type=created_run.task_type,
            metrics_used=getattr(created_run, "metrics_used", []),
            metric_configs=getattr(created_run, "metric_configs", {}),
            created_at=created_run.created_at,
            started_at=getattr(created_run, "started_at", None),
            completed_at=created_run.completed_at,
            duration_seconds=created_run.duration_seconds,
            total_items=created_run.total_items,
            successful_items=created_run.successful_items,
            failed_items=getattr(created_run, "failed_items", 0),
            success_rate=created_run.success_rate,
            avg_response_time=getattr(created_run, "avg_response_time", None),
            min_response_time=getattr(created_run, "min_response_time", None),
            max_response_time=getattr(created_run, "max_response_time", None),
            config=getattr(created_run, "config", {}),
            environment=getattr(created_run, "environment", {}),
            tags=created_run.tags,
            created_by=getattr(created_run, "created_by", None),
            project_id=getattr(created_run, "project_id", None),
        )

        logger.info(f"Created new evaluation run: {created_run.id}")

        return CreateRunResponse(
            success=True, message="Run created successfully", run=run_detail
        )

    except IntegrityError as e:
        logger.error(f"Failed to create run due to integrity error: {e}")
        raise HTTPException(
            status_code=400, detail="Failed to create run: data integrity violation"
        )
    except Exception as e:
        logger.error(f"Failed to create run: {e}")
        raise HTTPException(status_code=500, detail="Failed to create run")


@router.get("/", response_model=ListRunsResponse)
@router.get(
    "", response_model=ListRunsResponse
)  # Handle both with and without trailing slash
async def list_runs(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    dataset_name: Optional[str] = Query(None, description="Filter by dataset name"),
    model_name: Optional[str] = Query(None, description="Filter by model name"),
    status: Optional[str] = Query(
        None,
        pattern="^(running|completed|failed|cancelled)$",
        description="Filter by status",
    ),
    created_by: Optional[str] = Query(None, description="Filter by creator"),
    tags: Optional[List[str]] = Query(None, description="Filter by tags"),
    min_success_rate: Optional[float] = Query(
        None, ge=0, le=1, description="Minimum success rate"
    ),
    max_duration: Optional[float] = Query(
        None, gt=0, description="Maximum duration in seconds"
    ),
    created_after: Optional[datetime] = Query(
        None, description="Filter runs created after this date"
    ),
    created_before: Optional[datetime] = Query(
        None, description="Filter runs created before this date"
    ),
    search: Optional[str] = Query(
        None, min_length=1, description="Search in name, description, or dataset"
    ),
    order_by: str = Query(
        "created_at",
        pattern="^(created_at|name|status|success_rate|duration_seconds)$",
        description="Field to sort by",
    ),
    descending: bool = Query(True, description="Sort in descending order"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    repo: RunRepository = Depends(get_run_repository),
):
    """
    List evaluation runs with filtering, searching, and pagination.

    Returns:
        Paginated list of evaluation runs matching the criteria
    """
    try:
        # If search is provided, use search endpoint
        if search:
            runs = repo.search_runs(search, limit=per_page)
            total = len(runs)
        else:
            # Calculate offset
            offset = (page - 1) * per_page

            # Get filtered runs
            runs = repo.list_runs(
                project_id=project_id,
                dataset_name=dataset_name,
                model_name=model_name,
                status=status,
                created_by=created_by,
                tags=tags,
                min_success_rate=min_success_rate,
                max_duration=max_duration,
                created_after=created_after,
                created_before=created_before,
                order_by=order_by,
                descending=descending,
                limit=per_page,
                offset=offset,
            )

            # Get total count for pagination
            filter_params = {
                "project_id": project_id,
                "dataset_name": dataset_name,
                "model_name": model_name,
                "status": status,
                "created_by": created_by,
                "min_success_rate": min_success_rate,
                "max_duration": max_duration,
            }
            total = repo.count_runs(
                **{k: v for k, v in filter_params.items() if v is not None}
            )

        # Convert dictionaries to Pydantic models
        run_summaries = []
        for run_dict in runs:
            try:
                # Create RunSummary from dictionary
                run_summary = RunSummary(**run_dict)
                run_summaries.append(run_summary)
            except Exception as e:
                logger.warning(
                    f"Failed to convert run {run_dict.get('id', 'unknown')} to summary: {e}"
                )
                continue

        # Calculate pagination info
        total_pages = math.ceil(total / per_page) if total > 0 else 1

        return ListRunsResponse(
            items=run_summaries,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        )

    except Exception as e:
        logger.error(f"Failed to list runs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve runs")


@router.get("/{run_id}", response_model=GetRunResponse)
async def get_run(run_id: str, repo: RunRepository = Depends(get_run_repository)):
    """
    Get detailed information about a specific evaluation run.

    Args:
        run_id: UUID of the evaluation run

    Returns:
        Detailed run information including metrics

    Raises:
        HTTPException: If run is not found
    """
    try:
        # Validate UUID format
        try:
            UUID(run_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid run ID format")

        # Get run details
        run = repo.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        # Get run metrics
        metrics = repo.get_run_metrics(run_id)

        # Convert to response models manually to avoid session issues
        run_detail = RunDetail(
            id=run.id,
            name=run.name,
            description=run.description,
            status=run.status,
            dataset_name=run.dataset_name,
            model_name=run.model_name,
            model_version=getattr(run, "model_version", None),
            task_type=run.task_type,
            metrics_used=getattr(run, "metrics_used", []),
            metric_configs=getattr(run, "metric_configs", {}),
            created_at=run.created_at,
            started_at=getattr(run, "started_at", None),
            completed_at=run.completed_at,
            duration_seconds=run.duration_seconds,
            total_items=run.total_items,
            successful_items=run.successful_items,
            failed_items=getattr(run, "failed_items", 0),
            success_rate=run.success_rate,
            avg_response_time=getattr(run, "avg_response_time", None),
            min_response_time=getattr(run, "min_response_time", None),
            max_response_time=getattr(run, "max_response_time", None),
            config=getattr(run, "config", {}),
            environment=getattr(run, "environment", {}),
            tags=run.tags,
            created_by=getattr(run, "created_by", None),
            project_id=getattr(run, "project_id", None),
        )
        metric_details = []

        return GetRunResponse(success=True, run=run_detail, metrics=metric_details)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get run {run_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve run")


@router.put("/{run_id}", response_model=GetRunResponse)
async def update_run(
    run_id: str,
    update_data: UpdateRunRequest,
    repo: RunRepository = Depends(get_run_repository),
):
    """
    Update an evaluation run's metadata.

    Args:
        run_id: UUID of the evaluation run
        update_data: Fields to update

    Returns:
        Updated run details

    Raises:
        HTTPException: If run is not found or update fails
    """
    try:
        # Validate UUID format
        try:
            UUID(run_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid run ID format")

        # Convert to dict and exclude unset fields
        updates = update_data.model_dump(exclude_unset=True)

        if not updates:
            raise HTTPException(status_code=400, detail="No update data provided")

        # Update the run
        updated_run = repo.update_run(run_id, updates)
        if not updated_run:
            raise HTTPException(status_code=404, detail="Run not found")

        # Get updated metrics
        metrics = repo.get_run_metrics(run_id)

        # Convert to response models
        run_detail = RunDetail.model_validate(updated_run)
        metric_details = [RunMetricDetail.model_validate(metric) for metric in metrics]

        logger.info(f"Updated evaluation run: {run_id}")

        return GetRunResponse(
            success=True,
            message="Run updated successfully",
            run=run_detail,
            metrics=metric_details,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update run {run_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update run")


@router.delete("/{run_id}", response_model=APIResponse)
async def delete_run(run_id: str, repo: RunRepository = Depends(get_run_repository)):
    """
    Delete an evaluation run and all associated data.

    Args:
        run_id: UUID of the evaluation run

    Returns:
        Deletion confirmation

    Raises:
        HTTPException: If run is not found
    """
    try:
        # Validate UUID format
        try:
            UUID(run_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid run ID format")

        # Delete the run
        deleted = repo.delete_run(run_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Run not found")

        logger.info(f"Deleted evaluation run: {run_id}")

        return APIResponse(success=True, message="Run deleted successfully")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete run {run_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete run")


@router.get("/{run_id}/metrics", response_model=RunMetricsResponse)
async def get_run_metrics(
    run_id: str, repo: RunRepository = Depends(get_run_repository)
):
    """
    Get metrics for a specific evaluation run.

    Args:
        run_id: UUID of the evaluation run

    Returns:
        List of run metrics

    Raises:
        HTTPException: If run is not found
    """
    try:
        # Validate UUID format
        try:
            UUID(run_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid run ID format")

        # Check if run exists
        run = repo.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        # Get metrics
        metrics = repo.get_run_metrics(run_id)
        metric_details = [RunMetricDetail.model_validate(metric) for metric in metrics]

        return RunMetricsResponse(success=True, metrics=metric_details)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get metrics for run {run_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve metrics")


@router.get("/{run_id}/items", response_model=dict)
async def get_run_items(
    run_id: str,
    status: Optional[str] = Query(
        None, pattern="^(success|failed|pending)$", description="Filter by item status"
    ),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    offset: int = Query(0, ge=0, description="Items to skip"),
    repo: RunRepository = Depends(get_run_repository),
):
    """
    Get paginated items for a specific evaluation run.

    Args:
        run_id: UUID of the evaluation run
        status: Filter by item status
        limit: Number of items per page
        offset: Number of items to skip

    Returns:
        Paginated list of run items

    Raises:
        HTTPException: If run is not found
    """
    try:
        # Validate UUID format
        try:
            UUID(run_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid run ID format")

        # Check if run exists
        run = repo.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        # For now, return mock data since the actual implementation
        # would need to be connected to Langfuse or storage
        mock_items = []
        total_items = run.total_items or 0

        # Generate some mock items for demonstration
        for i in range(min(limit, total_items - offset)):
            item_status = (
                "success" if (i % 3) != 2 else "failed" if (i % 3) == 2 else "pending"
            )
            if status and item_status != status:
                continue

            mock_items.append(
                {
                    "id": f"item-{run_id}-{offset + i}",
                    "run_id": run_id,
                    "input_data": {
                        "question": f"Sample question {offset + i + 1}",
                        "context": f"Sample context for item {offset + i + 1}",
                    },
                    "output_data": (
                        {"answer": f"Sample answer {offset + i + 1}"}
                        if item_status != "pending"
                        else None
                    ),
                    "expected_output": {"answer": f"Expected answer {offset + i + 1}"},
                    "scores": (
                        {
                            "accuracy": 0.85 + (i % 10) * 0.01,
                            "relevance": 0.90 - (i % 5) * 0.02,
                            "faithfulness": 0.88 + (i % 7) * 0.015,
                        }
                        if item_status == "success"
                        else (
                            {
                                "accuracy": 0.45 + (i % 5) * 0.1,
                                "relevance": 0.50 - (i % 3) * 0.1,
                                "faithfulness": 0.40 + (i % 4) * 0.05,
                            }
                            if item_status == "failed"
                            else {}
                        )
                    ),
                    "status": item_status,
                    "error_message": (
                        f"Sample error message for item {offset + i + 1}"
                        if item_status == "failed"
                        else None
                    ),
                    "response_time": (
                        1.2 + (i % 10) * 0.1 if item_status != "pending" else None
                    ),
                    "tokens_used": 150 + (i % 50) if item_status != "pending" else None,
                    "cost": (
                        0.002 + (i % 10) * 0.0001 if item_status != "pending" else None
                    ),
                    "created_at": run.created_at.isoformat(),
                    "processed_at": (
                        run.created_at.isoformat() if item_status != "pending" else None
                    ),
                }
            )

        # Filter by status if specified
        if status:
            mock_items = [item for item in mock_items if item["status"] == status]
            if status == "success":
                total_filtered = len([i for i in range(total_items) if (i % 3) != 2])
            elif status == "failed":
                total_filtered = len([i for i in range(total_items) if (i % 3) == 2])
            else:
                total_filtered = len([i for i in range(total_items) if (i % 3) == 1])
            total_items = total_filtered

        return {
            "items": mock_items,
            "total": total_items,
            "limit": limit,
            "offset": offset,
            "has_next": offset + limit < total_items,
            "has_prev": offset > 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get items for run {run_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve run items")
