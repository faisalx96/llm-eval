"""Built-in evaluation metrics."""

from typing import Any, Union
from difflib import SequenceMatcher
import time
import re


def exact_match(output: Any, expected: Any) -> float:
    """
    Check if output exactly matches expected.
    
    Returns:
        1.0 if exact match, 0.0 otherwise
    """
    if output is None or expected is None:
        return False
    
    # Convert to strings for comparison
    output_str = str(output).strip()
    expected_str = str(expected).strip()
    score = True if output_str == expected_str else False
    return {"score": score, "metadata": {}} # {"contains": contains_expected(output, expected)}}


def contains_expected(output: Any, expected: Any) -> float:
    """
    Check if output contains the expected text.
    
    Returns:
        1.0 if output contains expected, 0.0 otherwise
    """
    if output is None or expected is None:
        return 0.0
    
    output_str = str(output).lower()
    expected_str = str(expected).lower()
    
    return 1.0 if expected_str in output_str else 0.0


def fuzzy_match(output: Any, expected: Any, threshold: float = 0.8) -> float:
    """
    Fuzzy string matching using sequence similarity.
    
    Args:
        output: Generated output
        expected: Expected output
        threshold: Minimum similarity to consider a match (not used in score)
        
    Returns:
        Similarity score between 0.0 and 1.0
    """
    if output is None or expected is None:
        return 0.0
    
    output_str = str(output).strip()
    expected_str = str(expected).strip()
    
    return SequenceMatcher(None, output_str, expected_str).ratio()


def response_time(output: Any) -> float:
    """
    Placeholder for response time metric.
    
    Note: Actual timing should be handled by the evaluator.
    This is here for consistency and future extension.
    
    Returns:
        Always returns 1.0 (success)
    """
    return 1.0


def token_count(output: Any) -> int:
    """
    Estimate token count in the output.
    
    Simple approximation using word count * 1.3.
    
    Returns:
        Estimated token count
    """
    if output is None:
        return 0
    
    # Simple tokenization
    text = str(output)
    # Split on whitespace and punctuation
    words = re.findall(r'\b\w+\b', text)
    
    # Rough approximation: 1 word ≈ 1.3 tokens
    return int(len(words) * 1.3)