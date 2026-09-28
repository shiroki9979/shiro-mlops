#!/usr/bin/env bash
set -euo pipefail

container="pagination-acceptance-$$"
container_started=false
cleanup() {
  status=$?
  if [[ "$container_started" == true ]]; then
    docker rm -f "$container" >/dev/null || status=1
  fi
  exit "$status"
}
trap cleanup EXIT

docker run --rm -d --name "$container" \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=pagination_acceptance \
  -p 127.0.0.1::5432 \
  timescale/timescaledb:latest-pg15 >/dev/null
container_started=true

# The image's init step runs a temporary server on the Unix socket only, then restarts;
# probing over TCP waits for the final server instead of the temporary one.
for attempt in {1..30}; do
  if docker exec "$container" pg_isready -h 127.0.0.1 -U postgres -d pagination_acceptance >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" pg_isready -h 127.0.0.1 -U postgres -d pagination_acceptance >/dev/null

port="$(docker port "$container" 5432/tcp | sed 's/.*://')"
DATA_EXPLORER_TIMESCALE_URI="postgresql+psycopg2://postgres:postgres@127.0.0.1:${port}/pagination_acceptance" \
  uv run pytest tests/integration/test_data_explorer_timescaledb*.py -q
