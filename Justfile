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

# Start web development server with auto-reload
dev:
    @echo "🚀 Starting Secret AGI development server with auto-reload..."
    @echo "🌐 Web interface: http://localhost:8000"
    @echo "📝 Auto-reloads on source code changes"
    @echo "⏹️  Press Ctrl+C to stop"
    @echo ""
    uv run uvicorn secret_agi.api.simple_api:app --host 0.0.0.0 --port 8000 --reload --reload-dir secret_agi --log-level info

# Database migration commands
db-init:
    uv run alembic init alembic

# Create a new database migration
db-migration MESSAGE:
    uv run alembic revision --autogenerate -m "{{MESSAGE}}"

# Apply pending migrations
db-upgrade:
    uv run alembic upgrade head

# Downgrade database by one revision
db-downgrade:
    uv run alembic downgrade -1

# Show current migration status
db-status:
    uv run alembic current

# Show migration history
db-history:
    uv run alembic history --verbose

# Reset database (downgrade to base then upgrade)
db-reset:
    uv run alembic downgrade base
    uv run alembic upgrade head

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