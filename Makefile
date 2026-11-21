.PHONY: help install dev test lint format clean compose-up compose-down smoke-check frontend-smoke frontend-smoke-ci backend-smoke-ci cloud-smoke infra-check dagster mlflow api frontend frontend-test frontend-build frontend-bundle-check

FRONTEND_SMOKE_IMAGE ?= shiro-frontend-smoke
FRONTEND_SMOKE_PORT ?= 8080

help:
	@echo "Available commands:"
	@echo "  make install       Install dependencies using uv"
	@echo "  make dev           Run FastAPI locally in development mode"
	@echo "  make frontend      Run the Forecast View and Engineering Console Vite dev servers"
	@echo "  make frontend-test Run frontend Vitest suites and workspace tooling tests"
	@echo "  make frontend-build Type-check and build both frontend apps"
	@echo "  make frontend-bundle-check Verify the built Forecast View carries no Engineering Console trace or /predict call (after frontend-build)"
	@echo "  make dagster       Run Dagster webserver locally"
	@echo "  make mlflow        Run MLflow UI locally"
	@echo "  make test          Run Python test suite with pytest"
	@echo "  make lint          Check code style and lint with ruff"
	@echo "  make format        Format code with ruff"
	@echo "  make compose-up    Rebuild images from current source and start full local stack"
	@echo "  make compose-down  Stop full local stack"
	@echo "  make smoke-check   Verify schedules, per-task readiness and forecast issuing in the Dagster container"
	@echo "  make frontend-smoke Verify both built apps (/, /history, /console/) and same-origin API routing through Nginx"
	@echo "  make frontend-smoke-ci Build the frontend image and run the CI Nginx smoke (FRONTEND_SMOKE_PORT=$(FRONTEND_SMOKE_PORT))"
	@echo "  make backend-smoke-ci Build the backend images, start the API and MLflow, and run the CI backend smoke"
	@echo "  make cloud-smoke   Verify the deployed Forecast View URL (ARGS=\"--base-url <forecast_view_url>\")"
	@echo "  make infra-check   Test CloudFront Functions, then check formatting and validity and run Terraform tests offline for both Terraform layers"
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

frontend-bundle-check:
	node scripts/check_forecast_view_bundle.mjs

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

# API 與前端映像內含原始碼；不帶 --build 時 Compose 沿用既有映像，已合併的修正不會生效。
compose-up:
	docker compose --env-file .env -f docker/docker-compose.yml up -d --build

compose-down:
	docker compose -f docker/docker-compose.yml down

# ARGS=--require-ready 會在冷啟動累積未完成時也回傳非零。
smoke-check:
	docker compose -f docker/docker-compose.yml exec dagster-webserver \
		python -m shiro_mlops.pipelines.smoke_check $(ARGS)

frontend-smoke:
	uv run --no-project python scripts/smoke_nginx.py $(ARGS)

frontend-smoke-ci:
	docker build -t $(FRONTEND_SMOKE_IMAGE) frontend
	scripts/ci_nginx_smoke.sh $(FRONTEND_SMOKE_IMAGE) $(FRONTEND_SMOKE_PORT)

backend-smoke-ci:
	scripts/ci_backend_smoke.sh

cloud-smoke:
	uv run --no-project python scripts/smoke_cloudfront.py $(ARGS)

infra-check:
	scripts/infra_check.sh

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build .dagster_home mlruns
	find . -type d -name "__pycache__" -exec rm -rf {} +
