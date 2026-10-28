#!/usr/bin/env bash
# Test the production routing: Caddy serves the UI at / and the API under /api/
# on one origin, as in docker-compose-prod.yml. No database, no TLS.
#
#   scripts/proxy_smoke.sh <api-image> <ui-image>
#
# The UI image must be built with NEXT_PUBLIC_HALAL_API_BASE_URL=/api (the
# ui.Dockerfile default). Runs from the repository root (copies ./Caddyfile).
set -euo pipefail

API_IMAGE=${1:?api image}
UI_IMAGE=${2:?ui image}
PORT=${PROXY_PORT:-18080}
NET=hl-proxy-smoke
BASE="http://127.0.0.1:$PORT"

cleanup() {
  docker rm -f hl-proxy-api hl-proxy-ui hl-proxy-caddy >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup
docker network create "$NET" >/dev/null

# Same API flags and proxy trust as docker-compose-prod.yml. A low public
# rate limit makes the forged X-Forwarded-For check below observable.
docker run -d --name hl-proxy-api --network "$NET" --network-alias api \
  -e POSTGRES_HOST=db.invalid -e MINIO_HOST=minio.invalid -e NARRATOR_MODE=rule \
  -e TRUST_PROXY_HEADERS=true -e RATE_LIMIT_PUBLIC_PER_MINUTE=3 \
  "$API_IMAGE" uvicorn api.app:app --host 0.0.0.0 --port 8001 \
  --proxy-headers --forwarded-allow-ips='*' --root-path /api >/dev/null
docker run -d --name hl-proxy-ui --network "$NET" --network-alias ui "$UI_IMAGE" >/dev/null
# ":80" makes Caddy serve plain HTTP for the test instead of requesting a cert.
# The Caddyfile is copied in rather than bind-mounted: on some hosts a
# single-file bind mount silently leaves the image's default config in place.
docker create --name hl-proxy-caddy --network "$NET" -p "$PORT:80" \
  -e HALAL_APP_DOMAIN=":80" -e ACME_EMAIL=smoke@example.invalid caddy:2 >/dev/null
docker cp Caddyfile hl-proxy-caddy:/etc/caddy/Caddyfile
docker start hl-proxy-caddy >/dev/null

for _ in $(seq 1 90); do
  curl -sf -o /dev/null "$BASE/api/health" && curl -sf -o /dev/null "$BASE/" && break
  sleep 1
done

fail() { echo "FAIL $*" >&2; docker logs hl-proxy-caddy 2>&1 | tail -20 >&2; exit 1; }
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
check() {  # label expected actual
  [ "$2" = "$3" ] || fail "$1: got $3, expected $2"
  echo "ok   $1 ($3)"
}

check "GET /api/health" 200 "$(status "$BASE/api/health")"
check "GET /api redirects to /api/" "308 $BASE/api/" \
  "$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "$BASE/api")"
check "GET /api/docs" 200 "$(status "$BASE/api/docs")"
# Swagger must fetch the schema under the prefix, not from the UI's root.
curl -s "$BASE/api/docs" | grep -q "'/api/openapi.json'\|\"/api/openapi.json\"" \
  || fail "/api/docs does not point at /api/openapi.json"
echo "ok   Swagger points at /api/openapi.json"
check "GET /api/openapi.json" 200 "$(status "$BASE/api/openapi.json")"
check "unknown API path stays an API 404" "404 application/json" \
  "$(curl -s -o /dev/null -w '%{http_code} %{content_type}' "$BASE/api/does-not-exist")"
check "POST /api/halal-score" 200 "$(status -H 'Content-Type: application/json' \
  -d '{"snapshot":{"symbol":"ABC","filing_date":"2026-01-01T00:00:00"},"market_data":{"market_cap":1000}}' \
  "$BASE/api/halal-score")"
check "GET / (dashboard)" 200 "$(status "$BASE/")"
check "GET /login/" 200 "$(status "$BASE/login/")"
check "policy page redirect keeps working" "308" "$(status "$BASE/terms")"
grep -q '"/api"\|/api/' <(curl -s "$BASE/" ; for f in $(curl -s "$BASE/" | grep -o '/_next/static/[^"]*\.js'); do curl -s "$BASE$f"; done) \
  || fail "the UI bundle does not call /api"
echo "ok   UI bundle calls /api"

# Caddy replaces a client-supplied X-Forwarded-For, so forging a new address
# per request must not escape the per-IP limit (3/minute above). One request
# was already spent on /api/halal-score.
codes=""
for i in 1 2 3; do
  codes="$codes $(status -H "X-Forwarded-For: 203.0.113.$i" -H 'Content-Type: application/json' \
    -d '{"snapshot":{"symbol":"ABC","filing_date":"2026-01-01T00:00:00"},"market_data":{"market_cap":1000}}' \
    "$BASE/api/halal-score")"
done
check "forged X-Forwarded-For does not reset the rate limit" " 200 200 429" "$codes"

echo "Proxy smoke test passed."
