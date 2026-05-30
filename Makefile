.DEFAULT_GOAL := help
PYTHON        := python3
SRC           := src
TESTS         := tests
DOCKER_IMAGE  := react-agent

.PHONY: help install dev down lint format typecheck test test-unit test-int \
        security audit all-checks build schema run trace clean bump

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Environment ──────────────────────────────────────────────────────────────

install: ## Install dependencies + pre-commit hooks
	uv sync --all-extras
	pre-commit install --install-hooks
	@echo "✓ Environment ready"

# ── Docker ───────────────────────────────────────────────────────────────────

dev: ## Start all services (API + Qdrant + Prometheus + Grafana)
	docker compose up -d
	@echo "✓ Services started — API: http://localhost:8000 | Qdrant: http://localhost:6333"

down: ## Stop all services
	docker compose down

build: ## Build Docker images
	docker compose build

# ── Code quality ─────────────────────────────────────────────────────────────

lint: ## Run ruff linter
	uv run ruff check $(SRC) tests/
	uv run ruff format --check $(SRC) tests/

format: ## Auto-fix lint issues and format code
	uv run ruff check --fix $(SRC) tests/
	uv run ruff format $(SRC) tests/

typecheck: ## Run mypy strict type checking
	uv run mypy $(SRC)/

# ── Tests ─────────────────────────────────────────────────────────────────────

test: test-unit ## Run unit tests with coverage (default)

test-unit: ## Run unit tests only (fast, no external services)
	uv run pytest $(TESTS)/unit/ -m "not integration and not slow" \
		--cov=$(SRC) --cov-report=term-missing --cov-fail-under=80 -v

test-int: ## Run integration tests (requires running services)
	uv run pytest $(TESTS)/integration/ -v --timeout=60

test-all: ## Run all tests (unit + integration)
	uv run pytest $(TESTS)/ -v

# ── Security ─────────────────────────────────────────────────────────────────

security: ## Run bandit (SAST) + safety + pip-audit
	uv run bandit -r $(SRC)/ -c pyproject.toml
	uv run safety check
	uv run pip-audit

secrets-scan: ## Scan for accidentally committed secrets
	uv run detect-secrets scan --all-files > .secrets.baseline

# ── Full check suite ──────────────────────────────────────────────────────────

all-checks: lint typecheck test-unit security ## Run all quality checks (CI equivalent)
	@echo "✓ All checks passed"

# ── API schema ────────────────────────────────────────────────────────────────

schema: ## Export OpenAPI schema to openapi.json
	uv run python scripts/export_schema.py
	@echo "✓ Schema exported to openapi.json"

# ── Runtime ──────────────────────────────────────────────────────────────────

run: ## Submit a task to the agent (GOAL="...your goal...")
	@[ -n "$(GOAL)" ] || (echo "Usage: make run GOAL=\"your goal here\"" && exit 1)
	uv run python scripts/run_task.py --goal "$(GOAL)"

trace: ## Inspect a task trace (ID="...")
	@[ -n "$(ID)" ] || (echo "Usage: make trace ID=\"<task-id>\"" && exit 1)
	uv run python scripts/inspect_trace.py --id "$(ID)"

server: ## Start API server locally (without Docker)
	uv run uvicorn agent.api.main:app --reload --host 0.0.0.0 --port 8000

# ── Versioning ────────────────────────────────────────────────────────────────

bump: ## Bump version (commitizen) — prompts for version type
	uv run cz bump --changelog
	@echo "✓ Version bumped and CHANGELOG.md updated"

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean: ## Remove build artifacts, caches, and coverage files
	find . -type d -name __pycache__ | xargs rm -rf
	find . -type d -name .mypy_cache | xargs rm -rf
	find . -type d -name .ruff_cache | xargs rm -rf
	find . -type d -name .pytest_cache | xargs rm -rf
	find . -type f -name "*.pyc" | xargs rm -f
	rm -f .coverage coverage.xml openapi.json
	@echo "✓ Cleaned"
