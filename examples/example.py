"""
Example showing automatic DeepEval metrics discovery and usage.
"""

import random
import time
from dotenv import load_dotenv
from llm_eval import Evaluator, list_available_metrics

# Load environment variables from .env file
load_dotenv()


def ai_assistant(question: str) -> str:
    """A simple AI assistant for demonstration."""
    question_lower = question['question'].lower()
    delay = random.randint(5, 20)  # random integer between 1 and 5
    time.sleep(delay)

    if "capital of france" in question_lower:
        return "Paris is the capital and largest city of France."
    elif "python" in question_lower:
        return "Python is a high-level, interpreted programming language known for its simplicity and readability."
    elif "hello" in question_lower or "hi" in question_lower:
        return "Hello! I'm an AI assistant. How can I help you today?"
    else:
        return "I'm not sure about that specific question, but I'd be happy to help with other topics."


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
    
    print("🎯 Mixing Built-in metrics with custom metrics...")
    evaluator_mixed = Evaluator(
        task=ai_assistant,
        dataset="saudi-qa-verification-v1",
        metrics=[
            # "answer_relevancy", # DeepEval metric
            response_length_check,  # Custom metric
            "exact_match"          # Simple comparison
        ]
    )
    
    results_mixed = evaluator_mixed.run(show_table=True)


if __name__ == "__main__":
    main()