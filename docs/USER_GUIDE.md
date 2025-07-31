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

## Live Progress Display

When running evaluations, you'll see a real-time status table showing:

```
Evaluation Status
┏━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┓
┃ Input                  ┃ Output               ┃ Expected             ┃ exact_match  ┃ fuzzy    ┃ Time  ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━┩
│ What is the capital... │ Paris                │ Paris                │ ✓            │ 1.000    │ 2.34s │
│ Explain Python prog... │ Python is a high...  │ Python is a progr... │ ✗            │ 0.756    │ 3.12s │
│ Calculate 15 + 27      │ running...           │ 42                   │ pending      │ pending  │ ...   │
└────────────────────────┴──────────────────────┴──────────────────────┴──────────────┴──────────┴───────┘
```

The display updates in real-time as each evaluation completes, showing:
- **Input/Output/Expected**: Truncated to 50 characters for readability
- **Metric columns**: Live updates as each metric is computed
- **Time**: Execution time for each item
- **Color coding**: Green (completed), Yellow (in progress), Red (errors)

## Understanding Results

After running evaluation, you'll see a comprehensive summary:

```
Overview
Dataset: my-test-dataset
Total Items: 50
Success Rate: 96.0%
Total Duration: 125.3s
Average Item Time: 2.51s ± 0.34s
Time Range: [1.23s, 4.56s]

Evaluation Results: experiment-42
┏━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━━┓
┃ Metric      ┃  Mean ┃ Std Dev ┃   Min ┃   Max ┃ Success ┃
┡━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━━┩
│ exact_match │ 0.720 │   0.449 │ 0.000 │ 1.000 │  100.0% │
│ fuzzy_match │ 0.865 │   0.123 │ 0.450 │ 1.000 │  100.0% │
└─────────────┴───────┴─────────┴───────┴───────┴─────────┘
```

### What the numbers mean:
- **Success Rate**: Percentage of test cases that ran without errors
- **Total Duration**: Time to complete all evaluations
- **Average Item Time**: Mean execution time per item with standard deviation
- **Time Range**: Fastest and slowest item execution times
- **Mean**: Average score across all test cases
- **Std Dev**: Standard deviation showing score consistency
- **Min/Max**: Lowest and highest scores achieved

## Saving and Exporting Results

LLM-Eval provides multiple ways to save your evaluation results for further analysis:

### Auto-save During Evaluation

Enable automatic saving when running evaluations:

```python
# Auto-save as JSON (default)
results = evaluator.run(auto_save=True)

# Auto-save as CSV for spreadsheet analysis
results = evaluator.run(auto_save=True, save_format="csv")
```

Files are saved with timestamps: `eval_results_datasetname_20240115_143022.json`

### Manual Save Options

Save results after evaluation completes:

```python
# Save as JSON with all details
results.save_json("my_results.json")

# Save as CSV for Excel/Google Sheets
results.save_csv("analysis/results.csv") 

# Use generic save method
results.save(format="json", filepath="custom_path.json")
```

### Export Formats

**JSON Format** includes:
- Complete evaluation metadata
- All metric scores per item
- Execution times
- Full outputs and errors
- Statistical summaries

**CSV Format** includes:
- Item IDs and truncated outputs
- Success status
- Individual metric scores as columns
- Execution times
- Perfect for pivot tables and charts

### Example: Analysis Workflow

```python
# Run evaluation with auto-save
results = evaluator.run(auto_save=True, save_format="csv")

# Also save JSON for complete record
results.save_json("detailed_results.json")

# Access results programmatically
stats = results.get_timing_stats()
print(f"Average time per item: {stats['mean']:.2f}s")

# Get specific metric performance
accuracy = results.get_metric_stats("exact_match")
print(f"Accuracy: {accuracy['mean']:.1%}")
```

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

# Run with export options
results = evaluator.run(
    show_progress=True,      # Show live status display
    auto_save=True,          # Auto-save results
    save_format="json"       # Format: "json" or "csv"
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