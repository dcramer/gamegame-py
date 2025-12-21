.PHONY: dev dev-all backend frontend worker install up down clean migrate db-reset

# Development
dev: ## Start frontend and backend servers
	@command -v overmind >/dev/null 2>&1 && overmind start -f Procfile.dev || honcho start -f Procfile.dev

dev-all: ## Start all services (including worker)
	@command -v overmind >/dev/null 2>&1 && overmind start || honcho start

backend: ## Start backend server only
	cd backend && uv run uvicorn gamegame.main:app --reload --port 8000

frontend: ## Start frontend server only
	cd frontend && npm run dev

worker: ## Start background worker
	cd backend && uv run python -m gamegame.worker

# Database
migrate: ## Run database migrations
	cd backend && uv run alembic upgrade head

db-reset: ## Reset database (destructive!)
	cd backend && uv run alembic downgrade base && uv run alembic upgrade head

# Docker services
up: ## Start Docker services (PostgreSQL, Redis)
	docker compose up -d

down: ## Stop Docker services
	docker compose down

# Setup
install: ## Initial project setup
	./scripts/bootstrap.sh

clean: ## Clean build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .venv -exec rm -rf {} + 2>/dev/null || true
	rm -rf frontend/build frontend/dist 2>/dev/null || true
