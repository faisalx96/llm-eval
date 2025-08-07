#!/usr/bin/env python3
"""
LLM-Eval Product Usage Demo
============================

Shows exactly how to use the Sprint 2 product with real examples.
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from llm_eval.storage.database import get_database_manager
from llm_eval.models.run_models import EvaluationRun
from datetime import datetime
import time

def demo_llm_task(question: str) -> str:
    """
    Your actual task function - this is where you'd call your LLM
    
    In real usage, this might be:
    - OpenAI API call: openai.completions.create(...)
    - LangChain chain: chain.invoke(question)
    - Custom model inference: my_model.generate(question)
    """
    time.sleep(0.1)  # Simulate API latency
    
    # Demo responses (in reality, this would be your LLM)
    responses = {
        "What is the capital of France?": "Paris",
        "What color is the sky?": "Blue", 
        "What is 2+2?": "4",
        "What is the capital of Italy?": "Rome",
        "What color is grass?": "Green"
    }
    
    return responses.get(question, "I don't know")

def main():
    print("="*70)
    print("LLM-EVAL PRODUCT USAGE - HOW IT ACTUALLY WORKS")
    print("="*70)
    print()
    
    # Show the key difference
    print("KEY DIFFERENCE in Sprint 2:")
    print("   Add config={'project_id': 'your-project'} to enable UI storage!")
    print()
    
    # Database status
    db = get_database_manager()
    health = db.health_check()
    print(f"Database: {health['status']} ({health['statistics'].get('run_count', 0)} runs)")
    print()
    
    print("="*70)
    print("STEP 1: THE OLD WAY (Sprint 1)")
    print("="*70)
    print()
    print("# Code-only evaluation (results in memory only)")
    print("from llm_eval import Evaluator")
    print()
    print("evaluator = Evaluator(")
    print("    task=my_llm_function,")
    print("    dataset='my-dataset',")
    print("    metrics=['exact_match']")
    print(")")
    print("result = evaluator.run()")
    print("print(result.summary())  # Only way to see results")
    print()
    print("PROBLEMS:")
    print("   - Results only in memory")
    print("   - Must manually export/save")
    print("   - No comparison between runs") 
    print("   - No historical tracking")
    print("   - No team collaboration")
    print()
    
    print("="*70)
    print("STEP 2: THE NEW WAY (Sprint 2)")
    print("="*70)
    print()
    print("# UI-first evaluation (results auto-stored + dashboard)")
    print("from llm_eval import Evaluator")
    print()
    print("evaluator = Evaluator(")
    print("    task=my_llm_function,")
    print("    dataset='my-dataset',")
    print("    metrics=['exact_match'],")
    print("    config={")
    print("        'project_id': 'my-project',      # <-- This enables storage!")
    print("        'tags': ['experiment', 'v1'],")
    print("        'run_name': 'GPT-4 QA Test'")
    print("    }")
    print(")")
    print("result = evaluator.run()  # Same call!")
    print()
    print("BENEFITS:")
    print("   - Results auto-stored in database")
    print("   - Immediately visible in web dashboard") 
    print("   - Compare runs side-by-side")
    print("   - Historical performance tracking")
    print("   - Export to Excel/CSV from UI")
    print("   - Real-time progress tracking")
    print("   - REST API access")
    print()
    
    print("="*70)
    print("STEP 3: SIMULATE EVALUATION RUN")
    print("="*70)
    print()
    
    # Simulate what happens during evaluation
    sample_data = [
        {"question": "What is the capital of France?", "expected": "Paris"},
        {"question": "What color is the sky?", "expected": "Blue"},
        {"question": "What is 2+2?", "expected": "4"},
        {"question": "What is the capital of Italy?", "expected": "Rome"},
        {"question": "What color is grass?", "expected": "Green"}
    ]
    
    print(f"[X] Processing {len(sample_data)} evaluation items...")
    print()
    
    results = []
    for i, item in enumerate(sample_data, 1):
        question = item["question"]
        expected = item["expected"]
        
        print(f"   Item {i}: {question}")
        
        # Call your task (this would be your LLM)
        actual = demo_llm_task(question)
        
        # Check if correct
        is_correct = actual.lower().strip() == expected.lower().strip()
        
        results.append({
            "question": question,
            "expected": expected, 
            "actual": actual,
            "correct": is_correct
        })
        
        status = "[X]" if is_correct else "[X]"
        print(f"          Expected: {expected}")
        print(f"          Got:      {actual} {status}")
        print()
    
    # Calculate metrics
    correct = sum(1 for r in results if r["correct"])
    total = len(results)
    accuracy = correct / total
    
    print(f"[X] RESULTS:")
    print(f"   Accuracy: {correct}/{total} = {accuracy:.1%}")
    print()
    
    print("="*70)
    print("STEP 4: WHAT HAPPENS AUTOMATICALLY (Sprint 2)")
    print("="*70)
    print()
    
    print("When you run evaluator.run(), Sprint 2 automatically:")
    print()
    print("1. [X][X]  Stores run metadata in database")
    print("2. [X] Saves individual item results")  
    print("3. [X] Calculates and caches metric statistics")
    print("4. [X][X]  Applies project/tag organization")
    print("5. [X] Makes results available via REST API")
    print("6. [X] Shows results in web dashboard")
    print("7. [X] Enables run comparison and analysis")
    print()
    
    # Simulate the storage (this would happen automatically)
    print("Simulating automatic storage...")
    
    run_data = {
        "name": "Product Demo Run",
        "dataset_name": "demo-questions",
        "model_name": "demo-llm",
        "task_type": "qa",
        "metrics_used": ["exact_match"],
        "status": "completed",
        "total_items": total,
        "successful_items": correct,
        "failed_items": total - correct,
        "success_rate": accuracy,
        "duration_seconds": 2.5,
        "project_id": "product-demo",
        "tags": ["tutorial", "usage-demo"],
        "created_at": datetime.utcnow()
    }
    
    with db.get_session() as session:
        run = EvaluationRun(**run_data)
        session.add(run)
    
    print("[X] Run automatically stored in database!")
    print()
    
    print("="*70)
    print("STEP 5: ACCESS YOUR RESULTS")
    print("="*70)
    print()
    
    print("[X] WEB DASHBOARD:")
    print("   1. Start API:      python -m llm_eval.api.main")
    print("   2. Start Frontend: cd frontend && npm run dev")
    print("   3. Open Browser:   http://localhost:3000")
    print("   4. View/compare/export your evaluation runs")
    print()
    
    print("💻 CLI ACCESS:")
    print("   llm-eval runs list                    # List all runs")
    print("   llm-eval runs search 'product-demo'  # Search your project")
    print("   llm-eval runs compare run1 run2      # Compare two runs")
    print()
    
    print("🔌 API ACCESS:")
    print("   GET  http://localhost:8000/api/runs")
    print("   POST http://localhost:8000/api/runs")
    print("   # Full REST API for integration")
    print()
    
    print("="*70)
    print("CURRENT DATABASE STATUS")
    print("="*70)
    print()
    
    # Show actual database contents
    final_health = db.health_check()
    print(f"[X] Total evaluation runs: {final_health['statistics'].get('run_count', 0)}")
    
    with db.get_session() as session:
        recent_runs = session.query(EvaluationRun).order_by(
            EvaluationRun.created_at.desc()
        ).limit(5).all()
        
        if recent_runs:
            print()
            print("📋 Recent evaluation runs:")
            print(f"{'Name':<25} {'Model':<15} {'Success Rate':<12} {'Items'}")
            print("-" * 65)
            for run in recent_runs:
                success_rate = f"{run.success_rate:.1%}" if run.success_rate else "N/A"
                items = f"{run.successful_items}/{run.total_items}"
                print(f"{run.name[:24]:<25} {run.model_name:<15} {success_rate:<12} {items}")
    
    print()
    print("="*70)
    print("[X] PRODUCT USAGE DEMO COMPLETE!")
    print("="*70)
    print()
    print("[X] KEY TAKEAWAY:")
    print("   Just add config={'project_id': 'your-project'} to any")
    print("   existing Evaluator and instantly get:")
    print()
    print("   [X] Database storage")
    print("   [X] Web dashboard")  
    print("   [X] Run comparison")
    print("   [X] Historical tracking")
    print("   [X] Team collaboration")
    print("   [X] Excel/CSV export")
    print("   [X] REST API access")
    print("   [X] Real-time progress")
    print()
    print("   Same code, UI-first results! [X]")
    print("="*70)

if __name__ == "__main__":
    main()