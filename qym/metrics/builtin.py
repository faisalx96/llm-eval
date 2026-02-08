"""Built-in evaluation metrics."""

from typing import Any, Dict
from difflib import SequenceMatcher
import re
import string


def exact_match(output: Any, expected: Any) -> Dict[str, Any]:
    """
    Check if output exactly matches expected.
    
    Returns:
        1.0 if exact match, 0.0 otherwise
    """
    if output is None or expected is None:
        return {"score": 0.0, "metadata": {}}
    
    # Convert to strings for comparison
    output_str = str(output).strip()
    expected_str = str(expected).strip()
    score = 1.0 if output_str == expected_str else 0.0
    return {"score": score, "metadata": {}}


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


# =============================================================================
# CORRECTNESS METRIC (F1 Score)
# Based on official SQuAD evaluation: https://rajpurkar.github.io/SQuAD-explorer/
# =============================================================================

def _normalize_answer(text: str) -> str:
    """
    Normalize text for QA comparison.

    Performs standard SQuAD-style normalization:
    - Lowercase
    - Remove articles (a, an, the)
    - Remove punctuation
    - Normalize whitespace
    """
    def remove_articles(text: str) -> str:
        regex = re.compile(r'\b(a|an|the)\b', re.UNICODE)
        return re.sub(regex, ' ', text)

    def white_space_fix(text: str) -> str:
        return ' '.join(text.split())

    def remove_punctuation(text: str) -> str:
        exclude = set(string.punctuation)
        return ''.join(ch for ch in text if ch not in exclude)

    def lower(text: str) -> str:
        return text.lower()

    return white_space_fix(remove_articles(remove_punctuation(lower(text))))


def _compute_f1(prediction: str, ground_truth: str) -> float:
    """
    Compute F1 score between prediction and ground truth at token level.
    Uses bag-of-words (Counter) to properly handle duplicate tokens.
    """
    from collections import Counter

    pred_tokens = _normalize_answer(prediction).split()
    truth_tokens = _normalize_answer(ground_truth).split()

    if len(pred_tokens) == 0 or len(truth_tokens) == 0:
        return float(pred_tokens == truth_tokens)

    pred_counter = Counter(pred_tokens)
    truth_counter = Counter(truth_tokens)

    # Count common tokens (minimum count for each token)
    common = pred_counter & truth_counter
    num_common = sum(common.values())

    if num_common == 0:
        return 0.0

    precision = num_common / len(pred_tokens)
    recall = num_common / len(truth_tokens)
    f1 = 2 * (precision * recall) / (precision + recall)

    return f1


def correctness(output: Any, expected: Any) -> Dict[str, Any]:
    """
    Correctness metric using SQuAD-style F1 score.

    Measures token-level overlap between output and expected answer.
    Standard metric used in QA benchmarks (SQuAD, TriviaQA, Natural Questions).

    Args:
        output: The model's generated answer
        expected: The ground truth answer

    Returns:
        Dict with score (0.0-1.0) and metadata
    """
    if output is None:
        output = ""
    if expected is None:
        expected = ""

    output = str(output)
    expected = str(expected)

    f1_score = _compute_f1(output, expected)
    exact = float(_normalize_answer(output) == _normalize_answer(expected))

    return {
        "score": f1_score,
        "metadata": {
            "prediction_tokens": len(_normalize_answer(output).split()),
            "ground_truth_tokens": len(_normalize_answer(expected).split()),
        }
    }


# =============================================================================
# FAITHFULNESS METRIC (Token Overlap)
# Lightweight heuristic measuring how much of the output is grounded in context
# =============================================================================

def faithfulness(output: Any, expected: Any, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Faithfulness metric using token overlap.

    Measures what proportion of meaningful tokens in the output appear in the context.
    A lightweight, dependency-free alternative to model-based faithfulness metrics.

    Score close to 1.0 = output tokens are well-grounded in context
    Score close to 0.0 = output contains many tokens not in context

    Args:
        output: The model's generated answer
        expected: The ground truth answer (not used for faithfulness)
        input_data: Dict containing 'context' field with source documents

    Returns:
        Dict with score (0.0-1.0) and metadata
    """
    if output is None or str(output).strip() == "":
        return {
            "score": 0.0,
            "metadata": {"error": "Empty output"}
        }

    # Extract context from input_data
    context = None
    if isinstance(input_data, dict):
        context = input_data.get("context")
        if context is None and "input" in input_data:
            context = input_data["input"].get("context")

    if context is None or str(context).strip() == "":
        return {
            "score": 0.0,
            "metadata": {"error": "No context found in input_data"}
        }

    context = str(context).lower()
    output = str(output).lower()

    # Tokenize: remove punctuation and split into words
    context_tokens = set(re.findall(r'\b\w+\b', context))
    output_tokens = re.findall(r'\b\w+\b', output)

    if len(output_tokens) == 0:
        return {
            "score": 0.0,
            "metadata": {"error": "No tokens in output"}
        }

    # Filter out common stopwords for more meaningful comparison
    stopwords = {
        'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
        'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by',
        'from', 'as', 'into', 'through', 'during', 'before', 'after', 'above',
        'below', 'between', 'under', 'again', 'further', 'then', 'once', 'and',
        'but', 'or', 'nor', 'so', 'yet', 'both', 'either', 'neither', 'not',
        'only', 'own', 'same', 'than', 'too', 'very', 'just', 'also', 'now',
        'that', 'this', 'these', 'those', 'what', 'which', 'who', 'whom',
        'whose', 'where', 'when', 'why', 'how', 'all', 'each', 'every', 'any',
        'some', 'no', 'none', 'one', 'two', 'three', 'first', 'second', 'i',
        'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your',
        'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she',
        'her', 'hers', 'herself', 'it', 'its', 'itself', 'they', 'them', 'their',
        'theirs', 'themselves', 'if', 'because', 'while', 'although', 'though',
        'unless', 'until', 'since', 'whether', 'however', 'therefore', 'thus'
    }

    # Filter output tokens (keep non-stopwords that are at least 2 chars)
    meaningful_output_tokens = [t for t in output_tokens if t not in stopwords and len(t) > 1]

    if len(meaningful_output_tokens) == 0:
        # All tokens were stopwords, use all tokens instead
        meaningful_output_tokens = output_tokens

    # Count how many output tokens appear in context
    grounded_tokens = [t for t in meaningful_output_tokens if t in context_tokens]
    grounded_count = len(grounded_tokens)
    total_count = len(meaningful_output_tokens)

    faithfulness_score = grounded_count / total_count if total_count > 0 else 0.0

    return {
        "score": faithfulness_score,
        "metadata": {
            "grounded_tokens": grounded_count,
            "total_tokens": total_count,
            "context_length": len(context),
            "output_length": len(output),
        }
    }
