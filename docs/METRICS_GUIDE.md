# LLM Evaluation Metrics Guide

## Overview
This document outlines common metrics for evaluating LLM applications and how to implement them in our framework.

## Core Metric Categories

### 1. Accuracy Metrics

#### Exact Match
```python
def exact_match(output: str, expected: str) -> float:
    """Returns 1.0 if output exactly matches expected, 0.0 otherwise."""
    return 1.0 if output.strip() == expected.strip() else 0.0
```

#### Fuzzy Match
```python
def fuzzy_match(output: str, expected: str, threshold: float = 0.8) -> float:
    """Returns similarity score between 0.0 and 1.0."""
    # Using string similarity (e.g., Levenshtein distance)
    from difflib import SequenceMatcher
    return SequenceMatcher(None, output, expected).ratio()
```

#### Contains Expected
```python
def contains_expected(output: str, expected: str) -> float:
    """Returns 1.0 if output contains expected text."""
    return 1.0 if expected.lower() in output.lower() else 0.0
```

### 2. Quality Metrics

#### Relevance
```python
def relevance_score(output: str, context: str) -> float:
    """Measures how relevant the output is to the input context."""
    # Can use:
    # - Keyword overlap
    # - Semantic similarity (embeddings)
    # - LLM-as-judge
    pass
```

#### Coherence
```python
def coherence_score(output: str) -> float:
    """Measures logical flow and consistency of the output."""
    # Typically uses LLM-as-judge or linguistic analysis
    pass
```

#### Completeness
```python
def completeness_score(output: str, requirements: list) -> float:
    """Checks if output addresses all required points."""
    addressed = sum(1 for req in requirements if req in output.lower())
    return addressed / len(requirements) if requirements else 0.0
```

### 3. Safety Metrics

#### Toxicity Check
```python
def toxicity_score(output: str) -> float:
    """Returns 0.0 for safe content, higher for toxic content."""
    # Use content moderation APIs or models
    pass
```

#### PII Detection
```python
def contains_pii(output: str) -> bool:
    """Checks for personally identifiable information."""
    # Regex patterns for emails, phone numbers, SSNs, etc.
    import re
    patterns = {
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'phone': r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        'ssn': r'\b\d{3}-\d{2}-\d{4}\b'
    }
    return any(re.search(pattern, output) for pattern in patterns.values())
```

### 4. Performance Metrics

#### Response Time
```python
def response_time_score(duration_ms: float, threshold_ms: float = 1000) -> float:
    """Score based on response time (lower is better)."""
    if duration_ms <= threshold_ms:
        return 1.0
    else:
        # Linear decay after threshold
        return max(0.0, 1.0 - (duration_ms - threshold_ms) / threshold_ms)
```

#### Token Efficiency
```python
def token_efficiency(output_tokens: int, expected_tokens: int) -> float:
    """Measures how concise the output is."""
    if output_tokens <= expected_tokens:
        return 1.0
    else:
        # Penalize verbosity
        return expected_tokens / output_tokens
```

### 5. Structured Output Metrics

#### JSON Validity
```python
def json_valid(output: str) -> float:
    """Returns 1.0 if output is valid JSON."""
    import json
    try:
        json.loads(output)
        return 1.0
    except:
        return 0.0
```

#### Schema Compliance
```python
def schema_compliance(output: dict, schema: dict) -> float:
    """Checks if output matches expected schema."""
    # Use jsonschema or similar validation
    pass
```

### 6. Domain-Specific Metrics

#### Code Correctness
```python
def code_runs(code: str, test_cases: list) -> float:
    """Tests if generated code executes successfully."""
    passed = 0
    for test in test_cases:
        try:
            # Execute code with test input
            exec(code, {"input": test["input"]})
            passed += 1
        except:
            pass
    return passed / len(test_cases) if test_cases else 0.0
```

#### Factual Accuracy
```python
def fact_check(output: str, facts: list) -> float:
    """Verifies factual claims in output."""
    # Check against knowledge base or use LLM-as-judge
    pass
```

## LLM-as-Judge Metrics

### General Pattern
```python
def llm_judge_metric(output: str, input: str, criteria: str) -> float:
    """Uses an LLM to evaluate output based on criteria."""
    prompt = f"""
    Evaluate the following output based on {criteria}.
    
    Input: {input}
    Output: {output}
    
    Score from 0.0 to 1.0: 
    """
    # Call LLM and parse score
    pass
```

### Common LLM-Judge Criteria
- Helpfulness
- Harmlessness  
- Honesty
- Creativity
- Technical Accuracy
- Tone Appropriateness

## Composite Metrics

### Weighted Average
```python
def composite_score(scores: dict, weights: dict = None) -> float:
    """Combines multiple metrics with optional weights."""
    if not weights:
        return sum(scores.values()) / len(scores)
    
    total_weight = sum(weights.values())
    weighted_sum = sum(scores[k] * weights.get(k, 1.0) for k in scores)
    return weighted_sum / total_weight
```

### Pass/Fail Threshold
```python
def threshold_metric(scores: dict, thresholds: dict) -> bool:
    """Returns True if all metrics meet their thresholds."""
    return all(scores.get(k, 0) >= v for k, v in thresholds.items())
```

## Implementation Best Practices

### 1. Metric Design
- Keep metrics deterministic when possible
- Normalize scores to 0.0-1.0 range
- Handle edge cases (empty outputs, None values)
- Document what each metric measures

### 2. Error Handling
```python
def safe_metric(metric_func):
    """Decorator to handle metric failures gracefully."""
    def wrapper(*args, **kwargs):
        try:
            return metric_func(*args, **kwargs)
        except Exception as e:
            # Log error and return failure score
            return 0.0
    return wrapper
```

### 3. Metric Metadata
```python
class Metric:
    def __init__(self, name: str, func: callable, data_type: str = "NUMERIC"):
        self.name = name
        self.func = func
        self.data_type = data_type
        self.description = func.__doc__
```

### 4. Async Support
```python
async def async_metric(output: str, expected: str) -> float:
    """Example async metric for external API calls."""
    # Useful for LLM-as-judge or API-based metrics
    pass
```

## Common Metric Combinations

### For Q&A Systems
- Exact Match
- Relevance Score
- Completeness
- Response Time

### For Creative Writing
- Coherence
- Creativity (LLM-judge)
- Length Appropriateness
- Toxicity Check

### For Code Generation
- Code Runs
- Syntax Valid
- Efficiency Score
- Style Compliance

### For Summarization
- Content Coverage
- Length Ratio
- Factual Consistency
- Readability Score

### For Classification
- Accuracy
- Precision/Recall
- F1 Score
- Confidence Calibration

## Integration with Framework

```python
# Built-in metrics registry
BUILTIN_METRICS = {
    "exact_match": exact_match,
    "fuzzy_match": fuzzy_match,
    "contains": contains_expected,
    "json_valid": json_valid,
    "response_time": response_time_score,
    # ... more metrics
}

# Usage in evaluator
evaluator = Evaluator(
    task=my_function,
    dataset="qa-dataset",
    metrics=["exact_match", "response_time", custom_metric]
)
```