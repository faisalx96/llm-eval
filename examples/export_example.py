"""
Example showing how to export evaluation results in different formats.
"""
import random
import time
from dotenv import load_dotenv
from llm_eval import Evaluator

# Load environment variables from .env file
load_dotenv()


def simple_qa_bot(question: str) -> str:
    """A simple Q&A bot for demonstration."""
    delay = random.randint(5, 20)  # random integer between 1 and 5
    time.sleep(delay)
    qa_pairs = {
        "what is the capital of france": "Paris",
        "what is 2+2": "4",
        "who wrote romeo and juliet": "William Shakespeare",
    }
    
    question_lower = question.lower().strip("?")
    return qa_pairs.get(question_lower, "I don't know the answer to that question.")


def main():
    print("🔍 Running evaluation with export examples...\n")
    
    # Example 1: Auto-save results in JSON format
    print("1️⃣ Running with auto-save (JSON)...")
    evaluator = Evaluator(
        task=simple_qa_bot,
        dataset="quickstart-demo",
        metrics=["exact_match"]
    )
    
    # Run with auto-save enabled
    results = evaluator.run(show_progress=True, auto_save=True, save_format="json")
    results.print_summary()
    
    print("\n" + "="*50 + "\n")
    
    # Example 2: Manual save in different formats
    print("2️⃣ Manual save in multiple formats...")
    
    # Save as JSON (complete results)
    json_path = results.save_json("results/my_eval_results.json")
    print(f"   JSON saved to: {json_path}")
    
    # Save as CSV (for Excel/spreadsheet analysis)
    csv_path = results.save_csv("results/my_eval_results.csv")
    print(f"   CSV saved to: {csv_path}")
    
    # Save with custom filename
    custom_path = results.save("json", "results/custom_name.json")
    print(f"   Custom save to: {custom_path}")
    
    print("\n" + "="*50 + "\n")
    
    # Example 3: Programmatic access to results
    print("3️⃣ Accessing results programmatically...")
    
    # Get the full results dictionary
    results_dict = results.to_dict()
    print(f"   Dataset: {results_dict['dataset_name']}")
    print(f"   Success rate: {results_dict['success_rate']:.1%}")
    print(f"   Total duration: {results_dict['duration']:.1f}s")
    
    # Get timing statistics
    timing_stats = results.get_timing_stats()
    print(f"   Average time per item: {timing_stats['mean']:.2f}s")
    
    # Get specific metric statistics
    for metric in results.metrics:
        stats = results.get_metric_stats(metric)
        print(f"   {metric} mean score: {stats['mean']:.3f}")
    
    print("\n✅ Export examples complete!")
    print("\nTip: Check the 'results/' directory for the saved files.")
    print("     JSON files contain complete evaluation details.")
    print("     CSV files are perfect for Excel analysis and reporting.")


if __name__ == "__main__":
    main()