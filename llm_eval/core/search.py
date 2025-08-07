"""Natural language query parsing for smart search functionality."""

import re
import ast
import operator
import logging
from typing import Any, Dict, List, Optional, Callable, Union, Tuple
from datetime import datetime, timedelta
from .results import EvaluationResult


class SearchQueryParser:
    """
    Natural language query parser for evaluation results.
    
    Supports common evaluation search patterns like:
    - "Show me failures" → success == False
    - "Find low relevancy scores" → answer_relevancy < threshold
    - "Slow responses" → time > threshold
    - "Perfect matches" → exact_match == 1.0
    """
    
    def __init__(self):
        """Initialize the search query parser with predefined patterns."""
        # Define query patterns and their transformations
        self.patterns = [
            # Failure patterns
            (re.compile(r'\b(failures?|failed|errors?)\b', re.I), self._parse_failures),
            (re.compile(r'\b(success(?:es|ful)?|passed)\b', re.I), self._parse_successes),
            
            # Performance patterns
            (re.compile(r'\b(slow|sluggish|timeout)\b.*?\b(responses?|evaluations?|items?)\b', re.I), self._parse_slow),
            (re.compile(r'\b(fast|quick|rapid)\b.*?\b(responses?|evaluations?|items?)\b', re.I), self._parse_fast),
            (re.compile(r'\btook\s+(more|less)\s+than\s+(\d+(?:\.\d+)?)\s*(seconds?|s|minutes?|m)\b', re.I), self._parse_time_threshold),
            
            # Metric-specific patterns - more flexible matching
            (re.compile(r'\b(low|poor|bad)\b.*?\b(relevancy|relevance|accuracy|scores?)\b', re.I), self._parse_low_metrics),
            (re.compile(r'\b(high|good|excellent)\b.*?\b(relevancy|relevance|accuracy|scores?)\b', re.I), self._parse_high_metrics),
            (re.compile(r'\b(perfect|exact)\b.*?\b(match(?:es)?|scores?)\b', re.I), self._parse_perfect_matches),
            (re.compile(r'\b(zero|no)\b.*?\b(match(?:es)?|scores?)\b', re.I), self._parse_zero_matches),
            
            # Specific metric thresholds
            (re.compile(r'\b(\w+(?:_\w+)*)\s*([<>=!]+)\s*(\d+(?:\.\d+)?)\b', re.I), self._parse_metric_comparison),
            (re.compile(r'\b(\w+(?:_\w+)*)\s+(above|below|over|under)\s+(\d+(?:\.\d+)?)\b', re.I), self._parse_metric_threshold),
            
            # Time range patterns
            (re.compile(r'\bbetween\s+(\d+(?:\.\d+)?)\s*and\s*(\d+(?:\.\d+)?)\s*(seconds?|s|minutes?|m)\b', re.I), self._parse_time_range),
        ]
        
        # Default thresholds
        self.default_thresholds = {
            'low_score': 0.5,
            'high_score': 0.8,
            'slow_time': 5.0,
            'fast_time': 1.0,
        }
        
        # Metric aliases for common naming variations
        self.metric_aliases = {
            'relevancy': ['answer_relevancy', 'relevance_score', 'relevancy_score'],
            'relevance': ['answer_relevancy', 'relevance_score', 'relevancy_score'],
            'accuracy': ['accuracy_score', 'acc'],
            'match': ['exact_match', 'exact_match_score'],
            'time': ['response_time', 'execution_time', 'duration'],
            'score': ['overall_score', 'total_score'],
        }
    
    def parse(self, query: str, available_metrics: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Parse natural language query into filter conditions.
        
        Args:
            query: Natural language query string
            available_metrics: List of available metrics to consider
            
        Returns:
            Dictionary containing filter conditions and metadata
        """
        query = query.strip()
        if not query:
            return {'filters': [], 'raw_query': query, 'parsed': False}
        
        filters = []
        parsed = False
        
        # Apply patterns in order of specificity
        for pattern, parser in self.patterns:
            if pattern.search(query):
                try:
                    filter_condition = parser(query, pattern, available_metrics)
                    if filter_condition:
                        filters.append(filter_condition)
                        parsed = True
                except Exception as e:
                    # Log parsing error but continue with other patterns
                    continue
        
        return {
            'filters': filters,
            'raw_query': query,
            'parsed': parsed,
            'metadata': {
                'available_metrics': available_metrics or [],
                'patterns_matched': len(filters)
            }
        }
    
    def filter_results(self, evaluation_result: EvaluationResult, query: str) -> Dict[str, Any]:
        """
        Filter evaluation results based on natural language query.
        
        Args:
            evaluation_result: EvaluationResult object to filter
            query: Natural language query string
            
        Returns:
            Filtered results dictionary with matching items
        """
        # Parse the query
        parsed_query = self.parse(query, evaluation_result.metrics)
        
        if not parsed_query['parsed'] or not parsed_query['filters']:
            # Return all results if query couldn't be parsed
            return {
                'matched_items': list(evaluation_result.results.keys()),
                'matched_errors': list(evaluation_result.errors.keys()),
                'total_matches': evaluation_result.total_items,
                'query_info': parsed_query,
                'parsed': parsed_query['parsed']
            }
        
        matched_items = []
        matched_errors = []
        
        # Apply filters to successful results
        for item_id, result in evaluation_result.results.items():
            if self._item_matches_filters(result, parsed_query['filters'], item_id):
                matched_items.append(item_id)
        
        # Apply filters to errors
        for item_id, error in evaluation_result.errors.items():
            error_result = {'success': False, 'error': error, 'scores': {}}
            if self._item_matches_filters(error_result, parsed_query['filters'], item_id):
                matched_errors.append(item_id)
        
        return {
            'matched_items': matched_items,
            'matched_errors': matched_errors,
            'total_matches': len(matched_items) + len(matched_errors),
            'query_info': parsed_query,
            'parsed': parsed_query['parsed']
        }
    
    def _item_matches_filters(self, result: Dict[str, Any], filters: List[Dict[str, Any]], item_id: str) -> bool:
        """Check if an item matches all filter conditions."""
        for filter_condition in filters:
            if not self._apply_filter(result, filter_condition, item_id):
                return False
        return True
    
    def _apply_filter(self, result: Dict[str, Any], filter_condition: Dict[str, Any], item_id: str) -> bool:
        """Apply a single filter condition to a result."""
        filter_type = filter_condition['type']
        
        if filter_type == 'success_status':
            return result.get('success', False) == filter_condition['value']
        
        elif filter_type == 'metric_comparison':
            metric_name = filter_condition['metric']
            operator_func = filter_condition['operator']
            threshold = filter_condition['value']
            
            # Get metric value
            metric_value = self._get_metric_value(result, metric_name)
            if metric_value is None:
                return False
            
            return operator_func(metric_value, threshold)
        
        elif filter_type == 'time_comparison':
            operator_func = filter_condition['operator']
            threshold = filter_condition['value']
            
            time_value = result.get('time', 0)
            if not isinstance(time_value, (int, float)):
                return False
            
            return operator_func(time_value, threshold)
        
        elif filter_type == 'time_range':
            min_time = filter_condition['min_value']
            max_time = filter_condition['max_value']
            
            time_value = result.get('time', 0)
            if not isinstance(time_value, (int, float)):
                return False
            
            return min_time <= time_value <= max_time
        
        return False
    
    def _get_metric_value(self, result: Dict[str, Any], metric_name: str) -> Optional[float]:
        """Extract numeric metric value from result."""
        scores = result.get('scores', {})
        
        # Try exact match first
        if metric_name in scores:
            score = scores[metric_name]
            return self._convert_to_numeric(score)
        
        # Try aliases
        if metric_name in self.metric_aliases:
            for alias in self.metric_aliases[metric_name]:
                if alias in scores:
                    score = scores[alias]
                    return self._convert_to_numeric(score)
        
        # Try partial matches (case-insensitive)
        metric_lower = metric_name.lower()
        for score_name, score in scores.items():
            if metric_lower in score_name.lower():
                return self._convert_to_numeric(score)
        
        return None
    
    def _convert_to_numeric(self, value: Any) -> Optional[float]:
        """Convert various value types to numeric."""
        if isinstance(value, (int, float)):
            return float(value)
        elif isinstance(value, bool):
            return 1.0 if value else 0.0
        elif isinstance(value, dict) and 'error' in value:
            return None  # Error values are not numeric
        elif isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None
    
    # Pattern parsing methods
    def _parse_failures(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Dict[str, Any]:
        """Parse failure-related queries."""
        return {
            'type': 'success_status',
            'value': False,
            'description': 'Failed evaluations'
        }
    
    def _parse_successes(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Dict[str, Any]:
        """Parse success-related queries."""
        return {
            'type': 'success_status',
            'value': True,
            'description': 'Successful evaluations'
        }
    
    def _parse_slow(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Dict[str, Any]:
        """Parse slow performance queries."""
        return {
            'type': 'time_comparison',
            'operator': operator.gt,
            'value': self.default_thresholds['slow_time'],
            'description': f'Slow responses (> {self.default_thresholds["slow_time"]}s)'
        }
    
    def _parse_fast(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Dict[str, Any]:
        """Parse fast performance queries."""
        return {
            'type': 'time_comparison',
            'operator': operator.lt,
            'value': self.default_thresholds['fast_time'],
            'description': f'Fast responses (< {self.default_thresholds["fast_time"]}s)'
        }
    
    def _parse_time_threshold(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Optional[Dict[str, Any]]:
        """Parse 'took more/less than X seconds' patterns."""
        match = pattern.search(query)
        if not match:
            return None
        
        comparison = match.group(1).lower()  # 'more' or 'less'
        value = float(match.group(2))
        unit = match.group(3).lower()
        
        # Convert to seconds
        if unit.startswith('m'):  # minutes
            value *= 60
        
        op = operator.gt if comparison == 'more' else operator.lt
        return {
            'type': 'time_comparison',
            'operator': op,
            'value': value,
            'description': f'Took {comparison} than {value}s'
        }
    
    def _parse_low_metrics(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Optional[Dict[str, Any]]:
        """Parse low metric score queries."""
        # Extract metric type from query
        metric_match = re.search(r'\b(relevancy|relevance|accuracy|scores?)\b', query, re.I)
        if not metric_match:
            return None
        
        metric_type = metric_match.group(1).lower()
        
        # Handle generic "scores" case - use first available metric as default
        if metric_type in ('score', 'scores') and available_metrics:
            metric_name = available_metrics[0]  # Use first available metric
            metric_type = 'scores'
        else:
            metric_name = self._resolve_metric_name(metric_type, available_metrics)
        
        return {
            'type': 'metric_comparison',
            'metric': metric_name,
            'operator': operator.lt,
            'value': self.default_thresholds['low_score'],
            'description': f'Low {metric_type} (< {self.default_thresholds["low_score"]})'
        }
    
    def _parse_high_metrics(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Optional[Dict[str, Any]]:
        """Parse high metric score queries."""
        metric_match = re.search(r'\b(relevancy|relevance|accuracy|scores?)\b', query, re.I)
        if not metric_match:
            return None
        
        metric_type = metric_match.group(1).lower()
        
        # Handle generic "scores" case - use first available metric as default
        if metric_type in ('score', 'scores') and available_metrics:
            metric_name = available_metrics[0]  # Use first available metric
            metric_type = 'scores'
        else:
            metric_name = self._resolve_metric_name(metric_type, available_metrics)
        
        return {
            'type': 'metric_comparison',
            'metric': metric_name,
            'operator': operator.gt,
            'value': self.default_thresholds['high_score'],
            'description': f'High {metric_type} (> {self.default_thresholds["high_score"]})'
        }
    
    def _parse_perfect_matches(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Dict[str, Any]:
        """Parse perfect/exact match queries."""
        # Check if query mentions "scores" specifically
        if re.search(r'\bscores?\b', query, re.I):
            # Use first available metric for perfect scores
            metric_name = available_metrics[0] if available_metrics else 'exact_match'
        else:
            metric_name = self._resolve_metric_name('match', available_metrics)
        
        return {
            'type': 'metric_comparison',
            'metric': metric_name,
            'operator': operator.eq,
            'value': 1.0,
            'description': 'Perfect matches (= 1.0)'
        }
    
    def _parse_zero_matches(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Dict[str, Any]:
        """Parse zero match queries."""
        # Check if query mentions "scores" specifically
        if re.search(r'\bscores?\b', query, re.I):
            # Use first available metric for zero scores
            metric_name = available_metrics[0] if available_metrics else 'exact_match'
        else:
            metric_name = self._resolve_metric_name('match', available_metrics)
        
        return {
            'type': 'metric_comparison',
            'metric': metric_name,
            'operator': operator.eq,
            'value': 0.0,
            'description': 'Zero matches (= 0.0)'
        }
    
    def _parse_metric_comparison(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Optional[Dict[str, Any]]:
        """Parse explicit metric comparisons like 'accuracy > 0.8'."""
        match = pattern.search(query)
        if not match:
            return None
        
        metric_name = match.group(1)
        operator_str = match.group(2)
        value = float(match.group(3))
        
        # Map operator strings to functions
        operator_map = {
            '>': operator.gt,
            '>=': operator.ge,
            '<': operator.lt,
            '<=': operator.le,
            '=': operator.eq,
            '==': operator.eq,
            '!=': operator.ne,
        }
        
        op = operator_map.get(operator_str)
        if not op:
            return None
        
        resolved_metric = self._resolve_metric_name(metric_name, available_metrics)
        
        return {
            'type': 'metric_comparison',
            'metric': resolved_metric,
            'operator': op,
            'value': value,
            'description': f'{resolved_metric} {operator_str} {value}'
        }
    
    def _parse_metric_threshold(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Optional[Dict[str, Any]]:
        """Parse threshold phrases like 'accuracy above 0.8'."""
        match = pattern.search(query)
        if not match:
            return None
        
        metric_name = match.group(1)
        direction = match.group(2).lower()
        value = float(match.group(3))
        
        op = operator.gt if direction in ('above', 'over') else operator.lt
        resolved_metric = self._resolve_metric_name(metric_name, available_metrics)
        
        return {
            'type': 'metric_comparison',
            'metric': resolved_metric,
            'operator': op,
            'value': value,
            'description': f'{resolved_metric} {direction} {value}'
        }
    
    def _parse_time_range(self, query: str, pattern: re.Pattern, available_metrics: Optional[List[str]]) -> Optional[Dict[str, Any]]:
        """Parse time range patterns like 'between 1 and 5 seconds'."""
        match = pattern.search(query)
        if not match:
            return None
        
        min_value = float(match.group(1))
        max_value = float(match.group(2))
        unit = match.group(3).lower()
        
        # Convert to seconds
        if unit.startswith('m'):  # minutes
            min_value *= 60
            max_value *= 60
        
        return {
            'type': 'time_range',
            'min_value': min_value,
            'max_value': max_value,
            'description': f'Time between {min_value}s and {max_value}s'
        }
    
    def _resolve_metric_name(self, metric_hint: str, available_metrics: Optional[List[str]]) -> str:
        """Resolve metric name from hint using available metrics and aliases."""
        if not available_metrics:
            return metric_hint
        
        # Try exact match
        if metric_hint in available_metrics:
            return metric_hint
        
        # Try aliases
        if metric_hint in self.metric_aliases:
            for alias in self.metric_aliases[metric_hint]:
                if alias in available_metrics:
                    return alias
        
        # Try partial matches
        metric_lower = metric_hint.lower()
        for metric in available_metrics:
            if metric_lower in metric.lower() or metric.lower() in metric_lower:
                return metric
        
        # Return original hint if no match found
        return metric_hint


class SearchEngine:
    """
    High-level search engine for evaluation results.
    
    Provides a simple interface for searching evaluation results using natural language.
    """
    
    def __init__(self):
        """Initialize the search engine."""
        self.parser = SearchQueryParser()
    
    def search(self, evaluation_result: EvaluationResult, query: str) -> Dict[str, Any]:
        """
        Search evaluation results using natural language query.
        
        Args:
            evaluation_result: EvaluationResult object to search
            query: Natural language search query
            
        Returns:
            Search results with matched items and metadata
        """
        return self.parser.filter_results(evaluation_result, query)
    
    def get_suggestions(self, evaluation_result: EvaluationResult) -> List[str]:
        """
        Get suggested search queries based on available data.
        
        Args:
            evaluation_result: EvaluationResult object to analyze
            
        Returns:
            List of suggested search queries
        """
        suggestions = []
        
        # Basic status suggestions
        if evaluation_result.errors:
            suggestions.append("Show me failures")
        if evaluation_result.results:
            suggestions.append("Show me successes")
        
        # Metric-based suggestions
        for metric in evaluation_result.metrics:
            suggestions.extend([
                f"Low {metric} scores",
                f"High {metric} scores",
                f"{metric} > 0.8",
                f"{metric} < 0.5"
            ])
        
        # Performance suggestions
        timing_stats = evaluation_result.get_timing_stats()
        if timing_stats['total'] > 0:
            suggestions.extend([
                "Slow responses",
                "Fast responses",
                f"Took more than {timing_stats['mean']:.1f} seconds"
            ])
        
        return suggestions[:10]  # Limit to top 10 suggestions


logger = logging.getLogger(__name__)


class RunSearchEngine:
    """
    Database-backed search engine for evaluation runs.
    
    Provides powerful search and filtering capabilities for stored evaluation runs
    with natural language query support and efficient database operations.
    """
    
    def __init__(self):
        """Initialize the run search engine."""
        self.query_parser = SearchQueryParser()
    
    def search_runs(
        self,
        query: Optional[str] = None,
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
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Search evaluation runs with advanced filtering.
        
        Args:
            query: Natural language search query
            project_id: Filter by project ID
            dataset_name: Filter by dataset name
            model_name: Filter by model name
            status: Filter by run status
            created_by: Filter by creator
            tags: Filter by tags
            min_success_rate: Minimum success rate threshold
            max_duration: Maximum duration in seconds
            created_after: Filter runs created after this date
            created_before: Filter runs created before this date
            order_by: Field to order by
            descending: Whether to sort in descending order
            limit: Maximum number of results
            offset: Number of results to skip
            
        Returns:
            Dictionary with search results and metadata
        """
        try:
            from ..storage.run_repository import RunRepository
            
            repo = RunRepository()
            
            # Apply text-based search if query provided
            if query:
                return self._search_runs_by_query(
                    query, repo, project_id, limit, offset
                )
            
            # Apply filters
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
                limit=limit,
                offset=offset
            )
            
            # Get total count for pagination
            total_count = repo.count_runs(
                project_id=project_id,
                dataset_name=dataset_name,
                model_name=model_name,
                status=status,
                created_by=created_by
            )
            
            return {
                'runs': [run.to_dict() for run in runs],
                'total_count': total_count,
                'limit': limit,
                'offset': offset,
                'has_more': total_count > offset + len(runs),
                'filters_applied': self._get_applied_filters(locals())
            }
            
        except ImportError:
            logger.error("Database storage components not available")
            return {'error': 'Database storage not available', 'runs': []}
        except Exception as e:
            logger.error(f"Run search failed: {e}")
            return {'error': str(e), 'runs': []}
    
    def _search_runs_by_query(
        self,
        query: str,
        repo,
        project_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Search runs using natural language query."""
        
        # First try simple text search
        runs = repo.search_runs(query, limit=limit)
        
        # If we have results, return them
        if runs:
            return {
                'runs': [run.to_dict() for run in runs],
                'total_count': len(runs),
                'limit': limit,
                'offset': offset,
                'has_more': False,
                'query': query,
                'search_type': 'text_search'
            }
        
        # Try parsing as structured query
        try:
            parsed_filters = self._parse_structured_query(query)
            return self._apply_parsed_filters(parsed_filters, repo, project_id, limit, offset)
        except Exception as e:
            logger.warning(f"Failed to parse structured query: {e}")
            return {
                'runs': [],
                'total_count': 0,
                'limit': limit,
                'offset': offset,
                'has_more': False,
                'query': query,
                'error': 'No results found'
            }
    
    def _parse_structured_query(self, query: str) -> Dict[str, Any]:
        """Parse structured query with run-specific filters."""
        filters = {}
        
        # Time-based queries
        if re.search(r'\b(today|yesterday|last\s+week|last\s+month)\b', query, re.I):
            filters.update(self._parse_time_filters(query))
        
        # Status queries
        if re.search(r'\b(failed|failure|error|completed|running|success)\b', query, re.I):
            filters.update(self._parse_status_filters(query))
        
        # Performance queries
        if re.search(r'\b(slow|fast|duration|time)\b', query, re.I):
            filters.update(self._parse_performance_filters(query))
        
        # Success rate queries
        if re.search(r'\b(success\s*rate|accuracy)\b', query, re.I):
            filters.update(self._parse_success_rate_filters(query))
        
        return filters
    
    def _parse_time_filters(self, query: str) -> Dict[str, Any]:
        """Parse time-based filter queries."""
        filters = {}
        now = datetime.utcnow()
        
        if re.search(r'\btoday\b', query, re.I):
            filters['created_after'] = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif re.search(r'\byesterday\b', query, re.I):
            yesterday = now - timedelta(days=1)
            filters['created_after'] = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            filters['created_before'] = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif re.search(r'\blast\s+week\b', query, re.I):
            filters['created_after'] = now - timedelta(weeks=1)
        elif re.search(r'\blast\s+month\b', query, re.I):
            filters['created_after'] = now - timedelta(days=30)
        
        return filters
    
    def _parse_status_filters(self, query: str) -> Dict[str, Any]:
        """Parse status-based filter queries."""
        filters = {}
        
        if re.search(r'\b(failed|failure|error)\b', query, re.I):
            filters['status'] = 'failed'
        elif re.search(r'\b(completed|success)\b', query, re.I):
            filters['status'] = 'completed'
        elif re.search(r'\brunning\b', query, re.I):
            filters['status'] = 'running'
        
        return filters
    
    def _parse_performance_filters(self, query: str) -> Dict[str, Any]:
        """Parse performance-based filter queries."""
        filters = {}
        
        # Look for duration patterns
        duration_match = re.search(r'(\d+(?:\.\d+)?)\s*(seconds?|minutes?|s|m)', query, re.I)
        if duration_match:
            value = float(duration_match.group(1))
            unit = duration_match.group(2).lower()
            
            if unit.startswith('m'):
                value *= 60
            
            if re.search(r'\b(slow|longer|more)\b.*?' + re.escape(duration_match.group(0)), query, re.I):
                filters['min_duration'] = value
            elif re.search(r'\b(fast|quick|less)\b.*?' + re.escape(duration_match.group(0)), query, re.I):
                filters['max_duration'] = value
        
        return filters
    
    def _parse_success_rate_filters(self, query: str) -> Dict[str, Any]:
        """Parse success rate filter queries."""
        filters = {}
        
        # Look for percentage patterns
        rate_match = re.search(r'(\d+(?:\.\d+)?)\s*%?', query)
        if rate_match:
            value = float(rate_match.group(1))
            
            # Convert percentage to decimal if needed
            if value > 1.0:
                value = value / 100.0
            
            if re.search(r'\b(above|over|greater|>)\b', query, re.I):
                filters['min_success_rate'] = value
            elif re.search(r'\b(below|under|less|<)\b', query, re.I):
                filters['max_success_rate'] = value
        
        return filters
    
    def _apply_parsed_filters(
        self,
        filters: Dict[str, Any],
        repo,
        project_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Apply parsed filters to repository query."""
        
        # Add project filter if specified
        if project_id:
            filters['project_id'] = project_id
        
        # Handle min_duration vs max_duration
        max_duration = filters.pop('min_duration', None)
        if max_duration:
            # For "slow" queries, we want runs that took MORE than the threshold
            # But the repository expects max_duration, so we invert this
            pass  # Skip this filter or implement custom logic
        
        runs = repo.list_runs(
            limit=limit,
            offset=offset,
            **filters
        )
        
        total_count = repo.count_runs(**filters)
        
        return {
            'runs': [run.to_dict() for run in runs],
            'total_count': total_count,
            'limit': limit,
            'offset': offset,
            'has_more': total_count > offset + len(runs),
            'filters_applied': filters,
            'search_type': 'structured_query'
        }
    
    def _get_applied_filters(self, locals_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Extract applied filters from function locals."""
        filter_keys = [
            'project_id', 'dataset_name', 'model_name', 'status', 'created_by',
            'tags', 'min_success_rate', 'max_duration', 'created_after', 'created_before'
        ]
        
        return {
            key: value for key, value in locals_dict.items()
            if key in filter_keys and value is not None
        }
    
    def search_run_items(
        self,
        run_id: str,
        query: Optional[str] = None,
        status: Optional[str] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        metric_name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Search individual evaluation items within a specific run.
        
        Args:
            run_id: ID of the evaluation run
            query: Search query for item content
            status: Filter by item status
            min_score: Minimum score threshold
            max_score: Maximum score threshold
            metric_name: Specific metric to filter by
            limit: Maximum number of results
            offset: Number of results to skip
            
        Returns:
            Dictionary with search results
        """
        try:
            from ..storage.database import get_database_manager
            from ..models.run_models import EvaluationItem
            
            db_manager = get_database_manager()
            
            with db_manager.get_session() as session:
                query_obj = session.query(EvaluationItem).filter(
                    EvaluationItem.run_id == run_id
                )
                
                # Apply filters
                if status:
                    query_obj = query_obj.filter(EvaluationItem.status == status)
                
                if query:
                    # Search in input data, expected output, or actual output
                    from sqlalchemy import or_
                    search_pattern = f"%{query}%"
                    query_obj = query_obj.filter(
                        or_(
                            EvaluationItem.expected_output.ilike(search_pattern),
                            EvaluationItem.actual_output.ilike(search_pattern),
                            EvaluationItem.error_message.ilike(search_pattern)
                        )
                    )
                
                # Score-based filtering requires JSON operations
                if (min_score is not None or max_score is not None) and metric_name:
                    # This would need database-specific JSON query syntax
                    pass
                
                # Apply pagination
                total_count = query_obj.count()
                items = query_obj.offset(offset).limit(limit).all()
                
                return {
                    'items': [item.to_dict() for item in items],
                    'total_count': total_count,
                    'limit': limit,
                    'offset': offset,
                    'has_more': total_count > offset + len(items),
                    'run_id': run_id
                }
                
        except ImportError:
            logger.error("Database storage components not available")
            return {'error': 'Database storage not available', 'items': []}
        except Exception as e:
            logger.error(f"Run item search failed: {e}")
            return {'error': str(e), 'items': []}
    
    def get_run_comparison(self, run1_id: str, run2_id: str) -> Dict[str, Any]:
        """
        Get or compute comparison between two evaluation runs.
        
        Args:
            run1_id: First run ID
            run2_id: Second run ID
            
        Returns:
            Comparison results
        """
        try:
            from ..storage.run_repository import RunRepository
            
            repo = RunRepository()
            
            # Check if comparison already exists
            comparison = repo.get_comparison(run1_id, run2_id)
            
            if comparison:
                return {
                    'comparison': comparison.to_dict() if hasattr(comparison, 'to_dict') else {
                        'id': str(comparison.id),
                        'run1_id': str(comparison.run1_id),
                        'run2_id': str(comparison.run2_id),
                        'summary': comparison.summary,
                        'metric_comparisons': comparison.metric_comparisons,
                        'created_at': comparison.created_at.isoformat()
                    },
                    'cached': True
                }
            
            # Need to compute comparison
            return self._compute_run_comparison(run1_id, run2_id, repo)
            
        except ImportError:
            logger.error("Database storage components not available")
            return {'error': 'Database storage not available'}
        except Exception as e:
            logger.error(f"Run comparison failed: {e}")
            return {'error': str(e)}
    
    def _compute_run_comparison(self, run1_id: str, run2_id: str, repo) -> Dict[str, Any]:
        """Compute comparison between two runs."""
        # Get run data
        run1 = repo.get_run(run1_id)
        run2 = repo.get_run(run2_id)
        
        if not run1 or not run2:
            return {'error': 'One or both runs not found'}
        
        # Get metrics for both runs
        metrics1 = repo.get_run_metrics(run1_id)
        metrics2 = repo.get_run_metrics(run2_id)
        
        # Basic comparison
        comparison_data = {
            'run1_id': run1_id,
            'run2_id': run2_id,
            'summary': {
                'run1_name': run1.name,
                'run2_name': run2.name,
                'run1_success_rate': run1.success_rate,
                'run2_success_rate': run2.success_rate,
                'success_rate_delta': (run2.success_rate or 0) - (run1.success_rate or 0),
                'run1_duration': run1.duration_seconds,
                'run2_duration': run2.duration_seconds,
                'duration_delta': (run2.duration_seconds or 0) - (run1.duration_seconds or 0)
            },
            'metric_comparisons': {},
            'computed': True
        }
        
        # Compare metrics
        metrics1_dict = {m.metric_name: m for m in metrics1}
        metrics2_dict = {m.metric_name: m for m in metrics2}
        
        all_metrics = set(metrics1_dict.keys()) | set(metrics2_dict.keys())
        
        for metric_name in all_metrics:
            m1 = metrics1_dict.get(metric_name)
            m2 = metrics2_dict.get(metric_name)
            
            comparison_data['metric_comparisons'][metric_name] = {
                'run1_mean': m1.mean_score if m1 else None,
                'run2_mean': m2.mean_score if m2 else None,
                'delta': (m2.mean_score if m2 else 0) - (m1.mean_score if m1 else 0),
                'run1_available': m1 is not None,
                'run2_available': m2 is not None
            }
        
        return {'comparison': comparison_data, 'cached': False}