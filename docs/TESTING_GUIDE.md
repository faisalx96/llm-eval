# 🧪 LLM-Eval Testing Guide

## Overview
Comprehensive guide for testing LLM-Eval components, from unit tests to end-to-end integration tests.

## Table of Contents
- [Testing Philosophy](#testing-philosophy)
- [Test Structure](#test-structure)
- [Running Tests](#running-tests)
- [Unit Testing](#unit-testing)
- [Integration Testing](#integration-testing)
- [End-to-End Testing](#end-to-end-testing)
- [Performance Testing](#performance-testing)
- [Test Coverage](#test-coverage)
- [CI/CD Integration](#cicd-integration)

---

## Testing Philosophy

### Testing Pyramid
```
         /\
        /E2E\        <- End-to-End (5%)
       /------\
      /Integration\   <- Integration (25%)
     /------------\
    /   Unit Tests  \  <- Unit Tests (70%)
   /________________\
```

### Key Principles
1. **Fast Feedback**: Unit tests run in milliseconds
2. **Isolation**: Mock external dependencies
3. **Deterministic**: Same input = same output
4. **Readable**: Tests document behavior
5. **Maintainable**: DRY principles apply

---

## Test Structure

### Directory Layout
```
tests/
├── unit/                    # Unit tests
│   ├── test_evaluator.py
│   ├── test_metrics.py
│   ├── test_storage.py
│   └── test_templates.py
├── integration/             # Integration tests
│   ├── test_api.py
│   ├── test_database.py
│   ├── test_langfuse.py
│   └── test_websocket.py
├── e2e/                     # End-to-end tests
│   ├── test_evaluation_flow.py
│   ├── test_dashboard.py
│   └── test_comparison.py
├── performance/             # Performance tests
│   ├── test_load.py
│   └── test_stress.py
├── fixtures/                # Test data
│   ├── datasets.json
│   ├── responses.json
│   └── mock_llm.py
└── conftest.py             # Shared fixtures
```

### Naming Conventions
```python
# Test files: test_*.py
# Test classes: Test*
# Test methods: test_*

# Good examples:
test_evaluator_handles_async_tasks()
test_api_returns_404_for_missing_run()
test_dashboard_displays_run_list()

# Bad examples:
testEvaluator()  # Not descriptive
check_api()      # Should start with test_
```

---

## Running Tests

### Quick Start
```bash
# Install test dependencies
pip install -e ".[test]"

# Run all tests
pytest

# Run with coverage
pytest --cov=llm_eval --cov-report=html

# Run specific test file
pytest tests/unit/test_evaluator.py

# Run specific test
pytest tests/unit/test_evaluator.py::test_basic_evaluation

# Run tests matching pattern
pytest -k "api" 

# Run with verbose output
pytest -v

# Run in parallel
pytest -n auto
```

### Test Commands
```bash
# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# E2E tests only
pytest tests/e2e/

# Performance tests
pytest tests/performance/ --benchmark-only

# Watch mode (re-run on file changes)
ptw

# Generate HTML report
pytest --html=report.html --self-contained-html
```

---

## Unit Testing

### Testing the Evaluator
```python
# tests/unit/test_evaluator.py
import pytest
from unittest.mock import Mock, patch, AsyncMock
from llm_eval import Evaluator
from llm_eval.core.results import EvaluationResult

class TestEvaluator:
    @pytest.fixture
    def mock_task(self):
        """Mock task function"""
        task = Mock(return_value="response")
        task.__name__ = "mock_task"
        return task
    
    @pytest.fixture
    def mock_dataset(self):
        """Mock Langfuse dataset"""
        return [
            {"input": "question1", "expected_output": "answer1"},
            {"input": "question2", "expected_output": "answer2"}
        ]
    
    @pytest.fixture
    def evaluator(self, mock_task, mock_dataset):
        """Create evaluator with mocks"""
        with patch('llm_eval.core.evaluator.fetch_dataset') as mock_fetch:
            mock_fetch.return_value = mock_dataset
            return Evaluator(
                task=mock_task,
                dataset="test-dataset",
                metrics=["exact_match"]
            )
    
    def test_evaluator_initialization(self, evaluator, mock_task):
        """Test evaluator initializes correctly"""
        assert evaluator.task == mock_task
        assert evaluator.dataset_name == "test-dataset"
        assert "exact_match" in evaluator.metrics
    
    def test_basic_evaluation(self, evaluator, mock_task):
        """Test basic evaluation flow"""
        result = evaluator.run()
        
        assert isinstance(result, EvaluationResult)
        assert mock_task.call_count == 2  # Called for each dataset item
        assert result.total_items == 2
        assert result.completed_items <= 2
    
    @pytest.mark.asyncio
    async def test_async_task_evaluation(self):
        """Test evaluation with async task"""
        async_task = AsyncMock(return_value="async response")
        
        with patch('llm_eval.core.evaluator.fetch_dataset') as mock_fetch:
            mock_fetch.return_value = [{"input": "q", "expected_output": "a"}]
            
            evaluator = Evaluator(
                task=async_task,
                dataset="test",
                metrics=["exact_match"]
            )
            result = evaluator.run()
            
            assert async_task.called
            assert result.completed_items == 1
    
    def test_error_handling(self, evaluator):
        """Test error handling during evaluation"""
        evaluator.task.side_effect = Exception("Task failed")
        
        result = evaluator.run()
        
        assert result.failed_items == 2
        assert "Task failed" in str(result.errors[0])
    
    def test_custom_metric(self):
        """Test custom metric function"""
        def custom_metric(output, expected):
            return 1.0 if output == expected else 0.0
        
        with patch('llm_eval.core.evaluator.fetch_dataset') as mock_fetch:
            mock_fetch.return_value = [{"input": "q", "expected_output": "a"}]
            
            evaluator = Evaluator(
                task=Mock(return_value="a"),
                dataset="test",
                metrics=[custom_metric]
            )
            result = evaluator.run()
            
            assert "custom_metric" in result.metrics
            assert result.metrics["custom_metric"]["mean"] == 1.0
```

### Testing Storage Layer
```python
# tests/unit/test_storage.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from llm_eval.storage.models import Base, EvaluationRun, EvaluationItem
from llm_eval.storage.run_repository import RunRepository

class TestRunRepository:
    @pytest.fixture
    def db_session(self):
        """Create in-memory database for testing"""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = Session(engine)
        yield session
        session.close()
    
    @pytest.fixture
    def repository(self, db_session):
        """Create repository with test database"""
        return RunRepository(session=db_session)
    
    def test_create_run(self, repository):
        """Test creating evaluation run"""
        run_data = {
            "name": "Test Run",
            "dataset_name": "test-dataset",
            "project_id": "test-project",
            "metrics_used": ["exact_match"],
            "total_items": 10
        }
        
        run = repository.create_run(**run_data)
        
        assert run.id is not None
        assert run.name == "Test Run"
        assert run.status == "created"
    
    def test_update_run_status(self, repository):
        """Test updating run status"""
        run = repository.create_run(
            name="Test",
            dataset_name="test",
            project_id="test"
        )
        
        updated = repository.update_run(
            run.id,
            status="completed",
            completed_items=10
        )
        
        assert updated.status == "completed"
        assert updated.completed_items == 10
    
    def test_list_runs_with_filters(self, repository):
        """Test listing runs with filters"""
        # Create test runs
        for i in range(5):
            repository.create_run(
                name=f"Run {i}",
                dataset_name="test",
                project_id="project1" if i < 3 else "project2",
                status="completed" if i % 2 == 0 else "running"
            )
        
        # Test project filter
        runs = repository.list_runs(project_id="project1")
        assert len(runs) == 3
        
        # Test status filter
        runs = repository.list_runs(status="completed")
        assert len(runs) == 3
        
        # Test pagination
        runs = repository.list_runs(limit=2, offset=2)
        assert len(runs) == 2
```

### Testing API Endpoints
```python
# tests/unit/test_api.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from llm_eval.api.main import app

class TestAPIEndpoints:
    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)
    
    @pytest.fixture
    def mock_repository(self):
        """Mock repository for testing"""
        with patch('llm_eval.api.endpoints.runs.RunRepository') as mock:
            repo = Mock()
            mock.return_value = repo
            yield repo
    
    def test_health_check(self, client):
        """Test health check endpoint"""
        response = client.get("/api/health/")
        
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    
    def test_list_runs(self, client, mock_repository):
        """Test listing runs"""
        mock_repository.list_runs.return_value = [
            {"id": "123", "name": "Test Run", "status": "completed"}
        ]
        mock_repository.count_runs.return_value = 1
        
        response = client.get("/api/runs/")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["runs"]) == 1
        assert data["runs"][0]["name"] == "Test Run"
    
    def test_get_run_not_found(self, client, mock_repository):
        """Test getting non-existent run"""
        mock_repository.get_run.return_value = None
        
        response = client.get("/api/runs/invalid-id")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_create_run(self, client, mock_repository):
        """Test creating new run"""
        mock_repository.create_run.return_value = Mock(
            id="123",
            name="New Run",
            status="created"
        )
        
        response = client.post("/api/runs/", json={
            "name": "New Run",
            "dataset_name": "test-dataset",
            "project_id": "test-project",
            "metrics": ["exact_match"]
        })
        
        assert response.status_code == 201
        assert response.json()["id"] == "123"
```

---

## Integration Testing

### Testing with Real Database
```python
# tests/integration/test_database.py
import pytest
import os
from sqlalchemy import create_engine
from llm_eval.storage.models import Base
from llm_eval.storage.run_repository import RunRepository

@pytest.mark.integration
class TestDatabaseIntegration:
    @pytest.fixture(scope="class")
    def db_url(self):
        """Use test database"""
        return os.getenv("TEST_DATABASE_URL", "postgresql://test:test@localhost/test_llm_eval")
    
    @pytest.fixture
    def db_engine(self, db_url):
        """Create database engine"""
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
        yield engine
        Base.metadata.drop_all(engine)
    
    def test_concurrent_writes(self, db_engine):
        """Test concurrent database writes"""
        from concurrent.futures import ThreadPoolExecutor
        
        def create_run(i):
            repo = RunRepository(engine=db_engine)
            return repo.create_run(
                name=f"Concurrent Run {i}",
                dataset_name="test",
                project_id="test"
            )
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_run, i) for i in range(100)]
            results = [f.result() for f in futures]
        
        assert len(results) == 100
        assert all(r.id is not None for r in results)
```

### Testing Langfuse Integration
```python
# tests/integration/test_langfuse.py
import pytest
from unittest.mock import patch, Mock
from langfuse import Langfuse
from llm_eval.core.langfuse_integration import fetch_dataset, log_evaluation

@pytest.mark.integration
class TestLangfuseIntegration:
    @pytest.fixture
    def mock_langfuse(self):
        """Mock Langfuse client"""
        with patch('llm_eval.core.langfuse_integration.Langfuse') as mock:
            client = Mock()
            mock.return_value = client
            yield client
    
    def test_fetch_dataset(self, mock_langfuse):
        """Test fetching dataset from Langfuse"""
        mock_langfuse.get_dataset.return_value.items = [
            Mock(input="q1", expected_output="a1"),
            Mock(input="q2", expected_output="a2")
        ]
        
        items = fetch_dataset("test-dataset")
        
        assert len(items) == 2
        assert items[0]["input"] == "q1"
        assert items[1]["expected_output"] == "a2"
    
    def test_log_evaluation_trace(self, mock_langfuse):
        """Test logging evaluation to Langfuse"""
        mock_trace = Mock()
        mock_langfuse.trace.return_value = mock_trace
        
        log_evaluation(
            run_id="123",
            item_id="item-1",
            input_data="question",
            output="answer",
            scores={"exact_match": 1.0}
        )
        
        mock_langfuse.trace.assert_called_once()
        mock_trace.score.assert_called_with(
            name="exact_match",
            value=1.0
        )
```

---

## End-to-End Testing

### Testing Complete Evaluation Flow
```python
# tests/e2e/test_evaluation_flow.py
import pytest
from playwright.sync_api import sync_playwright
from llm_eval import Evaluator

@pytest.mark.e2e
class TestEvaluationFlow:
    def test_complete_evaluation_workflow(self):
        """Test complete evaluation from code to dashboard"""
        # 1. Run evaluation programmatically
        def mock_task(input_text):
            return f"Response to {input_text}"
        
        evaluator = Evaluator(
            task=mock_task,
            dataset="e2e-test-dataset",
            metrics=["exact_match", "f1_score"],
            config={
                "project_id": "e2e-test",
                "run_name": "E2E Test Run"
            }
        )
        
        result = evaluator.run()
        run_id = result.run_id
        
        assert result.completed_items > 0
        
        # 2. Verify run appears in API
        import requests
        response = requests.get(f"http://localhost:8000/api/runs/{run_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "E2E Test Run"
        
        # 3. Verify run appears in dashboard
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            
            # Navigate to dashboard
            page.goto("http://localhost:3000/dashboard")
            
            # Wait for run to appear
            page.wait_for_selector(f"[data-run-id='{run_id}']")
            
            # Click on run to view details
            page.click(f"[data-run-id='{run_id}']")
            
            # Verify details page loads
            page.wait_for_selector(".run-details")
            assert "E2E Test Run" in page.content()
            
            browser.close()
```

### Testing Dashboard UI
```python
# tests/e2e/test_dashboard.py
import pytest
from playwright.sync_api import Page, expect

@pytest.mark.e2e
class TestDashboard:
    @pytest.fixture
    def page(self, browser):
        """Create page for testing"""
        page = browser.new_page()
        page.goto("http://localhost:3000")
        yield page
        page.close()
    
    def test_dashboard_loads(self, page: Page):
        """Test dashboard loads successfully"""
        expect(page).to_have_title("LLM-Eval Dashboard")
        expect(page.locator(".dashboard-header")).to_be_visible()
    
    def test_filtering_runs(self, page: Page):
        """Test filtering runs by status"""
        # Navigate to dashboard
        page.goto("http://localhost:3000/dashboard")
        
        # Apply filter
        page.select_option("select[name='status']", "completed")
        page.wait_for_load_state("network_idle")
        
        # Verify filtered results
        runs = page.locator(".run-card")
        count = runs.count()
        
        for i in range(count):
            status = runs.nth(i).locator(".status-badge").text_content()
            assert status == "completed"
    
    def test_run_comparison(self, page: Page):
        """Test comparing two runs"""
        page.goto("http://localhost:3000/dashboard")
        
        # Select two runs for comparison
        page.check(".run-checkbox:nth-child(1)")
        page.check(".run-checkbox:nth-child(2)")
        
        # Click compare button
        page.click("button:has-text('Compare')")
        
        # Verify comparison view
        page.wait_for_selector(".comparison-view")
        expect(page.locator(".comparison-table")).to_be_visible()
        expect(page.locator(".diff-highlight")).to_have_count(lambda c: c > 0)
```

---

## Performance Testing

### Load Testing
```python
# tests/performance/test_load.py
import pytest
from locust import HttpUser, task, between
import time

class EvaluationUser(HttpUser):
    wait_time = between(1, 3)
    
    @task(3)
    def list_runs(self):
        """Test listing runs endpoint"""
        self.client.get("/api/runs/")
    
    @task(1)
    def get_run_details(self):
        """Test getting run details"""
        # Assuming we have a known run ID
        self.client.get("/api/runs/test-run-id")
    
    @task(2)
    def create_run(self):
        """Test creating new run"""
        self.client.post("/api/runs/", json={
            "name": f"Load Test Run {time.time()}",
            "dataset_name": "load-test",
            "project_id": "load-test",
            "metrics": ["exact_match"]
        })

# Run with: locust -f tests/performance/test_load.py --host=http://localhost:8000
```

### Benchmark Testing
```python
# tests/performance/test_benchmarks.py
import pytest
import time
from llm_eval import Evaluator

@pytest.mark.benchmark
class TestPerformanceBenchmarks:
    def test_evaluation_speed(self, benchmark):
        """Benchmark evaluation speed"""
        def mock_task(input_text):
            return "response"
        
        def run_evaluation():
            evaluator = Evaluator(
                task=mock_task,
                dataset="benchmark-dataset",
                metrics=["exact_match"]
            )
            return evaluator.run()
        
        result = benchmark(run_evaluation)
        assert result.completed_items > 0
    
    def test_storage_write_speed(self, benchmark):
        """Benchmark database write speed"""
        from llm_eval.storage.run_repository import RunRepository
        
        repo = RunRepository()
        
        def create_runs():
            for i in range(100):
                repo.create_run(
                    name=f"Benchmark Run {i}",
                    dataset_name="benchmark",
                    project_id="benchmark"
                )
        
        benchmark(create_runs)
    
    def test_api_response_time(self, benchmark, client):
        """Benchmark API response times"""
        def api_call():
            response = client.get("/api/runs/")
            assert response.status_code == 200
            return response
        
        result = benchmark(api_call)
        
        # Assert performance requirements
        assert benchmark.stats["mean"] < 0.1  # Less than 100ms average
```

---

## Test Coverage

### Coverage Configuration
```ini
# .coveragerc
[run]
source = llm_eval
omit = 
    */tests/*
    */migrations/*
    */config/*
    */__init__.py

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
    if TYPE_CHECKING:

[html]
directory = htmlcov
```

### Running Coverage
```bash
# Run with coverage
pytest --cov=llm_eval --cov-report=term-missing

# Generate HTML report
pytest --cov=llm_eval --cov-report=html
open htmlcov/index.html

# Check coverage threshold
pytest --cov=llm_eval --cov-fail-under=80

# Coverage for specific module
pytest --cov=llm_eval.storage tests/unit/test_storage.py
```

### Coverage Goals
- **Overall**: 80% minimum
- **Core modules**: 90% minimum
- **API endpoints**: 85% minimum
- **Storage layer**: 85% minimum
- **UI components**: 70% minimum

---

## CI/CD Integration

### GitHub Actions
```yaml
# .github/workflows/test.yml
name: Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:13
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_llm_eval
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Cache dependencies
      uses: actions/cache@v3
      with:
        path: ~/.cache/pip
        key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
    
    - name: Install dependencies
      run: |
        pip install -e ".[test]"
    
    - name: Run unit tests
      run: |
        pytest tests/unit/ -v --cov=llm_eval --cov-report=xml
    
    - name: Run integration tests
      env:
        TEST_DATABASE_URL: postgresql://postgres:test@localhost/test_llm_eval
      run: |
        pytest tests/integration/ -v
    
    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml
        fail_ci_if_error: true
    
    - name: Run linting
      run: |
        flake8 llm_eval/
        black --check llm_eval/
        mypy llm_eval/
```

### Pre-commit Hooks
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
  
  - repo: https://github.com/psf/black
    rev: 23.1.0
    hooks:
      - id: black
        language_version: python3.10
  
  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
        args: ['--max-line-length=100']
  
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.0.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
  
  - repo: local
    hooks:
      - id: pytest
        name: pytest
        entry: pytest tests/unit/ --fail-under=80
        language: system
        pass_filenames: false
        always_run: true
```

### Test Automation
```bash
# Makefile
.PHONY: test test-unit test-integration test-e2e coverage lint format

test:
	pytest -v

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-e2e:
	pytest tests/e2e/ -v

coverage:
	pytest --cov=llm_eval --cov-report=html --cov-report=term

lint:
	flake8 llm_eval/
	mypy llm_eval/

format:
	black llm_eval/
	isort llm_eval/

ci: lint test coverage
```

---

## Best Practices

### Test Writing Guidelines
1. **One assertion per test** (when possible)
2. **Use descriptive test names**
3. **Follow AAA pattern**: Arrange, Act, Assert
4. **Mock external dependencies**
5. **Use fixtures for reusable setup**
6. **Test edge cases and error conditions**

### Common Pitfalls to Avoid
- ❌ Testing implementation details
- ❌ Brittle tests that break with refactoring
- ❌ Slow tests that discourage running
- ❌ Flaky tests with race conditions
- ❌ Tests without clear purpose

### Testing Checklist
- [ ] Unit tests for new functions
- [ ] Integration tests for API endpoints
- [ ] Error cases tested
- [ ] Edge cases covered
- [ ] Performance impact considered
- [ ] Documentation updated
- [ ] Coverage maintained above 80%

---

## Troubleshooting

### Common Test Issues

#### Database Connection Errors
```bash
# Ensure test database exists
createdb test_llm_eval

# Check connection
psql -h localhost -U postgres -d test_llm_eval
```

#### Flaky Tests
```python
# Add retry for flaky tests
@pytest.mark.flaky(reruns=3, reruns_delay=2)
def test_sometimes_fails():
    # Test that occasionally fails
    pass
```

#### Slow Tests
```python
# Mark slow tests
@pytest.mark.slow
def test_heavy_computation():
    # Long-running test
    pass

# Skip slow tests during development
pytest -m "not slow"
```

---

**Last Updated:** January 2025  
**Version:** 0.2.5  
**Coverage Target:** 80%+