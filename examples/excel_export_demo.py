"""
Example demonstrating Excel export functionality with rich formatting.
"""

import random
import time
from dotenv import load_dotenv
from llm_eval import Evaluator
from llm_eval.core.results import EvaluationResult

# Load environment variables from .env file
load_dotenv()


def ai_assistant(question: str) -> str:
    """A simple AI assistant for demonstration."""
    question_lower = question.lower()
    
    # Simulate processing time
    delay = random.uniform(0.1, 2.0)
    time.sleep(delay)
    
    # Simulate occasional failures
    if random.random() < 0.05:  # 5% failure rate
        raise Exception("Simulated processing error")

    if "capital of france" in question_lower:
        return "Paris is the capital and largest city of France."
    elif "python" in question_lower:
        return "Python is a high-level, interpreted programming language known for its simplicity and readability."
    elif "hello" in question_lower or "hi" in question_lower:
        return "Hello! I'm an AI assistant. How can I help you today?"
    elif "weather" in question_lower:
        return "I don't have access to real-time weather data, but I recommend checking a weather service."
    elif "math" in question_lower or "calculate" in question_lower:
        return "I can help with basic math calculations. What would you like me to calculate?"
    else:
        return "I'm not sure about that specific question, but I'd be happy to help with other topics."


def response_length_check(output: str) -> float:
    """Custom metric: Check if response is appropriate length."""
    length = len(output)
    if length < 10:
        return 0.0  # Too short
    elif length > 200:
        return 0.5  # Too long
    else:
        return 1.0  # Just right


def response_quality_score(output: str) -> float:
    """Custom metric: Basic quality assessment."""
    quality_indicators = ['helpful', 'recommend', 'can help', 'happy to', 'assist']
    score = 0.5  # Base score
    
    for indicator in quality_indicators:
        if indicator in output.lower():
            score += 0.1
    
    return min(score, 1.0)


def demo_basic_excel_export():
    """Demonstrate basic Excel export functionality."""
    print("🎯 Basic Excel Export Demo...")
    
    evaluator = Evaluator(
        task=ai_assistant,
        dataset="quickstart-demo",
        metrics=[
            response_length_check,
            response_quality_score,
            "exact_match"
        ]
    )
    
    # Run evaluation with Excel auto-save
    results = evaluator.run(
        show_progress=True,
        show_table=False,
        auto_save=True,
        save_format="excel"
    )
    
    print(f"\n📊 Excel report auto-saved with {results.total_items} items")
    return results


def demo_custom_excel_export():
    """Demonstrate custom Excel export with manual save."""
    print("\n🎯 Custom Excel Export Demo...")
    
    # Create evaluator
    evaluator = Evaluator(
        task=ai_assistant,
        dataset="quickstart-demo",
        metrics=[
            response_length_check,
            response_quality_score,
            "exact_match"
        ]
    )
    
    # Run evaluation without auto-save
    results = evaluator.run(show_progress=True, show_table=False)
    
    # Custom Excel export with specific filename
    excel_path = results.save_excel("custom_evaluation_report.xlsx")
    print(f"📈 Custom Excel report saved to: {excel_path}")
    
    # Also save in other formats for comparison
    json_path = results.save_json("evaluation_results.json")
    csv_path = results.save_csv("evaluation_results.csv")
    
    print(f"📄 JSON report saved to: {json_path}")
    print(f"📑 CSV report saved to: {csv_path}")
    
    return results


def demo_performance_test():
    """Test Excel export performance with simulated large dataset."""
    print("\n🎯 Performance Test Demo (simulated large dataset)...")
    
    # Create a results object manually to simulate large dataset
    results = EvaluationResult(
        dataset_name="performance-test-1000",
        run_name="large-scale-evaluation", 
        metrics=["response_length_check", "response_quality_score", "exact_match"]
    )
    
    # Simulate 1000+ evaluation results
    print("🔄 Generating 1000 simulated evaluation results...")
    start_time = time.time()
    
    for i in range(1000):
        item_id = f"item_{i:04d}"
        
        # Simulate success/failure (95% success rate)
        if random.random() < 0.95:
            # Successful result
            output = f"This is a simulated response for item {i}. " + \
                    "It contains helpful information and demonstrates various response lengths."
            
            result = {
                'output': output,
                'success': True,
                'time': random.uniform(0.1, 3.0),
                'scores': {
                    'response_length_check': random.uniform(0.7, 1.0),
                    'response_quality_score': random.uniform(0.6, 0.9),
                    'exact_match': random.choice([0.0, 1.0])
                }
            }
            results.add_result(item_id, result)
        else:
            # Failed result
            results.add_error(item_id, "Simulated evaluation error")
    
    results.finish()
    generation_time = time.time() - start_time
    print(f"✅ Generated {results.total_items} results in {generation_time:.2f}s")
    
    # Test Excel export performance
    print("📊 Testing Excel export performance...")
    export_start = time.time()
    excel_path = results.save_excel("performance_test_1000_items.xlsx")
    export_time = time.time() - export_start
    
    print(f"⚡ Excel export completed in {export_time:.2f}s")
    print(f"📈 Performance: {results.total_items/export_time:.1f} items/second")
    
    return results


def main():
    """Run all Excel export demonstrations."""
    print("🚀 Excel Export Functionality Demo")
    print("=" * 50)
    
    try:
        # Test 1: Basic Excel export with auto-save
        demo_basic_excel_export()
        
        # Test 2: Custom Excel export
        demo_custom_excel_export()
        
        # Test 3: Performance test with large dataset
        demo_performance_test()
        
        print("\n✅ All Excel export demos completed successfully!")
        print("\n📁 Check the generated Excel files:")
        print("   - Auto-generated Excel report (timestamped)")
        print("   - custom_evaluation_report.xlsx")
        print("   - performance_test_1000_items.xlsx")
        print("\n💡 Each Excel file contains:")
        print("   - Results worksheet: Detailed evaluation data")
        print("   - Summary worksheet: Aggregated statistics")
        print("   - Charts worksheet: Visual representations")
        
    except Exception as e:
        print(f"❌ Demo failed with error: {e}")
        print("💡 Make sure openpyxl is installed: pip install openpyxl")


if __name__ == "__main__":
    main()