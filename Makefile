# LLM Evaluation Framework - Development Commands

.PHONY: help install install-dev test test-unit test-integration test-performance test-all clean lint format security check-all build docs

# Default target
help:
	@echo "LLM-Eval Development Commands"
	@echo "============================="
	@echo ""
	@echo "🚀 Quick Start:"
	@echo "  setup-contributor       Set up development environment"
	@echo "  test                     Run all tests"
	@echo "  check-all               Run all quality checks"
	@echo ""
	@echo "📦 Installation:"
	@echo "  install                 Install package for production"
	@echo "  install-dev             Install with development dependencies"
	@echo "  install-all             Install with all optional dependencies"
	@echo ""
	@echo "🧪 Testing:"
	@echo "  test                    Run all tests"
	@echo "  test-unit               Run unit tests only"
	@echo "  test-integration        Run integration tests only"
	@echo "  test-performance        Run performance benchmarks"
	@echo "  test-all                Run all tests with coverage"
	@echo "  test-parallel           Run tests in parallel"
	@echo "  test-fast               Run tests with fail-fast"
	@echo ""
	@echo "🔍 Code Quality:"
	@echo "  lint                    Run code linting"
	@echo "  format                  Format code with black and isort"
	@echo "  format-check            Check code formatting"
	@echo "  security                Run security checks"
	@echo "  check-all               Run all quality checks"
	@echo ""
	@echo "🔄 CI/CD Commands:"
	@echo "  ci-quality-backend      Backend quality checks (CI equivalent)"
	@echo "  ci-quality-frontend     Frontend quality checks (CI equivalent)"
	@echo "  ci-test-backend         Backend tests (CI equivalent)"
	@echo "  ci-test-frontend        Frontend tests (CI equivalent)"
	@echo "  ci-integration          Integration tests (CI equivalent)"
	@echo ""
	@echo "🛠️ Development:"
	@echo "  pre-commit              Run pre-commit checks"
	@echo "  setup-precommit         Install pre-commit hooks"
	@echo "  run-api                 Start the API server"
	@echo "  run-frontend            Start the frontend dev server"
	@echo "  run-all                 Start both API and frontend"
	@echo ""
	@echo "🏗️ Build & Release:"
	@echo "  build                   Build package distributions"
	@echo "  clean                   Clean up temporary files"
	@echo "  check-release           Verify package ready for release"
	@echo ""
	@echo "🐳 Docker:"
	@echo "  docker-build            Build Docker images"
	@echo "  docker-test             Run tests in Docker"
	@echo ""
	@echo "ℹ️ Info:"
	@echo "  env-info                Show environment information"
	@echo "  docs                    Generate documentation"

# Installation commands
install:
	pip install -e .

install-dev:
	pip install -e .[dev]

install-all:
	pip install -e .[all,dev]

# Testing commands
test:
	pytest tests/ -v --tb=short

test-unit:
	pytest tests/unit/ -v --tb=short -m "unit"

test-integration:
	pytest tests/integration/ -v --tb=short -m "integration"

test-performance:
	pytest tests/performance/ -v --tb=short -m "performance"

test-all:
	pytest tests/ -v \
		--cov=llm_eval \
		--cov-report=html \
		--cov-report=term-missing \
		--cov-report=xml \
		--cov-fail-under=80 \
		--tb=short

test-parallel:
	pytest tests/ -v --tb=short -n auto

test-fast:
	pytest tests/unit/ tests/integration/ -v --tb=short -x --ff

# Code quality commands
lint:
	flake8 llm_eval tests --count --show-source --statistics
	mypy llm_eval --ignore-missing-imports --no-strict-optional

format:
	black llm_eval tests
	isort llm_eval tests

format-check:
	black --check llm_eval tests
	isort --check-only llm_eval tests

# Security commands
security:
	bandit -r llm_eval -f json -o bandit-report.json || true
	safety check

# Quality gates
check-all: format-check lint security test-all
	@echo "✅ All quality checks passed!"

# Cleanup commands
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf build/
	rm -rf dist/
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf coverage.xml
	rm -rf bandit-report.json
	rm -rf performance_report.json

# Build commands
build: clean
	python -m build

build-dev: clean
	python setup.py sdist bdist_wheel

# Documentation
docs:
	@echo "Documentation generation not implemented yet"

# Development workflow commands
dev-setup: install-dev
	@echo "Development environment setup complete!"
	@echo "Run 'make test' to verify everything works."

pre-commit: format lint test-fast
	@echo "✅ Pre-commit checks passed!"

ci-test: check-all
	@echo "✅ CI pipeline checks passed!"

# Performance monitoring
benchmark: test-performance
	@echo "Performance benchmarks completed."
	@echo "Check benchmark_results/ for detailed reports."

# Continuous testing
watch:
	@echo "Watching for changes... (requires entr: pip install entr)"
	find llm_eval tests -name "*.py" | entr -c make test-fast

# Application running commands
run-api:
	python -m llm_eval.api.main

run-frontend:
	cd frontend && npm run dev

run-all:
	@echo "Starting API server and frontend..."
	@make -j 2 run-api run-frontend

# Docker commands (if needed)
docker-build:
	docker build -t llm-eval:latest .
	cd frontend && docker build -t llm-eval-frontend:latest .

docker-test:
	docker run --rm llm-eval:latest make test

docker-compose-up:
	docker-compose up -d

docker-compose-down:
	docker-compose down

# Release commands
check-release: clean check-all build
	twine check dist/*
	@echo "✅ Release checks passed!"

# Development utilities
install-hooks:
	@echo "Setting up pre-commit hooks..."
	@echo "#!/bin/bash" > .git/hooks/pre-commit
	@echo "make pre-commit" >> .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "✅ Pre-commit hooks installed!"

# Environment info
env-info:
	@echo "Environment Information:"
	@echo "Python version: $$(python --version)"
	@echo "Pip version: $$(pip --version)"
	@echo "Current directory: $$(pwd)"
	@python -c "import llm_eval; print(f'LLM-Eval version: {llm_eval.__version__ if hasattr(llm_eval, \"__version__\") else \"dev\"}')" 2>/dev/null || echo "LLM-Eval not installed"

# CI/CD specific commands
ci-install-backend:
	pip install -e .[dev,all]

ci-install-frontend:
	cd frontend && npm ci

ci-quality-backend: format-check lint
	@echo "✅ Backend quality checks passed!"

ci-quality-frontend:
	cd frontend && npm run lint && npm run format:check && npm run type-check
	@echo "✅ Frontend quality checks passed!"

ci-test-backend: test-all
	@echo "✅ Backend tests passed!"

ci-test-frontend:
	cd frontend && npm run build
	@echo "✅ Frontend build passed!"

ci-integration:
	@echo "Running end-to-end integration tests..."
	python -m llm_eval.api.main &
	sleep 10
	curl -f http://localhost:8000/health || exit 1
	pkill -f "llm_eval.api.main" || true
	@echo "✅ Integration tests passed!"

# Pre-commit hooks setup
setup-precommit:
	@echo "Installing pre-commit hooks..."
	pip install pre-commit
	pre-commit install --install-hooks
	@echo "✅ Pre-commit hooks installed!"

# Quick setup for new contributors
setup-contributor: install-dev setup-precommit
	@echo "✅ Contributor environment setup complete!"
	@echo "Next steps:"
	@echo "  1. Run 'make test' to verify everything works"
	@echo "  2. Run 'make check-all' to run full quality checks"
	@echo "  3. Use 'make pre-commit' before committing changes"
	@echo ""
	@echo "CI/CD Commands:"
	@echo "  make ci-quality-backend   - Backend quality checks (CI equivalent)"
	@echo "  make ci-quality-frontend  - Frontend quality checks (CI equivalent)" 
	@echo "  make ci-test-backend     - Backend tests (CI equivalent)"
	@echo "  make ci-test-frontend    - Frontend tests (CI equivalent)"
	@echo "  make ci-integration      - Integration tests (CI equivalent)"