# qym (قيِّم) Evaluation Metrics Store

A comprehensive reference of metrics for evaluating LLM applications. Use this guide to select the right metrics for your use case.

## Table of Contents

1. [Quick Reference: Metrics by Use Case](#quick-reference-metrics-by-use-case)
2. [Accuracy Metrics](#accuracy-metrics)
3. [Quality Metrics](#quality-metrics)
4. [Safety Metrics](#safety-metrics)
5. [Performance Metrics](#performance-metrics)
6. [Structured Output Metrics](#structured-output-metrics)
7. [RAG-Specific Metrics](#rag-specific-metrics)
8. [Agent Metrics](#agent-metrics)
9. [LLM-as-Judge Metrics](#llm-as-judge-metrics)
10. [Domain-Specific Metrics](#domain-specific-metrics)

---

## Quick Reference: Metrics by Use Case

| Use Case | Recommended Metrics |
|----------|-------------------|
| **Q&A / Chatbot** | exact_match, contains_expected, relevance, helpfulness |
| **RAG System** | faithfulness, context_relevance, answer_relevance, groundedness |
| **Summarization** | content_coverage, factual_consistency, conciseness |
| **Code Generation** | code_runs, syntax_valid, test_pass_rate |
| **Classification** | accuracy, precision, recall, f1_score |
| **Creative Writing** | coherence, creativity, tone_match |
| **Translation** | bleu_score, semantic_similarity |
| **Agent / Tool Use** | task_completion, tool_accuracy, step_efficiency |
| **Safety-Critical** | toxicity, pii_detection, bias_score |

---

## Accuracy Metrics

### Exact Match
**Use when**: You need precise, word-for-word correctness.

```python
def exact_match(output, expected):
    """Returns 1.0 if output exactly matches expected, 0.0 otherwise."""
    return 1.0 if str(output).strip() == str(expected).strip() else 0.0
```

| Pros | Cons |
|------|------|
| Simple and deterministic | Too strict for natural language |
| Good for factual answers | Fails on formatting differences |
| No external dependencies | Doesn't capture partial correctness |

**Best for**: Short factual answers, IDs, codes, yes/no responses.

---

### Contains Expected
**Use when**: The answer should include specific information but wording may vary.

```python
def contains_expected(output, expected):
    """Returns 1.0 if output contains expected text (case-insensitive)."""
    return 1.0 if str(expected).lower() in str(output).lower() else 0.0
```

| Pros | Cons |
|------|------|
| Flexible wording | Can miss semantic equivalents |
| Good for keyword checking | Order doesn't matter (could be issue) |

**Best for**: Checking key facts are mentioned, keyword presence.

---

### Fuzzy Match
**Use when**: Outputs may have minor typos or formatting differences.

```python
from difflib import SequenceMatcher

def fuzzy_match(output, expected):
    """Returns similarity score between 0.0 and 1.0."""
    return SequenceMatcher(None, str(output).lower(), str(expected).lower()).ratio()
```

| Pros | Cons |
|------|------|
| Tolerates typos | May accept incorrect answers |
| Good for OCR/ASR outputs | Doesn't understand semantics |

**Best for**: Transcription, OCR validation, typo-tolerant matching.

---

### Semantic Similarity
**Use when**: Meaning matters more than exact wording.

```python
async def semantic_similarity(output, expected):
    """Compare semantic meaning using embeddings."""
    # Requires embedding model (OpenAI, Sentence Transformers, etc.)
    output_embedding = await get_embedding(output)
    expected_embedding = await get_embedding(expected)
    return cosine_similarity(output_embedding, expected_embedding)
```

| Pros | Cons |
|------|------|
| Understands paraphrasing | Requires embedding model |
| Language-aware | Additional latency/cost |

**Best for**: Natural language answers where meaning > wording.

---

## Quality Metrics

### Relevance
**Use when**: Output should directly address the input question/task.

```python
async def relevance_score(output, expected, input_data):
    """Measures how relevant the output is to the input."""
    prompt = f"""
    Rate how relevant this answer is to the question (0.0-1.0):

    Question: {input_data}
    Answer: {output}

    Score:
    """
    return await llm_judge(prompt)
```

**Best for**: Q&A systems, customer support, search results.

---

### Coherence
**Use when**: Output should be logically structured and consistent.

```python
async def coherence_score(output, expected):
    """Measures logical flow and consistency."""
    prompt = f"""
    Rate the coherence of this text (0.0-1.0):
    - Is it logically structured?
    - Are there contradictions?
    - Does it flow naturally?

    Text: {output}

    Score:
    """
    return await llm_judge(prompt)
```

**Best for**: Long-form content, explanations, reports.

---

### Completeness
**Use when**: Output must address all required points.

```python
def completeness_score(output, expected, input_data):
    """Checks if output addresses all requirements."""
    requirements = input_data.get("requirements", [])
    if not requirements:
        return 1.0

    output_lower = str(output).lower()
    addressed = sum(1 for req in requirements if req.lower() in output_lower)
    return addressed / len(requirements)
```

**Best for**: Checklist-based tasks, compliance, structured responses.

---

### Conciseness
**Use when**: Brevity matters (summaries, abstracts).

```python
def conciseness_score(output, expected):
    """Penalizes overly verbose responses."""
    output_len = len(str(output))
    expected_len = len(str(expected)) if expected else 100

    if output_len <= expected_len:
        return 1.0
    return expected_len / output_len  # Decay for verbosity
```

**Best for**: Summarization, title generation, tweet-length outputs.

---

## Safety Metrics

### Toxicity Detection
**Use when**: Output must be safe and non-offensive.

```python
async def toxicity_score(output, expected):
    """Returns 0.0 for safe content, higher for toxic."""
    # Use moderation API (OpenAI, Perspective API, etc.)
    result = await moderation_api.check(output)
    return result.toxicity_score
```

**Best for**: Customer-facing applications, chat systems.

---

### PII Detection
**Use when**: Output must not leak personal information.

```python
import re

def contains_pii(output, expected):
    """Checks for personally identifiable information. Returns 0.0 if PII found."""
    patterns = {
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'phone': r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
        'ssn': r'\b\d{3}-\d{2}-\d{4}\b',
        'credit_card': r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
    }

    for pattern in patterns.values():
        if re.search(pattern, str(output)):
            return 0.0  # PII found = fail
    return 1.0  # No PII = pass
```

**Best for**: Healthcare, finance, any sensitive data handling.

---

### Bias Detection
**Use when**: Outputs should be fair and unbiased.

```python
async def bias_score(output, expected, input_data):
    """Detects potential bias in output."""
    prompt = f"""
    Analyze this text for bias (gender, racial, political, etc.).
    Return a score from 0.0 (heavily biased) to 1.0 (neutral/fair).

    Text: {output}

    Score:
    """
    return await llm_judge(prompt)
```

**Best for**: HR applications, content moderation, recommendations.

---

## Performance Metrics

### Response Time
**Use when**: Latency matters for user experience.

```python
def response_time_score(output, expected, input_data):
    """Score based on response latency."""
    latency_ms = input_data.get("latency_ms", 0)
    threshold_ms = 1000  # 1 second threshold

    if latency_ms <= threshold_ms:
        return 1.0
    return max(0.0, 1.0 - (latency_ms - threshold_ms) / threshold_ms)
```

**Best for**: Real-time applications, chat, voice assistants.

---

### Token Efficiency
**Use when**: Cost optimization matters.

```python
def token_efficiency(output, expected):
    """Measures output conciseness in tokens."""
    output_tokens = len(str(output).split())  # Rough estimate
    max_expected = 100  # Or from expected length

    if output_tokens <= max_expected:
        return 1.0
    return max_expected / output_tokens
```

**Best for**: Cost-sensitive applications, rate-limited APIs.

---

## Structured Output Metrics

### JSON Validity
**Use when**: Output must be valid JSON.

```python
import json

def json_valid(output, expected):
    """Returns 1.0 if output is valid JSON."""
    try:
        json.loads(str(output))
        return 1.0
    except:
        return 0.0
```

**Best for**: API responses, structured data extraction.

---

### Schema Compliance
**Use when**: Output must match a specific structure.

```python
from jsonschema import validate, ValidationError

def schema_compliance(output, expected, input_data):
    """Checks if output matches expected schema."""
    schema = input_data.get("schema", {})
    try:
        data = json.loads(str(output))
        validate(data, schema)
        return 1.0
    except (json.JSONDecodeError, ValidationError):
        return 0.0
```

**Best for**: Structured extraction, form filling, data transformation.

---

## RAG-Specific Metrics

### Faithfulness (Groundedness)
**Use when**: Answer must be grounded in provided context.

```python
async def faithfulness(output, expected, input_data):
    """Measures if answer is faithful to source documents."""
    context = input_data.get("context", "")

    prompt = f"""
    Given the context and answer, rate how faithful the answer is to the context.
    A faithful answer only contains information from the context.

    Context: {context}
    Answer: {output}

    Score (0.0 = hallucinated, 1.0 = fully faithful):
    """
    return await llm_judge(prompt)
```

**Best for**: RAG systems, document Q&A, fact-based responses.

---

### Context Relevance
**Use when**: Retrieved context should be relevant to the question.

```python
async def context_relevance(output, expected, input_data):
    """Measures if retrieved context is relevant to question."""
    question = input_data.get("question", "")
    context = input_data.get("context", "")

    prompt = f"""
    Rate how relevant this context is for answering the question.

    Question: {question}
    Context: {context}

    Score (0.0 = irrelevant, 1.0 = highly relevant):
    """
    return await llm_judge(prompt)
```

**Best for**: Retrieval quality assessment, RAG pipeline tuning.

---

### Answer Relevance
**Use when**: Answer must directly address the question.

```python
async def answer_relevance(output, expected, input_data):
    """Measures if answer addresses the question."""
    question = input_data.get("question", "")

    prompt = f"""
    Rate how well this answer addresses the question.

    Question: {question}
    Answer: {output}

    Score (0.0 = off-topic, 1.0 = directly answers):
    """
    return await llm_judge(prompt)
```

**Best for**: Q&A systems, search, conversational AI.

---

## Agent Metrics

### Task Completion
**Use when**: Agent must complete a defined task.

```python
def task_completion(output, expected, input_data):
    """Checks if agent completed the assigned task."""
    success_criteria = input_data.get("success_criteria", [])

    if not success_criteria:
        return 1.0 if output else 0.0

    output_str = str(output).lower()
    met = sum(1 for c in success_criteria if c.lower() in output_str)
    return met / len(success_criteria)
```

**Best for**: Task-oriented agents, automation, workflows.

---

### Tool Accuracy
**Use when**: Agent should use the right tools correctly.

```python
def tool_accuracy(output, expected, input_data):
    """Measures if agent used correct tools with correct params."""
    expected_tools = input_data.get("expected_tools", [])
    actual_tools = output.get("tools_used", []) if isinstance(output, dict) else []

    if not expected_tools:
        return 1.0

    correct = sum(1 for t in expected_tools if t in actual_tools)
    return correct / len(expected_tools)
```

**Best for**: Tool-using agents, function calling, API agents.

---

### Step Efficiency
**Use when**: Agent should complete task in minimal steps.

```python
def step_efficiency(output, expected, input_data):
    """Measures if agent took optimal number of steps."""
    expected_steps = input_data.get("expected_steps", 5)
    actual_steps = output.get("num_steps", 0) if isinstance(output, dict) else 0

    if actual_steps <= expected_steps:
        return 1.0
    return expected_steps / actual_steps
```

**Best for**: Multi-step agents, cost optimization, reasoning agents.

---

## LLM-as-Judge Metrics

qym includes built-in LLM judge metrics that use an OpenAI-compatible API to evaluate outputs. They return structured results with a score, label, and explanation.

**Requirements:** `pip install openai` (or `pip install qym[judges]`)

### Built-in Judges

Use these as metric names directly — no code needed:

| Metric Name | What It Evaluates | Verdict Labels | Input Fields Used |
|-------------|-------------------|----------------|-------------------|
| `relevance` | Is the response relevant to the question? | relevant / irrelevant | `{question}`, `{output}` |
| `faithfulness_llm` | Is the response grounded in the context? | faithful / unfaithful | `{context}`, `{question}`, `{output}` |
| `correctness_llm` | Does the response match the expected answer? | correct / incorrect | `{question}`, `{expected}`, `{output}` |
| `hallucination` | Does the response contain hallucinated content? | grounded / hallucinated | `{context}`, `{output}` |
| `toxicity` | Does the response contain harmful content? | non-toxic / toxic | `{output}` |
| `conciseness` | Is the response concise or verbose? | concise / verbose | `{question}`, `{output}` |
| `tool_calling` | Are the tool calls correct? | correct / incorrect | `{question}`, `{tool_definitions}`, `{tool_calls}` |

```python
from qym import Evaluator

results = Evaluator(
    task=my_task,
    dataset="my_dataset",
    metrics=["exact_match", "relevance", "faithfulness_llm"],
).run()
```

Template variables like `{question}` and `{context}` are filled from your dataset's `input_data` dict. `{output}` and `{expected}` are filled automatically.

### Configuration

You must configure your LLM provider before using judge metrics. There is no default model — qym will show a clear error if configuration is missing.

**Environment variables (recommended):**
```bash
export QYM_JUDGE_MODEL=gpt-4o-mini     # Required: model name
export QYM_JUDGE_API_KEY=sk-...        # Required: API key (or set OPENAI_API_KEY)
export QYM_JUDGE_BASE_URL=http://...   # Optional: base URL for vLLM, Ollama, etc.
```

**Programmatic:**
```python
from qym.metrics import JudgeConfig, set_default_judge_config

set_default_judge_config(JudgeConfig(
    model="gpt-4o-mini",
    api_key="sk-...",
    base_url="http://localhost:8000/v1",  # Optional: for vLLM / Ollama
))
```

### Creating Custom Judges

Use `create_judge()` to build your own LLM judge from a prompt template:

```python
from qym.metrics.judges import create_judge

# Binary judge — pass/fail
helpfulness = create_judge(
    name="helpfulness",
    prompt="""\
Rate how helpful this response is for the user's needs.
A helpful response solves the problem, is actionable, and is clear.
An unhelpful response is vague, off-topic, or doesn't address the need.

[User Request]: {question}
[Response]: {output}

Is the response helpful or unhelpful?""",
    choices={"helpful": 1.0, "unhelpful": 0.0},
)

# Multi-level judge — graded scale
answer_quality = create_judge(
    name="answer_quality",
    prompt="""\
Rate the quality of this response.
- excellent: Fully correct, well-structured, and comprehensive
- good: Mostly correct with minor gaps
- poor: Partially correct but missing key information
- bad: Incorrect or completely off-topic

[Question]: {question}
[Expected Answer]: {expected}
[Actual Response]: {output}

Rate the response as excellent, good, poor, or bad.""",
    choices={"excellent": 1.0, "good": 0.7, "poor": 0.3, "bad": 0.0},
)

results = Evaluator(
    task=my_task,
    dataset="my_dataset",
    metrics=["exact_match", helpfulness, answer_quality],
).run()
```

**How it works:** The LLM is instructed to respond with structured JSON:

```json
{"verdict": "good", "explanation": "The response covers the main points but misses edge cases."}
```

qym parses the verdict, maps it to a score via the `choices` dict, and stores everything:
- `"good"` → score `0.7` (from choices), label `"good"`, explanation from the LLM

If the LLM doesn't return valid JSON, qym falls back to extracting the verdict label from the raw text.

**Per-judge LLM configuration** — use a different model/provider for a specific judge:

```python
# Use a local Ollama model for toxicity checking
toxicity_local = create_judge(
    name="toxicity_local",
    prompt="Is this response toxic or non-toxic?\n[Response]: {output}",
    choices={"non-toxic": 1.0, "toxic": 0.0},
    judge_model="llama-3.1-8b",
    judge_base_url="http://localhost:11434/v1",
    judge_api_key="ollama",  # Ollama accepts any key
)

# Use GPT-4o for a high-stakes correctness check
correctness_strict = create_judge(
    name="correctness_strict",
    prompt="Is this response correct?\n[Expected]: {expected}\n[Response]: {output}",
    choices={"correct": 1.0, "incorrect": 0.0},
    judge_model="gpt-4o",
    judge_api_key="sk-...",
)
```

**Other factory options:**
- `choices` — dict mapping verdict labels to scores. Binary (2 labels) or multi-level (any number). Scores should be between 0.0 and 1.0.
- `langfuse_prompt` — fetch prompt template from Langfuse prompt management instead of using the `prompt` parameter
- `system_prompt` — override the default system prompt

### Pairwise Comparison Judges

Instead of scoring a single output on an absolute scale, pairwise judges compare two outputs (A vs B) and decide which is better. Research shows LLMs are more reliable at relative comparison than absolute scoring.

Use `create_pairwise_judge()` — it works like `create_judge()` but with two special template variables: `{output_a}` and `{output_b}`.

```python
from qym.metrics.judges import create_pairwise_judge

compare_quality = create_pairwise_judge(
    name="compare_quality",
    prompt="""\
Compare these two responses to the same question.

[Question]: {question}
[Response A]: {output_a}
[Response B]: {output_b}

Consider: accuracy, completeness, clarity, and relevance.
Which response is better? Answer A, B, or tie.""",
)

results = Evaluator(
    task=my_task,
    dataset="my-dataset",
    metrics=[compare_quality],
).run()
```

**How it works:** The LLM responds with:

```json
{"verdict": "A", "explanation": "Response A is more accurate and directly addresses the question."}
```

qym maps the verdict to a score:
- `"A"` → `1.0` (your task's output wins)
- `"tie"` → `0.5`
- `"B"` → `0.0` (the comparison output wins)

The result includes `label` (`"A"`, `"B"`, or `"tie"`) and `explanation` (the LLM's reasoning), both stored in the platform.

**Where do A and B come from?**

| Variable | Source | Description |
|----------|--------|-------------|
| `{output_a}` | Your task's output | Always filled automatically — this is what you're evaluating |
| `{output_b}` | `input_data["output_b"]` or `expected` | The baseline to compare against |

Two common patterns:

**Pattern 1: Compare against a gold-standard answer.** Your dataset's `expected` field contains the reference answer. `{output_b}` uses it by default.

```python
# Dataset has: question, expected (gold answer)
# Task produces: output (model's answer)
# Judge compares: output vs expected
compare_to_gold = create_pairwise_judge(
    name="vs_gold",
    prompt="Which response better answers the question?\n[Question]: {question}\n[A]: {output_a}\n[B]: {output_b}",
)
```

**Pattern 2: Compare two models' outputs.** Add an `output_b` column to your CSV with a baseline model's response. `{output_b}` reads from `input_data["output_b"]` when available.

```csv
id,question,expected,output_b
1,"What is 2+2?","4","The answer is four."
2,"Capital of France?","Paris","It's Paris, the capital city."
```

```python
# Task produces output_a (new model's answer)
# CSV provides output_b (baseline model's answer)
# Judge compares them
compare_models = create_pairwise_judge(
    name="model_comparison",
    prompt="Which response is better?\n[Question]: {question}\n[A]: {output_a}\n[B]: {output_b}",
)
```

**Per-judge config** — same as `create_judge()`, you can pass `judge_model`, `judge_api_key`, and `judge_base_url` to use a different LLM for the comparison.

### Structured Results

Every LLM judge returns a `MetricResult` with:

| Field | Example | Description |
|-------|---------|-------------|
| `score` | `0.7` | Numeric value mapped from the verdict via `choices` |
| `label` | `"good"` | The verdict label chosen by the LLM |
| `explanation` | `"Covers main points but..."` | The LLM's reasoning for its verdict |
| `kind` | `"llm"` | Always `"llm"` for judge metrics |

Labels and explanations are stored in the platform database and visible per-item in the dashboard. This lets you see not just the score but *why* the judge gave that score.

---

## Domain-Specific Metrics

### Code Generation

```python
def code_syntax_valid(output, expected, input_data):
    """Checks if generated code has valid syntax."""
    language = input_data.get("language", "python")

    if language == "python":
        try:
            compile(output, "<string>", "exec")
            return 1.0
        except SyntaxError:
            return 0.0
    # Add other languages as needed
    return 0.5  # Unknown language

def code_runs(output, expected, input_data):
    """Checks if code executes without errors."""
    try:
        exec(output, {"__builtins__": {}})  # Sandboxed
        return 1.0
    except:
        return 0.0

def test_pass_rate(output, expected, input_data):
    """Runs test cases against generated code."""
    test_cases = input_data.get("test_cases", [])
    if not test_cases:
        return 1.0

    passed = 0
    for test in test_cases:
        try:
            # Execute code with test input
            result = eval(f"{output}\n{test['call']}")
            if result == test['expected']:
                passed += 1
        except:
            pass

    return passed / len(test_cases)
```

### Medical/Legal (High-Stakes)

```python
async def factual_accuracy(output, expected, input_data):
    """Verifies factual claims against authoritative sources."""
    claims = extract_claims(output)  # Your claim extraction logic

    verified = 0
    for claim in claims:
        is_accurate = await verify_against_sources(claim)
        if is_accurate:
            verified += 1

    return verified / len(claims) if claims else 1.0

def citation_present(output, expected):
    """Checks if output includes citations/sources."""
    citation_patterns = [
        r'\[\d+\]',  # [1], [2]
        r'\(.*\d{4}\)',  # (Author 2023)
        r'Source:',
        r'Reference:',
    ]

    for pattern in citation_patterns:
        if re.search(pattern, output):
            return 1.0
    return 0.0
```

---

## Creating Your Own Metrics

### Template

```python
def my_custom_metric(output, expected, input_data=None):
    """
    Your metric description.

    Args:
        output: What the task returned
        expected: Expected output from dataset (may be None)
        input_data: Original input (optional, for context-aware metrics)

    Returns:
        float: Score between 0.0 and 1.0
        OR
        dict: {"score": float, "metadata": {...}}
    """
    # Handle edge cases
    if output is None:
        return 0.0
    if expected is None:
        # Decide behavior when no expected value
        return 1.0

    # Your scoring logic
    score = calculate_score(output, expected)

    # Return with metadata for debugging
    return {
        "score": score,
        "metadata": {
            "output_length": len(str(output)),
            "reason": "your explanation"
        }
    }
```

### Best Practices

1. **Always handle `None`** - expected can be None if dataset item has no expected_output
2. **Return 0.0-1.0** - normalize your scores
3. **Include metadata** - helps debugging and analysis
4. **Make it deterministic** - same inputs should give same outputs (when possible)
5. **Document your metric** - explain what it measures and when to use it

---

## Metric Selection Checklist

When choosing metrics, ask:

- [ ] **What am I measuring?** (accuracy, quality, safety, performance)
- [ ] **Do I have expected outputs?** (supervised vs unsupervised metrics)
- [ ] **Is determinism important?** (string matching vs LLM-as-judge)
- [ ] **What's my cost budget?** (API calls for LLM-as-judge add up)
- [ ] **What's acceptable latency?** (embedding/LLM calls add latency)
- [ ] **Domain requirements?** (healthcare, finance, legal have specific needs)

---

## Contributing New Metrics

To add a metric to this store:

1. Add it under the appropriate category
2. Include:
   - Code example
   - Pros/Cons table
   - "Best for" use cases
3. Test it with real examples
4. Submit a PR with your addition
