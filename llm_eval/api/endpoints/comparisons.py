"""Run comparison endpoints for the LLM-Eval API.

This module provides endpoints for comparing multiple evaluation runs,
including metric-by-metric comparisons and statistical analysis.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Depends, status

from ..models import CompareRunsRequest, CompareRunsResponse, RunComparison, MetricComparison
from ...storage.run_repository import RunRepository


logger = logging.getLogger(__name__)

router = APIRouter()


def get_run_repository() -> RunRepository:
    """Dependency to get run repository instance."""
    return RunRepository()


@router.post("/", response_model=CompareRunsResponse)
async def compare_runs(
    request: CompareRunsRequest,
    repo: RunRepository = Depends(get_run_repository)
):
    """
    Compare multiple evaluation runs across specified metrics.
    
    Args:
        request: Comparison request with run IDs and options
        
    Returns:
        Detailed comparison results including metric analysis
        
    Raises:
        HTTPException: If runs are not found or comparison fails
    """
    try:
        # Validate all run IDs exist
        runs = []
        for run_id in request.run_ids:
            try:
                UUID(run_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid run ID format: {run_id}"
                )
            
            run = repo.get_run(run_id)
            if not run:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run not found: {run_id}"
                )
            runs.append(run)
        
        # Get metrics for each run
        all_metrics = {}
        common_metrics = set()
        
        for run in runs:
            run_metrics = repo.get_run_metrics(run.id)
            metrics_dict = {metric.metric_name: metric for metric in run_metrics}
            all_metrics[str(run.id)] = metrics_dict
            
            if not common_metrics:
                common_metrics = set(metrics_dict.keys())
            else:
                common_metrics &= set(metrics_dict.keys())
        
        # Determine which metrics to compare
        if request.metrics:
            # Use specified metrics, but only include ones that exist in all runs
            metrics_to_compare = [m for m in request.metrics if m in common_metrics]
            if not metrics_to_compare:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="None of the specified metrics are available in all runs"
                )
        else:
            # Use all common metrics
            metrics_to_compare = list(common_metrics)
        
        if not metrics_to_compare:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No common metrics found across all runs"
            )
        
        # Build metric comparisons
        metric_comparisons = []
        summary_data = {
            'run_count': len(runs),
            'common_metrics': len(metrics_to_compare),
            'comparison_type': request.comparison_type,
            'runs_info': {}
        }
        
        for metric_name in metrics_to_compare:
            metric_data = {}
            scores = []
            
            for run in runs:
                run_id = str(run.id)
                metric = all_metrics[run_id][metric_name]
                
                metric_info = {
                    'run_name': run.name,
                    'mean_score': metric.mean_score,
                    'median_score': metric.median_score,
                    'std_dev': metric.std_dev,
                    'min_score': metric.min_score,
                    'max_score': metric.max_score,
                    'success_rate': metric.success_rate,
                    'total_evaluated': metric.total_evaluated
                }
                
                metric_data[run_id] = metric_info
                if metric.mean_score is not None:
                    scores.append(metric.mean_score)
                
                # Add to summary
                if run_id not in summary_data['runs_info']:
                    summary_data['runs_info'][run_id] = {
                        'name': run.name,
                        'dataset': run.dataset_name,
                        'model': run.model_name,
                        'status': run.status,
                        'created_at': run.created_at.isoformat()
                    }
            
            # Calculate basic statistics
            statistical_tests = None
            if len(scores) >= 2 and request.comparison_type == "full":
                statistical_tests = _calculate_basic_stats(scores)
            
            # Generate summary for this metric
            metric_summary = _generate_metric_summary(metric_name, metric_data, scores)
            
            metric_comparison = MetricComparison(
                metric_name=metric_name,
                runs=metric_data,
                statistical_tests=statistical_tests,
                summary=metric_summary
            )
            metric_comparisons.append(metric_comparison)
        
        # Calculate performance differences if requested
        performance_differences = None
        if request.comparison_type == "full":
            performance_differences = _calculate_performance_differences(runs, all_metrics)
        
        # Build final comparison result
        comparison = RunComparison(
            run_ids=request.run_ids,
            comparison_type=request.comparison_type,
            created_at=datetime.utcnow(),
            metric_comparisons=metric_comparisons,
            summary=summary_data,
            performance_differences=performance_differences
        )
        
        logger.info(f"Compared {len(request.run_ids)} runs across {len(metrics_to_compare)} metrics")
        
        return CompareRunsResponse(
            success=True,
            message=f"Successfully compared {len(request.run_ids)} runs",
            comparison=comparison
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compare runs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compare runs"
        )


@router.get("/cached/{run1_id}/{run2_id}")
async def get_cached_comparison(
    run1_id: str,
    run2_id: str,
    repo: RunRepository = Depends(get_run_repository)
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
                    detail=f"Invalid run ID format: {run_id}"
                )
        
        # Get cached comparison
        comparison = repo.get_comparison(run1_id, run2_id)
        if not comparison:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No cached comparison found for these runs"
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
                "performance_delta": comparison.performance_delta
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cached comparison: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve cached comparison"
        )


def _calculate_basic_stats(scores: List[float]) -> Dict[str, Any]:
    """Calculate basic statistical measures for score comparison."""
    if len(scores) < 2:
        return {}
    
    import statistics
    
    stats = {
        'count': len(scores),
        'mean': statistics.mean(scores),
        'median': statistics.median(scores),
        'std_dev': statistics.stdev(scores) if len(scores) > 1 else 0,
        'min': min(scores),
        'max': max(scores),
        'range': max(scores) - min(scores)
    }
    
    # Add percentiles if we have enough data
    if len(scores) >= 4:
        sorted_scores = sorted(scores)
        stats['q1'] = statistics.quantiles(sorted_scores, n=4)[0]
        stats['q3'] = statistics.quantiles(sorted_scores, n=4)[2]
        stats['iqr'] = stats['q3'] - stats['q1']
    
    return stats


def _generate_metric_summary(metric_name: str, metric_data: Dict[str, Dict], scores: List[float]) -> str:
    """Generate a human-readable summary for a metric comparison."""
    if not scores:
        return f"No valid scores available for {metric_name}"
    
    if len(scores) == 1:
        return f"{metric_name}: Single run with score {scores[0]:.3f}"
    
    best_run = None
    best_score = max(scores)
    worst_score = min(scores)
    
    # Find which run had the best score
    for run_id, data in metric_data.items():
        if data.get('mean_score') == best_score:
            best_run = data.get('run_name', run_id)
            break
    
    range_val = best_score - worst_score
    
    if range_val == 0:
        return f"{metric_name}: All runs performed equally with score {best_score:.3f}"
    else:
        return (f"{metric_name}: Best performance by '{best_run}' ({best_score:.3f}), "
                f"range of {range_val:.3f} across all runs")


def _calculate_performance_differences(runs: List, all_metrics: Dict[str, Dict]) -> Dict[str, Any]:
    """Calculate performance differences between runs."""
    if len(runs) < 2:
        return {}
    
    differences = {
        'timing_comparison': {},
        'success_rate_comparison': {},
        'overall_ranking': []
    }
    
    # Compare timing metrics
    timing_data = []
    for run in runs:
        if run.avg_response_time is not None:
            timing_data.append({
                'run_id': str(run.id),
                'run_name': run.name,
                'avg_response_time': run.avg_response_time,
                'total_duration': run.duration_seconds
            })
    
    if timing_data:
        timing_data.sort(key=lambda x: x['avg_response_time'])
        differences['timing_comparison'] = {
            'fastest_run': timing_data[0],
            'slowest_run': timing_data[-1],
            'speed_difference': timing_data[-1]['avg_response_time'] - timing_data[0]['avg_response_time']
        }
    
    # Compare success rates
    success_data = []
    for run in runs:
        if run.success_rate is not None:
            success_data.append({
                'run_id': str(run.id),
                'run_name': run.name,
                'success_rate': run.success_rate
            })
    
    if success_data:
        success_data.sort(key=lambda x: x['success_rate'], reverse=True)
        differences['success_rate_comparison'] = {
            'highest_success': success_data[0],
            'lowest_success': success_data[-1],
            'success_rate_difference': success_data[0]['success_rate'] - success_data[-1]['success_rate']
        }
    
    # Simple overall ranking based on average metric performance
    run_scores = {}
    for run_id, metrics in all_metrics.items():
        scores = [m.mean_score for m in metrics.values() if m.mean_score is not None]
        if scores:
            run_scores[run_id] = sum(scores) / len(scores)
    
    if run_scores:
        sorted_runs = sorted(run_scores.items(), key=lambda x: x[1], reverse=True)
        differences['overall_ranking'] = [
            {
                'run_id': run_id,
                'run_name': next(run.name for run in runs if str(run.id) == run_id),
                'average_score': score
            }
            for run_id, score in sorted_runs
        ]
    
    return differences