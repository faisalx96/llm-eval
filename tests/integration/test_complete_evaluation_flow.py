"""End-to-end integration tests for complete evaluation setup flow.

This module tests the complete UI-driven evaluation workflow from initial setup
through execution, including dataset browsing, metric selection, task configuration,
template recommendations, and execution monitoring.
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

from llm_eval.api.main import app
from llm_eval.models.run_models import EvaluationConfig, TaskExecution


class TestCompleteEvaluationFlow:
    """Test the complete evaluation setup and execution flow."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_langfuse_datasets(self):
        """Mock Langfuse datasets for testing."""
        return [
            {
                "id": "dataset-1",
                "name": "customer_support_qa", 
                "description": "Q&A dataset for customer support scenarios",
                "created_at": "2024-01-15T10:00:00Z",
                "item_count": 1500,
                "last_used": "2024-01-20T15:30:00Z",
                "items_preview": [
                    {
                        "input": "How do I return a product?",
                        "expected_output": "You can return products within 30 days by contacting our support team or visiting our returns page.",
                        "metadata": {"category": "returns", "difficulty": "easy"}
                    },
                    {
                        "input": "What is your refund policy?", 
                        "expected_output": "We offer full refunds within 30 days of purchase for unused items in original condition.",
                        "metadata": {"category": "refunds", "difficulty": "medium"}
                    }
                ]
            },
            {
                "id": "dataset-2",
                "name": "product_classification",
                "description": "Product categorization dataset",
                "created_at": "2024-01-10T09:00:00Z",
                "item_count": 2800,
                "last_used": "2024-01-18T11:45:00Z",
                "items_preview": [
                    {
                        "input": "Wireless bluetooth headphones with noise cancellation",
                        "expected_output": "Electronics > Audio > Headphones",
                        "metadata": {"brand": "TechCorp", "price_range": "premium"}
                    }
                ]
            }
        ]

    def test_complete_ui_driven_evaluation_workflow(self, client, mock_langfuse_datasets):
        """Test complete end-to-end evaluation workflow through UI-driven APIs."""
        
        # PHASE 1: Dataset Discovery and Selection
        print("Phase 1: Dataset Discovery")
        
        # Mock dataset browsing (would normally connect to Langfuse)
        with patch('llm_eval.core.dataset.get_langfuse_datasets') as mock_datasets:
            mock_datasets.return_value = mock_langfuse_datasets
            
            # Browse available datasets
            datasets_response = client.get("/api/evaluations/datasets")
            assert datasets_response.status_code == 200
            datasets = datasets_response.json()
            
            assert len(datasets) == 2
            assert datasets[0]["name"] == "customer_support_qa"
            assert datasets[0]["item_count"] == 1500
            
            # Select customer support dataset
            selected_dataset = datasets[0]
            print(f"Selected dataset: {selected_dataset['name']}")

        # PHASE 2: Template Recommendation
        print("Phase 2: Template Recommendation")
        
        # Get template recommendations based on dataset and use case
        recommendation_request = {
            "description": "I want to evaluate a customer support chatbot that answers questions about returns, refunds, and product information. The bot should provide accurate and helpful responses to customer inquiries.",
            "sample_data": selected_dataset["items_preview"][0],
            "use_case": "customer_support",
            "dataset_name": selected_dataset["name"]
        }
        
        recommendations_response = client.post(
            "/api/evaluations/templates/recommend",
            json=recommendation_request
        )
        assert recommendations_response.status_code == 200
        recommendations = recommendations_response.json()
        
        assert len(recommendations) > 0
        # Should recommend Q&A template for this use case
        qa_recommendation = next((r for r in recommendations if "qa" in r["template_name"]), None)
        assert qa_recommendation is not None
        print(f"Recommended template: {qa_recommendation['template_name']}")

        # PHASE 3: Metric Selection and Configuration
        print("Phase 3: Metric Selection and Configuration")
        
        # Get available metrics
        metrics_response = client.get("/api/evaluations/metrics")
        assert metrics_response.status_code == 200
        metrics_data = metrics_response.json()
        
        available_metrics = metrics_data["metrics"]
        assert len(available_metrics) > 0
        
        # Select metrics suitable for Q&A evaluation
        selected_metrics = []
        for metric in available_metrics:
            if metric["name"] in ["exact_match", "semantic_similarity", "answer_relevance"]:
                selected_metrics.append({
                    "metric_name": metric["name"],
                    "parameters": metric.get("default_config", {})
                })
        
        assert len(selected_metrics) >= 1
        print(f"Selected {len(selected_metrics)} metrics")
        
        # Validate metrics configuration
        metrics_validation = {
            "metrics": selected_metrics
        }
        validation_response = client.post(
            "/api/evaluations/metrics/validate-batch",
            json=metrics_validation
        )
        assert validation_response.status_code == 200
        validation_result = validation_response.json()
        assert validation_result["is_valid"] is True
        print("Metrics validation: PASSED")

        # PHASE 4: Task Configuration Setup
        print("Phase 4: Task Configuration Setup")
        
        # Create comprehensive evaluation configuration
        config_data = {
            "name": f"Customer Support QA Evaluation - {uuid.uuid4().hex[:8]}",
            "description": "End-to-end evaluation of customer support Q&A system using UI-driven configuration",
            "task_type": qa_recommendation["template_name"],
            "template_name": qa_recommendation["template_name"],
            
            # Task configuration (API endpoint details)
            "task_config": {
                "endpoint_url": "https://api.example.com/chat/completions",
                "model": "gpt-3.5-turbo",
                "temperature": 0.3,
                "max_tokens": 200,
                "timeout": 30,
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer test-api-key"
                },
                "request_template": {
                    "model": "{model}",
                    "messages": [
                        {"role": "system", "content": "You are a helpful customer support assistant."},
                        {"role": "user", "content": "{input}"}
                    ],
                    "temperature": "{temperature}",
                    "max_tokens": "{max_tokens}"
                },
                "response_mapping": {
                    "output_path": "choices[0].message.content",
                    "error_path": "error.message"
                }
            },
            
            # Dataset configuration
            "dataset_config": {
                "dataset_name": selected_dataset["name"],
                "dataset_id": selected_dataset["id"],
                "filters": {
                    "category": ["returns", "refunds"],  # Focus on specific categories
                    "difficulty": ["easy", "medium"]     # Exclude difficult questions for now
                },
                "sample_size": 100,  # Limit for testing
                "randomize": True,
                "seed": 42
            },
            
            # Metrics configuration
            "metrics_config": {
                "metrics": selected_metrics,
                "evaluation_strategy": "parallel",
                "metric_weights": {
                    "exact_match": 0.3,
                    "semantic_similarity": 0.4,
                    "answer_relevance": 0.3
                }
            },
            
            # Execution configuration
            "execution_config": {
                "batch_size": 10,
                "max_concurrent": 3,
                "timeout_per_item": 30,
                "retry_failed": True,
                "max_retries": 2,
                "save_intermediate": True,
                "export_formats": ["json", "excel"],
                "real_time_monitoring": True
            },
            
            # Langfuse integration
            "langfuse_config": {
                "project_name": "customer-support-evaluation",
                "trace_all_requests": True,
                "tag_evaluations": True,
                "custom_tags": ["ui-driven", "customer-support", "qa-evaluation"]
            },
            
            "tags": ["ui-driven", "customer-support", "end-to-end-test"],
            "project_id": "e2e-test-project"
        }
        
        # Create evaluation configuration
        config_response = client.post("/api/evaluations/configs", json=config_data)
        assert config_response.status_code == 201
        config = config_response.json()
        
        assert config["name"] == config_data["name"]
        assert config["status"] == "draft"
        assert config["version"] == 1
        print(f"Created configuration: {config['id']}")

        # PHASE 5: Configuration Validation and Testing
        print("Phase 5: Configuration Validation")
        
        # Test configuration with preview data
        preview_request = {
            "metric_name": "exact_match",
            "parameters": {"case_sensitive": False},
            "sample_data": selected_dataset["items_preview"][:2]
        }
        
        preview_response = client.post(
            "/api/evaluations/metrics/preview",
            json=preview_request
        )
        assert preview_response.status_code == 200
        preview_result = preview_response.json()
        assert preview_result["is_valid"] is True
        assert len(preview_result["preview_results"]) == 2
        print("Configuration preview: PASSED")

        # PHASE 6: Configuration Publishing
        print("Phase 6: Configuration Publishing")
        
        # Publish configuration to make it executable
        publish_response = client.post(f"/api/evaluations/configs/{config['id']}/publish")
        assert publish_response.status_code == 200
        published_config = publish_response.json()
        
        assert published_config["status"] == "published"
        print("Configuration published: READY FOR EXECUTION")

        # PHASE 7: Task Execution
        print("Phase 7: Task Execution")
        
        with patch('llm_eval.core.task_engine.get_task_engine') as mock_get_engine:
            # Mock task engine for execution
            mock_engine = Mock()
            execution_id = f"exec-{uuid.uuid4().hex[:8]}"
            mock_engine.queue_task = AsyncMock(return_value=execution_id)
            mock_get_engine.return_value = mock_engine
            
            # Execute the configuration
            execution_request = {
                "config_id": config["id"],
                "task_name": f"E2E Customer Support Evaluation - {datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "priority": 1,
                "project_id": "e2e-test-project"
            }
            
            execution_response = client.post(
                "/api/evaluations/tasks/execute",
                json=execution_request
            )
            assert execution_response.status_code == 201
            execution = execution_response.json()
            
            assert execution["config_id"] == config["id"]
            assert execution["task_name"] == execution_request["task_name"]
            assert execution["status"] == "queued"
            print(f"Task execution started: {execution['id']}")

        # PHASE 8: Execution Monitoring
        print("Phase 8: Execution Monitoring")
        
        # List active executions
        executions_response = client.get("/api/evaluations/tasks?active_only=true")
        assert executions_response.status_code == 200
        executions_data = executions_response.json()
        
        # Should find our execution
        our_execution = next(
            (e for e in executions_data["executions"] if e["config_id"] == config["id"]), 
            None
        )
        assert our_execution is not None
        print(f"Found execution in active list: {our_execution['id']}")

        # PHASE 9: Results and Analysis (Simulated)
        print("Phase 9: Results Analysis")
        
        # In a real scenario, we would wait for execution completion and analyze results
        # For testing, we simulate successful completion
        
        # Get configuration usage statistics
        final_config_response = client.get(f"/api/evaluations/configs/{config['id']}")
        assert final_config_response.status_code == 200
        final_config = final_config_response.json()
        
        # Usage count should have increased
        assert final_config["usage_count"] >= 1
        assert final_config["last_used_at"] is not None
        print("Configuration usage tracked: SUCCESS")
        
        # Track template usage
        template_usage_response = client.post(
            f"/api/evaluations/templates/{qa_recommendation['template_name']}/track-usage",
            params={"user": "e2e_test_user", "project": "e2e-test-project"}
        )
        assert template_usage_response.status_code == 200
        print("Template usage tracked: SUCCESS")

        print("\n=== END-TO-END EVALUATION WORKFLOW COMPLETED SUCCESSFULLY ===")
        return {
            "dataset": selected_dataset,
            "template": qa_recommendation,
            "metrics": selected_metrics,
            "configuration": config,
            "execution": execution
        }

    def test_error_handling_in_evaluation_flow(self, client):
        """Test error handling throughout the evaluation workflow."""
        
        # Test invalid dataset selection
        print("Testing error handling...")
        
        # Invalid template recommendation (too short description)
        invalid_recommendation = {
            "description": "short"  # Too short
        }
        response = client.post("/api/evaluations/templates/recommend", json=invalid_recommendation)
        assert response.status_code == 422
        print("✓ Invalid template recommendation handled correctly")
        
        # Invalid metric configuration
        invalid_metrics = {
            "metrics": [{"metric_name": "non_existent_metric"}]
        }
        response = client.post("/api/evaluations/metrics/validate-batch", json=invalid_metrics)
        assert response.status_code == 200
        validation = response.json()
        assert validation["is_valid"] is False
        print("✓ Invalid metrics configuration detected")
        
        # Invalid evaluation configuration (missing required fields)
        invalid_config = {
            "name": "",  # Empty name
            "task_config": {},  # Empty task_config
            "dataset_config": {},  # Missing dataset_name
            "metrics_config": {}  # Missing metrics
        }
        response = client.post("/api/evaluations/configs", json=invalid_config)
        assert response.status_code == 422
        print("✓ Invalid configuration creation prevented")
        
        # Try to execute non-existent configuration
        invalid_execution = {
            "config_id": str(uuid.uuid4()),
            "task_name": "Invalid execution test"
        }
        response = client.post("/api/evaluations/tasks/execute", json=invalid_execution)
        assert response.status_code == 404
        print("✓ Non-existent configuration execution prevented")
        
        print("Error handling tests: ALL PASSED")

    @patch('llm_eval.core.task_engine.get_task_engine')
    def test_concurrent_evaluation_setup(self, mock_get_engine, client):
        """Test handling multiple concurrent evaluation setups."""
        
        print("Testing concurrent evaluation setup...")
        
        # Mock task engine
        mock_engine = Mock()
        mock_engine.queue_task = AsyncMock(side_effect=lambda **kwargs: f"exec-{uuid.uuid4().hex[:8]}")
        mock_get_engine.return_value = mock_engine
        
        # Create multiple configurations concurrently (simulated)
        configurations = []
        
        for i in range(5):
            config_data = {
                "name": f"Concurrent Test Config {i}",
                "description": f"Configuration for concurrent testing {i}",
                "task_type": "qa",
                "template_name": "qa",
                "task_config": {
                    "endpoint_url": f"https://api{i}.example.com/chat",
                    "model": "gpt-3.5-turbo"
                },
                "dataset_config": {
                    "dataset_name": f"concurrent_test_dataset_{i}",
                    "filters": {}
                },
                "metrics_config": {
                    "metrics": [{"metric_name": "exact_match", "parameters": {}}]
                },
                "project_id": f"concurrent-test-{i}"
            }
            
            # Create configuration
            config_response = client.post("/api/evaluations/configs", json=config_data)
            assert config_response.status_code == 201
            config = config_response.json()
            configurations.append(config)
            
            # Publish configuration
            publish_response = client.post(f"/api/evaluations/configs/{config['id']}/publish")
            assert publish_response.status_code == 200
        
        print(f"Created {len(configurations)} configurations")
        
        # Execute all configurations
        executions = []
        for i, config in enumerate(configurations):
            execution_request = {
                "config_id": config["id"],
                "task_name": f"Concurrent Execution {i}",
                "priority": i,  # Different priorities
                "project_id": f"concurrent-test-{i}"
            }
            
            execution_response = client.post("/api/evaluations/tasks/execute", json=execution_request)
            assert execution_response.status_code == 201
            executions.append(execution_response.json())
        
        print(f"Queued {len(executions)} executions")
        
        # Verify all executions are tracked
        all_executions_response = client.get("/api/evaluations/tasks")
        assert all_executions_response.status_code == 200
        all_executions = all_executions_response.json()
        
        # Should have at least our executions
        assert all_executions["total_count"] >= len(executions)
        assert all_executions["active_count"] >= len(executions)
        
        print("Concurrent evaluation setup: SUCCESS")

    def test_configuration_versioning_workflow(self, client):
        """Test configuration versioning in the evaluation workflow."""
        
        print("Testing configuration versioning workflow...")
        
        # Create initial configuration
        initial_config = {
            "name": "Versioning Test Configuration",
            "description": "Initial version for versioning test",
            "task_type": "qa",
            "template_name": "qa",
            "task_config": {
                "endpoint_url": "https://api.example.com/v1/chat",
                "model": "gpt-3.5-turbo",
                "temperature": 0.7
            },
            "dataset_config": {
                "dataset_name": "versioning_test_dataset",
                "filters": {"category": "test"}
            },
            "metrics_config": {
                "metrics": [{"metric_name": "exact_match", "parameters": {}}]
            }
        }
        
        # Create v1
        response = client.post("/api/evaluations/configs", json=initial_config)
        assert response.status_code == 201
        v1_config = response.json()
        assert v1_config["version"] == 1
        
        config_id = v1_config["id"]
        config_key = v1_config["config_key"]
        
        # Update to create v2
        v2_updates = {
            "description": "Updated version with improved settings",
            "task_config": {
                "endpoint_url": "https://api.example.com/v2/chat",  # Updated API version
                "model": "gpt-4",  # Better model
                "temperature": 0.3  # Lower temperature
            },
            "metrics_config": {
                "metrics": [
                    {"metric_name": "exact_match", "parameters": {}},
                    {"metric_name": "semantic_similarity", "parameters": {"threshold": 0.8}}  # Added metric
                ]
            }
        }
        
        response = client.put(
            f"/api/evaluations/configs/{config_id}?create_new_version=true",
            json=v2_updates
        )
        assert response.status_code == 200
        v2_config = response.json()
        
        assert v2_config["version"] == 2
        assert v2_config["parent_config_id"] == config_id
        assert v2_config["is_current_version"] is True
        assert len(v2_config["metrics_config"]["metrics"]) == 2
        
        # Get all versions
        versions_response = client.get(f"/api/evaluations/configs/{config_key}/versions")
        assert versions_response.status_code == 200
        versions = versions_response.json()
        
        assert len(versions) == 2
        assert versions[0]["version"] == 2  # Latest first
        assert versions[1]["version"] == 1
        assert versions[0]["is_current_version"] is True
        assert versions[1]["is_current_version"] is False
        
        print("Configuration versioning: SUCCESS")

    def test_evaluation_workflow_with_real_metrics(self, client):
        """Test evaluation workflow with realistic metric configurations."""
        
        print("Testing workflow with realistic metrics...")
        
        # Get actual available metrics
        metrics_response = client.get("/api/evaluations/metrics")
        assert metrics_response.status_code == 200
        available_metrics = {m["name"]: m for m in metrics_response.json()["metrics"]}
        
        # Configure realistic metrics for Q&A evaluation
        realistic_metrics = []
        
        if "exact_match" in available_metrics:
            realistic_metrics.append({
                "metric_name": "exact_match",
                "parameters": {
                    "case_sensitive": False,
                    "strip_whitespace": True
                }
            })
        
        if "semantic_similarity" in available_metrics:
            realistic_metrics.append({
                "metric_name": "semantic_similarity", 
                "parameters": {
                    "threshold": 0.75,
                    "model": "all-MiniLM-L6-v2"
                }
            })
        
        if "bleu" in available_metrics:
            realistic_metrics.append({
                "metric_name": "bleu",
                "parameters": {
                    "smoothing": True,
                    "max_gram": 4
                }
            })
        
        assert len(realistic_metrics) > 0
        
        # Validate realistic metrics configuration
        metrics_config = {"metrics": realistic_metrics}
        validation_response = client.post("/api/evaluations/metrics/validate-batch", json=metrics_config)
        assert validation_response.status_code == 200
        validation = validation_response.json()
        assert validation["is_valid"] is True
        
        # Test metric preview with realistic data
        if "exact_match" in available_metrics:
            preview_data = {
                "metric_name": "exact_match",
                "parameters": {"case_sensitive": False},
                "sample_data": [
                    {
                        "input": "What is the capital of France?",
                        "expected_output": "Paris",
                        "actual_output": "paris"  # Different case
                    },
                    {
                        "input": "What is 2 + 2?",
                        "expected_output": "4",
                        "actual_output": "4"
                    },
                    {
                        "input": "Name a primary color",
                        "expected_output": "red",
                        "actual_output": "blue"  # Different answer
                    }
                ]
            }
            
            preview_response = client.post("/api/evaluations/metrics/preview", json=preview_data)
            assert preview_response.status_code == 200
            preview_result = preview_response.json()
            
            assert preview_result["is_valid"] is True
            assert len(preview_result["preview_results"]) == 3
            assert preview_result["summary_stats"] is not None
            
            # Check expected scores (case insensitive should match paris/Paris)
            results = preview_result["preview_results"]
            assert results[0]["score"] == 1.0  # Case insensitive match
            assert results[1]["score"] == 1.0  # Exact match
            assert results[2]["score"] == 0.0  # Different answers
            
        print("Realistic metrics testing: SUCCESS")

    def test_template_recommendation_accuracy(self, client):
        """Test template recommendation accuracy for different use cases."""
        
        print("Testing template recommendation accuracy...")
        
        test_cases = [
            {
                "description": "I need to evaluate a question-answering system that provides factual answers to user questions about our product documentation. The system should be accurate and comprehensive.",
                "expected_template_types": ["qa"],
                "use_case": "documentation"
            },
            {
                "description": "Evaluate sentiment analysis model for social media posts, classifying them as positive, negative, or neutral based on user emotions and opinions.",
                "expected_template_types": ["classification", "sentiment"],
                "use_case": "sentiment_analysis"
            },
            {
                "description": "Test a text summarization system that creates concise summaries of long research articles while preserving key information and findings.",
                "expected_template_types": ["summarization"],
                "use_case": "research"
            },
            {
                "description": "Evaluate a conversational AI chatbot for customer service that handles multiple conversation turns and maintains context throughout the interaction.",
                "expected_template_types": ["conversation", "qa", "chatbot"],
                "use_case": "customer_service"
            }
        ]
        
        for i, test_case in enumerate(test_cases):
            print(f"Testing case {i+1}: {test_case['use_case']}")
            
            recommendation_request = {
                "description": test_case["description"],
                "use_case": test_case["use_case"]
            }
            
            response = client.post("/api/evaluations/templates/recommend", json=recommendation_request)
            assert response.status_code == 200
            recommendations = response.json()
            
            assert len(recommendations) > 0
            assert len(recommendations) <= 5  # Should limit recommendations
            
            # Check if any recommended template matches expected types
            template_names = [r["template_name"].lower() for r in recommendations]
            
            match_found = False
            for expected_type in test_case["expected_template_types"]:
                if any(expected_type in template_name for template_name in template_names):
                    match_found = True
                    break
            
            assert match_found, f"No matching template found for {test_case['use_case']}"
            
            # Check recommendation quality
            top_recommendation = recommendations[0]
            assert top_recommendation["confidence"] > 0.3  # Reasonable confidence
            assert len(top_recommendation["metrics"]) > 0
            assert len(top_recommendation["reason"]) > 10  # Meaningful explanation
            
        print("Template recommendation accuracy: SUCCESS")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])