"""
Main Locust load testing script for LLM-Eval API endpoints

This script simulates realistic user behavior patterns including:
- Creating evaluation runs
- Fetching run lists with pagination
- Getting run details
- Comparing multiple runs
- Updating and deleting runs

Usage:
    locust -f locustfile.py --host=http://localhost:8000 --users=50 --spawn-rate=5 --run-time=5m
    
    # For web UI:
    locust -f locustfile.py --host=http://localhost:8000
"""

import json
import random
import time
from typing import Dict, List, Any
from locust import HttpUser, task, between, events
from locust.exception import RescheduleTask

from utils.data_generator import test_data_generator
from config import LOAD_TEST_CONFIG

class EvaluationRunUser(HttpUser):
    """Simulates a user interacting with the LLM-Eval API"""
    
    # Wait time between requests (realistic user behavior)
    wait_time = between(1, 5)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.created_runs: List[str] = []
        self.auth_headers = {"Content-Type": "application/json"}
    
    def on_start(self):
        """Initialize user session"""
        # Health check to ensure API is available
        response = self.client.get("/health", name="health_check")
        if response.status_code != 200:
            raise RescheduleTask("API not available")
    
    @task(20)
    def create_evaluation_run(self):
        """Create a new evaluation run - most common operation"""
        run_data = test_data_generator.generate_run_data('pending')
        
        with self.client.post(
            "/api/runs",
            json=run_data,
            headers=self.auth_headers,
            catch_response=True,
            name="create_run"
        ) as response:
            if response.status_code == 201:
                run_id = response.json().get('id')
                if run_id:
                    self.created_runs.append(run_id)
                response.success()
            else:
                response.failure(f"Failed to create run: {response.status_code}")
    
    @task(30)
    def list_runs(self):
        """List runs with various filters - very common operation"""
        # Simulate different filtering scenarios
        params = {}
        
        # Random filtering
        if random.random() < 0.3:
            params['status'] = random.choice(['completed', 'running', 'failed'])
        
        if random.random() < 0.2:
            params['template'] = random.choice(['qa_template', 'classification_template'])
        
        # Pagination
        params['limit'] = random.choice([10, 20, 50])
        params['offset'] = random.randint(0, 100)
        
        # Sorting
        params['sort_by'] = random.choice(['created_at', 'updated_at', 'name'])
        params['sort_order'] = random.choice(['asc', 'desc'])
        
        with self.client.get(
            "/api/runs",
            params=params,
            catch_response=True,
            name="list_runs"
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if 'items' in data and isinstance(data['items'], list):
                    response.success()
                else:
                    response.failure("Invalid response format")
            else:
                response.failure(f"Failed to list runs: {response.status_code}")
    
    @task(15)
    def get_run_details(self):
        """Get details for a specific run"""
        if not self.created_runs:
            # Use a random run ID if we haven't created any
            run_id = f"test-run-{random.randint(1, 1000)}"
        else:
            run_id = random.choice(self.created_runs)
        
        with self.client.get(
            f"/api/runs/{run_id}",
            catch_response=True,
            name="get_run_details"
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                # Expected for non-existent runs
                response.success()
            else:
                response.failure(f"Unexpected error: {response.status_code}")
    
    @task(10)
    def compare_runs(self):
        """Compare two runs - computationally intensive"""
        if len(self.created_runs) < 2:
            # Use random run IDs if we don't have enough created runs
            run1_id = f"test-run-{random.randint(1, 500)}"
            run2_id = f"test-run-{random.randint(501, 1000)}"
        else:
            run1_id, run2_id = random.sample(self.created_runs, 2)
        
        with self.client.get(
            f"/api/comparisons/{run1_id}/{run2_id}",
            catch_response=True,
            name="compare_runs"
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in [404, 400]:
                # Expected for non-existent or incompatible runs
                response.success()
            else:
                response.failure(f"Comparison failed: {response.status_code}")
    
    @task(8)
    def update_run(self):
        """Update an existing run"""
        if not self.created_runs:
            return
        
        run_id = random.choice(self.created_runs)
        update_data = {
            'name': f"Updated Run {random.randint(1, 9999)}",
            'description': "Updated via load test",
            'status': random.choice(['running', 'completed', 'failed'])
        }
        
        with self.client.patch(
            f"/api/runs/{run_id}",
            json=update_data,
            headers=self.auth_headers,
            catch_response=True,
            name="update_run"
        ) as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Update failed: {response.status_code}")
    
    @task(12)
    def search_runs(self):
        """Search runs with various queries"""
        search_queries = [
            "test",
            "qa",
            "classification",
            "completed",
            "failed",
            f"run-{random.randint(1, 100)}"
        ]
        
        query = random.choice(search_queries)
        params = {
            'search': query,
            'limit': 20
        }
        
        with self.client.get(
            "/api/runs/search",
            params=params,
            catch_response=True,
            name="search_runs"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Search failed: {response.status_code}")
    
    @task(5)
    def export_comparison(self):
        """Export comparison data - resource intensive"""
        if len(self.created_runs) < 2:
            return
        
        run1_id, run2_id = random.sample(self.created_runs, 2)
        format_type = random.choice(['excel', 'json', 'csv'])
        
        with self.client.get(
            f"/api/comparisons/{run1_id}/{run2_id}/export",
            params={'format': format_type},
            catch_response=True,
            name="export_comparison"
        ) as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Export failed: {response.status_code}")
    
    @task(3)
    def delete_run(self):
        """Delete a run - less common operation"""
        if not self.created_runs:
            return
        
        run_id = self.created_runs.pop()
        
        with self.client.delete(
            f"/api/runs/{run_id}",
            catch_response=True,
            name="delete_run"
        ) as response:
            if response.status_code in [200, 204, 404]:
                response.success()
            else:
                response.failure(f"Delete failed: {response.status_code}")
    
    @task(5)
    def get_run_metrics(self):
        """Get detailed metrics for a run"""
        if not self.created_runs:
            return
        
        run_id = random.choice(self.created_runs)
        
        with self.client.get(
            f"/api/runs/{run_id}/metrics",
            catch_response=True,
            name="get_run_metrics"
        ) as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Get metrics failed: {response.status_code}")
    
    @task(4)
    def get_run_items(self):
        """Get paginated run items"""
        if not self.created_runs:
            return
        
        run_id = random.choice(self.created_runs)
        params = {
            'limit': random.choice([10, 20, 50]),
            'offset': random.randint(0, 100)
        }
        
        with self.client.get(
            f"/api/runs/{run_id}/items",
            params=params,
            catch_response=True,
            name="get_run_items"
        ) as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Get items failed: {response.status_code}")

class HighVolumeUser(HttpUser):
    """Simulates users creating many runs quickly - stress testing scenario"""
    
    weight = 1  # Lower weight than regular users
    wait_time = between(0.1, 0.5)  # Very fast operations
    
    @task
    def rapid_run_creation(self):
        """Create runs rapidly to test system under high load"""
        batch_size = random.randint(5, 10)
        
        for _ in range(batch_size):
            run_data = test_data_generator.generate_run_data('pending')
            
            with self.client.post(
                "/api/runs",
                json=run_data,
                headers={"Content-Type": "application/json"},
                catch_response=True,
                name="rapid_create_run"
            ) as response:
                if response.status_code == 201:
                    response.success()
                else:
                    response.failure(f"Rapid creation failed: {response.status_code}")
                    break  # Stop batch on first failure

class ReadOnlyUser(HttpUser):
    """Simulates users who only read data - analytics/monitoring users"""
    
    weight = 2
    wait_time = between(2, 8)
    
    @task(40)
    def browse_runs(self):
        """Browse through runs with different filters"""
        params = {
            'limit': 50,
            'offset': random.randint(0, 500),
            'status': random.choice(['completed', 'failed'])
        }
        
        self.client.get("/api/runs", params=params, name="browse_runs")
    
    @task(30)
    def view_comparisons(self):
        """View existing comparisons"""
        run1_id = f"test-run-{random.randint(1, 500)}"
        run2_id = f"test-run-{random.randint(501, 1000)}"
        
        self.client.get(
            f"/api/comparisons/{run1_id}/{run2_id}",
            name="view_comparison"
        )
    
    @task(20)
    def search_operations(self):
        """Perform search operations"""
        queries = ["accuracy", "precision", "qa", "classification", "error"]
        query = random.choice(queries)
        
        self.client.get(
            "/api/runs/search",
            params={'search': query, 'limit': 100},
            name="search_readonly"
        )
    
    @task(10)
    def analytics_queries(self):
        """Simulate analytics queries"""
        # These would be custom endpoints for analytics
        self.client.get("/api/analytics/summary", name="analytics_summary")
        self.client.get("/api/analytics/trends", name="analytics_trends")

# Event handlers for performance monitoring
@events.request.add_listener
def request_handler(request_type, name, response_time, response_length, response, context, exception, **kwargs):
    """Log performance metrics for analysis"""
    if response_time > LOAD_TEST_CONFIG['targets']['api_response_time_p95']:
        print(f"SLOW REQUEST: {name} took {response_time}ms")

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Initialize test environment"""
    print("Starting load test...")
    print(f"Target host: {environment.host}")
    print(f"Performance targets: {LOAD_TEST_CONFIG['targets']}")

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Clean up after tests"""
    print("Load test completed!")
    print(f"Total requests: {environment.stats.total.num_requests}")
    print(f"Failed requests: {environment.stats.total.num_failures}")
    print(f"Average response time: {environment.stats.total.avg_response_time:.2f}ms")
    print(f"95th percentile: {environment.stats.total.get_response_time_percentile(0.95):.2f}ms")