#!/usr/bin/env python3
"""
Example demonstrating the storage integration features.

This example shows how the storage system seamlessly integrates with
existing evaluation workflows while adding powerful new capabilities.
"""

import os
from datetime import datetime, timedelta

# Mock function for demonstration
def simple_qa_task(input_data):
    """Simple QA task that returns a mock answer."""
    question = input_data.get('question', '')
    if 'capital' in question.lower():
        return "Paris"
    elif 'color' in question.lower():
        return "Blue"
    else:
        return "I don't know"


def demonstrate_automatic_storage():
    """Demonstrate automatic storage integration with existing evaluation workflow."""
    print("🔄 Automatic Storage Integration")
    print("=" * 40)
    
    from llm_eval.core.evaluator import Evaluator
    
    # Create an evaluator with storage enabled (default)
    # The evaluator will automatically store runs in the database
    evaluator = Evaluator(
        task=simple_qa_task,
        dataset="demo-qa-dataset",  # This would need to exist in Langfuse
        metrics=["exact_match", "contains"],
        config={
            # Storage configuration
            'store_runs': True,  # Default: True
            'project_id': 'demo-project',
            'created_by': 'demo-user',
            'tags': ['demo', 'automatic-storage'],
            'run_name': f'auto-storage-demo-{datetime.now().strftime("%Y%m%d-%H%M%S")}'
        }
    )
    
    print("✅ Created evaluator with automatic storage enabled")
    print(f"✅ Will store run in project: demo-project")
    print(f"✅ Run will be tagged: ['demo', 'automatic-storage']")
    
    # Note: The actual run would happen here, but we can't run it without a real dataset
    # result = evaluator.run()
    # print(f"✅ Evaluation completed and automatically stored with ID: {evaluator.database_run_id}")
    
    return evaluator


def demonstrate_manual_migration():
    """Demonstrate manual migration of existing evaluation results."""
    print("\n📦 Manual Migration Example")
    print("=" * 40)
    
    from llm_eval.core.results import EvaluationResult
    from llm_eval.storage.migration import migrate_from_evaluation_result
    
    # Create a mock evaluation result (as if from a previous evaluation)
    result = EvaluationResult(
        dataset_name="manual-migration-dataset",
        run_name="manual-migration-demo",
        metrics=["exact_match", "fuzzy_match", "response_time"]
    )
    
    # Add mock results
    result.results = {
        "demo_item_1": {
            "input": {"question": "What is the capital of France?"},
            "expected": "Paris",
            "output": "Paris",
            "scores": {"exact_match": 1.0, "fuzzy_match": 1.0, "response_time": 1.2},
            "time": 1.2
        },
        "demo_item_2": {
            "input": {"question": "What color is the sky?"},
            "expected": "Blue",
            "output": "Blue",
            "scores": {"exact_match": 1.0, "fuzzy_match": 1.0, "response_time": 0.9},
            "time": 0.9
        },
        "demo_item_3": {
            "input": {"question": "What is 2+2?"},
            "expected": "4",
            "output": "Four",
            "scores": {"exact_match": 0.0, "fuzzy_match": 0.8, "response_time": 1.1},
            "time": 1.1
        }
    }
    
    # Set timing information
    result.start_time = datetime.utcnow() - timedelta(minutes=5)
    result.end_time = datetime.utcnow()
    
    print("✅ Created mock EvaluationResult with 3 items")
    
    # Migrate to database storage
    run_id = migrate_from_evaluation_result(
        evaluation_result=result,
        project_id="migration-demo-project",
        created_by="migration-demo-user", 
        tags=["demo", "migration", "manual"],
        store_individual_items=True
    )
    
    print(f"✅ Migrated result to database with run ID: {run_id}")
    print("✅ Individual evaluation items stored for detailed analysis")
    
    return run_id


def demonstrate_search_capabilities():
    """Demonstrate the enhanced search capabilities."""
    print("\n🔍 Enhanced Search Capabilities")
    print("=" * 40)
    
    from llm_eval.core.search import RunSearchEngine
    
    search_engine = RunSearchEngine()
    
    # Basic search with filters
    print("📋 Basic filtered search:")
    results = search_engine.search_runs(
        project_id="demo-project",
        status="completed",
        limit=5
    )
    
    print(f"   Found {len(results.get('runs', []))} completed runs in demo-project")
    
    # Natural language search
    print("\n💬 Natural language search:")
    nl_results = search_engine.search_runs(
        query="failed runs from last week",
        limit=10
    )
    
    print(f"   Natural language query returned {len(nl_results.get('runs', []))} results")
    
    # Text search
    print("\n📝 Text search:")
    text_results = search_engine.search_runs(
        query="demo",
        limit=10
    )
    
    print(f"   Text search for 'demo' found {len(text_results.get('runs', []))} runs")
    
    # Performance-based search
    print("\n⚡ Performance-based search:")
    perf_results = search_engine.search_runs(
        min_success_rate=0.8,
        max_duration=60.0,
        limit=10
    )
    
    print(f"   Found {len(perf_results.get('runs', []))} high-performing runs (>80% success, <60s duration)")


def demonstrate_run_comparison():
    """Demonstrate run comparison capabilities."""
    print("\n⚖️  Run Comparison Capabilities")
    print("=" * 40)
    
    from llm_eval.storage.run_repository import RunRepository
    from llm_eval.core.search import RunSearchEngine
    
    repo = RunRepository()
    search_engine = RunSearchEngine()
    
    # Get recent runs for comparison
    runs = repo.list_runs(limit=5, order_by='created_at', descending=True)
    
    if len(runs) >= 2:
        run1_id = str(runs[0].id)
        run2_id = str(runs[1].id)
        
        print(f"🔄 Comparing runs: {runs[0].name} vs {runs[1].name}")
        
        comparison = search_engine.get_run_comparison(run1_id, run2_id)
        
        if 'comparison' in comparison:
            comp_data = comparison['comparison']
            summary = comp_data['summary']
            
            print(f"   Success Rate: {summary['run1_success_rate']:.1%} → {summary['run2_success_rate']:.1%}")
            print(f"   Delta: {summary['success_rate_delta']:+.1%}")
            
            if summary.get('duration_delta'):
                print(f"   Duration Delta: {summary['duration_delta']:+.1f}s")
            
            # Metric comparisons
            metric_comparisons = comp_data.get('metric_comparisons', {})
            if metric_comparisons:
                print(f"   Metrics compared: {len(metric_comparisons)}")
                for metric_name, metric_data in list(metric_comparisons.items())[:3]:  # Show first 3
                    delta = metric_data.get('delta', 0)
                    print(f"     {metric_name}: {delta:+.3f}")
        
        print(f"✅ Comparison {'cached' if comparison.get('cached') else 'computed'}")
    else:
        print("⚠️  Need at least 2 runs for comparison demo")


def demonstrate_database_operations():
    """Demonstrate database management operations."""
    print("\n🗄️  Database Management")
    print("=" * 40)
    
    from llm_eval.storage.database import get_database_manager
    
    db_manager = get_database_manager()
    
    # Health check
    health = db_manager.health_check()
    print(f"📊 Database Status: {health['status']}")
    
    if health['status'] == 'healthy':
        stats = health.get('statistics', {})
        print(f"   📈 Total Runs: {stats.get('run_count', 0)}")
        print(f"   📈 Total Items: {stats.get('item_count', 0)}")
        print(f"   📈 Total Metrics: {stats.get('metric_count', 0)}")
        
        if stats.get('latest_run_date'):
            print(f"   🕒 Latest Run: {stats.get('latest_run_name')} ({stats.get('latest_run_date')})")


def demonstrate_backward_compatibility():
    """Demonstrate that existing workflows continue to work unchanged."""
    print("\n🔄 Backward Compatibility")
    print("=" * 40)
    
    from llm_eval.core.evaluator import Evaluator
    
    # Create evaluator with storage disabled (for backward compatibility)
    evaluator = Evaluator(
        task=simple_qa_task,
        dataset="demo-qa-dataset",
        metrics=["exact_match"],
        config={
            'store_runs': False,  # Disable storage for backward compatibility
            'run_name': 'backward-compatibility-demo'
        }
    )
    
    print("✅ Created evaluator with storage DISABLED")
    print("✅ This works exactly like the original system")
    print("✅ No database dependencies or storage overhead")
    
    # The evaluation would work exactly as before
    # result = evaluator.run()
    # print("✅ Evaluation completed without any storage")


def main():
    """Run the complete storage integration demonstration."""
    print("🚀 Storage Integration Demonstration")
    print("=" * 50)
    print("This example shows how the new storage features integrate")
    print("seamlessly with existing LLM-Eval workflows.")
    print()
    
    try:
        # Setup database if needed
        from llm_eval.storage.database import get_database_manager
        db_manager = get_database_manager()
        print("✅ Database connection established")
        print()
        
        # Demonstrate features
        demonstrate_automatic_storage()
        run_id = demonstrate_manual_migration()
        demonstrate_search_capabilities()
        demonstrate_run_comparison()
        demonstrate_database_operations()
        demonstrate_backward_compatibility()
        
        print("\n" + "=" * 50)
        print("✅ Storage integration demonstration completed!")
        print()
        print("Key Benefits:")
        print("• 🔄 Automatic storage with zero code changes")
        print("• 🔍 Powerful search and filtering capabilities")
        print("• ⚖️  Advanced run comparison features")
        print("• 📊 Rich analytics and reporting")
        print("• 🔒 Full backward compatibility")
        print("• 🗄️  Efficient database storage with indexing")
        
        print("\nNext Steps:")
        print("• Use 'llm-eval db init' to set up your database")
        print("• Use 'llm-eval runs list' to browse stored runs")
        print("• Use 'llm-eval runs search \"your query\"' for advanced search")
        print("• Use 'llm-eval runs compare <id1> <id2>' for run comparison")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Demonstration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())