.PHONY: help install dev test lint format clean compose-up compose-down dagster mlflow api

help:
	@echo "Available commands:"
	@echo "  make install       Install dependencies using uv"
	@echo "  make dev           Run FastAPI locally in development mode"
	@echo "  make frontend      Run Streamlit frontend dashboard locally"
	@echo "  make dagster       Run Dagster webserver locally"
	@echo "  make mlflow        Run MLflow UI locally"
	@echo "  make test          Run test suite with pytest"
	@echo "  make lint          Check code style and lint with ruff"
	@echo "  make format        Format code with ruff"
	@echo "  make compose-up    Start full local stack (Dagster, MLflow, Redis, Postgres)"
	@echo "  make compose-down  Stop full local stack"
	@echo "  make clean         Clean temporary files and caches"

install:
	uv sync --all-extras

dev:
	uv run uvicorn shiro_mlops.service.api:app --reload --host 0.0.0.0 --port 8000

frontend:
	uv run streamlit run frontend/app.py

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
	docker compose -f docker/docker-compose.yml up -d

compose-down:
	docker compose -f docker/docker-compose.yml down

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build .dagster_home mlruns
	find . -type d -name "__pycache__" -exec rm -rf {} +
