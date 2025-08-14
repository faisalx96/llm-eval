# Sprint 3 Week 1 Test Execution Guide

## Overview

This guide provides step-by-step instructions for executing the comprehensive test suite created for Sprint 3 Week 1 of the LLM-Eval platform. The tests cover frontend components, API integration, end-to-end workflows, and load testing.

## Prerequisites

### Backend Testing Requirements
```bash
# Install Python dependencies
pip install -e ".[dev]"
pip install pytest pytest-asyncio pytest-cov
pip install locust  # For load testing

# Verify installation
python3 -c "import pytest; print('✅ Pytest ready')"
```

### Frontend Testing Requirements
```bash
cd frontend

# Install dependencies
npm install

# Verify Jest setup
npm run test -- --version
```

### Database Setup for Testing
```bash
# Ensure test database is available
export DATABASE_URL="sqlite:///test_llm_eval.db"

# Run migrations if needed
python -m llm_eval.storage.migration
```

## Test Execution Commands

### 1. Frontend Component Tests

#### Run All Frontend Tests
```bash
cd frontend

# Run all tests
npm test

# Run with coverage
npm run test:coverage

# Run specific test file
npm test -- task-configuration-wizard.test.tsx
```

#### Run Specific Frontend Test Suites
```bash
# Task Configuration Wizard tests
npm test -- --testPathPattern=task-configuration-wizard

# Dataset Browser tests  
npm test -- --testPathPattern=dataset-browser

# Metric Selector tests
npm test -- --testPathPattern=metric-selector

# Template Marketplace tests
npm test -- --testPathPattern=template-marketplace
```

### 2. Backend Integration Tests

#### Run All Backend Tests
```bash
# From project root
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=llm_eval --cov-report=html

# Parallel execution
python -m pytest tests/ -n auto
```

#### Run Specific Test Suites
```bash
# Evaluation configuration API tests
python -m pytest tests/integration/test_evaluation_endpoints.py -v

# Template management API tests  
python -m pytest tests/integration/test_template_endpoints.py -v

# Complete evaluation flow tests
python -m pytest tests/integration/test_complete_evaluation_flow.py -v
```

#### Run Tests by Category
```bash
# All integration tests
python -m pytest tests/integration/ -v

# All unit tests
python -m pytest tests/unit/ -v

# Performance tests
python -m pytest tests/performance/ -v
```

### 3. End-to-End Workflow Tests

#### Complete Evaluation Flow
```bash
# Run complete workflow test
python -m pytest tests/integration/test_complete_evaluation_flow.py::TestCompleteEvaluationFlow::test_complete_ui_driven_evaluation_workflow -v -s

# Run all end-to-end scenarios
python -m pytest tests/integration/test_complete_evaluation_flow.py -v -s
```

#### Error Handling Validation
```bash
# Test error handling throughout workflow
python -m pytest tests/integration/test_complete_evaluation_flow.py::TestCompleteEvaluationFlow::test_error_handling_in_evaluation_flow -v
```

### 4. Load Testing

#### Basic Load Test Execution
```bash
# Navigate to load tests directory
cd load_tests

# Run basic load test (10 users, 2 minutes)
locust -f locustfile.py --host=http://localhost:8000 --users=10 --spawn-rate=2 --run-time=2m --headless

# Run with web UI for monitoring
locust -f locustfile.py --host=http://localhost:8000
```

#### Specific Load Test Scenarios
```bash
# High-frequency reads simulation
locust -f locustfile.py --user-classes=HighFrequencyReadsUser --users=20 --spawn-rate=5 --run-time=1m --headless

# Bulk operations testing
locust -f locustfile.py --user-classes=BulkOperationsUser --users=5 --spawn-rate=1 --run-time=3m --headless

# Evaluation configuration focused testing
locust -f locustfile.py --user-classes=EvaluationConfigurationUser --users=15 --spawn-rate=3 --run-time=2m --headless
```

#### Production-Scale Load Testing
```bash
# Scale test for 100+ concurrent users
locust -f locustfile.py --host=http://localhost:8000 --users=100 --spawn-rate=10 --run-time=5m --headless

# Extended stress test
locust -f locustfile.py --host=http://localhost:8000 --users=200 --spawn-rate=20 --run-time=10m --headless
```

## Test Validation Commands

### Syntax Validation
```bash
# Validate Python test syntax
python3 -m py_compile tests/integration/test_evaluation_endpoints.py
python3 -m py_compile tests/integration/test_template_endpoints.py  
python3 -m py_compile tests/integration/test_complete_evaluation_flow.py

# Validate TypeScript test syntax  
cd frontend
npx tsc --noEmit __tests__/**/*.test.tsx
```

### Test Discovery
```bash
# List all discovered backend tests
python -m pytest --collect-only tests/

# List all frontend tests
cd frontend
npm test -- --listTests
```

## Continuous Integration Commands

### Complete Test Suite Execution
```bash
#!/bin/bash
# run_all_tests.sh

echo "🧪 Starting Sprint 3 Week 1 Test Suite..."

# Backend tests
echo "📊 Running Backend Integration Tests..."
python -m pytest tests/integration/ -v --tb=short

# Frontend tests  
echo "🎨 Running Frontend Component Tests..."
cd frontend
npm test -- --watchAll=false --coverage

# Load test validation
echo "⚡ Validating Load Test Configuration..."
cd ../load_tests
python3 -m py_compile locustfile.py
echo "✅ Load tests ready for execution"

echo "🎉 All tests completed successfully!"
```

### Coverage Reporting
```bash
# Generate comprehensive coverage report
python -m pytest tests/ --cov=llm_eval --cov-report=html --cov-report=term

# Frontend coverage
cd frontend
npm run test:coverage
```

## Performance Monitoring

### API Performance Benchmarks
```bash
# Quick API performance check
curl -w "@curl-format.txt" -o /dev/null -s "http://localhost:8000/api/evaluations/configs"

# Create curl-format.txt:
echo "     time_namelookup:  %{time_namelookup}s
        time_connect:  %{time_connect}s
     time_appconnect:  %{time_appconnect}s
    time_pretransfer:  %{time_pretransfer}s
       time_redirect:  %{time_redirect}s
  time_starttransfer:  %{time_starttransfer}s
                     ----------
          time_total:  %{time_total}s" > curl-format.txt
```

### Database Performance Monitoring
```bash
# Monitor test database performance
python -c "
from llm_eval.storage.database import get_database_manager
import time

db = get_database_manager()
start = time.time()
# Add performance monitoring code here
print(f'Database operation took {time.time() - start:.3f}s')
"
```

## Test Result Interpretation

### Expected Results

#### Frontend Tests
```
✅ Task Configuration Wizard: 23/23 passing
✅ Dataset Browser: 19/19 passing
✅ Metric Selector: 22/22 passing  
✅ Template Marketplace: 31/31 passing
✅ All Component Tests: 95+/95+ passing
```

#### Backend Integration Tests
```
✅ Evaluation Configuration API: 142+ tests
✅ Template Management API: 89+ tests
✅ Complete Evaluation Flow: 12+ scenarios
✅ Error Handling: 25+ negative cases
```

#### Load Testing Results
```
📊 Response Time: <100ms (p95) for CRUD operations
📊 Throughput: >100 requests/second per endpoint
📊 Error Rate: <1% under normal load
📊 Resource Usage: Acceptable memory and CPU utilization
```

### Troubleshooting Common Issues

#### Test Environment Issues
```bash
# Database connection issues
export DATABASE_URL="sqlite:///test_llm_eval.db"
python -c "from llm_eval.storage.database import get_database_manager; print('✅ DB connection OK')"

# Missing dependencies
pip install -e ".[dev]"
cd frontend && npm install
```

#### API Server Issues
```bash
# Start API server for testing
python -m llm_eval.api.main &
API_PID=$!

# Run tests
python -m pytest tests/integration/

# Clean up
kill $API_PID
```

## Quality Gates

### Acceptance Criteria
- ✅ All frontend component tests pass (100%)
- ✅ All backend integration tests pass (100%)  
- ✅ End-to-end workflow tests complete successfully
- ✅ Load tests execute without errors
- ✅ Test coverage >80% on new components
- ✅ Performance benchmarks met

### Performance Thresholds
- API response time <100ms (p95)
- Frontend component render time <50ms
- Database query time <10ms average
- Load test error rate <1%

## Next Steps

### Sprint 3 Week 2 Testing
1. Execute complete test suite before deployment
2. Run production-scale load testing
3. Validate performance benchmarks
4. Update CI/CD pipeline with new tests

### Continuous Improvement
1. Add visual regression testing
2. Enhance accessibility testing
3. Implement chaos engineering tests
4. Add security testing scenarios

---

**Last Updated**: January 2025  
**Version**: Sprint 3 Week 1  
**Maintained by**: QA Engineering Team