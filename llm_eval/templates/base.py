"""Base evaluation template class."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union, Callable
from dataclasses import dataclass, field
import json


@dataclass
class TemplateConfig:
    """Configuration for evaluation templates."""
    name: str
    description: str
    use_cases: List[str]
    metrics: List[str]
    sample_data: Dict[str, Any] = field(default_factory=dict)
    best_practices: List[str] = field(default_factory=list)
    customization_guide: str = ""
    required_fields: List[str] = field(default_factory=lambda: ["input", "expected_output"])
    optional_fields: List[str] = field(default_factory=list)
    

class EvaluationTemplate(ABC):
    """
    Base class for evaluation templates that provide pre-configured evaluation patterns
    for common LLM evaluation scenarios.
    
    Templates help users get started quickly with best-practice evaluation patterns
    by providing:
    - Automatic metric selection based on use case
    - Sample datasets and expected outputs  
    - Best practice evaluation parameters
    - Customization guidance for specific domains
    """
    
    def __init__(self, config: Optional[TemplateConfig] = None):
        """Initialize the evaluation template."""
        self.config = config or self._get_default_config()
        self._validate_config()
    
    @abstractmethod
    def _get_default_config(self) -> TemplateConfig:
        """Get the default configuration for this template."""
        pass
    
    def _validate_config(self):
        """Validate the template configuration."""
        if not self.config.name:
            raise ValueError("Template name is required")
        if not self.config.metrics:
            raise ValueError("Template must specify at least one metric")
    
    def get_metrics(self) -> List[str]:
        """Get the recommended metrics for this template."""
        return self.config.metrics.copy()
    
    def get_sample_data(self) -> Dict[str, Any]:
        """Get sample data for this template."""
        return self.config.sample_data.copy()
    
    def get_best_practices(self) -> List[str]:
        """Get best practices for this evaluation type."""
        return self.config.best_practices.copy()
    
    def get_customization_guide(self) -> str:
        """Get guidance on customizing this template."""
        return self.config.customization_guide
    
    def get_required_fields(self) -> List[str]:
        """Get required fields for dataset items."""
        return self.config.required_fields.copy()
    
    def get_optional_fields(self) -> List[str]:
        """Get optional fields for dataset items."""
        return self.config.optional_fields.copy()
    
    def validate_dataset_item(self, item: Dict[str, Any]) -> List[str]:
        """
        Validate a dataset item against this template's requirements.
        
        Args:
            item: Dataset item to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Check required fields
        for field in self.config.required_fields:
            if field not in item:
                errors.append(f"Missing required field: {field}")
            elif item[field] is None or (isinstance(item[field], str) and not item[field].strip()):
                errors.append(f"Required field '{field}' is empty")
        
        return errors
    
    def create_evaluator_config(self, 
                               task: Any,
                               dataset: str,
                               custom_metrics: Optional[List[Union[str, Callable]]] = None,
                               **kwargs) -> Dict[str, Any]:
        """
        Create an evaluator configuration using this template.
        
        Args:
            task: The LLM task to evaluate
            dataset: Name of the dataset to use
            custom_metrics: Override default metrics with custom ones
            **kwargs: Additional configuration options
            
        Returns:
            Configuration dict that can be passed to Evaluator
        """
        # Use custom metrics if provided, otherwise use template defaults
        metrics = custom_metrics if custom_metrics is not None else self.get_metrics()
        
        config = {
            'task': task,
            'dataset': dataset,
            'metrics': metrics,
            **kwargs
        }
        
        return config
    
    def print_info(self):
        """Print detailed information about this template."""
        print(f"Template: {self.config.name}")
        print("=" * (len(self.config.name) + 10))
        print(f"Description: {self.config.description}")
        print()
        
        print("Use Cases:")
        for use_case in self.config.use_cases:
            print(f"  • {use_case}")
        print()
        
        print("Recommended Metrics:")
        for metric in self.config.metrics:
            print(f"  • {metric}")
        print()
        
        print("Required Fields:")
        for field in self.config.required_fields:
            print(f"  • {field}")
        
        if self.config.optional_fields:
            print("\nOptional Fields:")
            for field in self.config.optional_fields:
                print(f"  • {field}")
        print()
        
        if self.config.best_practices:
            print("Best Practices:")
            for practice in self.config.best_practices:
                print(f"  • {practice}")
            print()
        
        if self.config.customization_guide:
            print("Customization Guide:")
            print(f"  {self.config.customization_guide}")
            print()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert template to dictionary representation."""
        return {
            'name': self.config.name,
            'description': self.config.description,
            'use_cases': self.config.use_cases,
            'metrics': self.config.metrics,
            'sample_data': self.config.sample_data,
            'best_practices': self.config.best_practices,
            'customization_guide': self.config.customization_guide,
            'required_fields': self.config.required_fields,
            'optional_fields': self.config.optional_fields
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert template to JSON representation."""
        return json.dumps(self.to_dict(), indent=indent)