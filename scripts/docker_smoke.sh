#!/usr/bin/env bash
# Smoke-test the HalalLens images without a database, vendors or an LLM.
#
#   scripts/docker_smoke.sh <api-image> <ui-image> <scheduler-image>
#
# The scheduler role runs from the API image; pass it twice.
#
# Proves the images start and serve, not that a deployment works: there is no
# Postgres or MinIO here, so DB-backed routes are expected to return 503.
# Used by the `docker` CI job and, later, before publishing a release.
set -euo pipefail

API_IMAGE=${1:?api image}
UI_IMAGE=${2:?ui image}
SCHEDULER_IMAGE=${3:?scheduler image}
API_PORT=${API_PORT:-18001}
UI_PORT=${UI_PORT:-13000}

cleanup() { docker rm -f hl-smoke-api hl-smoke-ui >/dev/null 2>&1 || true; }
trap cleanup EXIT

wait_for() {  # url seconds
  for _ in $(seq 1 "$2"); do
    curl -sf -o /dev/null "$1" && return 0
    sleep 1
  done
  echo "Timed out waiting for $1" >&2
  return 1
}

expect() {  # label expected-status curl-args...
  local label=$1 want=$2 got
  shift 2
  got=$(curl -s -o /dev/null -w '%{http_code}' "$@")
  if [ "$got" != "$want" ]; then
    echo "FAIL $label: HTTP $got, expected $want" >&2
    return 1
  fi
  echo "ok   $label ($got)"
}

echo "== API ($API_IMAGE)"
user=$(docker run --rm "$API_IMAGE" id -u)
[ "$user" != "0" ] || { echo "FAIL the API image runs as root" >&2; exit 1; }
echo "ok   runs as uid $user (not root)"
# Unresolvable hosts: the API must start and degrade, not hang or crash.
docker run -d --name hl-smoke-api -p "$API_PORT:8001" \
  -e POSTGRES_HOST=db.invalid -e MINIO_HOST=minio.invalid \
  -e NARRATOR_MODE=rule -e RATE_LIMIT_ENABLED=false \
  "$API_IMAGE" >/dev/null
wait_for "http://127.0.0.1:$API_PORT/health" 60 || { docker logs hl-smoke-api; exit 1; }
expect "GET /health" 200 "http://127.0.0.1:$API_PORT/health"
expect "GET /openapi.json" 200 "http://127.0.0.1:$API_PORT/openapi.json"
expect "POST /halal-score" 200 -H 'Content-Type: application/json' \
  -d '{"snapshot":{"symbol":"ABC","filing_date":"2026-01-01T00:00:00"},"market_data":{"market_cap":1000}}' \
  "http://127.0.0.1:$API_PORT/halal-score"
expect "GET /filings/recent without a database" 503 "http://127.0.0.1:$API_PORT/filings/recent"

echo "== UI ($UI_IMAGE)"
docker run -d --name hl-smoke-ui -p "$UI_PORT:3000" "$UI_IMAGE" >/dev/null
wait_for "http://127.0.0.1:$UI_PORT/" 60 || { docker logs hl-smoke-ui; exit 1; }
expect "GET /" 200 "http://127.0.0.1:$UI_PORT/"
expect "GET /login/" 200 "http://127.0.0.1:$UI_PORT/login/"
asset=$(curl -s "http://127.0.0.1:$UI_PORT/" | grep -o '/_next/static/[^"]*\.js' | head -n 1)
[ -n "$asset" ] || { echo "FAIL no script asset referenced by /" >&2; exit 1; }
expect "GET $asset" 200 "http://127.0.0.1:$UI_PORT$asset"

echo "== Scheduler ($SCHEDULER_IMAGE)"
# Imports only: starting a cycle would try to reach BSE and the database.
docker run --rm -e POSTGRES_HOST=db.invalid "$SCHEDULER_IMAGE" python -c \
  "import jobs.ingestion_cycle, jobs.precompute_evaluations, jobs.ingestion_health, jobs.evaluation_health"
echo "ok   scheduler job modules import"

echo "Smoke test passed."
