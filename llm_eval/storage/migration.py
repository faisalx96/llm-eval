"""Migration utilities for converting EvaluationResult to database storage."""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import uuid4, UUID

from ..core.results import EvaluationResult
from ..models.run_models import EvaluationRun, EvaluationItem, RunMetric
from .database import get_database_manager
from .run_repository import RunRepository


logger = logging.getLogger(__name__)


def migrate_from_evaluation_result(
    evaluation_result: EvaluationResult,
    project_id: Optional[str] = None,
    created_by: Optional[str] = None,
    tags: Optional[List[str]] = None,
    store_individual_items: bool = True
) -> str:
    """
    Migrate EvaluationResult to database storage.
    
    Args:
        evaluation_result: EvaluationResult instance to migrate
        project_id: Optional project identifier
        created_by: User who created the run
        tags: Optional list of tags for organization
        store_individual_items: Whether to store individual evaluation items
        
    Returns:
        UUID of the created evaluation run
        
    Raises:
        Exception: If migration fails
    """
    logger.info(f"Migrating evaluation result: {evaluation_result.run_name}")
    
    try:
        # Create repository
        repo = RunRepository()
        
        # Prepare run data
        run_data = _convert_evaluation_result_to_run_data(
            evaluation_result, project_id, created_by, tags
        )
        
        # Create evaluation run
        run = repo.create_run(run_data)
        run_id = str(run.id)  # Convert to string immediately to avoid session issues
        
        logger.info(f"Created evaluation run with ID: {run_id}")
        
        # Store individual items if requested
        if store_individual_items:
            _store_evaluation_items(evaluation_result, run_id, repo)
        
        # Store metric statistics
        _store_run_metrics(evaluation_result, run_id, repo)
        
        logger.info(f"Successfully migrated evaluation result to run ID: {run_id}")
        return run_id  # Already a string
        
    except Exception as e:
        logger.error(f"Failed to migrate evaluation result: {e}")
        raise


def _convert_evaluation_result_to_run_data(
    evaluation_result: EvaluationResult,
    project_id: Optional[str] = None,
    created_by: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Convert EvaluationResult to run data dictionary."""
    
    # Extract timing statistics
    timing_stats = evaluation_result.get_timing_stats()
    
    # Determine task type from metrics (simple heuristic)
    task_type = _infer_task_type(evaluation_result.metrics)
    
    run_data = {
        'name': evaluation_result.run_name,
        'description': f"Migrated from EvaluationResult on {datetime.utcnow().isoformat()}",
        'status': 'completed',  # EvaluationResult is always completed
        'dataset_name': evaluation_result.dataset_name,
        'model_name': None,  # Not available in EvaluationResult
        'model_version': None,
        'task_type': task_type,
        'metrics_used': evaluation_result.metrics,
        'metric_configs': None,  # Not available in EvaluationResult
        'created_at': evaluation_result.start_time,
        'started_at': evaluation_result.start_time,
        'completed_at': evaluation_result.end_time,
        'duration_seconds': evaluation_result.duration,
        'total_items': evaluation_result.total_items,
        'successful_items': len(evaluation_result.results),
        'failed_items': len(evaluation_result.errors),
        'success_rate': evaluation_result.success_rate,
        'avg_response_time': timing_stats.get('mean'),
        'min_response_time': timing_stats.get('min'),
        'max_response_time': timing_stats.get('max'),
        'config': None,  # Not available in EvaluationResult
        'environment': _get_environment_info(),
        'tags': tags or [],
        'created_by': created_by,
        'project_id': project_id
    }
    
    return run_data


def _infer_task_type(metrics: List[str]) -> Optional[str]:
    """Infer task type from metrics used."""
    metric_set = set(m.lower() for m in metrics)
    
    if 'exact_match' in metric_set or 'f1' in metric_set:
        return 'qa'
    elif 'accuracy' in metric_set or 'precision' in metric_set:
        return 'classification'
    elif any(m.startswith('rouge') for m in metric_set) or 'bleu' in metric_set:
        return 'summarization'
    elif 'faithfulness' in metric_set or 'answer_relevancy' in metric_set:
        return 'rag'
    else:
        return 'general'


def _get_environment_info() -> Dict[str, Any]:
    """Get basic environment information."""
    import platform
    import sys
    
    return {
        'python_version': sys.version,
        'platform': platform.platform(),
        'migration_timestamp': datetime.utcnow().isoformat(),
        'migration_source': 'EvaluationResult'
    }


def _store_evaluation_items(
    evaluation_result: EvaluationResult,
    run_id: str,
    repo: RunRepository
):
    """Store individual evaluation items."""
    logger.info(f"Storing {evaluation_result.total_items} evaluation items")
    
    db_manager = get_database_manager()
    
    with db_manager.get_session() as session:
        sequence_number = 1
        
        # Store successful results
        for item_id, result in evaluation_result.results.items():
            item_data = {
                'run_id': UUID(run_id) if isinstance(run_id, str) else run_id,
                'item_id': item_id,
                'sequence_number': sequence_number,
                'input_data': result.get('input'),  # May not be available
                'expected_output': result.get('expected'),
                'actual_output': result.get('output'),
                'status': 'completed',
                'error_message': None,
                'error_type': None,
                'started_at': None,  # Not available in EvaluationResult
                'completed_at': None,
                'response_time': result.get('time'),
                'tokens_used': result.get('tokens'),
                'cost': result.get('cost'),
                'scores': result.get('scores', {}),
                'langfuse_trace_id': result.get('trace_id'),
                'langfuse_observation_id': result.get('observation_id')
            }
            
            item = EvaluationItem(**item_data)
            session.add(item)
            sequence_number += 1
        
        # Store failed results
        for item_id, error in evaluation_result.errors.items():
            item_data = {
                'run_id': UUID(run_id) if isinstance(run_id, str) else run_id,
                'item_id': item_id,
                'sequence_number': sequence_number,
                'input_data': None,
                'expected_output': None,
                'actual_output': None,
                'status': 'failed',
                'error_message': str(error),
                'error_type': 'evaluation_error',
                'started_at': None,
                'completed_at': None,
                'response_time': None,
                'tokens_used': None,
                'cost': None,
                'scores': {},
                'langfuse_trace_id': None,
                'langfuse_observation_id': None
            }
            
            item = EvaluationItem(**item_data)
            session.add(item)
            sequence_number += 1
        
        session.commit()
        logger.info(f"Stored {sequence_number - 1} evaluation items")


def _store_run_metrics(
    evaluation_result: EvaluationResult,
    run_id: str,
    repo: RunRepository
):
    """Store aggregate metric statistics."""
    logger.info(f"Computing and storing metrics for {len(evaluation_result.metrics)} metrics")
    
    db_manager = get_database_manager()
    
    with db_manager.get_session() as session:
        for metric_name in evaluation_result.metrics:
            stats = evaluation_result.get_metric_stats(metric_name)
            
            # Compute score distribution for visualization
            score_distribution = _compute_score_distribution(
                evaluation_result, metric_name
            )
            
            # Compute percentiles
            percentiles = _compute_percentiles(
                evaluation_result, metric_name
            )
            
            # Determine metric type
            metric_type = _determine_metric_type(
                evaluation_result, metric_name
            )
            
            metric_data = {
                'run_id': UUID(run_id) if isinstance(run_id, str) else run_id,
                'metric_name': metric_name,
                'metric_type': metric_type,
                'mean_score': stats.get('mean'),
                'median_score': None,  # Would need to compute from raw scores
                'std_dev': stats.get('std'),
                'min_score': stats.get('min'),
                'max_score': stats.get('max'),
                'total_evaluated': len(evaluation_result.results),
                'successful_evaluations': len([r for r in evaluation_result.results.values() 
                                             if 'scores' in r and metric_name in r['scores']]),
                'failed_evaluations': len(evaluation_result.errors),
                'success_rate': stats.get('success_rate'),
                'score_distribution': score_distribution,
                'percentiles': percentiles,
                'computed_at': datetime.utcnow()
            }
            
            metric = RunMetric(**metric_data)
            session.add(metric)
        
        session.commit()
        logger.info(f"Stored metrics for {len(evaluation_result.metrics)} metrics")


def _compute_score_distribution(
    evaluation_result: EvaluationResult,
    metric_name: str,
    num_buckets: int = 10
) -> Dict[str, Any]:
    """Compute score distribution for histogram visualization."""
    scores = []
    
    for result in evaluation_result.results.values():
        if 'scores' in result and metric_name in result['scores']:
            score = result['scores'][metric_name]
            if isinstance(score, (int, float)):
                scores.append(float(score))
            elif isinstance(score, bool):
                scores.append(1.0 if score else 0.0)
    
    if not scores:
        return {'buckets': [], 'counts': []}
    
    # Create histogram buckets
    min_score = min(scores)
    max_score = max(scores)
    
    if min_score == max_score:
        return {
            'buckets': [min_score],
            'counts': [len(scores)]
        }
    
    bucket_size = (max_score - min_score) / num_buckets
    buckets = [min_score + i * bucket_size for i in range(num_buckets + 1)]
    counts = [0] * num_buckets
    
    for score in scores:
        bucket_idx = min(int((score - min_score) / bucket_size), num_buckets - 1)
        counts[bucket_idx] += 1
    
    return {
        'buckets': buckets,
        'counts': counts,
        'total_scores': len(scores)
    }


def _compute_percentiles(
    evaluation_result: EvaluationResult,
    metric_name: str
) -> Dict[str, float]:
    """Compute common percentiles for a metric."""
    scores = []
    
    for result in evaluation_result.results.values():
        if 'scores' in result and metric_name in result['scores']:
            score = result['scores'][metric_name]
            if isinstance(score, (int, float)):
                scores.append(float(score))
            elif isinstance(score, bool):
                scores.append(1.0 if score else 0.0)
    
    if not scores:
        return {}
    
    scores.sort()
    n = len(scores)
    
    def percentile(p):
        """Calculate percentile."""
        if n == 0:
            return 0.0
        k = (n - 1) * p / 100
        f = int(k)
        c = k - f
        if f + 1 < n:
            return scores[f] * (1 - c) + scores[f + 1] * c
        else:
            return scores[f]
    
    return {
        'p25': percentile(25),
        'p50': percentile(50),  # median
        'p75': percentile(75),
        'p90': percentile(90),
        'p95': percentile(95),
        'p99': percentile(99)
    }


def _determine_metric_type(
    evaluation_result: EvaluationResult,
    metric_name: str
) -> str:
    """Determine metric type from sample scores."""
    for result in evaluation_result.results.values():
        if 'scores' in result and metric_name in result['scores']:
            score = result['scores'][metric_name]
            if isinstance(score, bool):
                return 'boolean'
            elif isinstance(score, (int, float)):
                return 'numeric'
            else:
                return 'custom'
    
    return 'unknown'


def migrate_json_export(
    json_file_path: str,
    project_id: Optional[str] = None,
    created_by: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> str:
    """
    Migrate evaluation results from JSON export file.
    
    Args:
        json_file_path: Path to JSON file created by EvaluationResult.save_json()
        project_id: Optional project identifier
        created_by: User who created the run
        tags: Optional list of tags
        
    Returns:
        UUID of the created evaluation run
    """
    logger.info(f"Migrating JSON export from: {json_file_path}")
    
    with open(json_file_path, 'r') as f:
        data = json.load(f)
    
    # Reconstruct EvaluationResult from JSON data
    eval_result = EvaluationResult(
        dataset_name=data['dataset_name'],
        run_name=data['run_name'],
        metrics=data['metrics']
    )
    
    # Restore timing information
    eval_result.start_time = datetime.fromisoformat(data['start_time'])
    if data['end_time']:
        eval_result.end_time = datetime.fromisoformat(data['end_time'])
    
    # Restore results and errors
    eval_result.results = data['results']
    eval_result.errors = data['errors']
    
    # Migrate to database
    return migrate_from_evaluation_result(
        eval_result, project_id, created_by, tags
    )