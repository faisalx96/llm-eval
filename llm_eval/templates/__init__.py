"""Evaluation templates for common LLM evaluation scenarios."""

from .base import EvaluationTemplate
from .classification_template import ClassificationTemplate
from .general_template import GeneralLLMTemplate
from .qa_template import QAEvaluationTemplate
from .registry import (
    get_template,
    list_templates,
    print_available_templates,
    recommend_template,
)
from .summarization_template import SummarizationTemplate

__all__ = [
    "EvaluationTemplate",
    "QAEvaluationTemplate",
    "SummarizationTemplate",
    "ClassificationTemplate",
    "GeneralLLMTemplate",
    "get_template",
    "list_templates",
    "recommend_template",
    "print_available_templates",
]
