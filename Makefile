.PHONY: help install dev test lint format clean compose-up compose-down smoke-check frontend-smoke frontend-smoke-ci backend-smoke-ci cloud-smoke infra-check dagster mlflow api frontend frontend-test frontend-build frontend-bundle-check rc-start rc-stop rc-status rc-attach

FRONTEND_SMOKE_IMAGE ?= shiro-frontend-smoke
FRONTEND_SMOKE_PORT ?= 8080
RC_SESSION ?= claude-rc-$(notdir $(CURDIR))
RC_ARGS ?=
RC_STOP_TIMEOUT ?= 10

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
	@echo "  make rc-start      Start Claude Remote Control in a detached tmux session (no-op if running; RC_ARGS=\"...\")"
	@echo "  make rc-stop       Stop Claude Remote Control: Ctrl-C first, kill after RC_STOP_TIMEOUT=$(RC_STOP_TIMEOUT)s (no-op if stopped)"
	@echo "  make rc-status     Show whether the Remote Control tmux session ($(RC_SESSION)) is running"
	@echo "  make rc-attach     Attach to the Remote Control tmux session"
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

# `=` 前綴讓 tmux 精確比對名稱，避免 claude-rc-x 誤配到 claude-rc-xy。
# claude 直接當 session 的主程序：claude 結束 session 即消失，session 存在與否就代表是否在跑。
# env -u CLAUDECODE：從 Claude Code 內呼叫 make 時，避免子程序被判定為巢狀 session。
rc-start:
	@if tmux has-session -t '=$(RC_SESSION)' 2>/dev/null; then \
		echo "Remote Control already running in tmux session '$(RC_SESSION)'"; \
	else \
		tmux new-session -d -s '$(RC_SESSION)' -c '$(CURDIR)' "env -u CLAUDECODE claude remote-control $(RC_ARGS)" && \
		echo "Started Remote Control in tmux session '$(RC_SESSION)' (make rc-attach to view)"; \
	fi

# 先送 Ctrl-C 讓 Remote Control 正常結束並向 claude.ai 註銷，逾時才強制 kill-session。
rc-stop:
	@if ! tmux has-session -t '=$(RC_SESSION)' 2>/dev/null; then \
		echo "Remote Control not running (no tmux session '$(RC_SESSION)')"; \
		exit 0; \
	fi; \
	tmux send-keys -t '=$(RC_SESSION):' C-c; \
	for _ in $$(seq $(RC_STOP_TIMEOUT)); do \
		tmux has-session -t '=$(RC_SESSION)' 2>/dev/null || { echo "Stopped Remote Control"; exit 0; }; \
		sleep 1; \
	done; \
	tmux kill-session -t '=$(RC_SESSION)' 2>/dev/null || true; \
	echo "Remote Control did not exit within $(RC_STOP_TIMEOUT)s; killed tmux session '$(RC_SESSION)'"

rc-status:
	@if tmux has-session -t '=$(RC_SESSION)' 2>/dev/null; then \
		echo "running: tmux session '$(RC_SESSION)'"; \
	else \
		echo "stopped"; \
	fi

rc-attach:
	tmux attach-session -t '=$(RC_SESSION)'

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build .dagster_home mlruns
	find . -type d -name "__pycache__" -exec rm -rf {} +
