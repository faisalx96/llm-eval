"""
Test script to verify HTML display functionality.
"""

import os
from dotenv import load_dotenv
from llm_eval import Evaluator

# Load environment variables
load_dotenv()

def simple_task(input_text: str) -> str:
    """A simple task that returns the input uppercased."""
    import time
    import random
    # Simulate some processing time
    time.sleep(random.uniform(0.1, 0.5))
    return input_text.upper()

def main():
    print("Testing HTML display functionality...")
    
    # Create evaluator with simple metrics
    evaluator = Evaluator(
        task=simple_task,
        dataset="quickstart-demo",  # This should exist in your Langfuse account
        metrics=["exact_match"]
    )
    
    # Run with show_table=True to test HTML display
    print("\n🚀 Running evaluation with HTML display enabled...")
    results = evaluator.run(show_table=True)
    
    print("\n✅ Evaluation complete!")
    print(f"Success rate: {results.success_rate:.1%}")

if __name__ == "__main__":
    main()