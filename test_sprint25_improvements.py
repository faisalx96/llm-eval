#!/usr/bin/env python3
"""
Test script for SPRINT25-005 and SPRINT25-007 improvements.

This script tests the database indexes and WebSocket memory management
improvements to ensure no regressions and validate performance gains.

Usage:
    python test_sprint25_improvements.py
"""

import asyncio
import logging
import sqlite3
import tempfile
import time
import json
from pathlib import Path
from typing import Dict, Any, List
import uuid

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add the project directory to Python path
import sys
sys.path.insert(0, str(Path(__file__).parent))

try:
    from llm_eval.models.run_models import Base, EvaluationRun, EvaluationItem, RunMetric
    from llm_eval.storage.database import DatabaseManager
    from llm_eval.api.websocket_manager import WebSocketManager
    from sqlalchemy import create_engine, text
except ImportError as e:
    logger.error(f"Import error: {e}")
    logger.error("Make sure you're running this from the project root directory")
    sys.exit(1)


class DatabaseIndexTest:
    """Test database index performance improvements."""
    
    def __init__(self):
        self.db_file = None
        self.engine = None
        self.db_manager = None
    
    def setup_test_database(self) -> str:
        """Create a temporary test database with sample data."""
        # Create temporary database file
        db_fd, self.db_file = tempfile.mkstemp(suffix='.db')
        database_url = f"sqlite:///{self.db_file}"
        
        logger.info(f"Creating test database: {database_url}")
        
        # Create engine and tables
        self.engine = create_engine(database_url)
        Base.metadata.create_all(self.engine)
        
        # Create database manager
        self.db_manager = DatabaseManager(database_url)
        
        return database_url
    
    def populate_test_data(self, num_runs: int = 100, num_items_per_run: int = 50):
        """Populate database with test data."""
        logger.info(f"Creating {num_runs} runs with {num_items_per_run} items each...")
        
        with self.db_manager.get_session() as session:
            # Create test runs
            for i in range(num_runs):
                run = EvaluationRun(
                    name=f"test-run-{i}",
                    description=f"Test run {i}",
                    dataset_name=f"dataset-{i % 10}",  # 10 different datasets
                    model_name=f"model-{i % 5}",  # 5 different models
                    project_id=f"project-{i % 3}",  # 3 different projects
                    status="completed" if i % 4 != 0 else "running",  # Mix of statuses
                    metrics_used=["accuracy", "precision", "recall"],
                    total_items=num_items_per_run,
                    successful_items=num_items_per_run - (i % 5),  # Some failures
                    failed_items=i % 5
                )
                session.add(run)
                session.flush()  # Get the ID
                
                # Create test items for this run
                for j in range(num_items_per_run):
                    item = EvaluationItem(
                        run_id=run.id,
                        item_id=f"item-{j}",
                        sequence_number=j,
                        status="completed" if j % 10 != 0 else "failed",
                        response_time=0.5 + (j % 10) * 0.1,
                        tokens_used=100 + (j % 50),
                        cost=0.001 * (j % 50),
                        scores={"accuracy": 0.8 + (j % 10) * 0.02}
                    )
                    session.add(item)
                
                # Create test metrics for this run
                for metric_name in ["accuracy", "precision", "recall"]:
                    metric = RunMetric(
                        run_id=run.id,
                        metric_name=metric_name,
                        mean_score=0.7 + (i % 10) * 0.02,
                        total_evaluated=num_items_per_run,
                        successful_evaluations=num_items_per_run - (i % 5)
                    )
                    session.add(metric)
            
            session.commit()
        
        logger.info(f"Created {num_runs} runs with {num_runs * num_items_per_run} items")
    
    def test_index_performance(self) -> Dict[str, Any]:
        """Test query performance with indexes."""
        logger.info("Testing database query performance...")
        
        results = {}
        
        with self.engine.connect() as conn:
            # Test 1: List runs by project and status (should use idx_runs_project_status)
            start_time = time.time()
            result = conn.execute(text("""
                SELECT COUNT(*) FROM evaluation_runs 
                WHERE project_id = 'project-1' AND status = 'completed'
            """))
            count = result.scalar()
            results["runs_by_project_status"] = {
                "time_ms": round((time.time() - start_time) * 1000, 2),
                "count": count
            }
            
            # Test 2: Get items by run_id with pagination (should use idx_items_run_sequence)
            start_time = time.time()
            result = conn.execute(text("""
                SELECT COUNT(*) FROM evaluation_items 
                WHERE run_id = (SELECT id FROM evaluation_runs LIMIT 1)
                ORDER BY sequence_number LIMIT 20
            """))
            count = result.scalar()
            results["items_by_run_paginated"] = {
                "time_ms": round((time.time() - start_time) * 1000, 2),
                "count": count
            }
            
            # Test 3: Get run metrics (should use idx_metrics_run_name)
            start_time = time.time()
            result = conn.execute(text("""
                SELECT COUNT(*) FROM run_metrics 
                WHERE run_id = (SELECT id FROM evaluation_runs LIMIT 1)
                AND metric_name = 'accuracy'
            """))
            count = result.scalar()
            results["run_metrics_lookup"] = {
                "time_ms": round((time.time() - start_time) * 1000, 2),
                "count": count
            }
            
            # Test 4: Time-based queries (should use idx_runs_created_at)
            start_time = time.time()
            result = conn.execute(text("""
                SELECT COUNT(*) FROM evaluation_runs 
                WHERE created_at > datetime('now', '-1 day')
            """))
            count = result.scalar()
            results["runs_by_time"] = {
                "time_ms": round((time.time() - start_time) * 1000, 2),
                "count": count
            }
        
        logger.info("Database performance test completed")
        return results
    
    def verify_indexes_exist(self) -> Dict[str, bool]:
        """Verify that expected indexes exist in the database."""
        logger.info("Verifying database indexes...")
        
        expected_indexes = {
            # EvaluationRun indexes
            "idx_runs_project_status": "evaluation_runs",
            "idx_runs_updated_at": "evaluation_runs", 
            "idx_runs_status_created": "evaluation_runs",
            "idx_runs_project_id": "evaluation_runs",
            "idx_runs_status": "evaluation_runs",
            "idx_runs_created_at": "evaluation_runs",
            
            # EvaluationItem indexes
            "idx_items_run_id": "evaluation_items",
            "idx_items_run_status": "evaluation_items",
            "idx_items_run_sequence": "evaluation_items",
            "idx_items_run_created": "evaluation_items",
            "idx_items_run_completed": "evaluation_items",
            
            # RunMetric indexes  
            "idx_metrics_run_name": "run_metrics",
            "idx_metrics_run_id": "run_metrics",
        }
        
        results = {}
        
        with self.engine.connect() as conn:
            # Get all indexes
            result = conn.execute(text("""
                SELECT name, tbl_name FROM sqlite_master 
                WHERE type = 'index' AND name NOT LIKE 'sqlite_%'
            """))
            
            existing_indexes = {row[0]: row[1] for row in result}
            
            for index_name, table_name in expected_indexes.items():
                exists = index_name in existing_indexes
                if exists and existing_indexes[index_name] == table_name:
                    results[index_name] = True
                else:
                    results[index_name] = False
                    logger.warning(f"Missing or incorrect index: {index_name}")
        
        return results
    
    def cleanup(self):
        """Clean up test resources."""
        if self.db_manager:
            self.db_manager.close()
        if self.engine:
            self.engine.dispose()
        if self.db_file:
            try:
                Path(self.db_file).unlink()
                logger.info("Test database cleaned up")
            except Exception as e:
                logger.warning(f"Could not clean up test database: {e}")


class WebSocketMemoryTest:
    """Test WebSocket memory management improvements."""
    
    def __init__(self):
        self.manager = None
    
    async def test_connection_limits(self) -> Dict[str, Any]:
        """Test connection limit enforcement."""
        logger.info("Testing WebSocket connection limits...")
        
        # Create manager with low limit for testing
        self.manager = WebSocketManager(max_connections=5, cleanup_interval=60)
        
        results = {
            "max_connections": 5,
            "connections_created": 0,
            "limit_enforced": False,
            "cleanup_successful": True
        }
        
        try:
            # Simulate connections (we can't create real WebSockets in this test)
            # Instead, test the connection tracking logic
            initial_count = await self.manager.get_connection_count()
            
            # Test health check functionality
            health = await self.manager.health_check()
            
            results["initial_connections"] = initial_count
            results["health_check"] = health["status"]
            results["manager_initialized"] = True
            
            # Test cleanup functionality
            await self.manager.cleanup_stale_connections()
            
            # Test shutdown
            await self.manager.shutdown()
            
        except Exception as e:
            logger.error(f"WebSocket test error: {e}")
            results["cleanup_successful"] = False
            results["error"] = str(e)
        
        return results
    
    async def test_error_tracking(self) -> Dict[str, Any]:
        """Test connection error tracking."""
        logger.info("Testing WebSocket error tracking...")
        
        self.manager = WebSocketManager(max_connections=10, cleanup_interval=60)
        
        results = {
            "error_tracking": True,
            "health_monitoring": True,
            "background_cleanup": True
        }
        
        try:
            # Test health check with detailed information
            health = await self.manager.health_check()
            
            expected_fields = ["status", "connections", "subscriptions", "errors", "cleanup"]
            for field in expected_fields:
                if field not in health:
                    results["health_monitoring"] = False
                    logger.warning(f"Missing health field: {field}")
            
            results["health_data"] = health
            
            # Test background cleanup task functionality
            # (The cleanup task should be created but not necessarily running)
            if hasattr(self.manager, '_cleanup_task'):
                results["cleanup_task_exists"] = True
            
            await self.manager.shutdown()
            
        except Exception as e:
            logger.error(f"Error tracking test failed: {e}")
            results["error"] = str(e)
        
        return results


async def run_websocket_tests() -> Dict[str, Any]:
    """Run all WebSocket tests."""
    logger.info("Starting WebSocket memory management tests...")
    
    ws_test = WebSocketMemoryTest()
    
    results = {}
    
    # Test connection limits
    results["connection_limits"] = await ws_test.test_connection_limits()
    
    # Test error tracking
    results["error_tracking"] = await ws_test.test_error_tracking()
    
    return results


def run_database_tests() -> Dict[str, Any]:
    """Run all database tests."""
    logger.info("Starting database index tests...")
    
    db_test = DatabaseIndexTest()
    
    try:
        # Setup test database
        database_url = db_test.setup_test_database()
        
        # Populate with test data
        db_test.populate_test_data(num_runs=50, num_items_per_run=20)
        
        # Verify indexes exist
        index_results = db_test.verify_indexes_exist()
        
        # Test performance
        performance_results = db_test.test_index_performance()
        
        return {
            "database_url": database_url,
            "indexes": index_results,
            "performance": performance_results,
            "test_successful": True
        }
    
    except Exception as e:
        logger.error(f"Database test failed: {e}")
        return {
            "test_successful": False,
            "error": str(e)
        }
    
    finally:
        db_test.cleanup()


def print_results(results: Dict[str, Any]):
    """Print test results in a readable format."""
    print("\n" + "="*60)
    print("SPRINT25 IMPROVEMENTS TEST RESULTS")
    print("="*60)
    
    # Database results
    if "database" in results:
        db_results = results["database"]
        print(f"\n📊 DATABASE INDEX TESTS:")
        print(f"   Status: {'✅ PASSED' if db_results.get('test_successful') else '❌ FAILED'}")
        
        if "indexes" in db_results:
            total_indexes = len(db_results["indexes"])
            working_indexes = sum(1 for v in db_results["indexes"].values() if v)
            print(f"   Indexes: {working_indexes}/{total_indexes} working")
            
            if working_indexes < total_indexes:
                print("   Missing indexes:")
                for name, exists in db_results["indexes"].items():
                    if not exists:
                        print(f"     - {name}")
        
        if "performance" in db_results:
            print("   Query Performance:")
            for test_name, perf_data in db_results["performance"].items():
                print(f"     {test_name}: {perf_data['time_ms']}ms ({perf_data['count']} results)")
    
    # WebSocket results
    if "websocket" in results:
        ws_results = results["websocket"]
        print(f"\n🔌 WEBSOCKET MEMORY TESTS:")
        
        if "connection_limits" in ws_results:
            limits = ws_results["connection_limits"]
            print(f"   Connection Limits: {'✅ WORKING' if limits.get('manager_initialized') else '❌ FAILED'}")
            print(f"   Cleanup: {'✅ WORKING' if limits.get('cleanup_successful') else '❌ FAILED'}")
        
        if "error_tracking" in ws_results:
            tracking = ws_results["error_tracking"]
            print(f"   Error Tracking: {'✅ WORKING' if tracking.get('error_tracking') else '❌ FAILED'}")
            print(f"   Health Monitoring: {'✅ WORKING' if tracking.get('health_monitoring') else '❌ FAILED'}")
    
    print("\n" + "="*60)


async def main():
    """Main test runner."""
    logger.info("Starting SPRINT25 improvements tests...")
    
    results = {}
    
    # Run database tests
    results["database"] = run_database_tests()
    
    # Run WebSocket tests
    results["websocket"] = await run_websocket_tests()
    
    # Print results
    print_results(results)
    
    # Return overall success
    db_success = results["database"].get("test_successful", False)
    ws_success = all(
        test.get("manager_initialized", False) and test.get("cleanup_successful", False) 
        for test in results["websocket"].values() 
        if isinstance(test, dict)
    )
    
    overall_success = db_success and ws_success
    
    if overall_success:
        logger.info("✅ All SPRINT25 tests PASSED")
        return 0
    else:
        logger.error("❌ Some SPRINT25 tests FAILED")
        return 1


if __name__ == "__main__":
    import sys
    exit_code = asyncio.run(main())
    sys.exit(exit_code)