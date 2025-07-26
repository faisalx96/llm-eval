"""
Simple example of using llm-eval framework.

This example shows how to evaluate a basic Q&A function.
"""

from dotenv import load_dotenv
from llm_eval import Evaluator

# Load environment variables from .env file
# load_dotenv()


# Example 1: Simple function evaluation
def simple_qa_bot(question: str) -> str:
    """A simple Q&A bot that answers basic questions."""
    question_lower = question.lower()
    
    if "capital of france" in question_lower:
        return "Paris"
    elif "2+2" in question_lower or "2 + 2" in question_lower:
        return "4"
    elif "python" in question_lower:
        return "Python is a high-level programming language."
    else:
        return "I don't know the answer to that question."


# Example 2: Using the evaluator
def main():
    # Create evaluator with minimal configuration
    evaluator = Evaluator(
        task=simple_qa_bot,
        dataset="quickstart-demo",  # Dataset must exist in your Langfuse project
        metrics=["exact_match", "contains", "fuzzy_match"]
    )
    
    # Run evaluation
    print("Starting evaluation...")
    results = evaluator.run()
    
    # Print results
    print("\nEvaluation complete!")
    results.print_summary()
    
    # Access detailed results
    print(f"\nTotal items evaluated: {results.total_items}")
    print(f"Success rate: {results.success_rate:.1%}")
    
    # Get metrics for specific metric
    exact_match_stats = results.get_metric_stats("exact_match")
    print(f"\nExact match accuracy: {exact_match_stats['mean']:.1%}")


# Example 3: With custom metric
def response_length(output: str) -> float:
    """Custom metric that scores based on response length."""
    length = len(output)
    if length < 10:
        return 0.0
    elif length > 100:
        return 0.5
    else:
        return 1.0


def example_with_custom_metric():
    evaluator = Evaluator(
        task=simple_qa_bot,
        dataset="quickstart-demo",
        metrics=["exact_match", response_length]  # Mix built-in and custom
    )
    
    results = evaluator.run()
    print(results.summary())


# Example 4: With configuration
def example_with_config():
    evaluator = Evaluator(
        task=simple_qa_bot,
        dataset="quickstart-demo",
        metrics=["exact_match"],
        config={
            "max_concurrency": 5,  # Run 5 evaluations in parallel
            "timeout": 10.0,       # 10 second timeout per item
            "run_name": "qa-bot-v1-test",
            "run_metadata": {
                "version": "1.0",
                "environment": "development"
            }
        }
    )
    
    results = evaluator.run()
    results.print_summary()


if __name__ == "__main__":
    # Note: You need to set up Langfuse credentials as environment variables:
    # LANGFUSE_PUBLIC_KEY=your_public_key
    # LANGFUSE_SECRET_KEY=your_secret_key
    # LANGFUSE_HOST=https://cloud.langfuse.com (or your self-hosted URL)
    
    # And create a dataset in Langfuse with name "quickstart-demo"
    # containing items with 'input' (questions) and 'expected_output' (answers)
    
    main()