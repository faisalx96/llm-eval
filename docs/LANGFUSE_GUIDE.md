# Langfuse Integration Guide for LLM Evaluation Framework

## Overview
This guide provides comprehensive information about using Langfuse for our LLM evaluation framework. Langfuse serves as the backbone for dataset management, trace logging, and evaluation scoring.

## Core Langfuse Concepts

### 1. Datasets
Langfuse datasets are collections of test cases used for systematic evaluation.

**Key Properties:**
- Unique name within a project
- 20-100 example inputs (recommended)
- Include input and optional expected output
- Support metadata for additional context

**Dataset Item Structure:**
```python
{
    "input": {...},              # Required: Input to your LLM application
    "expected_output": {...},    # Optional: Expected output for evaluation
    "metadata": {...}            # Optional: Additional context
}
```

### 2. Traces
Traces capture the complete execution flow of LLM applications.

**Features:**
- Multi-step interaction tracking
- Automatic linking to dataset items
- Performance metrics (latency, tokens, costs)
- Hierarchical structure support

### 3. Scores
Flexible scoring system for evaluation results.

**Score Types:**
- `NUMERIC`: Float values (e.g., 0.0 to 1.0)
- `BOOLEAN`: True/False values
- `CATEGORICAL`: String categories (e.g., "good", "bad", "neutral")

## Python SDK Methods for Evaluation

### Dataset Operations

```python
from langfuse import Langfuse
client = Langfuse()

# Create a dataset
dataset = client.create_dataset(
    name="evaluation-dataset-v1",
    description="Test cases for Q&A evaluation",
    metadata={"version": "1.0"}
)

# Add dataset items
client.create_dataset_item(
    dataset_name="evaluation-dataset-v1",
    input={"question": "What is the capital of France?"},
    expected_output={"answer": "Paris"},
    metadata={"category": "geography"}
)

# Fetch dataset
dataset = client.get_dataset(name="evaluation-dataset-v1")

# Iterate through items
for item in dataset.items:
    print(f"Input: {item.input}")
    print(f"Expected: {item.expected_output}")
```

### Running Evaluations

```python
# Standard evaluation pattern
dataset = client.get_dataset("my-eval-dataset")

for item in dataset.items:
    # Create a trace linked to dataset item
    with item.run(
        run_name="gpt-4-evaluation-run",
        run_metadata={"model": "gpt-4", "temperature": 0.7},
        run_description="Evaluating GPT-4 on Q&A tasks"
    ) as trace:
        # Run your LLM application
        result = my_llm_application(item.input)
        
        # Log the generation
        trace.generation(
            name="llm-call",
            input=item.input,
            output=result,
            model="gpt-4"
        )
        
        # Score the result
        score_value = evaluate_result(result, item.expected_output)
        trace.score_trace(
            name="accuracy",
            value=score_value,
            data_type="NUMERIC"
        )
```

### Scoring Methods

```python
# Score at observation level
generation.score(
    name="relevance",
    value=0.85,
    data_type="NUMERIC",
    comment="High relevance to user query"
)

# Score at trace level
trace.score_trace(
    name="overall_quality",
    value="excellent",
    data_type="CATEGORICAL"
)

# Direct score creation (low-level)
client.create_score(
    name="custom_metric",
    value=True,
    data_type="BOOLEAN",
    trace_id="specific-trace-id",
    observation_id="optional-observation-id"
)
```

## Evaluation Workflow

### 1. Dataset Preparation
```python
# Create dataset from production traces
production_traces = client.get_traces(limit=100)
selected_traces = filter_high_quality_traces(production_traces)

for trace in selected_traces:
    client.create_dataset_item(
        dataset_name="production-derived-dataset",
        input=trace.input,
        expected_output=trace.output,
        metadata={"source": "production", "trace_id": trace.id}
    )
```

### 2. Experiment Execution
```python
def run_evaluation_experiment(dataset_name, run_name, llm_function):
    dataset = client.get_dataset(dataset_name)
    
    for item in dataset.items:
        with item.run(run_name=run_name) as trace:
            try:
                # Execute LLM application
                output = llm_function(item.input)
                
                # Update trace with execution details
                trace.update(output=output)
                
                # Apply multiple evaluators
                scores = {
                    "accuracy": accuracy_evaluator(output, item.expected_output),
                    "relevance": relevance_evaluator(output, item.input),
                    "coherence": coherence_evaluator(output)
                }
                
                # Log all scores
                for metric_name, score_value in scores.items():
                    trace.score_trace(
                        name=metric_name,
                        value=score_value,
                        data_type="NUMERIC"
                    )
                    
            except Exception as e:
                trace.score_trace(
                    name="error",
                    value=str(e),
                    data_type="CATEGORICAL"
                )
```

### 3. Handling Non-Traced Tasks
For tasks without built-in Langfuse tracing:

```python
def wrap_untraced_function(func, client):
    def wrapped(*args, **kwargs):
        # Create manual trace
        trace = client.trace(
            name=f"{func.__name__}_evaluation",
            input={"args": args, "kwargs": kwargs}
        )
        
        try:
            result = func(*args, **kwargs)
            trace.update(output=result)
            return result
        except Exception as e:
            trace.update(output={"error": str(e)})
            raise
        finally:
            trace.end()
    
    return wrapped
```

## Best Practices for Our Framework

### 1. Dataset Management
- Store all evaluation datasets in Langfuse
- Use consistent naming: `{purpose}-{version}-{date}`
- Include comprehensive metadata for filtering
- Version datasets when making changes

### 2. Trace Organization
- Use clear, descriptive trace names
- Include model parameters in metadata
- Link all evaluation runs to dataset items
- Group related evaluations with run_name

### 3. Scoring Strategy
- Define consistent metric names across evaluations
- Use appropriate data types for each metric
- Include score comments for context
- Aggregate scores at trace level for overall performance

### 4. Error Handling
- Always wrap evaluations in try-except blocks
- Log errors as categorical scores
- Continue evaluation even if individual items fail
- Report partial results

## Integration Points

### For LangChain Applications
```python
from langfuse.callback import CallbackHandler

# Use Langfuse callback for automatic tracing
langfuse_handler = CallbackHandler()

chain.invoke(
    {"input": dataset_item.input},
    config={"callbacks": [langfuse_handler]}
)
```

### For Direct API Calls
```python
@observe()  # Langfuse decorator for automatic tracing
def call_openai_api(prompt):
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content
```

## API Reference Summary

### Key Methods
- `create_dataset()`: Create new dataset
- `get_dataset()`: Retrieve existing dataset
- `create_dataset_item()`: Add items to dataset
- `trace()`: Create manual trace
- `score_trace()`: Add scores to trace
- `generation()`: Log LLM generation details

### Environment Variables
```bash
LANGFUSE_PUBLIC_KEY=your_public_key
LANGFUSE_SECRET_KEY=your_secret_key
LANGFUSE_HOST=https://cloud.langfuse.com  # or self-hosted URL
```

## Limitations and Considerations

1. **Dataset Size**: Recommended 20-100 items for manageable evaluation
2. **Score Types**: Limited to numeric, boolean, and categorical
3. **Async Support**: Use `AsyncLangfuse` for async applications
4. **Rate Limits**: Consider API rate limits for large evaluations
5. **Data Privacy**: Ensure sensitive data is properly handled

## Important API Notes

### Dataset Item Runs
When using `item.run()`, the returned span object has specific methods:
- ✅ Use `span.update(input=data)` to set trace input
- ✅ Use `span.update(output=result)` to update trace output
- ✅ Use `span.score_trace(name, value, data_type)` to add scores
- ❌ **Do NOT use** `span.generation()` - this method doesn't exist on span objects

### Correct Usage Pattern
```python
for item in dataset.items:
    with item.run(run_name="evaluation") as span:
        # Update span with input first
        span.update(input=item.input)
        
        # Execute task
        result = my_task(item.input)
        
        # Update span with output - NOT span.generation()
        span.update(output=result)
        
        # Add scores
        span.score_trace(name="accuracy", value=0.95, data_type="NUMERIC")
```

This guide provides the foundation for building our evaluation framework on top of Langfuse's infrastructure.