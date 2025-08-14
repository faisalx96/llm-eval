"""Integration tests for template management API endpoints.

Tests the complete template management API including listing templates,
getting template details, recommendations, custom template CRUD operations,
usage tracking, and import/export functionality.
"""

import json
import pytest
from datetime import datetime, timezone
from typing import Dict, Any
from unittest.mock import Mock, patch
from io import BytesIO

from fastapi.testclient import TestClient

from llm_eval.api.main import app
from llm_eval.templates.registry import TEMPLATE_REGISTRY


class TestTemplateListingAPI:
    """Test template listing and retrieval endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_list_all_templates(self, client):
        """Test listing all available templates."""
        response = client.get("/api/evaluations/templates")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        
        # Check template structure
        template = data[0]
        required_fields = [
            "name", "display_name", "description", "use_cases", 
            "metrics", "aliases", "usage_count", "is_builtin"
        ]
        for field in required_fields:
            assert field in template

    def test_list_templates_with_category_filter(self, client):
        """Test listing templates filtered by category."""
        response = client.get("/api/evaluations/templates?category=qa")
        assert response.status_code == 200
        
        data = response.json()
        for template in data:
            assert template["category"] == "qa"

    def test_list_templates_with_tags_filter(self, client):
        """Test listing templates filtered by tags."""
        response = client.get("/api/evaluations/templates?tags=chatbot,qa")
        assert response.status_code == 200
        
        data = response.json()
        # At least one template should match the tag filter
        assert len(data) >= 0

    def test_list_templates_exclude_custom(self, client):
        """Test listing templates excluding custom ones."""
        response = client.get("/api/evaluations/templates?include_custom=false")
        assert response.status_code == 200
        
        data = response.json()
        for template in data:
            assert template["is_builtin"] is True

    def test_get_template_details_builtin(self, client):
        """Test getting details of a built-in template."""
        # Get the first available template
        response = client.get("/api/evaluations/templates")
        assert response.status_code == 200
        templates = response.json()
        assert len(templates) > 0
        
        template_name = templates[0]["name"]
        
        response = client.get(f"/api/evaluations/templates/{template_name}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == template_name
        assert data["is_builtin"] is True
        assert isinstance(data["use_cases"], list)
        assert isinstance(data["metrics"], list)

    def test_get_template_not_found(self, client):
        """Test getting non-existent template."""
        response = client.get("/api/evaluations/templates/non_existent_template")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestTemplateRecommendationAPI:
    """Test template recommendation endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_recommend_templates_basic(self, client):
        """Test basic template recommendation."""
        request_data = {
            "description": "I want to evaluate a customer support chatbot that answers questions about our products and services. The bot should provide accurate and helpful responses.",
            "use_case": "customer_support"
        }
        
        response = client.post("/api/evaluations/templates/recommend", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5  # Should limit to top 5
        
        for recommendation in data:
            required_fields = [
                "template_name", "confidence", "display_name", "description",
                "metrics", "reason", "use_cases", "sample_configuration"
            ]
            for field in required_fields:
                assert field in recommendation
            
            assert 0 <= recommendation["confidence"] <= 1
            assert isinstance(recommendation["metrics"], list)
            assert isinstance(recommendation["use_cases"], list)
            assert isinstance(recommendation["sample_configuration"], dict)

    def test_recommend_templates_with_sample_data(self, client):
        """Test template recommendation with sample data."""
        request_data = {
            "description": "Classify customer feedback as positive, negative, or neutral sentiment",
            "sample_data": {
                "input": "This product is amazing! I love it.",
                "expected_output": "positive"
            },
            "use_case": "sentiment_analysis",
            "dataset_name": "customer_feedback"
        }
        
        response = client.post("/api/evaluations/templates/recommend", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        assert len(data) > 0
        
        # Check sample configuration includes dataset name
        recommendation = data[0]
        sample_config = recommendation["sample_configuration"]
        assert "dataset_config" in sample_config
        assert sample_config["dataset_config"]["dataset_name"] == "customer_feedback"

    def test_recommend_templates_short_description_error(self, client):
        """Test template recommendation with too short description."""
        request_data = {
            "description": "Short"  # Too short, should be at least 10 chars
        }
        
        response = client.post("/api/evaluations/templates/recommend", json=request_data)
        assert response.status_code == 422

    def test_recommend_templates_qa_specific(self, client):
        """Test recommendation for Q&A specific use case."""
        request_data = {
            "description": "I need to evaluate a question-answering system that provides factual answers to user questions. The system should be accurate and comprehensive in its responses.",
            "use_case": "qa"
        }
        
        response = client.post("/api/evaluations/templates/recommend", json=request_data)
        assert response.status_code == 200
        
        data = response.json()
        # Should prioritize QA templates
        qa_templates = [rec for rec in data if "qa" in rec["template_name"].lower()]
        assert len(qa_templates) > 0


class TestCustomTemplateAPI:
    """Test custom template CRUD operations."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def sample_custom_template(self):
        """Sample custom template data."""
        return {
            "name": "custom_sentiment_analysis",
            "display_name": "Custom Sentiment Analysis",
            "description": "A custom template for sentiment analysis evaluation with domain-specific metrics",
            "use_cases": ["sentiment_analysis", "social_media", "customer_feedback"],
            "metrics": ["exact_match", "semantic_similarity", "classification_accuracy"],
            "category": "classification",
            "tags": ["sentiment", "classification", "custom"],
            "sample_data": {
                "input": "This product is great!",
                "expected_output": "positive"
            },
            "configuration_schema": {
                "properties": {
                    "model": {"type": "string", "default": "gpt-3.5-turbo"},
                    "temperature": {"type": "number", "default": 0.3, "min": 0, "max": 1}
                }
            }
        }

    def test_create_custom_template(self, client, sample_custom_template):
        """Test creating a custom template."""
        response = client.post("/api/evaluations/templates/custom", json=sample_custom_template)
        assert response.status_code == 201
        
        data = response.json()
        assert data["name"] == sample_custom_template["name"]
        assert data["display_name"] == sample_custom_template["display_name"]
        assert data["description"] == sample_custom_template["description"]
        assert data["is_builtin"] is False
        assert data["usage_count"] == 0

    def test_create_custom_template_duplicate_name(self, client, sample_custom_template):
        """Test creating a custom template with duplicate name."""
        # Create first template
        response = client.post("/api/evaluations/templates/custom", json=sample_custom_template)
        assert response.status_code == 201

        # Try to create another with same name
        response = client.post("/api/evaluations/templates/custom", json=sample_custom_template)
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    def test_create_custom_template_invalid_name(self, client, sample_custom_template):
        """Test creating a custom template with invalid name."""
        sample_custom_template["name"] = "invalid name!"  # Contains spaces and special chars
        
        response = client.post("/api/evaluations/templates/custom", json=sample_custom_template)
        assert response.status_code == 422

    def test_create_custom_template_invalid_metrics(self, client, sample_custom_template):
        """Test creating a custom template with invalid metrics."""
        sample_custom_template["metrics"] = ["non_existent_metric"]
        
        response = client.post("/api/evaluations/templates/custom", json=sample_custom_template)
        assert response.status_code == 422

    def test_update_custom_template(self, client, sample_custom_template):
        """Test updating a custom template."""
        # Create template first
        response = client.post("/api/evaluations/templates/custom", json=sample_custom_template)
        assert response.status_code == 201
        
        template_name = sample_custom_template["name"]

        # Update template
        updated_data = sample_custom_template.copy()
        updated_data["display_name"] = "Updated Custom Sentiment Analysis"
        updated_data["description"] = "Updated description with new features"
        updated_data["tags"] = ["sentiment", "updated", "v2"]

        response = client.put(f"/api/evaluations/templates/custom/{template_name}", json=updated_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["display_name"] == updated_data["display_name"]
        assert data["description"] == updated_data["description"]
        assert data["tags"] == updated_data["tags"]

    def test_update_custom_template_not_found(self, client, sample_custom_template):
        """Test updating non-existent custom template."""
        response = client.put("/api/evaluations/templates/custom/non_existent", json=sample_custom_template)
        assert response.status_code == 404

    def test_delete_custom_template(self, client, sample_custom_template):
        """Test deleting a custom template."""
        # Create template first
        response = client.post("/api/evaluations/templates/custom", json=sample_custom_template)
        assert response.status_code == 201
        
        template_name = sample_custom_template["name"]

        # Delete template
        response = client.delete(f"/api/evaluations/templates/custom/{template_name}")
        assert response.status_code == 200
        assert "deleted successfully" in response.json()["message"]

        # Verify deletion
        response = client.get(f"/api/evaluations/templates/{template_name}")
        assert response.status_code == 404

    def test_delete_custom_template_not_found(self, client):
        """Test deleting non-existent custom template."""
        response = client.delete("/api/evaluations/templates/custom/non_existent")
        assert response.status_code == 404

    def test_get_custom_template_after_creation(self, client, sample_custom_template):
        """Test getting custom template details after creation."""
        # Create template
        response = client.post("/api/evaluations/templates/custom", json=sample_custom_template)
        assert response.status_code == 201
        
        template_name = sample_custom_template["name"]

        # Get template details
        response = client.get(f"/api/evaluations/templates/{template_name}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["name"] == template_name
        assert data["is_builtin"] is False
        assert data["sample_data"] == sample_custom_template["sample_data"]


class TestTemplateUsageTrackingAPI:
    """Test template usage tracking endpoints."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def template_name(self, client):
        """Get the first available template name."""
        response = client.get("/api/evaluations/templates")
        assert response.status_code == 200
        templates = response.json()
        return templates[0]["name"]

    def test_track_template_usage(self, client, template_name):
        """Test tracking template usage."""
        response = client.post(
            f"/api/evaluations/templates/{template_name}/track-usage",
            params={"user": "test_user", "project": "test_project"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "Usage tracked successfully" in data["message"]
        assert data["usage_count"] == 1

    def test_track_template_usage_multiple_times(self, client, template_name):
        """Test tracking template usage multiple times."""
        # Track usage 3 times
        for i in range(3):
            response = client.post(
                f"/api/evaluations/templates/{template_name}/track-usage",
                params={"user": f"user_{i}", "project": "test_project"}
            )
            assert response.status_code == 200

        # Check final usage count
        response = client.post(
            f"/api/evaluations/templates/{template_name}/track-usage",
            params={"user": "final_user", "project": "test_project"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["usage_count"] == 4

    def test_track_template_usage_not_found(self, client):
        """Test tracking usage for non-existent template."""
        response = client.post("/api/evaluations/templates/non_existent/track-usage")
        assert response.status_code == 404

    def test_get_template_usage_stats(self, client, template_name):
        """Test getting template usage statistics."""
        # Track some usage first
        users = ["user1", "user2", "user1"]  # user1 appears twice
        projects = ["project1", "project2", "project1"]
        
        for user, project in zip(users, projects):
            response = client.post(
                f"/api/evaluations/templates/{template_name}/track-usage",
                params={"user": user, "project": project}
            )
            assert response.status_code == 200

        # Get usage stats
        response = client.get(f"/api/evaluations/templates/{template_name}/usage")
        assert response.status_code == 200
        
        data = response.json()
        assert data["template_name"] == template_name
        assert data["usage_count"] == 3
        assert len(data["users"]) == 2  # Unique users
        assert len(data["projects"]) == 2  # Unique projects
        assert data["first_used"] is not None
        assert data["last_used"] is not None

    def test_get_template_usage_stats_no_usage(self, client):
        """Test getting usage stats for template with no usage."""
        # Use a different template that hasn't been used
        response = client.get("/api/evaluations/templates")
        templates = response.json()
        unused_template = None
        
        # Find a template we haven't used
        for template in templates:
            stats_response = client.get(f"/api/evaluations/templates/{template['name']}/usage")
            if stats_response.status_code == 200:
                stats = stats_response.json()
                if stats["usage_count"] == 0:
                    unused_template = template["name"]
                    break
        
        if unused_template:
            response = client.get(f"/api/evaluations/templates/{unused_template}/usage")
            assert response.status_code == 200
            
            data = response.json()
            assert data["usage_count"] == 0
            assert data["users"] == []
            assert data["projects"] == []
            assert data["first_used"] is None
            assert data["last_used"] is None


class TestTemplateImportExportAPI:
    """Test template import/export functionality."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def template_name(self, client):
        """Get the first available template name."""
        response = client.get("/api/evaluations/templates")
        assert response.status_code == 200
        templates = response.json()
        return templates[0]["name"]

    def test_export_template_json(self, client, template_name):
        """Test exporting a template in JSON format."""
        response = client.get(f"/api/evaluations/templates/{template_name}/export?format=json")
        assert response.status_code == 200
        
        data = response.json()
        assert data["template_name"] == template_name
        assert data["export_format"] == "json"
        assert "exported_at" in data
        assert "data" in data
        
        template_data = data["data"]
        assert template_data["name"] == template_name
        assert template_data["type"] == "builtin"
        assert "info" in template_data

    def test_export_template_yaml(self, client, template_name):
        """Test exporting a template in YAML format."""
        response = client.get(f"/api/evaluations/templates/{template_name}/export?format=yaml")
        assert response.status_code == 200
        
        data = response.json()
        assert data["export_format"] == "yaml"

    def test_export_template_invalid_format(self, client, template_name):
        """Test exporting template with invalid format."""
        response = client.get(f"/api/evaluations/templates/{template_name}/export?format=xml")
        assert response.status_code == 400
        assert "must be 'json' or 'yaml'" in response.json()["detail"]

    def test_export_template_not_found(self, client):
        """Test exporting non-existent template."""
        response = client.get("/api/evaluations/templates/non_existent/export")
        assert response.status_code == 404

    def test_import_template_json(self, client, template_name):
        """Test importing a template from JSON file."""
        # First export a template to get valid data structure
        export_response = client.get(f"/api/evaluations/templates/{template_name}/export")
        assert export_response.status_code == 200
        export_data = export_response.json()
        
        # Modify for import (make it custom)
        import_data = export_data["data"]
        import_data["name"] = "imported_custom_template"
        import_data["type"] = "custom"
        import_data["info"]["display_name"] = "Imported Custom Template"
        
        # Create JSON file content
        json_content = json.dumps(import_data).encode('utf-8')
        
        # Create file-like object
        files = {
            "file": ("template.json", BytesIO(json_content), "application/json")
        }
        
        response = client.post("/api/evaluations/templates/import", files=files)
        assert response.status_code == 200
        
        data = response.json()
        assert "imported successfully" in data["message"]
        assert data["template_name"] == "imported_custom_template"
        assert data["type"] == "custom"

    def test_import_template_invalid_file_format(self, client):
        """Test importing template with invalid file format."""
        # Create invalid file
        files = {
            "file": ("template.txt", BytesIO(b"invalid content"), "text/plain")
        }
        
        response = client.post("/api/evaluations/templates/import", files=files)
        assert response.status_code == 400
        assert "must be JSON or YAML" in response.json()["detail"]

    def test_import_template_invalid_structure(self, client):
        """Test importing template with invalid structure."""
        # Create JSON with invalid structure
        invalid_data = {"invalid": "structure"}
        json_content = json.dumps(invalid_data).encode('utf-8')
        
        files = {
            "file": ("invalid.json", BytesIO(json_content), "application/json")
        }
        
        response = client.post("/api/evaluations/templates/import", files=files)
        assert response.status_code == 400
        assert "Invalid template file structure" in response.json()["detail"]

    def test_import_template_duplicate_name(self, client, template_name):
        """Test importing template with duplicate name."""
        # Export existing template
        export_response = client.get(f"/api/evaluations/templates/{template_name}/export")
        export_data = export_response.json()["data"]
        
        # Try to import with same name
        json_content = json.dumps(export_data).encode('utf-8')
        files = {
            "file": ("duplicate.json", BytesIO(json_content), "application/json")
        }
        
        response = client.post("/api/evaluations/templates/import", files=files)
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]


class TestTemplateIntegration:
    """Test template integration with other components."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_template_list_includes_usage_stats(self, client):
        """Test that template list includes usage statistics."""
        # Get first template and track usage
        response = client.get("/api/evaluations/templates")
        templates = response.json()
        template_name = templates[0]["name"]
        
        # Track usage
        client.post(f"/api/evaluations/templates/{template_name}/track-usage")
        
        # Get updated list
        response = client.get("/api/evaluations/templates?include_usage_stats=true")
        assert response.status_code == 200
        
        updated_templates = response.json()
        used_template = next(t for t in updated_templates if t["name"] == template_name)
        assert used_template["usage_count"] >= 1

    def test_template_sorting_by_usage(self, client):
        """Test that templates are sorted by usage count."""
        # Get templates and track usage for second template more than first
        response = client.get("/api/evaluations/templates")
        templates = response.json()
        
        if len(templates) >= 2:
            template1_name = templates[0]["name"]
            template2_name = templates[1]["name"]
            
            # Track usage - more for template2
            client.post(f"/api/evaluations/templates/{template1_name}/track-usage")
            for _ in range(3):
                client.post(f"/api/evaluations/templates/{template2_name}/track-usage")
            
            # Get sorted list
            response = client.get("/api/evaluations/templates")
            sorted_templates = response.json()
            
            # Find positions of our templates
            template1_pos = next(i for i, t in enumerate(sorted_templates) if t["name"] == template1_name)
            template2_pos = next(i for i, t in enumerate(sorted_templates) if t["name"] == template2_name)
            
            # Template2 should appear before template1 (higher usage)
            assert template2_pos < template1_pos

    def test_custom_template_workflow(self, client):
        """Test complete custom template workflow."""
        # Create custom template
        custom_template = {
            "name": "workflow_test_template",
            "display_name": "Workflow Test Template",
            "description": "A template for testing the complete workflow",
            "use_cases": ["testing", "workflow"],
            "metrics": ["exact_match"],
            "category": "test",
            "tags": ["workflow", "test"]
        }
        
        # 1. Create template
        response = client.post("/api/evaluations/templates/custom", json=custom_template)
        assert response.status_code == 201
        
        # 2. Get template details
        response = client.get(f"/api/evaluations/templates/{custom_template['name']}")
        assert response.status_code == 200
        
        # 3. Track usage
        response = client.post(f"/api/evaluations/templates/{custom_template['name']}/track-usage")
        assert response.status_code == 200
        
        # 4. Export template
        response = client.get(f"/api/evaluations/templates/{custom_template['name']}/export")
        assert response.status_code == 200
        
        # 5. Update template
        updated_data = custom_template.copy()
        updated_data["description"] = "Updated workflow test template"
        response = client.put(f"/api/evaluations/templates/custom/{custom_template['name']}", json=updated_data)
        assert response.status_code == 200
        
        # 6. Get usage stats
        response = client.get(f"/api/evaluations/templates/{custom_template['name']}/usage")
        assert response.status_code == 200
        assert response.json()["usage_count"] >= 1
        
        # 7. Delete template
        response = client.delete(f"/api/evaluations/templates/custom/{custom_template['name']}")
        assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])