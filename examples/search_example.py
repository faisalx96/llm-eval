#!/usr/bin/env python3
"""
Example demonstrating natural language search functionality for evaluation results.

This example shows how to use the SearchQueryParser and SearchEngine classes
to filter evaluation results using plain English queries.
"""

from llm_eval.core.search import SearchQueryParser, SearchEngine
from llm_eval.core.results import EvaluationResult

def create_sample_evaluation_result():
    """Create a sample evaluation result for demonstration."""
    
    # Create evaluation result with common metrics
    eval_result = EvaluationResult(
        dataset_name="qa_evaluation_sample", 
        run_name="demo_run_2024",
        metrics=["exact_match", "answer_relevancy", "response_time", "accuracy_score"]
    )
    
    # Add sample results with varied performance
    sample_data = [
        # High performing items
        {
            "id": "item_001", 
            "output": "The capital of France is Paris.",
            "scores": {
                "exact_match": 1.0,
                "answer_relevancy": 0.95, 
                "response_time": 0.8,
                "accuracy_score": 0.98
            },
            "success": True,
            "time": 0.8
        },
        {
            "id": "item_002",
            "output": "Machine learning is a subset of artificial intelligence.",
            "scores": {
                "exact_match": 0.9,
                "answer_relevancy": 0.88,
                "response_time": 1.2,
                "accuracy_score": 0.92
            },
            "success": True,
            "time": 1.2
        },
        
        # Medium performing items
        {
            "id": "item_003",
            "output": "The Earth orbits around the Sun in approximately 365 days.",
            "scores": {
                "exact_match": 0.7,
                "answer_relevancy": 0.65,
                "response_time": 2.5,
                "accuracy_score": 0.75
            },
            "success": True,
            "time": 2.5
        },
        {
            "id": "item_004",
            "output": "Python is a programming language used for various applications.",
            "scores": {
                "exact_match": 0.6,
                "answer_relevancy": 0.58,
                "response_time": 3.1,
                "accuracy_score": 0.68
            },
            "success": True,
            "time": 3.1
        },
        
        # Poor performing items
        {
            "id": "item_005",
            "output": "I'm not sure about this question.",
            "scores": {
                "exact_match": 0.0,
                "answer_relevancy": 0.25,
                "response_time": 0.5,
                "accuracy_score": 0.15
            },
            "success": True,
            "time": 0.5
        },
        {
            "id": "item_006",
            "output": "This query took too long to process properly.",
            "scores": {
                "exact_match": 0.2,
                "answer_relevancy": 0.35,
                "response_time": 8.5,
                "accuracy_score": 0.30
            },
            "success": True,
            "time": 8.5
        }
    ]
    
    # Add the sample data to results
    for item in sample_data:
        eval_result.results[item["id"]] = {
            "output": item["output"],
            "scores": item["scores"],
            "success": item["success"],
            "time": item["time"]
        }
    
    # Add some error cases
    eval_result.errors = {
        "item_007": "Connection timeout during evaluation",
        "item_008": "Model API rate limit exceeded",
        "item_009": "Invalid input format provided"
    }
    
    eval_result.finish()
    return eval_result

def demonstrate_search_queries(eval_result, search_engine):
    """Demonstrate various natural language search queries."""
    
    print("🔍 Natural Language Search Demonstration")
    print("=" * 50)
    print()
    
    # Define test queries with descriptions
    search_queries = [
        ("Show me failures", "Find all failed evaluations"),
        ("Show me perfect matches", "Find items with exact match = 1.0"),
        ("Find slow responses", "Find evaluations that took too long"),
        ("Show me low relevancy scores", "Find items with poor relevancy"),
        ("accuracy_score > 0.8", "Find high accuracy items using explicit comparison"),
        ("took more than 3 seconds", "Find items that exceeded time threshold"),
        ("answer_relevancy < 0.4", "Find items with very low relevancy"),
        ("between 1 and 3 seconds", "Find items within specific time range"),
        ("Show me high accuracy scores", "Find items with good accuracy"),
        ("exact_match above 0.8", "Find items with high exact match scores")
    ]
    
    for query, description in search_queries:
        print(f"Query: '{query}'")
        print(f"Description: {description}")
        
        # Perform search
        result = search_engine.search(eval_result, query)
        
        print(f"Results: {result['total_matches']} matches found")
        
        if result['matched_items']:
            print(f"  Successful items: {result['matched_items']}")
        
        if result['matched_errors']:
            print(f"  Failed items: {result['matched_errors']}")
        
        # Show query parsing info
        if result['query_info']['parsed']:
            filters = result['query_info']['filters']
            print(f"  Query parsed successfully with {len(filters)} filter(s)")
            for i, filter_info in enumerate(filters, 1):
                if 'description' in filter_info:
                    print(f"    Filter {i}: {filter_info['description']}")
        else:
            print("  Query could not be parsed")
        
        print("-" * 40)
        print()

def demonstrate_search_suggestions(eval_result, search_engine):
    """Demonstrate search suggestions feature."""
    
    print("💡 Search Suggestions")
    print("=" * 30)
    print()
    
    suggestions = search_engine.get_suggestions(eval_result)
    
    print("Based on your evaluation data, here are some suggested queries:")
    for i, suggestion in enumerate(suggestions, 1):
        print(f"{i:2d}. {suggestion}")
    
    print()

def demonstrate_advanced_filtering():
    """Demonstrate advanced filtering capabilities."""
    
    print("🔧 Advanced Filtering Features")
    print("=" * 35)
    print()
    
    parser = SearchQueryParser()
    
    # Show supported query patterns
    print("Supported Query Patterns:")
    print("1. Status queries: 'failures', 'successes', 'errors'")
    print("2. Performance queries: 'slow responses', 'fast items'")
    print("3. Metric comparisons: 'accuracy > 0.8', 'relevancy < 0.5'")
    print("4. Time thresholds: 'took more than 5 seconds'")
    print("5. Time ranges: 'between 1 and 3 seconds'")
    print("6. Qualitative filters: 'low scores', 'perfect matches'")
    print()
    
    # Show default thresholds
    print("Default Thresholds:")
    for key, value in parser.default_thresholds.items():
        print(f"  {key}: {value}")
    print()
    
    # Show metric aliases
    print("Metric Aliases (for flexible naming):")
    for alias, variants in parser.metric_aliases.items():
        print(f"  '{alias}' → {variants}")
    print()

def main():
    """Main demonstration function."""
    
    print("🎯 LLM Evaluation Natural Language Search Demo")
    print("=" * 55)
    print()
    
    # Create sample evaluation result
    print("Creating sample evaluation result...")
    eval_result = create_sample_evaluation_result()
    
    print(f"✅ Created evaluation with:")
    print(f"   - {len(eval_result.results)} successful evaluations")
    print(f"   - {len(eval_result.errors)} failed evaluations") 
    print(f"   - {len(eval_result.metrics)} metrics: {', '.join(eval_result.metrics)}")
    print()
    
    # Initialize search engine
    search_engine = SearchEngine()
    
    # Demonstrate search queries
    demonstrate_search_queries(eval_result, search_engine)
    
    # Show search suggestions
    demonstrate_search_suggestions(eval_result, search_engine)
    
    # Show advanced features
    demonstrate_advanced_filtering()
    
    print("🎉 Demo Complete!")
    print("\nKey Features Demonstrated:")
    print("✓ Natural language query parsing")
    print("✓ Flexible metric filtering")
    print("✓ Performance-based filtering")
    print("✓ Error/success status filtering")
    print("✓ Time-based filtering")
    print("✓ Query suggestions")
    print("✓ Safe query execution (no SQL injection)")
    print("✓ High performance with large datasets")

if __name__ == "__main__":
    main()