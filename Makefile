.PHONY: install format lint test build publish clean

# Install package with dev dependencies
install:
	pip install -e ".[dev]"

# Format code with ruff
format:
	ruff format src tests
	ruff check --fix src tests

# Lint code
lint:
	ruff check src tests
	ruff format --check src tests
	mypy src

# Run tests with coverage
test:
	pytest tests/ -v --cov=aiogarmin --cov-report=term-missing --cov-report=html

# Run tests without coverage (faster)
test-quick:
	pytest tests/ -v

# Build package
build: clean
	pip install build
	python -m build

# Publish to PyPI
publish: build
	pip install twine
	twine upload dist/*

# Publish to Test PyPI
publish-test: build
	pip install twine
	twine upload --repository testpypi dist/*

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf src/*.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Run all checks (CI simulation)
all: format lint test

# Show help
help:
	@echo "Available targets:"
	@echo "  install       - Install package with dev dependencies"
	@echo "  format        - Format code with ruff"
	@echo "  lint          - Run linting (ruff + mypy)"
	@echo "  test          - Run tests with coverage"
	@echo "  test-quick    - Run tests without coverage"
	@echo "  build         - Build wheel and sdist"
	@echo "  publish       - Publish to PyPI"
	@echo "  publish-test  - Publish to Test PyPI"
	@echo "  clean         - Remove build artifacts"
	@echo "  all           - Run format, lint, and test"
