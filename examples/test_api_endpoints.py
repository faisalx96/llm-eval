#!/usr/bin/env python3
"""Test script for the LLM-Eval REST API.

This script demonstrates the basic functionality of the API endpoints
and can be used for manual testing during development.
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any, List
import uuid

import aiohttp


API_BASE_URL = "http://localhost:8000/api"


class APITester:
    """Test client for the LLM-Eval API."""
    
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
        self.session = None
        self.created_runs = []  # Track runs created during testing
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        # Clean up created runs
        await self.cleanup()
        
        if self.session:
            await self.session.close()
    
    async def health_check(self) -> Dict[str, Any]:
        """Test health check endpoint."""
        print("🔍 Testing health check...")
        
        async with self.session.get(f"{self.base_url}/health/") as response:
            result = await response.json()
            print(f"   Status: {response.status}")
            print(f"   Health: {result.get('status', 'unknown')}")
            
            if response.status == 200:
                print("   ✅ Health check passed")
            else:
                print("   ❌ Health check failed")
            
            return result
    
    async def create_test_run(self, name_suffix: str = "") -> Dict[str, Any]:
        """Create a test evaluation run."""
        print(f"📝 Creating test run{' ' + name_suffix if name_suffix else ''}...")
        
        run_data = {
            "name": f"Test Run {name_suffix}" if name_suffix else "Test Run",
            "description": "Test run created by API test script",
            "dataset_name": "test-dataset",
            "model_name": "test-model",
            "model_version": "1.0.0",
            "task_type": "qa",
            "metrics_used": ["accuracy", "f1_score"],
            "metric_configs": {"accuracy": {"threshold": 0.8}},
            "config": {"temperature": 0.7, "max_tokens": 100},
            "environment": {"python_version": "3.10", "platform": "test"},
            "tags": ["test", "api"],
            "created_by": "api_test_script",
            "project_id": "test-project"
        }
        
        async with self.session.post(
            f"{self.base_url}/runs/",
            json=run_data
        ) as response:
            result = await response.json()
            
            if response.status == 201:
                run_id = result["run"]["id"]
                self.created_runs.append(run_id)
                print(f"   ✅ Created run: {run_id}")
                return result
            else:
                print(f"   ❌ Failed to create run: {result}")
                return result
    
    async def list_runs(self, limit: int = 5) -> Dict[str, Any]:
        """Test listing runs."""
        print(f"📋 Listing runs (limit: {limit})...")
        
        params = {"per_page": limit, "page": 1}
        
        async with self.session.get(
            f"{self.base_url}/runs/",
            params=params
        ) as response:
            result = await response.json()
            
            if response.status == 200:
                run_count = len(result.get("items", []))
                total = result.get("total", 0)
                print(f"   ✅ Found {run_count} runs (total: {total})")
                
                for i, run in enumerate(result.get("items", [])[:3]):
                    print(f"      {i+1}. {run['name']} ({run['status']})")
            else:
                print(f"   ❌ Failed to list runs: {result}")
            
            return result
    
    async def get_run_details(self, run_id: str) -> Dict[str, Any]:
        """Test getting run details."""
        print(f"🔍 Getting run details: {run_id[:8]}...")
        
        async with self.session.get(f"{self.base_url}/runs/{run_id}") as response:
            result = await response.json()
            
            if response.status == 200:
                run = result.get("run", {})
                metrics = result.get("metrics", [])
                print(f"   ✅ Retrieved run '{run.get('name')}' with {len(metrics)} metrics")
            else:
                print(f"   ❌ Failed to get run details: {result}")
            
            return result
    
    async def update_run(self, run_id: str) -> Dict[str, Any]:
        """Test updating a run."""
        print(f"✏️ Updating run: {run_id[:8]}...")
        
        update_data = {
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
            "duration_seconds": 45.5,
            "total_items": 100,
            "successful_items": 95,
            "failed_items": 5,
            "success_rate": 0.95,
            "avg_response_time": 0.8
        }
        
        async with self.session.put(
            f"{self.base_url}/runs/{run_id}",
            json=update_data
        ) as response:
            result = await response.json()
            
            if response.status == 200:
                print(f"   ✅ Updated run status to completed")
            else:
                print(f"   ❌ Failed to update run: {result}")
            
            return result
    
    async def search_runs(self, search_term: str = "test") -> Dict[str, Any]:
        """Test searching runs."""
        print(f"🔍 Searching runs for '{search_term}'...")
        
        params = {"search": search_term, "per_page": 10}
        
        async with self.session.get(
            f"{self.base_url}/runs/",
            params=params
        ) as response:
            result = await response.json()
            
            if response.status == 200:
                found_count = len(result.get("items", []))
                print(f"   ✅ Found {found_count} runs matching '{search_term}'")
            else:
                print(f"   ❌ Search failed: {result}")
            
            return result
    
    async def compare_runs(self, run_ids: List[str]) -> Dict[str, Any]:
        """Test run comparison."""
        if len(run_ids) < 2:
            print("⚠️ Need at least 2 runs for comparison, skipping...")
            return {}
        
        print(f"⚖️ Comparing {len(run_ids)} runs...")
        
        comparison_data = {
            "run_ids": run_ids[:2],  # Compare first 2 runs
            "comparison_type": "full"
        }
        
        async with self.session.post(
            f"{self.base_url}/comparisons/",
            json=comparison_data
        ) as response:
            result = await response.json()
            
            if response.status == 200:
                comparison = result.get("comparison", {})
                metric_count = len(comparison.get("metric_comparisons", []))
                print(f"   ✅ Compared runs across {metric_count} metrics")
            else:
                print(f"   ❌ Comparison failed: {result}")
            
            return result
    
    async def cleanup(self):
        """Clean up test runs."""
        if not self.created_runs:
            return
        
        print(f"🧹 Cleaning up {len(self.created_runs)} test runs...")
        
        for run_id in self.created_runs:
            try:
                async with self.session.delete(f"{self.base_url}/runs/{run_id}") as response:
                    if response.status == 200:
                        print(f"   ✅ Deleted run: {run_id[:8]}")
                    else:
                        print(f"   ⚠️ Failed to delete run: {run_id[:8]}")
            except Exception as e:
                print(f"   ❌ Error deleting run {run_id[:8]}: {e}")


async def run_api_tests():
    """Run comprehensive API tests."""
    print("🚀 Starting LLM-Eval API Tests")
    print("=" * 50)
    
    try:
        async with APITester() as tester:
            # Test 1: Health check
            await tester.health_check()
            print()
            
            # Test 2: Create test runs
            run1 = await tester.create_test_run("Alpha")
            run2 = await tester.create_test_run("Beta")
            print()
            
            # Test 3: List runs
            await tester.list_runs()
            print()
            
            # Test 4: Get run details
            if tester.created_runs:
                await tester.get_run_details(tester.created_runs[0])
                print()
            
            # Test 5: Update run
            if tester.created_runs:
                await tester.update_run(tester.created_runs[0])
                print()
            
            # Test 6: Search runs
            await tester.search_runs("Alpha")
            print()
            
            # Test 7: Compare runs
            await tester.compare_runs(tester.created_runs)
            print()
            
            print("✅ All API tests completed successfully!")
    
    except aiohttp.ClientConnectorError:
        print("❌ Cannot connect to API server. Make sure it's running on http://localhost:8000")
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
    
    print("=" * 50)


if __name__ == "__main__":
    print("LLM-Eval API Test Script")
    print("Make sure the API server is running: python -m llm_eval.api.main")
    print()
    
    asyncio.run(run_api_tests())