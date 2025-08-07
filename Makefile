# LLM Evaluation Framework - Development Commands

.PHONY: help install install-dev test test-unit test-integration test-performance test-all clean lint format security check-all build docs

# Default target
help:
	@echo "Available commands:"
	@echo "  install         Install package for production"
	@echo "  install-dev     Install package with development dependencies"
	@echo "  test            Run all tests"
	@echo "  test-unit       Run unit tests only"
	@echo "  test-integration Run integration tests only"
	@echo "  test-performance Run performance benchmarks"
	@echo "  test-all        Run all tests with coverage"
	@echo "  lint            Run code linting"
	@echo "  format          Format code with black and isort"
	@echo "  security        Run security checks"
	@echo "  check-all       Run all quality checks"
	@echo "  clean           Clean up temporary files"
	@echo "  build           Build package distributions"
	@echo "  docs            Generate documentation"

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

# Quick setup for new contributors
setup-contributor: install-dev install-hooks
	@echo "✅ Contributor environment setup complete!"
	@echo "Next steps:"
	@echo "  1. Run 'make test' to verify everything works"
	@echo "  2. Run 'make check-all' to run full quality checks"
	@echo "  3. Use 'make pre-commit' before committing changes"