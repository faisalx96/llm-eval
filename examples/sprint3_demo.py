"""Sprint 3 Backend Features Demo

This script demonstrates the new UI-driven evaluation features:
1. Evaluation Configuration API
2. Task Execution Engine
3. Metric Configuration System
4. Template Management System
"""

import asyncio
import json
import logging
import time
from datetime import datetime

import requests
from llm_eval.api.main import create_app
from llm_eval.core.task_engine import get_task_engine
from llm_eval.storage.database import get_database_manager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Sprint3BackendDemo:
    """Demo class for Sprint 3 backend features."""
    
    def __init__(self, api_base_url: str = "http://localhost:8000/api"):
        self.api_base_url = api_base_url
        self.session = requests.Session()
    
    def demo_template_management(self):
        """Demonstrate template management features."""
        logger.info("=== Template Management Demo ===")
        
        # List available templates
        response = self.session.get(f"{self.api_base_url}/templates")
        if response.status_code == 200:
            templates = response.json()
            logger.info(f"Found {len(templates)} templates")
            for template in templates[:3]:
                logger.info(f"  - {template['name']}: {template['description'][:80]}...")
        
        # Get template recommendations
        recommendation_request = {
            "description": "I want to evaluate a question answering system that answers user questions based on a knowledge base",
            "use_case": "customer support chatbot",
            "dataset_name": "customer_qa_dataset"
        }
        
        response = self.session.post(
            f"{self.api_base_url}/templates/recommend",
            json=recommendation_request
        )
        
        if response.status_code == 200:
            recommendations = response.json()
            logger.info(f"Got {len(recommendations)} template recommendations:")
            for rec in recommendations:
                logger.info(f"  - {rec['template_name']} (confidence: {rec['confidence']:.2f}): {rec['reason']}")
        
        # Create custom template
        custom_template = {
            "name": "custom_qa_template",
            "display_name": "Custom QA Template",
            "description": "A custom template for question answering evaluation with specialized metrics",
            "use_cases": ["customer support", "knowledge base qa", "chatbot evaluation"],
            "metrics": ["exact_match", "semantic_similarity", "answer_relevance"],
            "category": "qa",
            "tags": ["qa", "chatbot", "custom"]
        }
        
        response = self.session.post(
            f"{self.api_base_url}/templates/custom",
            json=custom_template
        )
        
        if response.status_code == 201:
            created_template = response.json()
            logger.info(f"Created custom template: {created_template['name']}")
        elif response.status_code == 409:
            logger.info("Custom template already exists")
    
    def demo_metric_configuration(self):
        """Demonstrate metric configuration and validation features."""
        logger.info("=== Metric Configuration Demo ===")
        
        # List available metrics
        response = self.session.get(f"{self.api_base_url}/evaluations/metrics")
        if response.status_code == 200:
            metrics_data = response.json()
            logger.info(f"Found {metrics_data['total_count']} metrics in {len(metrics_data['categories'])} categories")
            for metric in metrics_data['metrics'][:3]:
                logger.info(f"  - {metric['name']}: {metric['description'][:60]}...")
        
        # Get specific metric details
        response = self.session.get(f"{self.api_base_url}/evaluations/metrics/semantic_similarity")
        if response.status_code == 200:
            metric_details = response.json()
            logger.info(f"Semantic similarity metric has {len(metric_details['parameters'])} parameters")
            for param in metric_details['parameters']:
                logger.info(f"  - {param['name']} ({param['type']}): {param['description'][:50]}...")
        
        # Validate metric configuration
        metric_config = {
            "metric_name": "semantic_similarity",
            "parameters": {
                "model_name": "sentence-transformers/all-MiniLM-L6-v2",
                "threshold": 0.8
            }
        }
        
        response = self.session.post(
            f"{self.api_base_url}/evaluations/metrics/validate",
            json=metric_config
        )
        
        if response.status_code == 200:
            validation_result = response.json()
            logger.info(f"Metric validation: {'Valid' if validation_result['is_valid'] else 'Invalid'}")
            if not validation_result['is_valid']:
                logger.error(f"Validation errors: {validation_result['errors']}")
        
        # Preview metric with sample data
        preview_request = {
            "metric_name": "exact_match",
            "parameters": {
                "case_sensitive": False,
                "strip_whitespace": True
            },
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
        
        response = self.session.post(
            f"{self.api_base_url}/evaluations/metrics/preview",
            json=preview_request
        )
        
        if response.status_code == 200:
            preview_result = response.json()
            logger.info(f"Metric preview results: {len(preview_result['preview_results'])} samples processed")
            if preview_result['summary_stats']:
                stats = preview_result['summary_stats']
                logger.info(f"  Mean score: {stats['mean']:.3f}, Min: {stats['min']:.3f}, Max: {stats['max']:.3f}")
    
    def demo_evaluation_configuration(self):
        """Demonstrate evaluation configuration API."""
        logger.info("=== Evaluation Configuration Demo ===")
        
        # Create evaluation configuration
        config_data = {
            "name": "Customer Support QA Evaluation",
            "description": "Evaluation configuration for customer support chatbot QA performance",
            "task_type": "qa",
            "template_name": "qa",
            "task_config": {
                "description": "Evaluate customer support chatbot responses",
                "input_field": "question",
                "output_field": "answer"
            },
            "dataset_config": {
                "dataset_name": "customer_support_qa",
                "filters": {
                    "category": "general"
                }
            },
            "metrics_config": {
                "metrics": [
                    {
                        "name": "exact_match",
                        "parameters": {
                            "case_sensitive": False
                        }
                    },
                    {
                        "name": "semantic_similarity",
                        "parameters": {
                            "threshold": 0.8
                        }
                    }
                ]
            },
            "execution_config": {
                "batch_size": 10,
                "max_parallel": 3
            },
            "tags": ["qa", "customer_support", "demo"]
        }
        
        response = self.session.post(
            f"{self.api_base_url}/evaluations/configs",
            json=config_data,
            params={"created_by": "demo_user"}
        )
        
        if response.status_code == 201:
            created_config = response.json()
            config_id = created_config['id']
            logger.info(f"Created evaluation configuration: {config_id}")
            
            # Publish the configuration
            response = self.session.post(
                f"{self.api_base_url}/evaluations/configs/{config_id}/publish"
            )
            
            if response.status_code == 200:
                logger.info("Configuration published successfully")
                return config_id
        
        return None
    
    async def demo_task_execution(self, config_id: str):
        """Demonstrate task execution engine."""
        logger.info("=== Task Execution Demo ===")
        
        if not config_id:
            logger.warning("No configuration ID provided, skipping task execution demo")
            return
        
        # Execute configuration
        execution_request = {
            "config_id": config_id,
            "task_name": "Demo Customer Support QA Evaluation",
            "priority": 1
        }
        
        response = self.session.post(
            f"{self.api_base_url}/evaluations/tasks/execute",
            json=execution_request,
            params={"created_by": "demo_user"}
        )
        
        if response.status_code == 201:
            execution = response.json()
            execution_id = execution['id']
            logger.info(f"Started task execution: {execution_id}")
            
            # Monitor execution progress
            for i in range(10):  # Check up to 10 times
                response = self.session.get(
                    f"{self.api_base_url}/evaluations/tasks/{execution_id}"
                )
                
                if response.status_code == 200:
                    task_status = response.json()
                    status = task_status['status']
                    progress = task_status['progress_percentage']
                    
                    logger.info(f"Task status: {status} ({progress:.1f}%)")
                    
                    if status in ['completed', 'failed', 'cancelled']:
                        break
                    
                    # Wait a bit before checking again
                    await asyncio.sleep(2)
                
                # Demo pause and resume (only if still running)
                if i == 3:  # After a few checks
                    response = self.session.post(
                        f"{self.api_base_url}/evaluations/tasks/{execution_id}/pause"
                    )
                    if response.status_code == 200:
                        logger.info("Task paused successfully")
                    
                elif i == 5:  # Resume after pause
                    response = self.session.post(
                        f"{self.api_base_url}/evaluations/tasks/{execution_id}/resume"
                    )
                    if response.status_code == 200:
                        logger.info("Task resumed successfully")
            
            # List all active tasks
            response = self.session.get(f"{self.api_base_url}/evaluations/tasks")
            if response.status_code == 200:
                tasks = response.json()
                logger.info(f"Active tasks: {tasks['active_count']}/{tasks['total_count']}")
    
    def demo_configuration_management(self):
        """Demonstrate configuration listing and filtering."""
        logger.info("=== Configuration Management Demo ===")
        
        # List configurations
        response = self.session.get(
            f"{self.api_base_url}/evaluations/configs",
            params={"page_size": 5}
        )
        
        if response.status_code == 200:
            configs = response.json()
            logger.info(f"Found {configs['total_count']} configurations")
            for config in configs['configurations']:
                logger.info(f"  - {config['name']} (status: {config['status']}, usage: {config['usage_count']})")
        
        # Search configurations
        response = self.session.get(
            f"{self.api_base_url}/evaluations/configs",
            params={"search": "qa", "status_filter": "published"}
        )
        
        if response.status_code == 200:
            search_results = response.json()
            logger.info(f"Found {search_results['filtered_count']} QA configurations")


async def run_demo():
    """Run the complete Sprint 3 backend demo."""
    logger.info("Starting Sprint 3 Backend Features Demo")
    
    # Initialize database
    db_manager = get_database_manager()
    health_status = db_manager.health_check()
    
    if health_status["status"] != "healthy":
        logger.error(f"Database not healthy: {health_status}")
        return
    
    logger.info("Database connection healthy")
    
    # Create demo instance
    demo = Sprint3BackendDemo()
    
    try:
        # Run all demos
        demo.demo_template_management()
        demo.demo_metric_configuration()
        config_id = demo.demo_evaluation_configuration()
        
        # Task execution demo requires async
        if config_id:
            await demo.demo_task_execution(config_id)
        
        demo.demo_configuration_management()
        
        logger.info("Sprint 3 Backend Demo completed successfully!")
        
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Note: This demo requires the FastAPI server to be running
    # Start the server with: python -m llm_eval.api.main
    # Then run this demo in a separate terminal
    
    print("Sprint 3 Backend Features Demo")
    print("===============================")
    print("This demo showcases:")
    print("1. Template Management API")
    print("2. Metric Configuration & Validation")
    print("3. Evaluation Configuration API")
    print("4. Task Execution Engine")
    print("")
    print("Make sure the API server is running at http://localhost:8000")
    print("Start server with: python -m llm_eval.api.main")
    print("")
    
    try:
        asyncio.run(run_demo())
    except KeyboardInterrupt:
        print("\nDemo interrupted by user")
    except Exception as e:
        print(f"\nDemo failed: {e}")