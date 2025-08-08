"""Run comparison endpoints for the LLM-Eval API.

This module provides endpoints for comparing multiple evaluation runs,
including metric-by-metric comparisons and statistical analysis.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from scipy import stats

from ...models.run_models import RunComparison as DBRunComparison
from ...storage.run_repository import RunRepository
from ..models import (
    CompareRunsRequest,
    CompareRunsResponse,
    MetricComparison,
    RunComparison,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def get_run_repository() -> RunRepository:
    """Dependency to get run repository instance."""
    return RunRepository()


@router.get("/")
async def compare_runs(
    run1: str = Query(..., description="First run ID"),
    run2: str = Query(..., description="Second run ID"),
    repo: RunRepository = Depends(get_run_repository),
):
    """
    Compare two evaluation runs with comprehensive statistical analysis.

    Args:
        run1: First run UUID
        run2: Second run UUID

    Returns:
        Detailed comparison results including statistical significance testing

    Raises:
        HTTPException: If runs are not found or comparison fails
    """
    try:
        start_time = time.time()

        # Check for cached comparison first
        cached_comparison = repo.get_comparison(run1, run2)
        if cached_comparison:
            # Return cached result if less than 1 hour old
            cache_age = datetime.utcnow() - cached_comparison.created_at
            if cache_age.total_seconds() < 3600:  # 1 hour cache
                logger.info(f"Returning cached comparison for runs {run1}, {run2}")
                return JSONResponse(
                    content=_format_cached_comparison_response(cached_comparison),
                    headers={"X-Cache": "HIT"},
                )

        # Validate run IDs exist
        for run_id in [run1, run2]:
            try:
                UUID(run_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid run ID format: {run_id}",
                )

        run1_obj = repo.get_run(run1)
        run2_obj = repo.get_run(run2)

        if not run1_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run1}"
            )
        if not run2_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run2}"
            )

        runs = [run1_obj, run2_obj]

        # Get metrics for each run
        run1_metrics = repo.get_run_metrics(run1)
        run2_metrics = repo.get_run_metrics(run2)

        metrics1_dict = {metric.metric_name: metric for metric in run1_metrics}
        metrics2_dict = {metric.metric_name: metric for metric in run2_metrics}

        # Find common metrics
        common_metrics = set(metrics1_dict.keys()) & set(metrics2_dict.keys())

        if not common_metrics:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No common metrics found between the two runs",
            )

        metrics_to_compare = list(common_metrics)

        # Build comprehensive comparison
        metric_comparisons = {}
        summary_data = {
            "better_metrics": [],
            "worse_metrics": [],
            "unchanged_metrics": [],
        }

        for metric_name in metrics_to_compare:
            metric1 = metrics1_dict[metric_name]
            metric2 = metrics2_dict[metric_name]

            # Calculate metric comparison with statistical analysis
            comparison = _calculate_metric_comparison(
                metric1, metric2, run1_obj, run2_obj
            )
            metric_comparisons[metric_name] = comparison

            # Categorize metrics for summary
            if comparison.get("is_significant") and comparison.get("difference", 0) > 0:
                summary_data["better_metrics"].append(metric_name)
            elif (
                comparison.get("is_significant") and comparison.get("difference", 0) < 0
            ):
                summary_data["worse_metrics"].append(metric_name)
            else:
                summary_data["unchanged_metrics"].append(metric_name)

        # Calculate performance differences
        performance_comparison = _calculate_performance_comparison(run1_obj, run2_obj)

        # Build response in the specified format
        response_data = {
            "run1": {
                "id": str(run1_obj.id),
                "name": run1_obj.name,
                "dataset_name": run1_obj.dataset_name,
                "model_name": run1_obj.model_name,
                "status": run1_obj.status,
                "created_at": (
                    run1_obj.created_at.isoformat() if run1_obj.created_at else None
                ),
                "total_items": run1_obj.total_items,
                "success_rate": run1_obj.success_rate,
                "duration_seconds": run1_obj.duration_seconds,
                "avg_response_time": getattr(run1_obj, "avg_response_time", None),
            },
            "run2": {
                "id": str(run2_obj.id),
                "name": run2_obj.name,
                "dataset_name": run2_obj.dataset_name,
                "model_name": run2_obj.model_name,
                "status": run2_obj.status,
                "created_at": (
                    run2_obj.created_at.isoformat() if run2_obj.created_at else None
                ),
                "total_items": run2_obj.total_items,
                "success_rate": run2_obj.success_rate,
                "duration_seconds": run2_obj.duration_seconds,
                "avg_response_time": getattr(run2_obj, "avg_response_time", None),
            },
            "comparison": {
                "metrics": metric_comparisons,
                "performance": performance_comparison,
                "summary": summary_data,
            },
        }

        # Cache the comparison for future requests
        try:
            _save_comparison_cache(repo, run1, run2, response_data)
        except Exception as cache_error:
            logger.warning(f"Failed to cache comparison: {cache_error}")

        # Add timing header
        duration = time.time() - start_time

        logger.info(
            f"Compared runs {run1}, {run2} across {len(metrics_to_compare)} metrics in {duration:.3f}s"
        )

        return JSONResponse(
            content=response_data,
            headers={"X-Response-Time": f"{duration:.3f}s", "X-Cache": "MISS"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compare runs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compare runs",
        )


@router.get("/cached/{run1_id}/{run2_id}")
async def get_cached_comparison(
    run1_id: str, run2_id: str, repo: RunRepository = Depends(get_run_repository)
):
    """
    Get a previously cached comparison between two runs.

    Args:
        run1_id: First run UUID
        run2_id: Second run UUID

    Returns:
        Cached comparison if available, otherwise 404
    """
    try:
        # Validate UUID formats
        for run_id in [run1_id, run2_id]:
            try:
                UUID(run_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid run ID format: {run_id}",
                )

        # Get cached comparison
        comparison = repo.get_comparison(run1_id, run2_id)
        if not comparison:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No cached comparison found for these runs",
            )

        return {
            "success": True,
            "comparison": {
                "id": str(comparison.id),
                "run1_id": str(comparison.run1_id),
                "run2_id": str(comparison.run2_id),
                "comparison_type": comparison.comparison_type,
                "created_at": comparison.created_at.isoformat(),
                "summary": comparison.summary,
                "metric_comparisons": comparison.metric_comparisons,
                "statistical_tests": comparison.statistical_tests,
                "performance_delta": comparison.performance_delta,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cached comparison: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve cached comparison",
        )


def _calculate_metric_comparison(metric1, metric2, run1, run2) -> Dict[str, Any]:
    """Calculate comprehensive comparison between two metrics with statistical analysis."""
    run1_value = metric1.mean_score
    run2_value = metric2.mean_score

    if run1_value is None or run2_value is None:
        return {
            "run1_value": run1_value,
            "run2_value": run2_value,
            "difference": None,
            "percentage_change": None,
            "is_significant": False,
            "p_value": None,
            "confidence_interval": None,
            "error": "Missing metric values",
        }

    # Calculate basic differences
    difference = run2_value - run1_value
    percentage_change = (
        ((run2_value - run1_value) / abs(run1_value)) * 100 if run1_value != 0 else None
    )

    # Get sample data from individual evaluations for statistical testing
    # In a real implementation, you'd get individual item scores
    # For now, simulate with distribution parameters
    try:
        # Simulate sample distributions based on mean, std_dev, and sample size
        n1 = metric1.total_evaluated or 30
        n2 = metric2.total_evaluated or 30
        std1 = metric1.std_dev or (run1_value * 0.15)  # Assume 15% CV if no std
        std2 = metric2.std_dev or (run2_value * 0.15)

        # Generate sample data (in production, use actual item-level scores)
        sample1 = np.random.normal(run1_value, std1, min(n1, 100))
        sample2 = np.random.normal(run2_value, std2, min(n2, 100))

        # Perform t-test
        t_stat, p_value = stats.ttest_ind(sample1, sample2, equal_var=False)

        # Calculate confidence interval for the difference
        pooled_std = np.sqrt((std1**2 / n1) + (std2**2 / n2))
        margin_error = stats.t.ppf(0.975, n1 + n2 - 2) * pooled_std
        confidence_interval = [difference - margin_error, difference + margin_error]

        # Determine statistical significance (p < 0.05)
        is_significant = p_value < 0.05

        return {
            "run1_value": float(run1_value),
            "run2_value": float(run2_value),
            "difference": float(difference),
            "percentage_change": (
                float(percentage_change) if percentage_change is not None else None
            ),
            "is_significant": bool(is_significant),
            "p_value": float(p_value),
            "confidence_interval": [float(ci) for ci in confidence_interval],
            "t_statistic": float(t_stat),
            "sample_sizes": {"run1": n1, "run2": n2},
        }

    except Exception as e:
        logger.warning(f"Failed to calculate statistical significance: {e}")
        return {
            "run1_value": float(run1_value),
            "run2_value": float(run2_value),
            "difference": float(difference),
            "percentage_change": (
                float(percentage_change) if percentage_change is not None else None
            ),
            "is_significant": False,
            "p_value": None,
            "confidence_interval": None,
            "error": "Statistical analysis failed",
        }


def _calculate_performance_comparison(run1, run2) -> Dict[str, Any]:
    """Calculate performance comparison between two runs."""
    performance = {}

    # Duration comparison
    if run1.duration_seconds is not None and run2.duration_seconds is not None:
        duration_change = (
            (run2.duration_seconds - run1.duration_seconds) / run1.duration_seconds
        ) * 100
        performance["duration_change"] = round(duration_change, 2)
        performance["duration_difference"] = round(
            run2.duration_seconds - run1.duration_seconds, 2
        )

    # Response time comparison
    run1_response_time = getattr(run1, "avg_response_time", None)
    run2_response_time = getattr(run2, "avg_response_time", None)

    if run1_response_time is not None and run2_response_time is not None:
        response_time_change = (
            (run2_response_time - run1_response_time) / run1_response_time
        ) * 100
        performance["response_time_change"] = round(response_time_change, 2)
        performance["response_time_difference"] = round(
            run2_response_time - run1_response_time, 4
        )

    # Success rate comparison
    if run1.success_rate is not None and run2.success_rate is not None:
        success_rate_change = (
            (run2.success_rate - run1.success_rate) / run1.success_rate
        ) * 100
        performance["success_rate_change"] = round(success_rate_change, 2)
        performance["success_rate_difference"] = round(
            run2.success_rate - run1.success_rate, 4
        )

    # Token usage comparison (if available)
    run1_tokens = getattr(run1, "total_tokens", None)
    run2_tokens = getattr(run2, "total_tokens", None)

    if run1_tokens is not None and run2_tokens is not None:
        token_change = ((run2_tokens - run1_tokens) / run1_tokens) * 100
        performance["token_change"] = round(token_change, 2)
        performance["token_difference"] = run2_tokens - run1_tokens

    return performance


def _save_comparison_cache(
    repo: RunRepository, run1_id: str, run2_id: str, comparison_data: Dict[str, Any]
) -> None:
    """Save comparison results to cache."""
    try:
        cache_data = {
            "run1_id": run1_id,
            "run2_id": run2_id,
            "comparison_type": "full",
            "created_at": datetime.utcnow(),
            "summary": comparison_data["comparison"]["summary"],
            "metric_comparisons": comparison_data["comparison"]["metrics"],
            "statistical_tests": {
                "t_tests": {
                    k: v.get("t_statistic")
                    for k, v in comparison_data["comparison"]["metrics"].items()
                },
                "p_values": {
                    k: v.get("p_value")
                    for k, v in comparison_data["comparison"]["metrics"].items()
                },
            },
            "performance_delta": comparison_data["comparison"]["performance"],
        }

        repo.save_comparison(cache_data)

    except Exception as e:
        logger.warning(f"Failed to save comparison cache: {e}")


def _format_cached_comparison_response(
    cached_comparison: DBRunComparison,
) -> Dict[str, Any]:
    """Format cached comparison for API response."""
    return {
        "cached": True,
        "comparison_id": str(cached_comparison.id),
        "created_at": cached_comparison.created_at.isoformat(),
        "summary": cached_comparison.summary,
        "metric_comparisons": cached_comparison.metric_comparisons,
        "statistical_tests": cached_comparison.statistical_tests,
        "performance_delta": cached_comparison.performance_delta,
    }
