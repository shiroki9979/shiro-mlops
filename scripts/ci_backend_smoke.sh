#!/usr/bin/env bash
# Build the backend images from docker/docker-compose.yml, start the API and MLflow with the
# TimescaleDB and Redis they depend on, and check them with scripts/smoke_backend.py. Catches
# failures that only show inside the containers: DDL initialisation, TimescaleDB connection and
# MLflow startup. The dagster-webserver image is built but not started; nothing here checks it.
# Shared by CI and `make backend-smoke-ci`. Uses its own Compose project and volumes, which it
# removes on exit, but the fixed container names and host ports in docker/docker-compose.yml
# mean the local full stack must be stopped first.
#
# Usage: scripts/ci_backend_smoke.sh
set -euo pipefail

if (($# != 0)); then
  echo "Usage: $0" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly PROJECT="shiro-backend-smoke"
readonly -a COMPOSE=(docker compose -p "$PROJECT" -f "${REPO_ROOT}/docker/docker-compose.yml")
readonly -a IMAGES=(api mlflow dagster-webserver)
readonly -a SERVICES=(api mlflow)
# MLflow migrates its schema in TimescaleDB on first start, which takes the longest.
readonly WAIT_SECONDS=180
# Must match the host ports the api and mlflow services publish in docker/docker-compose.yml.
readonly API_URL="http://127.0.0.1:8000"
readonly MLFLOW_URL="http://127.0.0.1:5001"

main() {
  trap cleanup EXIT

  echo "==> Building backend images: ${IMAGES[*]}"
  "${COMPOSE[@]}" build "${IMAGES[@]}"

  echo "==> Starting ${SERVICES[*]} and their dependencies"
  "${COMPOSE[@]}" up -d "${SERVICES[@]}"

  echo "==> Checking API data status, API readiness and MLflow health"
  if ! uv run --no-project python "${REPO_ROOT}/scripts/smoke_backend.py" \
    --api-url "$API_URL" --mlflow-url "$MLFLOW_URL" --wait-seconds "$WAIT_SECONDS"; then
    print_diagnostics
    exit 1
  fi

  echo "Backend CI smoke passed"
}

print_diagnostics() {
  echo "--- docker compose ps" >&2
  "${COMPOSE[@]}" ps --all >&2
  echo "--- docker compose logs" >&2
  "${COMPOSE[@]}" logs --no-color >&2
}

cleanup() {
  local status=$?
  "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || status=1
  exit "$status"
}

main
