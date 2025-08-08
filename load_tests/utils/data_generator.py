"""
Test data generation utilities for load testing
"""

import random
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from faker import Faker

fake = Faker()

class TestDataGenerator:
    """Generates realistic test data for load testing scenarios"""
    
    def __init__(self):
        self.templates = ['qa_template', 'classification_template', 'summarization_template']
        self.metrics = ['exact_match', 'answer_relevancy', 'faithfulness', 'hallucination']
        self.statuses = ['pending', 'running', 'completed', 'failed']
        
    def generate_run_data(self, status: str = 'completed') -> Dict[str, Any]:
        """Generate realistic evaluation run data"""
        created_at = fake.date_time_between(start_date='-30d', end_date='now')
        duration_seconds = random.randint(60, 3600) if status == 'completed' else None
        
        return {
            'id': str(uuid.uuid4()),
            'name': f"Load Test Run {fake.word().title()} {fake.random_int(1, 9999)}",
            'description': fake.sentence(nb_words=10),
            'status': status,
            'template_id': str(uuid.uuid4()),
            'template_name': random.choice(self.templates),
            'created_at': created_at.isoformat(),
            'updated_at': (created_at + timedelta(seconds=duration_seconds or 0)).isoformat(),
            'started_at': (created_at + timedelta(seconds=5)).isoformat() if status != 'pending' else None,
            'completed_at': (created_at + timedelta(seconds=duration_seconds)).isoformat() if status == 'completed' else None,
            'duration_seconds': duration_seconds,
            'total_items': random.randint(50, 500),
            'processed_items': random.randint(45, 500) if status in ['completed', 'failed'] else random.randint(0, 50),
            'failed_items': random.randint(0, 25),
            'langfuse_session_id': f"session_{uuid.uuid4().hex[:8]}",
            'dataset_name': f"dataset_{fake.word()}_{random.randint(1, 100)}",
            'metrics_config': {
                metric: {'enabled': random.choice([True, False])}
                for metric in random.sample(self.metrics, k=random.randint(2, 4))
            },
            'metadata': {
                'version': fake.numerify('#.#.#'),
                'environment': random.choice(['dev', 'staging', 'prod']),
                'user_id': str(uuid.uuid4())
            }
        }
    
    def generate_run_batch(self, count: int, status_distribution: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
        """Generate batch of runs with realistic status distribution"""
        if status_distribution is None:
            status_distribution = {
                'completed': 0.7,
                'failed': 0.15,
                'running': 0.1,
                'pending': 0.05
            }
        
        runs = []
        for _ in range(count):
            status = random.choices(
                list(status_distribution.keys()),
                weights=list(status_distribution.values())
            )[0]
            runs.append(self.generate_run_data(status))
        
        return runs
    
    def generate_run_metrics(self, run_id: str) -> Dict[str, Any]:
        """Generate realistic run metrics data"""
        return {
            'run_id': run_id,
            'overall_scores': {
                metric: round(random.uniform(0.6, 0.95), 3)
                for metric in random.sample(self.metrics, k=3)
            },
            'metric_details': {
                metric: {
                    'score': round(random.uniform(0.6, 0.95), 3),
                    'passed_items': random.randint(60, 95),
                    'failed_items': random.randint(5, 40),
                    'distribution': [random.uniform(0, 1) for _ in range(10)]
                }
                for metric in random.sample(self.metrics, k=3)
            },
            'performance_stats': {
                'avg_response_time': round(random.uniform(0.5, 3.0), 2),
                'total_tokens': random.randint(10000, 100000),
                'total_cost': round(random.uniform(1.0, 50.0), 2)
            },
            'error_analysis': {
                'error_types': {
                    'timeout': random.randint(0, 5),
                    'api_error': random.randint(0, 3),
                    'validation_error': random.randint(0, 2)
                },
                'common_failures': [
                    fake.sentence(nb_words=5) for _ in range(random.randint(1, 4))
                ]
            }
        }
    
    def generate_run_items(self, run_id: str, count: int) -> List[Dict[str, Any]]:
        """Generate realistic run items for detailed testing"""
        items = []
        for i in range(count):
            item = {
                'id': str(uuid.uuid4()),
                'run_id': run_id,
                'input_data': {
                    'question': fake.sentence(nb_words=random.randint(5, 20)),
                    'context': fake.text(max_nb_chars=random.randint(100, 1000)),
                    'expected_output': fake.sentence(nb_words=random.randint(3, 15))
                },
                'output_data': {
                    'answer': fake.sentence(nb_words=random.randint(3, 15)),
                    'confidence': round(random.uniform(0.1, 1.0), 3)
                },
                'scores': {
                    metric: round(random.uniform(0.0, 1.0), 3)
                    for metric in random.sample(self.metrics, k=random.randint(2, 4))
                },
                'status': random.choice(['success', 'failed']),
                'error_message': fake.sentence() if random.random() < 0.1 else None,
                'response_time': round(random.uniform(0.1, 5.0), 3),
                'tokens_used': random.randint(50, 1000),
                'cost': round(random.uniform(0.001, 0.1), 4),
                'created_at': fake.date_time_between(start_date='-1d').isoformat(),
                'processed_at': fake.date_time_between(start_date='-1d').isoformat()
            }
            items.append(item)
        
        return items
    
    def generate_comparison_data(self, run1_id: str, run2_id: str) -> Dict[str, Any]:
        """Generate realistic comparison data between two runs"""
        common_metrics = random.sample(self.metrics, k=3)
        
        metrics_comparison = {}
        for metric in common_metrics:
            run1_score = round(random.uniform(0.6, 0.9), 3)
            run2_score = round(random.uniform(0.6, 0.9), 3)
            difference = run2_score - run1_score
            
            metrics_comparison[metric] = {
                'run1_score': run1_score,
                'run2_score': run2_score,
                'difference': round(difference, 3),
                'percentage_change': round((difference / run1_score) * 100, 2) if run1_score > 0 else 0,
                'improvement_direction': 'better' if difference > 0.01 else 'worse' if difference < -0.01 else 'neutral'
            }
        
        return {
            'metrics': metrics_comparison,
            'overall_performance': {
                'winner': random.choice(['run1', 'run2', 'tie']),
                'significant_improvements': random.randint(0, len(common_metrics)),
                'significant_regressions': random.randint(0, len(common_metrics))
            },
            'statistical_analysis': {
                metric: {
                    'p_value': round(random.uniform(0.001, 0.1), 4),
                    'confidence_interval': [
                        round(random.uniform(-0.1, 0.0), 3),
                        round(random.uniform(0.0, 0.1), 3)
                    ],
                    'is_significant': random.choice([True, False]),
                    'effect_size': round(random.uniform(0.1, 0.8), 2)
                }
                for metric in common_metrics
            }
        }
    
    def generate_websocket_message(self, run_id: str, message_type: str) -> Dict[str, Any]:
        """Generate realistic WebSocket messages for testing"""
        messages = {
            'run_update': {
                'type': 'run_update',
                'run_id': run_id,
                'data': {
                    'status': random.choice(['running', 'completed', 'failed']),
                    'processed_items': random.randint(1, 100),
                    'current_metric': random.choice(self.metrics),
                    'estimated_completion': fake.date_time_between(start_date='now', end_date='+1h').isoformat()
                }
            },
            'progress': {
                'type': 'progress',
                'run_id': run_id,
                'data': {
                    'progress_percentage': random.randint(0, 100),
                    'items_processed': random.randint(0, 500),
                    'current_item': random.randint(1, 500),
                    'processing_rate': round(random.uniform(0.5, 10.0), 2)
                }
            },
            'error': {
                'type': 'error',
                'run_id': run_id,
                'data': {
                    'error_code': random.choice(['TIMEOUT', 'API_ERROR', 'VALIDATION_ERROR']),
                    'error_message': fake.sentence(),
                    'retry_available': random.choice([True, False])
                }
            },
            'completion': {
                'type': 'completion',
                'run_id': run_id,
                'data': {
                    'final_status': random.choice(['completed', 'failed']),
                    'total_processed': random.randint(50, 500),
                    'total_failed': random.randint(0, 25),
                    'final_scores': {
                        metric: round(random.uniform(0.6, 0.95), 3)
                        for metric in random.sample(self.metrics, k=2)
                    }
                }
            }
        }
        
        message = messages.get(message_type, messages['run_update'])
        message['timestamp'] = datetime.now().isoformat()
        return message

# Global instance
test_data_generator = TestDataGenerator()