#!/usr/bin/env bash
# Build the backend images from docker/docker-compose.yml, start the API and MLflow with the
# TimescaleDB and Redis they depend on, and check them with scripts/smoke_backend.py. Catches
# failures that only show inside the containers: DDL initialisation, TimescaleDB connection and
# MLflow startup. The API's own DDL initialisation is checked in its log: the postgres service
# also runs the DDL from its init directory, so /data/status alone still passes when the API
# image cannot. The dagster-webserver image is built but not started; nothing here checks it.
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
# Must match the message `lifespan` in src/shiro_mlops/service/api.py logs when init_db() fails.
readonly API_DDL_FAILURE="Database initialization failed"

main() {
  trap cleanup EXIT

  echo "==> Building backend images: ${IMAGES[*]}"
  "${COMPOSE[@]}" build "${IMAGES[@]}"

  echo "==> Starting ${SERVICES[*]} and their dependencies"
  "${COMPOSE[@]}" up -d "${SERVICES[@]}"

  echo "==> Checking API data status, API readiness and MLflow health"
  uv run --no-project python "${REPO_ROOT}/scripts/smoke_backend.py" \
    --api-url "$API_URL" --mlflow-url "$MLFLOW_URL" --wait-seconds "$WAIT_SECONDS"

  echo "==> Checking the API initialised the database schema itself"
  # The log is read before it is searched, not piped into grep: under pipefail a failing
  # `docker compose logs` makes the whole pipeline false, which is this check's passing
  # branch, so the failure it looks for would go unreported.
  local api_log
  api_log="$("${COMPOSE[@]}" logs --no-color api)"
  if grep --fixed-strings "$API_DDL_FAILURE" <<<"$api_log" >&2; then
    echo "API log reports \"${API_DDL_FAILURE}\"" >&2
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

# Runs on every exit, so a failed build or start prints the same diagnostics as a failed check.
cleanup() {
  local status=$?
  if ((status != 0)); then
    print_diagnostics || true
  fi
  "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || status=1
  exit "$status"
}

main
