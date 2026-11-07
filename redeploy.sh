#!/usr/bin/env bash
# Rebuild the Docker Compose stack (db, api, web) from the current code and restart what changed.
# Data lives in the pgdata volume, so it survives this.
#   ./redeploy.sh           rebuild + restart
#   ./redeploy.sh --env     restart the api only (after editing .env; no rebuild)
set -euo pipefail
cd "$(dirname "$0")"

# Port the site is published on: WEB_PORT from the shell, then .env, else 8000 (same as docker-compose.yml).
PORT="${WEB_PORT:-$(sed -n 's/^WEB_PORT=//p' .env 2>/dev/null | tail -1)}"
PORT="${PORT:-8000}"

# The old single-container setup also used port 8000. Remove that container (its volume is kept).
if docker ps -a --format '{{.Names}}' | grep -qx matchmaker; then
  echo "Removing the old single-container 'matchmaker' (its matchmaker-data volume is kept)..."
  docker rm -f matchmaker >/dev/null
fi

if [[ "${1:-}" == "--env" ]]; then
  echo "Restarting the api with the current .env..."
  docker compose up -d --force-recreate --no-deps api
else
  echo "Building and starting db, api, web..."
  docker compose up -d --build
fi

echo -n "Waiting for the site"
for _ in $(seq 1 90); do
  if curl -fs -o /dev/null "http://localhost:$PORT/api/meta"; then
    echo " ready: http://localhost:$PORT (hard refresh with Cmd+Shift+R)"
    exit 0
  fi
  echo -n "."
  sleep 1
done
echo
echo "The site didn't come up within 90s."
docker compose ps
echo "Recent api logs:"
docker compose logs --tail 30 api
exit 1
