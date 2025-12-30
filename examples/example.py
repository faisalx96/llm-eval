"""
Example showing automatic DeepEval metrics discovery and usage.

Demonstrates:
- Smart argument resolution (model, trace_id)
- Adding custom spans to Langfuse traces
- Custom and built-in metrics
"""

import random
import time
from typing import Optional

from dotenv import load_dotenv
from langfuse import Langfuse
from qym import Evaluator, list_available_metrics

# Load environment variables from .env file
load_dotenv()

# Initialize Langfuse client for adding custom spans
langfuse = Langfuse()


def ai_assistant(question: str, model: Optional[str] = None, trace_id: Optional[str] = None) -> str:
    """
    A simple AI assistant for demonstration.

    Args:
        question: The input question from the dataset
        model: Model name (automatically passed by Evaluator)
        trace_id: Langfuse trace ID (automatically passed by Evaluator)

    Returns:
        The assistant's response
    """
    # Add a custom span to the existing trace for observability
    # Use trace_context to attach the span to the existing evaluation trace
    span = None
    if trace_id:
        span = langfuse.start_span(
            name="ai_assistant_processing",
            trace_context={"trace_id": trace_id},
            input={"question": question, "model": model},
        )

    question_lower = question.lower()
    delay = random.randint(3, 10)  # Simulate processing time
    time.sleep(delay)
    prefix = f"[{model}]" if model else "[default-model]"
    if "capital of france" in question_lower:
        response = f"{prefix} Paris is the capital and largest city of France."
    elif "python" in question_lower:
        response = f"{prefix} Python is a high-level, interpreted programming language known for its simplicity and readability."
    elif "hello" in question_lower or "hi" in question_lower:
        response = f"{prefix} Hello! I'm an AI assistant. How can I help you today?"
    else:
        response = f"{prefix} I'm not sure about that specific question, but I'd be happy to help with other topics."

    # End the span with output
    if span:
        span.update(output={"response": response, "delay": delay})
        span.end()

    return response


def main():    
    
    # Example: Mix DeepEval metrics with custom metrics
    def response_length_check(output: str) -> float:
        """Custom metric: Check if response is appropriate length."""
        length = len(output)
        if length < 10:
            return 0.0  # Too short
        elif length > 200:
            return 0.5  # Too long
        else:
            return 1.0  # Just right
    
    evaluator_mixed = Evaluator(
        task=ai_assistant,
        dataset="saudi-qa-verification-v1",
        metrics=[
            # "answer_relevancy", # DeepEval metric
            response_length_check,  # Custom metric
            "exact_match"          # Simple comparison
        ],
        model=["gpt-4o-mini", "llama-3.1"],
        # config={"run_name": "saudi qa"}
    )
    
    results_mixed = evaluator_mixed.run(save_format="csv")
    # if isinstance(results_mixed, list):
    #     for res in results_mixed:
    #         res.print_summary()
    # else:
    #     results_mixed.print_summary()


if __name__ == "__main__":
    main()
