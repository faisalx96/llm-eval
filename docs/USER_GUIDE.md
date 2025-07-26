# LLM-Eval User Guide

Welcome to LLM-Eval! This guide will help you evaluate your LLM applications in just a few minutes.

## What is LLM-Eval?

LLM-Eval is a simple framework that helps you test and measure how well your AI applications are performing. Think of it as automated testing for your AI - you provide test cases, and we'll tell you how well your AI handles them.

## Getting Started in 5 Minutes

### 1. Installation

```bash
pip install llm-eval
```

### 2. Set Up Langfuse Credentials

LLM-Eval uses Langfuse to store your test data and results. You'll need to configure your Langfuse credentials:

1. Get your API keys from your Langfuse instance (Settings → API Keys)
2. Set them as environment variables:

```bash
export LANGFUSE_PUBLIC_KEY="your-public-key"
export LANGFUSE_SECRET_KEY="your-secret-key"
export LANGFUSE_HOST="your-langfuse-host-url"
```

### 3. Create Your First Dataset

In Langfuse, create a dataset with test cases:

1. Go to Datasets → New Dataset
2. Name it "my-test-dataset"
3. Add some test items with questions and expected answers

Example dataset item:
```json
{
  "input": "What is the capital of France?",
  "expected_output": "Paris"
}
```

### 4. Evaluate Your Function

```python
from llm_eval import Evaluator

# Your AI function to test
def my_ai_assistant(question):
    # Your AI logic here
    return "Paris"  # Example response

# Create and run evaluation
evaluator = Evaluator(
    task=my_ai_assistant,
    dataset="my-test-dataset",
    metrics=["exact_match"]
)

results = evaluator.run()
results.print_summary()
```

That's it! You'll see how well your AI performed on the test cases.

## Understanding Metrics

Metrics tell you how to measure success. Here are the built-in options:

### Basic Metrics

- **exact_match**: Checks if the output exactly matches what you expected (100% or 0%)
- **contains**: Checks if the expected answer appears somewhere in the output
- **fuzzy_match**: Measures how similar the output is to expected (0% to 100%)

### Example: Choosing the Right Metric

```python
# For yes/no questions, use exact_match
evaluator = Evaluator(task=my_bot, dataset="yes-no-questions", 
                     metrics=["exact_match"])

# For longer responses, use contains or fuzzy_match
evaluator = Evaluator(task=my_bot, dataset="explanation-questions",
                     metrics=["contains", "fuzzy_match"])

# Use multiple metrics to get different perspectives
evaluator = Evaluator(task=my_bot, dataset="mixed-questions",
                     metrics=["exact_match", "contains", "fuzzy_match"])
```

## Working with Different AI Tools

### OpenAI

```python
import openai

def my_openai_bot(question):
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": question}]
    )
    return response.choices[0].message.content

evaluator = Evaluator(
    task=my_openai_bot,
    dataset="my-test-dataset",
    metrics=["fuzzy_match"]
)
```

### LangChain

```python
from langchain.chains import LLMChain
from langchain.llms import OpenAI

# Create your chain
chain = LLMChain(llm=OpenAI(), prompt=my_prompt)

# Evaluate it directly!
evaluator = Evaluator(
    task=chain,
    dataset="my-test-dataset", 
    metrics=["contains"]
)
```

## Custom Metrics

Need something specific? Create your own metric:

```python
def keyword_count(output, expected):
    """Count how many expected keywords appear in output."""
    keywords = expected.split(",")  # Expect comma-separated keywords
    found = sum(1 for kw in keywords if kw.lower() in output.lower())
    return found / len(keywords)

evaluator = Evaluator(
    task=my_bot,
    dataset="keyword-dataset",
    metrics=["exact_match", keyword_count]
)
```

## Understanding Results

After running evaluation, you'll see a summary like this:

```
Overview
Dataset: my-test-dataset
Total Items: 50
Success Rate: 96.0%
Duration: 12.3s

Metric Results:
  exact_match:
    Mean: 0.720    (72% exactly correct)
    Range: [0.0, 1.0]
  fuzzy_match:
    Mean: 0.865    (86.5% similarity on average)
    Range: [0.45, 1.0]
```

### What the numbers mean:
- **Success Rate**: How many test cases ran without errors
- **Mean**: Average score across all test cases
- **Range**: Lowest and highest scores

## Tips for Success

### 1. Start Small
Begin with 10-20 test cases to get a feel for how your AI performs.

### 2. Use Representative Examples
Your test cases should cover typical use cases and edge cases.

### 3. Iterate Quickly
```python
# Test → Improve → Test again
results1 = evaluator.run()
# Make improvements to your AI
results2 = evaluator.run()
# Compare results
```

### 4. Mix Metrics
Different metrics reveal different insights:
```python
metrics=["exact_match", "fuzzy_match", "contains"]
```

### 5. Track Progress Over Time
Use descriptive run names:
```python
config={"run_name": "v2-with-context-improvement"}
```

## Common Patterns

### Testing a Chatbot
```python
def chatbot(message):
    # Your chatbot logic
    return response

evaluator = Evaluator(
    task=chatbot,
    dataset="chatbot-conversations",
    metrics=["fuzzy_match", "contains"]
)
```

### Testing a Classifier
```python
def classify_sentiment(text):
    # Returns "positive", "negative", or "neutral"
    return classification

evaluator = Evaluator(
    task=classify_sentiment,
    dataset="sentiment-test-cases",
    metrics=["exact_match"]  # Classification needs exact matches
)
```

### Testing a Summarizer
```python
def summarize(text):
    # Returns summary
    return summary

# Custom metric for summaries
def summary_quality(output, expected):
    # Check if key points are covered
    key_points = expected.split("|")  # Pipe-separated key points
    covered = sum(1 for point in key_points if point in output)
    return covered / len(key_points)

evaluator = Evaluator(
    task=summarize,
    dataset="summarization-tests",
    metrics=["fuzzy_match", summary_quality]
)
```

## Troubleshooting

### "Dataset not found"
- Check the dataset name matches exactly (case-sensitive)
- Ensure you're connected to the right Langfuse project
- Verify the dataset exists in Langfuse dashboard

### "Invalid credentials"
- Double-check your API keys
- Ensure environment variables are set correctly
- Try refreshing your API keys in Langfuse

### Evaluation is slow
- Reduce concurrency: `config={"max_concurrency": 5}`
- Add timeout: `config={"timeout": 10.0}`
- Use fewer test cases for quick iterations

### Metrics returning 0
- Check if expected_output is set in your dataset
- Verify output format matches what metrics expect
- Use print statements to debug

## Advanced Configuration

```python
evaluator = Evaluator(
    task=my_ai,
    dataset="comprehensive-tests",
    metrics=["exact_match", "fuzzy_match", custom_metric],
    config={
        # Performance settings
        "max_concurrency": 10,     # Parallel evaluations
        "timeout": 30.0,           # Seconds per test
        
        # Tracking settings  
        "run_name": "experiment-42",
        "run_metadata": {
            "model": "gpt-4",
            "temperature": 0.7,
            "version": "2.1.0"
        },
        
        # Langfuse settings (if not using env vars)
        "langfuse_public_key": "pk-...",
        "langfuse_secret_key": "sk-...",
        "langfuse_host": "https://cloud.langfuse.com"
    }
)
```

## Next Steps

1. **Create more comprehensive datasets** - Cover edge cases and failure modes
2. **Build custom metrics** - Measure what matters for your use case
3. **Automate evaluation** - Run evaluations in CI/CD pipelines
4. **Track improvements** - Use Langfuse dashboard to visualize progress

## Getting Help

- Check the examples folder for more use cases
- View API documentation for detailed reference
- Contact your system administrator for technical issues

Happy evaluating! 🚀