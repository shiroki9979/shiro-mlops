#!/usr/bin/env bash
# Smoke-test a built frontend image: Nginx config syntax, both apps (Forecast View at /, Engineering
# Console at /console/) and the `/api` gateway through Nginx,
# then recovery after the API container is recreated. Shared by CI and `make frontend-smoke-ci`;
# the Makefile owns the default image name and host port.
#
# Usage: scripts/ci_nginx_smoke.sh <image> <host-port>
#   host-port  published on loopback only
set -euo pipefail

if (($# != 2)); then
  echo "Usage: $0 <image> <host-port>" >&2
  exit 2
fi

readonly IMAGE="$1"
readonly HOST_PORT="$2"
readonly GATEWAY_TIMEOUT_SECONDS=30
readonly PROBE_TIMEOUT_SECONDS=2
readonly PROBE_INTERVAL_SECONDS=1
readonly STUB_IMAGE="python:3.11-alpine"
# Must match the upstream host in frontend/nginx.conf.
readonly API_ALIAS="api"
# Must match `listen` in frontend/nginx.conf.
readonly NGINX_PORT=80
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
readonly RUN_ID="nginx-smoke-$$"
readonly NETWORK="shiro-${RUN_ID}"
readonly GATEWAY="shiro-${RUN_ID}-gateway"
readonly API_FIRST="shiro-${RUN_ID}-api-first"
readonly API_NEXT="shiro-${RUN_ID}-api-next"
readonly -a CONTAINERS=("$GATEWAY" "$API_FIRST" "$API_NEXT")
readonly BASE_URL="http://127.0.0.1:${HOST_PORT}"

main() {
  require_port

  echo "==> Checking Nginx configuration without an API upstream"
  docker run --rm "$IMAGE" nginx -t

  trap cleanup EXIT
  docker network create "$NETWORK" >/dev/null

  echo "==> Starting stub API and gateway (${IMAGE} on ${BASE_URL})"
  start_stub_api "$API_FIRST"
  docker run -d --name "$GATEWAY" --network "$NETWORK" \
    -p "127.0.0.1:${HOST_PORT}:${NGINX_PORT}" "$IMAGE" >/dev/null
  wait_for_gateway

  echo "==> Checking both apps and API gateway"
  # Same invocation as `make frontend-smoke`; keep the two in sync.
  uv run --no-project python "${REPO_ROOT}/scripts/smoke_nginx.py" \
    --base-url "$BASE_URL" --expected-upstream-path /health

  echo "==> Checking gateway recovery after API container recreation"
  # The replacement starts before the original is removed so it cannot reuse the same IP;
  # the gateway then only recovers if Nginx re-resolves `api` instead of caching its first IP.
  start_stub_api "$API_NEXT"
  docker rm -f "$API_FIRST" >/dev/null
  wait_for_gateway

  echo "Nginx CI smoke passed"
}

require_port() {
  if [[ ! "$HOST_PORT" =~ ^[0-9]+$ ]]; then
    echo "Invalid host port: ${HOST_PORT}" >&2
    exit 2
  fi
}

start_stub_api() {
  docker run -d --name "$1" --network "$NETWORK" --network-alias "$API_ALIAS" \
    -v "${REPO_ROOT}/scripts/stub_api.py:/stub_api.py:ro" \
    "$STUB_IMAGE" python /stub_api.py >/dev/null
}

wait_for_gateway() {
  local deadline=$((SECONDS + GATEWAY_TIMEOUT_SECONDS))
  while ((SECONDS < deadline)); do
    if curl --fail --silent --max-time "$PROBE_TIMEOUT_SECONDS" "${BASE_URL}/api/health" >/dev/null; then
      return 0
    fi
    sleep "$PROBE_INTERVAL_SECONDS"
  done
  echo "Gateway ${BASE_URL}/api/health did not respond within ${GATEWAY_TIMEOUT_SECONDS} seconds" >&2
  print_container_logs
  return 1
}

print_container_logs() {
  local container
  for container in "${CONTAINERS[@]}"; do
    if container_exists "$container"; then
      echo "--- docker logs ${container}" >&2
      docker logs "$container" >&2
    fi
  done
}

cleanup() {
  local status=$?
  local container
  for container in "${CONTAINERS[@]}"; do
    if container_exists "$container"; then
      docker rm -f "$container" >/dev/null || status=1
    fi
  done
  if docker network inspect "$NETWORK" >/dev/null 2>&1; then
    docker network rm "$NETWORK" >/dev/null || status=1
  fi
  exit "$status"
}

container_exists() {
  docker container inspect "$1" >/dev/null 2>&1
}

main
