.PHONY: help install dev test lint format clean compose-up compose-down smoke-check frontend-smoke dagster mlflow api frontend frontend-test frontend-build

help:
	@echo "Available commands:"
	@echo "  make install       Install dependencies using uv"
	@echo "  make dev           Run FastAPI locally in development mode"
	@echo "  make frontend      Run React 19 SPA frontend dashboard locally"
	@echo "  make frontend-test Run frontend Vitest test suite"
	@echo "  make dagster       Run Dagster webserver locally"
	@echo "  make mlflow        Run MLflow UI locally"
	@echo "  make test          Run Python test suite with pytest"
	@echo "  make lint          Check code style and lint with ruff"
	@echo "  make format        Format code with ruff"
	@echo "  make compose-up    Start full local stack with built frontend preview"
	@echo "  make compose-down  Stop full local stack"
	@echo "  make smoke-check   Verify schedules and per-task training/monitoring readiness in the Dagster container"
	@echo "  make frontend-smoke Verify built SPA and same-origin API routing through Nginx"
	@echo "  make clean         Clean temporary files and caches"

install:
	uv sync --all-extras

dev:
	uv run uvicorn shiro_mlops.service.api:app --reload --host 0.0.0.0 --port 8000

frontend:
	pnpm --dir frontend run dev

frontend-test:
	pnpm --dir frontend run test

frontend-build:
	pnpm --dir frontend run build

dagster:
	DAGSTER_HOME=.dagster_home uv run dagster dev -f src/shiro_mlops/pipelines/definitions.py

mlflow:
	uv run mlflow server --backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlruns --port 5001

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

compose-up:
	docker compose --env-file .env -f docker/docker-compose.yml up -d

compose-down:
	docker compose -f docker/docker-compose.yml down

# ARGS=--require-ready 會在冷啟動累積未完成時也回傳非零。
smoke-check:
	docker compose -f docker/docker-compose.yml exec dagster-webserver \
		python -m shiro_mlops.pipelines.smoke_check $(ARGS)

frontend-smoke:
	python3 scripts/smoke_nginx.py $(ARGS)

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build .dagster_home mlruns
	find . -type d -name "__pycache__" -exec rm -rf {} +
