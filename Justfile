# Secret AGI Development Commands
# Run with: just <command>

# Default recipe - show available commands
default:
    @just --list

# Format code with ruff
fmt:
    uv run ruff format .

# Lint code with ruff
lint:
    uv run ruff check .

# Fix linting issues automatically
fix:
    uv run ruff check --fix .

# Type check with mypy
typecheck:
    uv run mypy .

# Run unit tests
test:
    uv run pytest

# Run tests with verbose output
test-verbose:
    uv run pytest -v

# Run tests with coverage
test-cov:
    uv run pytest --cov=secret_agi --cov-report=term-missing

# Run all quality checks (lint, typecheck, test)
check: lint typecheck test

# Run all quality checks, fix issues, and format code
quality: fix fmt check

# Run game completeness validation
test-completeness:
    uv run python test_completeness.py

# Run a quick random game simulation
demo:
    uv run python -c "from secret_agi.engine.game_engine import run_random_game; print(run_random_game(5))"

# Install dependencies
install:
    uv sync --dev

# Clean up cache files
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete
    rm -rf .pytest_cache
    rm -rf .mypy_cache
    rm -rf .coverage

# Show project status
status:
    @echo "=== Secret AGI Project Status ==="
    @echo "Python version: $(python --version)"
    @echo "UV version: $(uv --version)"
    @echo "Dependencies:"
    @uv tree --depth 1