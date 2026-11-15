.DEFAULT_GOAL := help
.PHONY: help install run logs up down reset-db migrate dev test test-db test-live lint fmt typecheck check smoke-jev case-orders

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install dependencies into .venv
	uv sync

run: ## Build and start the whole stack in Docker (API on http://localhost:8000)
	docker compose up -d --build --wait
	@$(MAKE) --no-print-directory migrate
	@echo "Admin screen: http://localhost:8000/admin/carriers   API docs: http://localhost:8000/docs"

logs: ## Follow the API container logs
	docker compose logs -f app

up: ## Start PostgreSQL only, wait until healthy, apply migrations (for make dev / tests)
	docker compose up -d --wait db
	@$(MAKE) --no-print-directory migrate

down: ## Stop containers (data is kept)
	docker compose down

reset-db: ## Recreate the database from db/init + migrations (DELETES DATA)
	docker compose down -v
	docker compose up -d --wait db
	@$(MAKE) --no-print-directory migrate

migrate: ## Apply the idempotent SQL files in db/migrations (keeps data)
	@for f in db/migrations/*.sql; do \
		[ -e "$$f" ] || continue; \
		echo "applying $$f"; \
		docker compose exec -T db sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' < "$$f" || exit 1; \
	done

dev: up ## Run the API locally with auto-reload on http://localhost:8000
	uv run uvicorn app.main:app --reload

test: ## Fast tests: no database, no network, no Jev
	uv run pytest -m "not db and not live"

test-db: up ## Repository/integration tests against the PostgreSQL container
	uv run pytest -m db

test-live: ## Real Jev / ORS calls (costs tokens or quota; opt-in)
	uv run --env-file .env pytest -m live

lint: ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

fmt: ## Auto-format and auto-fix lint
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## mypy --strict on app/ and scripts/
	uv run mypy

check: lint typecheck test ## Lint + types + fast tests

smoke-jev: ## One tiny Jev call to verify the API key (a few input tokens)
	uv run --env-file .env python scripts/jev_smoke.py

case-orders: ## Send the 7 case orders to the running API and compare with the expected results
	uv run python scripts/run_case_orders.py
