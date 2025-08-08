"""Sample datasets for evaluation templates."""

from .classification_samples import get_classification_samples
from .general_samples import get_general_samples
from .qa_samples import get_qa_samples
from .summarization_samples import get_summarization_samples

__all__ = [
    "get_qa_samples",
    "get_summarization_samples",
    "get_classification_samples",
    "get_general_samples",
]
