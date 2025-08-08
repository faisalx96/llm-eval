"""Evaluation templates for common LLM evaluation scenarios."""

from .base import EvaluationTemplate
from .qa_template import QAEvaluationTemplate
from .summarization_template import SummarizationTemplate
from .classification_template import ClassificationTemplate
from .general_template import GeneralLLMTemplate
from .registry import get_template, list_templates, recommend_template, print_available_templates

__all__ = [
    'EvaluationTemplate',
    'QAEvaluationTemplate', 
    'SummarizationTemplate',
    'ClassificationTemplate',
    'GeneralLLMTemplate',
    'get_template',
    'list_templates',
    'recommend_template',
    'print_available_templates'
]