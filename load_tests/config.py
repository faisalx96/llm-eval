"""
Load testing configuration settings
"""

import os
from typing import Dict, Any

# API Configuration
API_BASE_URL = os.getenv('LOAD_TEST_API_URL', 'http://localhost:8000')
WEBSOCKET_URL = os.getenv('LOAD_TEST_WS_URL', 'ws://localhost:8000/ws')
DATABASE_URL = os.getenv('LOAD_TEST_DB_URL', 'sqlite:///llm_eval_runs.db')

# Load Testing Parameters
LOAD_TEST_CONFIG: Dict[str, Any] = {
    # User simulation
    'users': {
        'min': 10,
        'max': 100,
        'spawn_rate': 5,
        'run_time': '5m'
    },
    
    # Performance targets
    'targets': {
        'api_response_time_p95': 500,  # ms
        'websocket_latency': 100,      # ms
        'database_query_time': 200,    # ms
        'memory_leak_threshold': 0.1   # 10% increase
    },
    
    # Test data generation
    'data': {
        'max_runs': 1000,
        'items_per_run': 100,
        'concurrent_comparisons': 50,
        'websocket_clients': 100
    },
    
    # Test scenarios
    'scenarios': {
        'api_crud': {
            'weight': 40,
            'operations': ['create', 'read', 'update', 'delete']
        },
        'run_comparison': {
            'weight': 30,
            'concurrent_comparisons': 20
        },
        'websocket_updates': {
            'weight': 20,
            'message_rate': 10  # messages per second
        },
        'database_queries': {
            'weight': 10,
            'complex_queries': True
        }
    }
}

# Test environment setup
TEST_ENV = {
    'cleanup_after_test': True,
    'preserve_test_data': False,
    'log_level': 'INFO',
    'report_format': 'html',
    'screenshot_on_failure': True
}

# Performance monitoring
MONITORING = {
    'cpu_threshold': 80,    # %
    'memory_threshold': 80, # %
    'disk_io_threshold': 100, # MB/s
    'network_threshold': 50   # MB/s
}