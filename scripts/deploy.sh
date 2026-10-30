#!/usr/bin/env bash
# Deploy a HalalLens release on the server: scripts/deploy.sh vX.Y.Z
#
# Run from the checkout that holds .env (production: /opt/halallens). It checks
# out the release tag (compose file, Caddyfile, migrations), then either
#   - pulls the published images for that tag, when IMAGE_REPOSITORY is set in
#     .env (e.g. ghcr.io/<owner>; the images CI tested, scanned and signed), or
#   - builds the images on the server from the tag (the default),
# starts the stack, waits for the API to be healthy and smoke-tests through
# Caddy. Rollback = run it again with the previous tag (docs/ROLLBACK.md).
set -euo pipefail

TAG=${1:?usage: scripts/deploy.sh vX.Y.Z}
cd "$(dirname "$0")/.."
[ -f .env ] || { echo ".env missing in $(pwd)" >&2; exit 1; }
chmod 600 .env

git fetch -q --tags origin
git -c advice.detachedHead=false checkout -q "$TAG"
echo "== deploying $(git describe --tags) ($(git rev-parse --short HEAD))"

COMPOSE="docker compose -f docker-compose-prod.yml"
# tr: an .env edited on Windows has CRLF endings; a trailing CR would end up
# inside the image reference ("invalid reference format").
IMAGE_REPOSITORY=$(sed -n 's/^IMAGE_REPOSITORY=//p' .env | tail -1 | tr -d '\r')
if [ -n "$IMAGE_REPOSITORY" ]; then
  export API_IMAGE="$IMAGE_REPOSITORY/halallens-api:$TAG"
  export UI_IMAGE="$IMAGE_REPOSITORY/halallens-ui:$TAG"
  echo "== pulling $API_IMAGE and $UI_IMAGE"
  $COMPOSE pull --quiet api ui
  $COMPOSE up -d --no-build
else
  echo "== building on this server (set IMAGE_REPOSITORY in .env to pull published images)"
  $COMPOSE build
  $COMPOSE up -d
fi

echo "== waiting for the API to become healthy"
state=starting
for _ in $(seq 1 60); do
  state=$(docker inspect -f '{{.State.Health.Status}}' "$($COMPOSE ps -q api)" 2>/dev/null || echo starting)
  [ "$state" = healthy ] && break
  sleep 10
done
$COMPOSE ps --format 'table {{.Service}}\t{{.State}}\t{{.Health}}'
if [ "$state" != healthy ]; then
  $COMPOSE logs --tail 60 api preflight migrations
  exit 1
fi

echo "== smoke test through Caddy"
host=$(sed -n 's/^HALAL_APP_DOMAIN=//p' .env | tail -1 | tr -d '\r')
fail=0
for path in /api/health /api/openapi.json / /products/; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: ${host:-localhost}" "http://127.0.0.1$path")
  printf '%-18s %s\n' "$path" "$code"
  [ "$code" = 200 ] || fail=1
done

# Pulled release images pile up (one API + UI pair per deploy). After a good
# deploy keep the running tag and the two newest others (rollback targets);
# an older tag is simply pulled again if it is ever deployed.
if [ "$fail" = 0 ] && [ -n "$IMAGE_REPOSITORY" ]; then
  echo "== removing old release images"
  for name in halallens-api halallens-ui; do
    docker images --format '{{.Repository}}:{{.Tag}}' "$IMAGE_REPOSITORY/$name" \
      | grep -vxF "$IMAGE_REPOSITORY/$name:$TAG" | tail -n +3 \
      | xargs -r docker rmi >/dev/null || true
  done
fi
exit $fail
