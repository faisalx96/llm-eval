# LLM-Eval Load Testing Suite

A comprehensive load testing suite for the LLM-Eval platform designed to validate system performance under high concurrent load and ensure scalability targets are met.

## Overview

This load testing suite validates the following components:
- **API Endpoints**: CRUD operations, comparisons, exports
- **WebSocket Connections**: Real-time updates and message delivery
- **Database Performance**: Query optimization with 1000+ runs
- **System Resources**: Memory usage, CPU utilization, connection pooling

## Performance Targets

### API Performance
- **Response Time**: < 500ms (95th percentile) under load
- **Throughput**: Support 100+ concurrent users
- **Error Rate**: < 1% for all operations
- **Availability**: > 99.9% uptime during load

### WebSocket Performance
- **Connection Time**: < 2 seconds to establish
- **Message Latency**: < 100ms delivery time
- **Concurrent Connections**: Support 100+ active connections
- **Message Delivery**: > 99% success rate

### Database Performance
- **Query Response**: < 200ms (95th percentile)
- **Concurrent Operations**: Support 50+ simultaneous queries
- **Data Volume**: Handle 1000+ evaluation runs efficiently
- **Index Effectiveness**: Maintain performance with large datasets

### System Resources
- **Memory Growth**: < 10% increase during extended runs
- **CPU Usage**: < 80% average under peak load
- **Connection Pool**: No connection leaks or exhaustion

## Test Suite Components

### 1. API Load Testing (`locustfile.py`)

**Simulated User Behaviors:**
- **EvaluationRunUser**: Regular users performing CRUD operations
- **HighVolumeUser**: Power users creating many runs rapidly
- **ReadOnlyUser**: Analytics users performing read-heavy operations

**Test Scenarios:**
```python
# Operations with realistic weights
create_evaluation_run: 20%    # Most common operation
list_runs: 30%               # Very frequent browsing
get_run_details: 15%         # Detailed views
compare_runs: 10%            # Intensive operations
update_run: 8%               # Modifications
search_runs: 12%             # Search functionality
export_comparison: 5%        # Resource-intensive exports
```

**Usage:**
```bash
# Basic load test
locust -f locustfile.py --host=http://localhost:8000 --users=50 --spawn-rate=5 --run-time=5m

# Web UI mode
locust -f locustfile.py --host=http://localhost:8000

# High-intensity test
locust -f locustfile.py --host=http://localhost:8000 --users=100 --spawn-rate=10 --run-time=10m
```

### 2. WebSocket Load Testing (`websocket_load_test.py`)

**Features:**
- **Concurrent Connections**: Test multiple simultaneous WebSocket connections
- **Message Patterns**: Realistic message types (updates, progress, errors, completion)
- **Latency Tracking**: Measure end-to-end message delivery time
- **Connection Stability**: Test connection persistence under load
- **Resource Monitoring**: Track memory usage and connection pools

**Message Types Tested:**
- `run_update`: Status changes and progress updates
- `progress`: Real-time evaluation progress
- `error`: Error notifications and recovery
- `completion`: Final results and cleanup

**Usage:**
```bash
# Standard WebSocket load test
python websocket_load_test.py --clients=50 --duration=300

# High concurrency test
python websocket_load_test.py --clients=100 --duration=600 --host=ws://localhost:8000/ws

# Extended stability test
python websocket_load_test.py --clients=75 --duration=1800  # 30 minutes
```

### 3. Database Performance Testing (`database_performance_test.py`)

**Test Phases:**
1. **Data Insertion**: Bulk insert 1000+ evaluation runs
2. **Query Performance**: Test individual query types
3. **Concurrent Load**: Simulate real-world concurrent access

**Query Types Tested:**
- **Single SELECT**: ID-based lookups with primary key
- **Paginated SELECT**: List operations with LIMIT/OFFSET
- **Filtered SELECT**: Index-based filtering (status, template, date)
- **Complex JOINs**: Multi-table queries with aggregations
- **Aggregate Queries**: COUNT, AVG, SUM operations
- **Search Queries**: LIKE operations for text search
- **UPDATE Operations**: Status and data modifications

**Database Schema:**
```sql
-- Optimized indexes for performance
CREATE INDEX idx_runs_status ON evaluation_runs(status);
CREATE INDEX idx_runs_created_at ON evaluation_runs(created_at);
CREATE INDEX idx_runs_composite ON evaluation_runs(status, created_at, template_name);
```

**Usage:**
```bash
# Full performance test suite
python database_performance_test.py --runs=1000 --concurrent=20 --duration=600

# Quick performance check
python database_performance_test.py --runs=100 --concurrent=5 --duration=120

# Clean start with new database
python database_performance_test.py --runs=1000 --clean
```

## Test Data Generation

The suite includes realistic test data generation:

**Evaluation Runs:**
- Varied statuses (70% completed, 15% failed, 10% running, 5% pending)
- Different templates and metrics configurations
- Realistic timing and duration data
- Proper foreign key relationships

**Run Items:**
- Complex input/output data structures
- Score distributions matching real evaluation patterns
- Error scenarios and edge cases
- Performance characteristics (tokens, cost, timing)

**WebSocket Messages:**
- Realistic message payloads
- Proper timestamp and sequence handling
- Error conditions and recovery scenarios
- Progress tracking patterns

## Running the Complete Test Suite

### Prerequisites

```bash
# Install dependencies
pip install -r load_tests/requirements.txt

# Ensure LLM-Eval API is running
python -m llm_eval.api.main

# Ensure WebSocket endpoint is available
# (Usually included with API server)
```

### Test Execution Scripts

Create `run_all_tests.sh`:
```bash
#!/bin/bash
echo "Starting LLM-Eval Load Testing Suite..."

# Configuration
API_HOST="http://localhost:8000"
WS_HOST="ws://localhost:8000/ws"
DB_PATH="load_test_$(date +%Y%m%d_%H%M%S).db"

echo "=== API Load Testing ==="
locust -f locustfile.py --host=$API_HOST --users=50 --spawn-rate=5 --run-time=5m --html=api_load_test_report.html

echo "=== WebSocket Load Testing ==="
python websocket_load_test.py --clients=50 --duration=300 --host=$WS_HOST

echo "=== Database Performance Testing ==="
python database_performance_test.py --runs=1000 --concurrent=20 --duration=600 --db-path=$DB_PATH

echo "Load testing completed. Check generated report files."
```

### Continuous Integration Integration

For CI/CD pipelines, create `ci_load_test.py`:
```python
#!/usr/bin/env python3
"""
Automated load testing for CI/CD pipeline
Returns exit code 0 if all targets are met, 1 if any fail
"""

import subprocess
import json
import sys
from datetime import datetime

def run_api_load_test():
    """Run API load test in headless mode"""
    cmd = [
        'locust', '-f', 'locustfile.py',
        '--host', 'http://localhost:8000',
        '--users', '25', '--spawn-rate', '5',
        '--run-time', '2m', '--headless',
        '--csv', 'ci_api_results'
    ]
    
    return subprocess.run(cmd, capture_output=True, text=True)

def run_websocket_test():
    """Run WebSocket load test"""
    cmd = [
        'python', 'websocket_load_test.py',
        '--clients', '25', '--duration', '120'
    ]
    
    return subprocess.run(cmd, capture_output=True, text=True)

def run_database_test():
    """Run database performance test"""
    cmd = [
        'python', 'database_performance_test.py',
        '--runs', '100', '--concurrent', '10',
        '--duration', '180', '--clean'
    ]
    
    return subprocess.run(cmd, capture_output=True, text=True)

def main():
    print(f"Starting CI load tests at {datetime.now()}")
    
    tests = [
        ("API Load Test", run_api_load_test),
        ("WebSocket Test", run_websocket_test),
        ("Database Test", run_database_test)
    ]
    
    failed_tests = []
    
    for test_name, test_func in tests:
        print(f"\nRunning {test_name}...")
        result = test_func()
        
        if result.returncode == 0:
            print(f"✓ {test_name} passed")
        else:
            print(f"✗ {test_name} failed")
            print(f"Error: {result.stderr}")
            failed_tests.append(test_name)
    
    if failed_tests:
        print(f"\n❌ Tests failed: {', '.join(failed_tests)}")
        return 1
    else:
        print(f"\n✅ All load tests passed!")
        return 0

if __name__ == '__main__':
    sys.exit(main())
```

## Interpreting Results

### API Load Test Results

Locust generates detailed HTML reports with:
- **Request statistics**: Response times, failure rates
- **Response time charts**: Performance over time
- **Failure analysis**: Error types and frequencies

**Key Metrics to Monitor:**
```
Name                          # reqs    # fails   Avg   Min   Max  Median   req/s
create_run                      1000        5    245    89   1200     220    8.5
list_runs                       1500        2    156    45    890     140   12.3
compare_runs                     500       12    567   120   2100     450    4.2
```

**Success Criteria:**
- 95th percentile < 500ms for all operations
- Error rate < 1%
- No memory leaks or connection issues

### WebSocket Test Results

Sample output format:
```json
{
  "duration_seconds": 300,
  "connections": {
    "established": 50,
    "failed": 0,
    "success_rate": 100.0
  },
  "message_latencies_ms": {
    "avg": 45.2,
    "p95": 89.3,
    "max": 156.7
  },
  "messages": {
    "sent": 1500,
    "received": 1498,
    "delivery_rate": 99.87
  }
}
```

**Success Criteria:**
- Message latency p95 < 100ms
- Delivery rate > 99%
- No connection failures

### Database Performance Results

Query performance breakdown:
```json
{
  "query_performance": {
    "select_single": {
      "avg_ms": 12.5,
      "p95_ms": 45.2,
      "count": 200
    },
    "select_filtered": {
      "avg_ms": 89.3,
      "p95_ms": 167.8,
      "count": 150
    }
  }
}
```

**Success Criteria:**
- All query types p95 < 200ms
- No query failures
- Stable performance with 1000+ runs

## Troubleshooting

### Common Issues

**1. Connection Pool Exhaustion**
```
Error: Connection pool exhausted
Solution: Increase max_connections or reduce concurrent workers
```

**2. WebSocket Connection Failures**
```
Error: WebSocket connection failed
Check: Server WebSocket endpoint is accessible
Check: No firewall blocking WebSocket connections
```

**3. Database Lock Contention**
```
Error: Database is locked
Solution: Reduce concurrent database workers
Solution: Implement connection retry logic
```

**4. Memory Growth**
```
Warning: Memory increased by 25%
Check: Proper connection cleanup
Check: No data structure leaks in test code
```

### Performance Debugging

**Enable Detailed Logging:**
```bash
export LOG_LEVEL=DEBUG
python websocket_load_test.py --verbose
```

**Database Query Analysis:**
```sql
-- Check query performance
EXPLAIN QUERY PLAN SELECT * FROM evaluation_runs WHERE status = 'completed';

-- Analyze index usage
.schema evaluation_runs
```

**Resource Monitoring:**
```bash
# Monitor during tests
htop
iotop
netstat -an | grep :8000
```

## Extending the Test Suite

### Adding New Test Scenarios

1. **Create new user class in locustfile.py:**
```python
class CustomUser(HttpUser):
    @task
    def custom_operation(self):
        # Your custom test logic
        pass
```

2. **Add new WebSocket message types:**
```python
# In data_generator.py
def generate_custom_message(self, run_id: str) -> Dict[str, Any]:
    return {
        'type': 'custom_event',
        'run_id': run_id,
        'data': {'custom_field': 'value'}
    }
```

3. **Create specialized database tests:**
```python
def test_custom_query_pattern(self):
    """Test specific query optimization"""
    def custom_query():
        with self.connection_manager.get_connection() as conn:
            return conn.execute("YOUR_CUSTOM_QUERY").fetchall()
    
    self._measure_query_time('custom_query', custom_query)
```

### Performance Monitoring Integration

Integrate with monitoring tools:
```python
# Prometheus metrics export
from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter('requests_total', 'Total requests')
REQUEST_LATENCY = Histogram('request_duration_seconds', 'Request latency')

@REQUEST_LATENCY.time()
def timed_request():
    # Your request logic
    REQUEST_COUNT.inc()
```

## Best Practices

### Test Environment Setup
- Use dedicated test database (isolated from development)
- Ensure consistent system resources across test runs
- Clean up test data between runs to ensure reproducible results
- Monitor system resources during tests

### Test Data Management
- Use realistic data volumes and patterns
- Include edge cases and error scenarios
- Maintain data consistency across test runs
- Clean up generated data after tests

### Performance Baseline Management
- Establish baseline measurements for comparison
- Track performance trends over time
- Set up alerts for performance regressions
- Document environmental factors affecting performance

### Continuous Testing
- Integrate load tests into CI/CD pipeline
- Run performance tests on every major release
- Monitor performance in staging environments
- Validate performance after infrastructure changes

This comprehensive load testing suite ensures the LLM-Eval platform can handle production workloads while maintaining excellent user experience and system reliability.