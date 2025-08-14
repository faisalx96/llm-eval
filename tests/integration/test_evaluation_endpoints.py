"""Integration tests for evaluation configuration API endpoints.

Tests the complete evaluation configuration API including CRUD operations,
task execution lifecycle, metric validation, and template recommendations.
"""

import asyncio
import json
import pytest
import uuid
from datetime import datetime, timezone
from typing import Dict, Any
from unittest.mock import AsyncMock, Mock, patch

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from llm_eval.api.main import app
from llm_eval.api.endpoints.evaluations import router
from llm_eval.models.run_models import EvaluationConfig, TaskExecution
from llm_eval.storage.database import get_database_manager
from llm_eval.templates.registry import TEMPLATE_REGISTRY
from llm_eval.metrics.configuration import get_metric_registry


class TestEvaluationConfigurationAPI:
    """Test evaluation configuration CRUD operations."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def sample_config_data(self):
        """Sample configuration data for testing."""
        return {
            "name": "Test QA Configuration",
            "description": "A test configuration for Q&A evaluation",
            "task_type": "qa",
            "template_name": "qa",
            "task_config": {
                "endpoint_url": "https://api.example.com/chat",
                "model": "gpt-3.5-turbo",
                "temperature": 0.7
            },
            "dataset_config": {
                "dataset_name": "test_qa_dataset",
                "filters": {"category": "customer_support"}
            },
            "metrics_config": {
                "metrics": [
                    {"metric_name": "exact_match", "parameters": {}},
                    {"metric_name": "semantic_similarity", "parameters": {"threshold": 0.8}}
                ]
            },
            "execution_config": {
                "batch_size": 10,
                "max_concurrent": 5,
                "timeout": 30
            },
            "tags": ["test", "qa", "customer_support"],
            "project_id": "test-project"
        }

    def test_create_configuration_success(self, client, sample_config_data):
        """Test successful configuration creation."""
        response = client.post("/api/evaluations/configs", json=sample_config_data)
        
        assert response.status_code == 201
        data = response.json()
        
        assert data["name"] == sample_config_data["name"]
        assert data["description"] == sample_config_data["description"]
        assert data["task_type"] == sample_config_data["task_type"]
        assert data["template_name"] == sample_config_data["template_name"]
        assert data["status"] == "draft"
        assert data["version"] == 1
        assert data["is_current_version"] is True
        assert data["usage_count"] == 0
        assert "id" in data
        assert "config_key" in data
        assert "created_at" in data

    def test_create_configuration_validation_error(self, client):
        """Test configuration creation with validation errors."""
        invalid_data = {
            "name": "",  # Empty name should fail
            "task_config": {},  # Empty task_config should fail
            "dataset_config": {},  # Missing dataset_name should fail
            "metrics_config": {}  # Missing metrics should fail
        }
        
        response = client.post("/api/evaluations/configs", json=invalid_data)
        assert response.status_code == 422

    def test_create_configuration_duplicate_key(self, client, sample_config_data):
        """Test configuration creation with duplicate config_key."""
        # Create first configuration
        sample_config_data["config_key"] = "test-unique-key"
        response1 = client.post("/api/evaluations/configs", json=sample_config_data)
        assert response1.status_code == 201

        # Try to create another with same key
        duplicate_data = sample_config_data.copy()
        duplicate_data["name"] = "Different Name"
        response2 = client.post("/api/evaluations/configs", json=duplicate_data)
        assert response2.status_code == 409
        assert "already exists" in response2.json()["detail"]

    def test_list_configurations_empty(self, client):
        """Test listing configurations when none exist."""
        response = client.get("/api/evaluations/configs")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["configurations"] == []
        assert data["total_count"] == 0
        assert data["filtered_count"] == 0
        assert data["page"] == 1
        assert data["has_more"] is False

    def test_list_configurations_with_data(self, client, sample_config_data):
        """Test listing configurations with existing data."""
        # Create test configurations
        config1 = sample_config_data.copy()
        config1["name"] = "Config 1"
        response1 = client.post("/api/evaluations/configs", json=config1)
        assert response1.status_code == 201

        config2 = sample_config_data.copy()
        config2["name"] = "Config 2"
        config2["task_type"] = "classification"
        response2 = client.post("/api/evaluations/configs", json=config2)
        assert response2.status_code == 201

        # List all configurations
        response = client.get("/api/evaluations/configs")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["configurations"]) == 2
        assert data["total_count"] == 2
        assert data["filtered_count"] == 2

    def test_list_configurations_with_filters(self, client, sample_config_data):
        """Test listing configurations with filters."""
        # Create configurations with different properties
        config1 = sample_config_data.copy()
        config1["name"] = "QA Config"
        config1["task_type"] = "qa"
        response1 = client.post("/api/evaluations/configs", json=config1)
        assert response1.status_code == 201

        config2 = sample_config_data.copy()
        config2["name"] = "Classification Config"
        config2["task_type"] = "classification"
        response2 = client.post("/api/evaluations/configs", json=config2)
        assert response2.status_code == 201

        # Filter by task type
        response = client.get("/api/evaluations/configs?task_type_filter=qa")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["configurations"]) == 1
        assert data["configurations"][0]["task_type"] == "qa"

    def test_list_configurations_with_search(self, client, sample_config_data):
        """Test listing configurations with search."""
        config1 = sample_config_data.copy()
        config1["name"] = "Customer Support QA"
        config1["description"] = "For customer support evaluation"
        response1 = client.post("/api/evaluations/configs", json=config1)
        assert response1.status_code == 201

        config2 = sample_config_data.copy()
        config2["name"] = "Product Classification"
        config2["description"] = "For product categorization"
        response2 = client.post("/api/evaluations/configs", json=config2)
        assert response2.status_code == 201

        # Search by name
        response = client.get("/api/evaluations/configs?search=customer")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["configurations"]) == 1
        assert "Customer Support" in data["configurations"][0]["name"]

    def test_list_configurations_pagination(self, client, sample_config_data):
        """Test configuration list pagination."""
        # Create multiple configurations
        for i in range(5):
            config = sample_config_data.copy()
            config["name"] = f"Config {i}"
            response = client.post("/api/evaluations/configs", json=config)
            assert response.status_code == 201

        # Test pagination
        response = client.get("/api/evaluations/configs?page=1&page_size=3")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["configurations"]) == 3
        assert data["page"] == 1
        assert data["page_size"] == 3
        assert data["has_more"] is True

        # Test second page
        response = client.get("/api/evaluations/configs?page=2&page_size=3")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["configurations"]) == 2
        assert data["has_more"] is False

    def test_get_configuration_by_id(self, client, sample_config_data):
        """Test getting a configuration by ID."""
        # Create configuration
        response = client.post("/api/evaluations/configs", json=sample_config_data)
        assert response.status_code == 201
        
        config_id = response.json()["id"]

        # Get configuration by ID
        response = client.get(f"/api/evaluations/configs/{config_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == config_id
        assert data["name"] == sample_config_data["name"]

    def test_get_configuration_not_found(self, client):
        """Test getting non-existent configuration."""
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/evaluations/configs/{fake_id}")
        assert response.status_code == 404

    def test_update_configuration_in_place(self, client, sample_config_data):
        """Test updating a configuration in place."""
        # Create configuration
        response = client.post("/api/evaluations/configs", json=sample_config_data)
        assert response.status_code == 201
        
        config_id = response.json()["id"]
        original_version = response.json()["version"]

        # Update configuration
        update_data = {
            "name": "Updated Configuration Name",
            "description": "Updated description",
            "tags": ["updated", "test"]
        }
        
        response = client.put(f"/api/evaluations/configs/{config_id}", json=update_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == update_data["name"]
        assert data["description"] == update_data["description"]
        assert data["tags"] == update_data["tags"]
        assert data["version"] == original_version  # Same version for in-place update

    def test_update_configuration_create_version(self, client, sample_config_data):
        """Test updating a configuration by creating new version."""
        # Create configuration
        response = client.post("/api/evaluations/configs", json=sample_config_data)
        assert response.status_code == 201
        
        config_id = response.json()["id"]
        original_version = response.json()["version"]

        # Update with new version
        update_data = {
            "name": "Updated Configuration Name",
            "task_config": {
                "endpoint_url": "https://api.new-example.com/chat",
                "model": "gpt-4",
                "temperature": 0.5
            }
        }
        
        response = client.put(
            f"/api/evaluations/configs/{config_id}?create_new_version=true", 
            json=update_data
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == update_data["name"]
        assert data["version"] == original_version + 1
        assert data["parent_config_id"] == config_id
        assert data["is_current_version"] is True

    def test_delete_configuration(self, client, sample_config_data):
        """Test deleting a configuration."""
        # Create configuration
        response = client.post("/api/evaluations/configs", json=sample_config_data)
        assert response.status_code == 201
        
        config_id = response.json()["id"]

        # Delete configuration
        response = client.delete(f"/api/evaluations/configs/{config_id}")
        assert response.status_code == 200

        # Verify deletion
        response = client.get(f"/api/evaluations/configs/{config_id}")
        assert response.status_code == 404

    def test_publish_configuration(self, client, sample_config_data):
        """Test publishing a draft configuration."""
        # Create configuration (defaults to draft)
        response = client.post("/api/evaluations/configs", json=sample_config_data)
        assert response.status_code == 201
        
        config_id = response.json()["id"]
        assert response.json()["status"] == "draft"

        # Publish configuration
        response = client.post(f"/api/evaluations/configs/{config_id}/publish")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "published"

    def test_duplicate_configuration(self, client, sample_config_data):
        """Test duplicating a configuration."""
        # Create configuration
        response = client.post("/api/evaluations/configs", json=sample_config_data)
        assert response.status_code == 201
        
        config_id = response.json()["id"]

        # Duplicate configuration
        response = client.post(f"/api/evaluations/configs/{config_id}/duplicate")
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == f"{sample_config_data['name']} (Copy)"
        assert data["id"] != config_id
        assert data["config_key"] != response.json()["config_key"]

    def test_get_configuration_versions(self, client, sample_config_data):
        """Test getting all versions of a configuration."""
        # Create configuration
        response = client.post("/api/evaluations/configs", json=sample_config_data)
        assert response.status_code == 201
        
        config_id = response.json()["id"]
        config_key = response.json()["config_key"]

        # Create new version
        update_data = {"name": "Updated Name"}
        response = client.put(
            f"/api/evaluations/configs/{config_id}?create_new_version=true", 
            json=update_data
        )
        assert response.status_code == 200

        # Get all versions
        response = client.get(f"/api/evaluations/configs/{config_key}/versions")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data) == 2  # Original + new version
        assert data[0]["version"] > data[1]["version"]  # Sorted by version desc


class TestTaskExecutionAPI:
    """Test task execution lifecycle endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def published_config_data(self, client):
        """Create a published configuration for testing execution."""
        config_data = {
            "name": "Published Test Config",
            "description": "Ready for execution",
            "task_type": "qa",
            "template_name": "qa",
            "task_config": {"endpoint_url": "https://api.example.com/chat"},
            "dataset_config": {"dataset_name": "test_dataset"},
            "metrics_config": {"metrics": [{"metric_name": "exact_match"}]},
        }
        
        # Create and publish configuration
        response = client.post("/api/evaluations/configs", json=config_data)
        assert response.status_code == 201
        
        config_id = response.json()["id"]
        
        # Publish it
        response = client.post(f"/api/evaluations/configs/{config_id}/publish")
        assert response.status_code == 200
        
        return config_id

    @patch('llm_eval.core.task_engine.get_task_engine')
    def test_execute_configuration(self, mock_get_engine, client, published_config_data):
        """Test executing a published configuration."""
        # Mock task engine
        mock_engine = Mock()
        mock_engine.queue_task = AsyncMock(return_value="exec-123")
        mock_get_engine.return_value = mock_engine

        execution_data = {
            "config_id": published_config_data,
            "task_name": "Test Execution",
            "priority": 1,
            "project_id": "test-project"
        }

        response = client.post("/api/evaluations/tasks/execute", json=execution_data)
        assert response.status_code == 201
        
        data = response.json()
        assert data["config_id"] == published_config_data
        assert data["task_name"] == execution_data["task_name"]
        assert data["priority"] == execution_data["priority"]
        assert data["status"] == "queued"

    def test_execute_draft_configuration_error(self, client):
        """Test executing a draft configuration should fail."""
        # Create draft configuration
        config_data = {
            "name": "Draft Config",
            "task_type": "qa",
            "task_config": {"endpoint_url": "https://api.example.com"},
            "dataset_config": {"dataset_name": "test"},
            "metrics_config": {"metrics": [{"metric_name": "exact_match"}]},
        }
        
        response = client.post("/api/evaluations/configs", json=config_data)
        assert response.status_code == 201
        config_id = response.json()["id"]

        execution_data = {
            "config_id": config_id,
            "task_name": "Test Execution",
        }

        response = client.post("/api/evaluations/tasks/execute", json=execution_data)
        assert response.status_code == 400
        assert "Only published configurations" in response.json()["detail"]

    def test_list_task_executions_empty(self, client):
        """Test listing task executions when none exist."""
        response = client.get("/api/evaluations/tasks")
        assert response.status_code == 200
        
        data = response.json()
        assert data["executions"] == []
        assert data["total_count"] == 0
        assert data["active_count"] == 0

    @patch('llm_eval.core.task_engine.get_task_engine')
    def test_pause_task_execution(self, mock_get_engine, client, published_config_data):
        """Test pausing a running task execution."""
        # Mock task engine
        mock_engine = Mock()
        mock_engine.queue_task = AsyncMock(return_value="exec-123")
        mock_engine.pause_task = AsyncMock(return_value=True)
        mock_get_engine.return_value = mock_engine

        # Create execution
        execution_data = {
            "config_id": published_config_data,
            "task_name": "Test Execution"
        }
        response = client.post("/api/evaluations/tasks/execute", json=execution_data)
        assert response.status_code == 201
        
        execution_id = response.json()["id"]

        # Mock the execution as running
        with patch('llm_eval.api.endpoints.evaluations.get_db') as mock_get_db:
            mock_session = Mock()
            mock_execution = Mock()
            mock_execution.status = "running"
            mock_session.query.return_value.filter.return_value.first.return_value = mock_execution
            mock_get_db.return_value.__enter__.return_value = mock_session

            response = client.post(f"/api/evaluations/tasks/{execution_id}/pause")
            assert response.status_code == 200
            assert "paused successfully" in response.json()["message"]

    @patch('llm_eval.core.task_engine.get_task_engine')
    def test_resume_task_execution(self, mock_get_engine, client, published_config_data):
        """Test resuming a paused task execution."""
        mock_engine = Mock()
        mock_engine.resume_task = AsyncMock(return_value=True)
        mock_get_engine.return_value = mock_engine

        execution_id = "test-execution-id"

        # Mock the execution as paused
        with patch('llm_eval.api.endpoints.evaluations.get_db') as mock_get_db:
            mock_session = Mock()
            mock_execution = Mock()
            mock_execution.status = "paused"
            mock_session.query.return_value.filter.return_value.first.return_value = mock_execution
            mock_get_db.return_value.__enter__.return_value = mock_session

            response = client.post(f"/api/evaluations/tasks/{execution_id}/resume")
            assert response.status_code == 200
            assert "resumed successfully" in response.json()["message"]

    @patch('llm_eval.core.task_engine.get_task_engine')
    def test_cancel_task_execution(self, mock_get_engine, client):
        """Test cancelling a task execution."""
        mock_engine = Mock()
        mock_engine.cancel_task = AsyncMock(return_value=True)
        mock_get_engine.return_value = mock_engine

        execution_id = "test-execution-id"

        # Mock the execution as running
        with patch('llm_eval.api.endpoints.evaluations.get_db') as mock_get_db:
            mock_session = Mock()
            mock_execution = Mock()
            mock_execution.status = "running"
            mock_session.query.return_value.filter.return_value.first.return_value = mock_execution
            mock_get_db.return_value.__enter__.return_value = mock_session

            response = client.post(f"/api/evaluations/tasks/{execution_id}/cancel")
            assert response.status_code == 200
            assert "cancelled successfully" in response.json()["message"]


class TestMetricConfigurationAPI:
    """Test metric configuration and validation endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_list_available_metrics(self, client):
        """Test listing all available metrics."""
        response = client.get("/api/evaluations/metrics")
        assert response.status_code == 200
        
        data = response.json()
        assert "metrics" in data
        assert "total_count" in data
        assert "categories" in data
        assert "available_tags" in data
        assert data["total_count"] > 0

    def test_list_metrics_with_category_filter(self, client):
        """Test listing metrics with category filter."""
        response = client.get("/api/evaluations/metrics?category=accuracy")
        assert response.status_code == 200
        
        data = response.json()
        for metric in data["metrics"]:
            assert metric["category"] == "accuracy"

    def test_get_metric_details(self, client):
        """Test getting detailed information about a specific metric."""
        response = client.get("/api/evaluations/metrics/exact_match")
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == "exact_match"
        assert "display_name" in data
        assert "description" in data
        assert "parameters" in data
        assert "default_config" in data

    def test_get_metric_not_found(self, client):
        """Test getting non-existent metric."""
        response = client.get("/api/evaluations/metrics/non_existent_metric")
        assert response.status_code == 404

    def test_validate_metric_configuration_valid(self, client):
        """Test validating a valid metric configuration."""
        config_data = {
            "metric_name": "exact_match",
            "parameters": {
                "case_sensitive": False
            }
        }
        
        response = client.post("/api/evaluations/metrics/validate", json=config_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["is_valid"] is True
        assert data["errors"] == []
        assert data["metric_name"] == "exact_match"

    def test_validate_metric_configuration_invalid(self, client):
        """Test validating an invalid metric configuration."""
        config_data = {
            "metric_name": "semantic_similarity",
            "parameters": {
                "threshold": 1.5  # Invalid threshold > 1.0
            }
        }
        
        response = client.post("/api/evaluations/metrics/validate", json=config_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["is_valid"] is False
        assert len(data["errors"]) > 0

    def test_validate_metrics_configuration_batch(self, client):
        """Test validating a complete metrics configuration."""
        metrics_config = {
            "metrics": [
                {
                    "metric_name": "exact_match",
                    "parameters": {"case_sensitive": False}
                },
                {
                    "metric_name": "semantic_similarity", 
                    "parameters": {"threshold": 0.8}
                }
            ]
        }
        
        response = client.post("/api/evaluations/metrics/validate-batch", json=metrics_config)
        assert response.status_code == 200
        
        data = response.json()
        assert data["is_valid"] is True
        assert data["errors"] == []
        assert data["metrics_count"] == 2

    def test_preview_metric(self, client):
        """Test previewing a metric with sample data."""
        preview_data = {
            "metric_name": "exact_match",
            "parameters": {"case_sensitive": False},
            "sample_data": [
                {
                    "input": "What is the capital of France?",
                    "expected_output": "Paris",
                    "actual_output": "paris"
                },
                {
                    "input": "What is 2+2?",
                    "expected_output": "4",
                    "actual_output": "4"
                }
            ]
        }
        
        response = client.post("/api/evaluations/metrics/preview", json=preview_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["is_valid"] is True
        assert data["errors"] == []
        assert len(data["preview_results"]) == 2
        assert data["summary_stats"] is not None
        assert "mean" in data["summary_stats"]


class TestTemplateRecommendationAPI:
    """Test template recommendation endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_recommend_evaluation_template(self, client):
        """Test getting template recommendations."""
        recommendation_data = {
            "description": "I want to evaluate a chatbot that answers customer support questions. The bot should provide accurate and helpful responses to user inquiries about our products and services.",
            "sample_data": {
                "input": "How do I return a product?",
                "expected_output": "You can return products within 30 days by contacting customer service."
            },
            "use_case": "customer_support"
        }
        
        response = client.post("/api/evaluations/recommend-template", json=recommendation_data)
        assert response.status_code == 200
        
        data = response.json()
        assert len(data) > 0
        assert len(data) <= 5  # Should limit to top 5
        
        for recommendation in data:
            assert "template_name" in recommendation
            assert "confidence" in recommendation
            assert "name" in recommendation
            assert "description" in recommendation
            assert "metrics" in recommendation
            assert "reason" in recommendation
            assert 0 <= recommendation["confidence"] <= 1


class TestEndToEndEvaluationWorkflow:
    """Test complete end-to-end evaluation workflow."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @patch('llm_eval.core.task_engine.get_task_engine')
    def test_complete_evaluation_workflow(self, mock_get_engine, client):
        """Test complete workflow from configuration to execution."""
        # Mock task engine
        mock_engine = Mock()
        mock_engine.queue_task = AsyncMock(return_value="exec-123")
        mock_get_engine.return_value = mock_engine

        # Step 1: Get template recommendations
        recommendation_data = {
            "description": "Evaluate a Q&A system for customer support",
            "use_case": "customer_support"
        }
        
        response = client.post("/api/evaluations/recommend-template", json=recommendation_data)
        assert response.status_code == 200
        recommendations = response.json()
        assert len(recommendations) > 0

        # Step 2: Create configuration based on recommendation
        template = recommendations[0]
        config_data = {
            "name": "Customer Support QA Evaluation",
            "description": "Evaluate customer support Q&A responses",
            "task_type": template["template_name"],
            "template_name": template["template_name"],
            "task_config": {
                "endpoint_url": "https://api.example.com/chat",
                "model": "gpt-3.5-turbo"
            },
            "dataset_config": {
                "dataset_name": "customer_support_qa",
                "filters": {}
            },
            "metrics_config": {
                "metrics": [
                    {"metric_name": metric, "parameters": {}}
                    for metric in template["metrics"][:2]  # Use first 2 metrics
                ]
            }
        }
        
        response = client.post("/api/evaluations/configs", json=config_data)
        assert response.status_code == 201
        config = response.json()

        # Step 3: Validate metrics configuration
        metrics_validation = {
            "metrics": config_data["metrics_config"]["metrics"]
        }
        
        response = client.post("/api/evaluations/metrics/validate-batch", json=metrics_validation)
        assert response.status_code == 200
        validation = response.json()
        assert validation["is_valid"] is True

        # Step 4: Publish configuration
        response = client.post(f"/api/evaluations/configs/{config['id']}/publish")
        assert response.status_code == 200

        # Step 5: Execute configuration
        execution_data = {
            "config_id": config["id"],
            "task_name": "Test Customer Support Evaluation",
            "priority": 1
        }
        
        response = client.post("/api/evaluations/tasks/execute", json=execution_data)
        assert response.status_code == 201
        execution = response.json()

        # Step 6: Check execution status
        response = client.get(f"/api/evaluations/tasks/{execution['id']}")
        assert response.status_code == 200
        
        # Verify complete workflow
        assert execution["config_id"] == config["id"]
        assert execution["task_name"] == execution_data["task_name"]
        assert execution["status"] == "queued"

    def test_error_handling_workflow(self, client):
        """Test error handling in various workflow scenarios."""
        # Test invalid template name
        config_data = {
            "name": "Invalid Template Test",
            "task_type": "invalid_type",
            "template_name": "non_existent_template",
            "task_config": {"endpoint": "test"},
            "dataset_config": {"dataset_name": "test"},
            "metrics_config": {"metrics": [{"metric_name": "exact_match"}]}
        }
        
        response = client.post("/api/evaluations/configs", json=config_data)
        assert response.status_code == 422  # Validation error

        # Test executing non-existent configuration
        execution_data = {
            "config_id": str(uuid.uuid4()),
            "task_name": "Test Execution"
        }
        
        response = client.post("/api/evaluations/tasks/execute", json=execution_data)
        assert response.status_code == 404

        # Test invalid metric configuration
        invalid_metrics = {
            "metrics": [
                {"metric_name": "non_existent_metric", "parameters": {}}
            ]
        }
        
        response = client.post("/api/evaluations/metrics/validate-batch", json=invalid_metrics)
        assert response.status_code == 200
        validation = response.json()
        assert validation["is_valid"] is False
        assert len(validation["errors"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])