"""Load testing for LLM-Eval API endpoints using Locust.

This module provides comprehensive load testing scenarios for all API endpoints
including evaluation configurations, task execution, metric validation, and
template management. Tests are designed to simulate realistic usage patterns
and identify performance bottlenecks under load.
"""

import json
import random
import uuid
from typing import Dict, Any, List

from locust import HttpUser, TaskSet, task, between
from locust.exception import RescheduleTask


class EvaluationConfigurationTasks(TaskSet):
    """Load tests for evaluation configuration endpoints."""
    
    def on_start(self):
        """Initialize test data for configuration tasks."""
        self.created_configs = []
        self.sample_config_templates = [
            {
                "name_suffix": "QA Configuration",
                "task_type": "qa",
                "template_name": "qa",
                "task_config": {
                    "endpoint_url": "https://api.example.com/chat",
                    "model": "gpt-3.5-turbo",
                    "temperature": 0.7
                },
                "dataset_config": {
                    "dataset_name": "qa_dataset",
                    "filters": {"category": "general"}
                },
                "metrics_config": {
                    "metrics": [
                        {"metric_name": "exact_match", "parameters": {}},
                        {"metric_name": "semantic_similarity", "parameters": {"threshold": 0.8}}
                    ]
                }
            },
            {
                "name_suffix": "Classification Configuration", 
                "task_type": "classification",
                "template_name": "classification",
                "task_config": {
                    "endpoint_url": "https://api.example.com/classify",
                    "model": "bert-base-uncased"
                },
                "dataset_config": {
                    "dataset_name": "classification_dataset",
                    "filters": {"domain": "sentiment"}
                },
                "metrics_config": {
                    "metrics": [
                        {"metric_name": "exact_match", "parameters": {}},
                        {"metric_name": "classification_accuracy", "parameters": {}}
                    ]
                }
            },
            {
                "name_suffix": "Summarization Configuration",
                "task_type": "summarization", 
                "template_name": "summarization",
                "task_config": {
                    "endpoint_url": "https://api.example.com/summarize",
                    "model": "t5-base",
                    "max_length": 150
                },
                "dataset_config": {
                    "dataset_name": "summarization_dataset",
                    "filters": {"length": "medium"}
                },
                "metrics_config": {
                    "metrics": [
                        {"metric_name": "rouge", "parameters": {"rouge_type": "rouge-l"}},
                        {"metric_name": "bleu", "parameters": {}}
                    ]
                }
            }
        ]

    @task(3)
    def create_configuration(self):
        """Create a new evaluation configuration."""
        template = random.choice(self.sample_config_templates)
        config_data = {
            "name": f"Load Test {template['name_suffix']} {uuid.uuid4().hex[:8]}",
            "description": f"Load testing configuration for {template['task_type']} evaluation",
            "task_type": template["task_type"],
            "template_name": template["template_name"],
            "task_config": template["task_config"],
            "dataset_config": template["dataset_config"], 
            "metrics_config": template["metrics_config"],
            "execution_config": {
                "batch_size": random.randint(5, 50),
                "max_concurrent": random.randint(1, 10),
                "timeout": random.randint(30, 120)
            },
            "tags": [f"load-test-{random.randint(1, 100)}", template["task_type"], "automated"],
            "project_id": f"load-test-project-{random.randint(1, 10)}"
        }
        
        with self.client.post("/api/evaluations/configs", 
                             json=config_data, 
                             catch_response=True) as response:
            if response.status_code == 201:
                config = response.json()
                self.created_configs.append(config["id"])
                response.success()
            elif response.status_code == 409:
                # Conflict is acceptable (duplicate config key)
                response.success()
            else:
                response.failure(f"Failed to create configuration: {response.text}")

    @task(5)
    def list_configurations(self):
        """List evaluation configurations with various filters."""
        params = {}
        
        # Randomly apply filters
        if random.random() < 0.3:
            params["task_type_filter"] = random.choice(["qa", "classification", "summarization"])
        
        if random.random() < 0.3:
            params["status_filter"] = random.choice(["draft", "published"])
            
        if random.random() < 0.4:
            params["search"] = random.choice(["Load Test", "QA", "Classification", "test"])
            
        if random.random() < 0.5:
            params["page_size"] = random.randint(5, 50)
            params["page"] = random.randint(1, 3)

        with self.client.get("/api/evaluations/configs", 
                            params=params, 
                            catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                response.success()
            else:
                response.failure(f"Failed to list configurations: {response.text}")

    @task(2)
    def get_configuration_details(self):
        """Get details of a specific configuration."""
        if not self.created_configs:
            raise RescheduleTask()
            
        config_id = random.choice(self.created_configs)
        with self.client.get(f"/api/evaluations/configs/{config_id}", 
                            catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                # Remove non-existent config from our list
                self.created_configs.remove(config_id)
                response.success()  # Not really a failure
            else:
                response.failure(f"Failed to get configuration: {response.text}")

    @task(1)
    def update_configuration(self):
        """Update an existing configuration."""
        if not self.created_configs:
            raise RescheduleTask()
            
        config_id = random.choice(self.created_configs)
        update_data = {
            "description": f"Updated description at {uuid.uuid4().hex[:8]}",
            "tags": [f"updated-{random.randint(1, 100)}", "load-test"]
        }
        
        create_version = random.random() < 0.3  # 30% chance to create new version
        params = {"create_new_version": create_version} if create_version else {}
        
        with self.client.put(f"/api/evaluations/configs/{config_id}",
                            json=update_data,
                            params=params,
                            catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                self.created_configs.remove(config_id)
                response.success()
            else:
                response.failure(f"Failed to update configuration: {response.text}")

    @task(1)
    def publish_configuration(self):
        """Publish a draft configuration."""
        if not self.created_configs:
            raise RescheduleTask()
            
        config_id = random.choice(self.created_configs)
        with self.client.post(f"/api/evaluations/configs/{config_id}/publish",
                             catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                self.created_configs.remove(config_id)
                response.success()
            elif response.status_code == 409:
                # Already published is fine
                response.success()
            else:
                response.failure(f"Failed to publish configuration: {response.text}")


class MetricValidationTasks(TaskSet):
    """Load tests for metric validation endpoints."""
    
    def on_start(self):
        """Initialize test data for metric validation."""
        self.available_metrics = []
        self.metric_categories = []
        
        # Get available metrics
        response = self.client.get("/api/evaluations/metrics")
        if response.status_code == 200:
            data = response.json()
            self.available_metrics = [m["name"] for m in data["metrics"]]
            self.metric_categories = data["categories"]

    @task(4)
    def list_metrics(self):
        """List available metrics with filters."""
        params = {}
        
        if random.random() < 0.4 and self.metric_categories:
            params["category"] = random.choice(self.metric_categories)
            
        if random.random() < 0.3:
            params["tags"] = random.choice(["accuracy", "semantic", "safety", "performance"])

        with self.client.get("/api/evaluations/metrics", 
                            params=params, 
                            catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to list metrics: {response.text}")

    @task(3)
    def get_metric_details(self):
        """Get details of a specific metric."""
        if not self.available_metrics:
            raise RescheduleTask()
            
        metric_name = random.choice(self.available_metrics)
        with self.client.get(f"/api/evaluations/metrics/{metric_name}",
                            catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to get metric details: {response.text}")

    @task(5)
    def validate_metric_configuration(self):
        """Validate individual metric configurations."""
        if not self.available_metrics:
            raise RescheduleTask()
            
        metric_name = random.choice(self.available_metrics)
        
        # Generate random parameters based on metric
        parameters = {}
        if metric_name == "semantic_similarity":
            parameters = {"threshold": random.uniform(0.1, 0.9)}
        elif metric_name == "exact_match":
            parameters = {"case_sensitive": random.choice([True, False])}
        elif metric_name == "rouge":
            parameters = {"rouge_type": random.choice(["rouge-1", "rouge-2", "rouge-l"])}

        config_data = {
            "metric_name": metric_name,
            "parameters": parameters
        }
        
        with self.client.post("/api/evaluations/metrics/validate",
                             json=config_data,
                             catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to validate metric configuration: {response.text}")

    @task(3)
    def validate_metrics_batch(self):
        """Validate multiple metrics configuration."""
        if not self.available_metrics:
            raise RescheduleTask()
            
        num_metrics = random.randint(1, 4)
        selected_metrics = random.sample(self.available_metrics, min(num_metrics, len(self.available_metrics)))
        
        metrics_config = {
            "metrics": [
                {
                    "metric_name": metric,
                    "parameters": {}
                }
                for metric in selected_metrics
            ]
        }
        
        with self.client.post("/api/evaluations/metrics/validate-batch",
                             json=metrics_config,
                             catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to validate metrics batch: {response.text}")

    @task(2)
    def preview_metric(self):
        """Preview metric with sample data."""
        if not self.available_metrics:
            raise RescheduleTask()
            
        metric_name = random.choice(self.available_metrics)
        
        # Generate sample data
        sample_data = []
        for i in range(random.randint(2, 5)):
            sample_data.append({
                "input": f"Sample input {i}",
                "expected_output": f"Expected output {i}",
                "actual_output": f"Actual output {i}"
            })
        
        preview_data = {
            "metric_name": metric_name,
            "parameters": {},
            "sample_data": sample_data
        }
        
        with self.client.post("/api/evaluations/metrics/preview",
                             json=preview_data,
                             catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to preview metric: {response.text}")


class TemplateTasks(TaskSet):
    """Load tests for template management endpoints."""
    
    def on_start(self):
        """Initialize test data for template tasks."""
        self.custom_templates = []

    @task(6)
    def list_templates(self):
        """List available templates with filters."""
        params = {}
        
        if random.random() < 0.3:
            params["category"] = random.choice(["qa", "classification", "summarization", "general"])
            
        if random.random() < 0.4:
            params["tags"] = random.choice(["chatbot", "sentiment", "qa", "nlp"])
            
        if random.random() < 0.2:
            params["include_custom"] = random.choice([True, False])

        with self.client.get("/api/evaluations/templates",
                            params=params,
                            catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to list templates: {response.text}")

    @task(3)
    def get_template_details(self):
        """Get details of a specific template."""
        # Get list of templates first
        response = self.client.get("/api/evaluations/templates")
        if response.status_code == 200:
            templates = response.json()
            if templates:
                template_name = random.choice(templates)["name"]
                
                with self.client.get(f"/api/evaluations/templates/{template_name}",
                                    catch_response=True) as response:
                    if response.status_code == 200:
                        response.success()
                    else:
                        response.failure(f"Failed to get template details: {response.text}")

    @task(4)
    def recommend_templates(self):
        """Get template recommendations."""
        descriptions = [
            "I need to evaluate a customer support chatbot that answers questions about products",
            "Evaluate sentiment analysis model for social media posts",
            "Test a question-answering system for educational content",
            "Evaluate text summarization quality for news articles",
            "Test classification accuracy for product categorization",
            "Evaluate conversational AI for booking appointments"
        ]
        
        use_cases = ["customer_support", "sentiment_analysis", "qa", "summarization", "classification", "conversation"]
        
        request_data = {
            "description": random.choice(descriptions),
            "use_case": random.choice(use_cases)
        }
        
        # Sometimes add sample data
        if random.random() < 0.4:
            request_data["sample_data"] = {
                "input": "Sample input for recommendation",
                "expected_output": "Expected result"
            }

        with self.client.post("/api/evaluations/templates/recommend",
                             json=request_data,
                             catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to get template recommendations: {response.text}")

    @task(1)
    def create_custom_template(self):
        """Create a custom template."""
        template_id = uuid.uuid4().hex[:8]
        template_data = {
            "name": f"load_test_template_{template_id}",
            "display_name": f"Load Test Template {template_id}",
            "description": f"A custom template created during load testing {template_id}",
            "use_cases": [random.choice(["testing", "evaluation", "qa", "classification"])],
            "metrics": ["exact_match"],  # Use simple metric to avoid validation issues
            "category": "custom",
            "tags": ["load-test", f"test-{random.randint(1, 100)}"]
        }
        
        with self.client.post("/api/evaluations/templates/custom",
                             json=template_data,
                             catch_response=True) as response:
            if response.status_code == 201:
                self.custom_templates.append(template_data["name"])
                response.success()
            elif response.status_code == 409:
                # Duplicate name is acceptable
                response.success()
            else:
                response.failure(f"Failed to create custom template: {response.text}")

    @task(2)
    def track_template_usage(self):
        """Track template usage."""
        # Get templates first
        response = self.client.get("/api/evaluations/templates")
        if response.status_code == 200:
            templates = response.json()
            if templates:
                template_name = random.choice(templates)["name"]
                
                params = {
                    "user": f"load_test_user_{random.randint(1, 50)}",
                    "project": f"load_test_project_{random.randint(1, 10)}"
                }
                
                with self.client.post(f"/api/evaluations/templates/{template_name}/track-usage",
                                     params=params,
                                     catch_response=True) as response:
                    if response.status_code == 200:
                        response.success()
                    else:
                        response.failure(f"Failed to track template usage: {response.text}")


class TaskExecutionTasks(TaskSet):
    """Load tests for task execution endpoints."""
    
    def on_start(self):
        """Initialize test data for task execution."""
        self.published_configs = []
        self.active_executions = []
        
        # Create some published configurations for execution
        self._create_published_config()

    def _create_published_config(self):
        """Create and publish a configuration for execution testing."""
        config_data = {
            "name": f"Execution Test Config {uuid.uuid4().hex[:8]}",
            "description": "Configuration for execution load testing",
            "task_type": "qa",
            "template_name": "qa",
            "task_config": {"endpoint_url": "https://api.example.com/chat"},
            "dataset_config": {"dataset_name": "test_dataset"},
            "metrics_config": {"metrics": [{"metric_name": "exact_match"}]}
        }
        
        # Create configuration
        response = self.client.post("/api/evaluations/configs", json=config_data)
        if response.status_code == 201:
            config_id = response.json()["id"]
            
            # Publish it
            publish_response = self.client.post(f"/api/evaluations/configs/{config_id}/publish")
            if publish_response.status_code == 200:
                self.published_configs.append(config_id)

    @task(1)
    def execute_configuration(self):
        """Execute a published configuration."""
        if not self.published_configs:
            self._create_published_config()
            
        if self.published_configs:
            config_id = random.choice(self.published_configs)
            
            execution_data = {
                "config_id": config_id,
                "task_name": f"Load Test Execution {uuid.uuid4().hex[:8]}",
                "priority": random.randint(0, 5),
                "project_id": f"load-test-project-{random.randint(1, 5)}"
            }
            
            with self.client.post("/api/evaluations/tasks/execute",
                                 json=execution_data,
                                 catch_response=True) as response:
                if response.status_code == 201:
                    execution_id = response.json()["id"]
                    self.active_executions.append(execution_id)
                    response.success()
                else:
                    response.failure(f"Failed to execute configuration: {response.text}")

    @task(3)
    def list_task_executions(self):
        """List task executions with filters."""
        params = {}
        
        if random.random() < 0.4:
            params["project_id"] = f"load-test-project-{random.randint(1, 5)}"
            
        if random.random() < 0.3:
            params["status_filter"] = random.choice(["queued", "running", "completed", "failed"])
            
        if random.random() < 0.5:
            params["active_only"] = random.choice([True, False])

        with self.client.get("/api/evaluations/tasks",
                            params=params,
                            catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to list task executions: {response.text}")

    @task(1)
    def get_task_execution_details(self):
        """Get details of a specific task execution."""
        if not self.active_executions:
            raise RescheduleTask()
            
        execution_id = random.choice(self.active_executions)
        with self.client.get(f"/api/evaluations/tasks/{execution_id}",
                            catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 404:
                self.active_executions.remove(execution_id)
                response.success()
            else:
                response.failure(f"Failed to get task execution details: {response.text}")


class LLMEvalUser(HttpUser):
    """Main user class for LLM-Eval load testing."""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    host = "http://localhost:8000"  # Default API host
    
    tasks = [
        EvaluationConfigurationTasks,
        MetricValidationTasks, 
        TemplateTasks,
        TaskExecutionTasks
    ]
    
    # Weight different task sets
    weight = 1


class EvaluationConfigurationUser(HttpUser):
    """User focused on evaluation configuration operations."""
    
    wait_time = between(0.5, 2)
    host = "http://localhost:8000"
    tasks = [EvaluationConfigurationTasks]
    weight = 3


class MetricValidationUser(HttpUser):
    """User focused on metric validation operations."""
    
    wait_time = between(0.5, 1.5)
    host = "http://localhost:8000"
    tasks = [MetricValidationTasks]
    weight = 2


class TemplateUser(HttpUser):
    """User focused on template management operations."""
    
    wait_time = between(1, 2)
    host = "http://localhost:8000"
    tasks = [TemplateTasks]
    weight = 2


class TaskExecutionUser(HttpUser):
    """User focused on task execution operations."""
    
    wait_time = between(2, 4)  # Longer wait for execution operations
    host = "http://localhost:8000"
    tasks = [TaskExecutionTasks]
    weight = 1


# Custom test scenarios for specific load patterns

class HighFrequencyReadsUser(HttpUser):
    """Simulate high-frequency read operations (dashboard-like usage)."""
    
    wait_time = between(0.1, 0.5)  # Very fast requests
    host = "http://localhost:8000"
    weight = 1
    
    @task(5)
    def list_configurations(self):
        """Frequently list configurations."""
        params = {"page_size": 10}
        self.client.get("/api/evaluations/configs", params=params)
    
    @task(3)
    def list_templates(self):
        """Frequently list templates."""
        self.client.get("/api/evaluations/templates")
        
    @task(3)
    def list_metrics(self):
        """Frequently list metrics."""
        self.client.get("/api/evaluations/metrics")
        
    @task(2)
    def list_executions(self):
        """Frequently list task executions."""
        self.client.get("/api/evaluations/tasks")


class BulkOperationsUser(HttpUser):
    """Simulate bulk operations and heavy data processing."""
    
    wait_time = between(2, 5)
    host = "http://localhost:8000"
    weight = 1
    
    @task(2)
    def create_many_configurations(self):
        """Create multiple configurations in sequence."""
        for i in range(random.randint(3, 8)):
            config_data = {
                "name": f"Bulk Config {i} {uuid.uuid4().hex[:6]}",
                "task_type": "qa",
                "template_name": "qa",
                "task_config": {"endpoint_url": "https://api.example.com"},
                "dataset_config": {"dataset_name": f"bulk_dataset_{i}"},
                "metrics_config": {"metrics": [{"metric_name": "exact_match"}]}
            }
            self.client.post("/api/evaluations/configs", json=config_data)
    
    @task(1)
    def batch_metric_validation(self):
        """Validate large batch of metrics."""
        metrics = []
        for i in range(random.randint(5, 15)):
            metrics.append({
                "metric_name": random.choice(["exact_match", "semantic_similarity", "rouge"]),
                "parameters": {}
            })
        
        config = {"metrics": metrics}
        self.client.post("/api/evaluations/metrics/validate-batch", json=config)


if __name__ == "__main__":
    # This allows running the load test directly
    import subprocess
    import sys
    
    print("Starting LLM-Eval Load Test")
    print("Make sure the API server is running on http://localhost:8000")
    print("\nRunning with default configuration...")
    print("Use 'locust -f locustfile.py' for custom configuration")
    
    # Run with reasonable defaults for testing
    subprocess.run([
        sys.executable, "-m", "locust",
        "-f", __file__,
        "--host", "http://localhost:8000",
        "--users", "10",
        "--spawn-rate", "2",
        "--run-time", "2m",
        "--headless"
    ])