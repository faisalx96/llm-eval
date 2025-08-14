"""Metric configuration and validation system for UI-driven evaluations.

This module provides metric configuration validation, parameter management,
and metric preview capabilities for the UI-first evaluation platform.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from enum import Enum
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

import numpy as np
from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Supported metric types."""
    
    NUMERIC = "numeric"
    BOOLEAN = "boolean" 
    CATEGORICAL = "categorical"
    TEXT_SIMILARITY = "text_similarity"
    CUSTOM = "custom"


class ParameterType(str, Enum):
    """Parameter types for metric configuration."""
    
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    STRING = "string"
    SELECT = "select"
    MULTI_SELECT = "multi_select"


@dataclass
class MetricParameter:
    """Configuration parameter for a metric."""
    
    name: str
    type: ParameterType
    description: str
    default: Any = None
    required: bool = True
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    options: Optional[List[str]] = None
    validation_regex: Optional[str] = None
    
    def validate_value(self, value: Any) -> Tuple[bool, Optional[str]]:
        """Validate a parameter value."""
        if value is None:
            if self.required:
                return False, f"Parameter '{self.name}' is required"
            return True, None
        
        # Type validation
        if self.type == ParameterType.FLOAT:
            try:
                val = float(value)
                if self.min_value is not None and val < self.min_value:
                    return False, f"Value {val} is below minimum {self.min_value}"
                if self.max_value is not None and val > self.max_value:
                    return False, f"Value {val} is above maximum {self.max_value}"
            except (ValueError, TypeError):
                return False, f"Parameter '{self.name}' must be a valid number"
                
        elif self.type == ParameterType.INT:
            try:
                val = int(value)
                if self.min_value is not None and val < self.min_value:
                    return False, f"Value {val} is below minimum {self.min_value}"
                if self.max_value is not None and val > self.max_value:
                    return False, f"Value {val} is above maximum {self.max_value}"
            except (ValueError, TypeError):
                return False, f"Parameter '{self.name}' must be a valid integer"
                
        elif self.type == ParameterType.BOOL:
            if not isinstance(value, bool):
                return False, f"Parameter '{self.name}' must be a boolean"
                
        elif self.type == ParameterType.STRING:
            if not isinstance(value, str):
                return False, f"Parameter '{self.name}' must be a string"
            if self.validation_regex:
                import re
                if not re.match(self.validation_regex, value):
                    return False, f"Parameter '{self.name}' does not match required pattern"
                    
        elif self.type == ParameterType.SELECT:
            if self.options and value not in self.options:
                return False, f"Parameter '{self.name}' must be one of: {', '.join(self.options)}"
                
        elif self.type == ParameterType.MULTI_SELECT:
            if not isinstance(value, list):
                return False, f"Parameter '{self.name}' must be a list"
            if self.options:
                invalid_options = [v for v in value if v not in self.options]
                if invalid_options:
                    return False, f"Invalid options for '{self.name}': {', '.join(invalid_options)}"
        
        return True, None


@dataclass
class MetricDefinition:
    """Definition of a metric including its parameters and metadata."""
    
    name: str
    display_name: str
    description: str
    metric_type: MetricType
    parameters: List[MetricParameter] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    category: str = "general"
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    higher_is_better: bool = True
    requires_reference: bool = True
    supports_batch: bool = True
    
    def validate_config(self, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate a metric configuration."""
        errors = []
        
        for param in self.parameters:
            value = config.get(param.name)
            is_valid, error = param.validate_value(value)
            if not is_valid:
                errors.append(error)
        
        return len(errors) == 0, errors
    
    def get_default_config(self) -> Dict[str, Any]:
        """Get default configuration for this metric."""
        return {param.name: param.default for param in self.parameters if param.default is not None}


class MetricConfigurationRequest(BaseModel):
    """Request model for metric configuration validation."""
    
    metric_name: str = Field(..., description="Name of the metric")
    parameters: Dict[str, Any] = Field(..., description="Metric parameters")
    
    @validator('metric_name')
    def validate_metric_name(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError("metric_name cannot be empty")
        return v.strip()


class MetricConfigurationResponse(BaseModel):
    """Response model for metric configuration."""
    
    metric_name: str
    is_valid: bool
    errors: List[str]
    validated_parameters: Optional[Dict[str, Any]]
    default_parameters: Dict[str, Any]


class MetricPreviewRequest(BaseModel):
    """Request model for metric preview."""
    
    metric_name: str = Field(..., description="Name of the metric")
    parameters: Dict[str, Any] = Field(..., description="Metric parameters")
    sample_data: List[Dict[str, Any]] = Field(..., description="Sample data for preview", max_items=10)
    
    @validator('sample_data')
    def validate_sample_data(cls, v):
        if not v:
            raise ValueError("sample_data cannot be empty")
        
        # Check required fields
        for i, item in enumerate(v):
            if 'input' not in item:
                raise ValueError(f"Sample item {i} missing 'input' field")
            if 'expected_output' not in item:
                raise ValueError(f"Sample item {i} missing 'expected_output' field")
                
        return v


class MetricPreviewResponse(BaseModel):
    """Response model for metric preview."""
    
    metric_name: str
    is_valid: bool
    errors: List[str]
    preview_results: Optional[List[Dict[str, Any]]]
    summary_stats: Optional[Dict[str, float]]


class MetricRegistry:
    """Registry for available metrics and their configurations."""
    
    def __init__(self):
        self._metrics: Dict[str, MetricDefinition] = {}
        self._initialize_builtin_metrics()
    
    def _initialize_builtin_metrics(self):
        """Initialize built-in metric definitions."""
        
        # Exact Match
        self.register_metric(MetricDefinition(
            name="exact_match",
            display_name="Exact Match",
            description="Binary metric checking if output exactly matches expected output",
            metric_type=MetricType.BOOLEAN,
            parameters=[
                MetricParameter(
                    name="case_sensitive",
                    type=ParameterType.BOOL,
                    description="Whether to perform case-sensitive matching",
                    default=False,
                    required=False
                ),
                MetricParameter(
                    name="strip_whitespace",
                    type=ParameterType.BOOL,
                    description="Whether to strip leading/trailing whitespace",
                    default=True,
                    required=False
                )
            ],
            tags=["accuracy", "classification"],
            category="accuracy",
            min_score=0.0,
            max_score=1.0
        ))
        
        # BLEU Score
        self.register_metric(MetricDefinition(
            name="bleu",
            display_name="BLEU Score",
            description="BLEU score for text generation evaluation",
            metric_type=MetricType.NUMERIC,
            parameters=[
                MetricParameter(
                    name="n_gram",
                    type=ParameterType.INT,
                    description="N-gram order for BLEU calculation",
                    default=4,
                    required=False,
                    min_value=1,
                    max_value=6
                ),
                MetricParameter(
                    name="smoothing",
                    type=ParameterType.BOOL,
                    description="Apply smoothing for short sentences",
                    default=True,
                    required=False
                )
            ],
            tags=["generation", "similarity"],
            category="similarity",
            min_score=0.0,
            max_score=1.0
        ))
        
        # Rouge Score
        self.register_metric(MetricDefinition(
            name="rouge",
            display_name="ROUGE Score",
            description="ROUGE score for summarization evaluation",
            metric_type=MetricType.NUMERIC,
            parameters=[
                MetricParameter(
                    name="rouge_type",
                    type=ParameterType.SELECT,
                    description="Type of ROUGE metric",
                    default="rouge-l",
                    options=["rouge-1", "rouge-2", "rouge-l", "rouge-w"],
                    required=False
                ),
                MetricParameter(
                    name="use_stemmer",
                    type=ParameterType.BOOL,
                    description="Whether to use Porter stemmer",
                    default=True,
                    required=False
                )
            ],
            tags=["summarization", "similarity"],
            category="similarity",
            min_score=0.0,
            max_score=1.0
        ))
        
        # Semantic Similarity
        self.register_metric(MetricDefinition(
            name="semantic_similarity",
            display_name="Semantic Similarity",
            description="Cosine similarity using sentence embeddings",
            metric_type=MetricType.NUMERIC,
            parameters=[
                MetricParameter(
                    name="model_name",
                    type=ParameterType.SELECT,
                    description="Embedding model to use",
                    default="sentence-transformers/all-MiniLM-L6-v2",
                    options=[
                        "sentence-transformers/all-MiniLM-L6-v2",
                        "sentence-transformers/all-mpnet-base-v2",
                        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
                    ],
                    required=False
                ),
                MetricParameter(
                    name="threshold",
                    type=ParameterType.FLOAT,
                    description="Similarity threshold for binary classification",
                    default=0.8,
                    required=False,
                    min_value=0.0,
                    max_value=1.0
                )
            ],
            tags=["similarity", "semantic"],
            category="similarity",
            min_score=0.0,
            max_score=1.0
        ))
        
        # Answer Relevance
        self.register_metric(MetricDefinition(
            name="answer_relevance",
            display_name="Answer Relevance",
            description="Evaluates how relevant the answer is to the question",
            metric_type=MetricType.NUMERIC,
            parameters=[
                MetricParameter(
                    name="model",
                    type=ParameterType.SELECT,
                    description="LLM model for relevance evaluation",
                    default="gpt-3.5-turbo",
                    options=["gpt-3.5-turbo", "gpt-4", "claude-3-sonnet"],
                    required=False
                ),
                MetricParameter(
                    name="use_cot",
                    type=ParameterType.BOOL,
                    description="Use chain-of-thought reasoning",
                    default=True,
                    required=False
                )
            ],
            tags=["qa", "relevance", "llm-judge"],
            category="qa",
            min_score=0.0,
            max_score=1.0
        ))
        
        # Toxicity Detection
        self.register_metric(MetricDefinition(
            name="toxicity",
            display_name="Toxicity Detection",
            description="Detects toxic content in generated text",
            metric_type=MetricType.NUMERIC,
            parameters=[
                MetricParameter(
                    name="threshold",
                    type=ParameterType.FLOAT,
                    description="Toxicity threshold (0-1)",
                    default=0.5,
                    required=False,
                    min_value=0.0,
                    max_value=1.0
                ),
                MetricParameter(
                    name="model_name",
                    type=ParameterType.SELECT,
                    description="Toxicity detection model",
                    default="unitary/toxic-bert",
                    options=[
                        "unitary/toxic-bert",
                        "martin-ha/toxic-comment-model",
                        "perspective-api"
                    ],
                    required=False
                )
            ],
            tags=["safety", "toxicity"],
            category="safety",
            min_score=0.0,
            max_score=1.0,
            higher_is_better=False  # Lower toxicity is better
        ))
        
        # Bias Detection
        self.register_metric(MetricDefinition(
            name="bias_detection",
            display_name="Bias Detection",
            description="Detects potential bias in generated content",
            metric_type=MetricType.NUMERIC,
            parameters=[
                MetricParameter(
                    name="bias_types",
                    type=ParameterType.MULTI_SELECT,
                    description="Types of bias to detect",
                    default=["gender", "race", "religion"],
                    options=["gender", "race", "religion", "age", "nationality", "political"],
                    required=False
                ),
                MetricParameter(
                    name="threshold",
                    type=ParameterType.FLOAT,
                    description="Bias detection threshold",
                    default=0.3,
                    required=False,
                    min_value=0.0,
                    max_value=1.0
                )
            ],
            tags=["safety", "bias", "fairness"],
            category="safety",
            min_score=0.0,
            max_score=1.0,
            higher_is_better=False  # Lower bias is better
        ))
        
    def register_metric(self, metric_def: MetricDefinition):
        """Register a new metric definition."""
        self._metrics[metric_def.name] = metric_def
        logger.info(f"Registered metric: {metric_def.name}")
    
    def get_metric(self, name: str) -> Optional[MetricDefinition]:
        """Get a metric definition by name."""
        return self._metrics.get(name)
    
    def list_metrics(
        self, 
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metric_type: Optional[MetricType] = None
    ) -> List[MetricDefinition]:
        """List available metrics with optional filtering."""
        metrics = list(self._metrics.values())
        
        if category:
            metrics = [m for m in metrics if m.category == category]
        
        if tags:
            metrics = [m for m in metrics if any(tag in m.tags for tag in tags)]
        
        if metric_type:
            metrics = [m for m in metrics if m.metric_type == metric_type]
        
        return sorted(metrics, key=lambda m: m.display_name)
    
    def get_categories(self) -> List[str]:
        """Get all available metric categories."""
        categories = set(m.category for m in self._metrics.values())
        return sorted(list(categories))
    
    def get_tags(self) -> List[str]:
        """Get all available metric tags."""
        tags = set()
        for metric in self._metrics.values():
            tags.update(metric.tags)
        return sorted(list(tags))
    
    def validate_config(self, metric_name: str, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate a metric configuration."""
        metric_def = self.get_metric(metric_name)
        if not metric_def:
            return False, [f"Unknown metric: {metric_name}"]
        
        return metric_def.validate_config(config)
    
    def get_default_config(self, metric_name: str) -> Optional[Dict[str, Any]]:
        """Get default configuration for a metric."""
        metric_def = self.get_metric(metric_name)
        if not metric_def:
            return None
        
        return metric_def.get_default_config()


class MetricConfigurationValidator:
    """Validator for metric configurations in UI contexts."""
    
    def __init__(self, registry: Optional[MetricRegistry] = None):
        self.registry = registry or MetricRegistry()
    
    def validate_metrics_config(self, metrics_config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate a complete metrics configuration."""
        errors = []
        
        if 'metrics' not in metrics_config:
            errors.append("metrics_config must contain 'metrics' field")
            return False, errors
        
        metrics = metrics_config['metrics']
        if not isinstance(metrics, list):
            errors.append("'metrics' must be a list")
            return False, errors
        
        if len(metrics) == 0:
            errors.append("At least one metric must be specified")
            return False, errors
        
        # Validate each metric
        for i, metric_config in enumerate(metrics):
            if not isinstance(metric_config, dict):
                errors.append(f"Metric {i} must be a dictionary")
                continue
            
            if 'name' not in metric_config:
                errors.append(f"Metric {i} missing 'name' field")
                continue
            
            metric_name = metric_config['name']
            parameters = metric_config.get('parameters', {})
            
            is_valid, metric_errors = self.registry.validate_config(metric_name, parameters)
            if not is_valid:
                errors.extend([f"Metric '{metric_name}': {error}" for error in metric_errors])
        
        return len(errors) == 0, errors
    
    def get_metrics_with_defaults(self, metric_names: List[str]) -> List[Dict[str, Any]]:
        """Get metric configurations with default parameters filled in."""
        metrics = []
        
        for name in metric_names:
            metric_def = self.registry.get_metric(name)
            if metric_def:
                metrics.append({
                    'name': name,
                    'parameters': metric_def.get_default_config()
                })
        
        return metrics


# Global registry instance
_metric_registry: Optional[MetricRegistry] = None


def get_metric_registry() -> MetricRegistry:
    """Get the global metric registry instance."""
    global _metric_registry
    if _metric_registry is None:
        _metric_registry = MetricRegistry()
    return _metric_registry


def get_metric_validator() -> MetricConfigurationValidator:
    """Get a metric configuration validator."""
    return MetricConfigurationValidator(get_metric_registry())