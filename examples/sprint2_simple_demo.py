#!/usr/bin/env python3
"""
Sprint 2 Demo - Working Database Demo
=====================================
"""

import sys
sys.path.append('.')

from llm_eval.storage.database import get_database_manager
from llm_eval.models.run_models import EvaluationRun
from datetime import datetime
import uuid

def main():
    print("="*60)
    print("LLM-EVAL SPRINT 2 - DATABASE DEMO")
    print("="*60)
    
    # Get database manager
    print("Connecting to database...")
    db = get_database_manager()
    
    # Check health
    health = db.health_check()
    print(f"Database Status: {health['status']}")
    print(f"Database URL: {health['database_url']}")
    print(f"Current Runs: {health['statistics'].get('run_count', 0)}")
    print()
    
    if health['status'] != 'healthy':
        print(f"Database Error: {health.get('error')}")
        return
    
    # Create a test run directly
    print("Creating test evaluation run...")
    
    with db.get_session() as session:
        test_run = EvaluationRun(
            name="Sprint 2 Demo Run",
            dataset_name="demo-dataset", 
            model_name="gpt-4",
            task_type="qa",
            metrics_used=["exact_match", "f1_score"],
            status="completed",
            total_items=100,
            successful_items=95,
            failed_items=5,
            success_rate=0.95,
            duration_seconds=120.5,
            created_at=datetime.utcnow(),
            tags=["demo", "sprint2"]
        )
        session.add(test_run)
        # Commit happens automatically with context manager
    
    print("OK - Test run created successfully!")
    
    # Check updated stats
    health = db.health_check()
    print(f"Updated Run Count: {health['statistics'].get('run_count', 0)}")
    
    # List runs
    print("\nCurrent runs in database:")
    with db.get_session() as session:
        runs = session.query(EvaluationRun).all()
        for run in runs:
            print(f"- {run.name} ({run.model_name}) - {run.status} - {run.success_rate:.1%}")
    
    print("\n" + "="*60)
    print("DATABASE DEMO COMPLETE!")
    print("The SQLite database is working and ready for the platform.")
    print("Start the API and frontend to see the full UI:")
    print("1. python -m llm_eval.api.main")
    print("2. cd frontend && npm run dev") 
    print("="*60)

if __name__ == "__main__":
    main()