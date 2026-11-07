#!/usr/bin/env bash
# Rebuild the Docker image from the current code and replace the running container.
# Data lives in the matchmaker-data volume, so it survives this.
#   ./redeploy.sh           rebuild + restart
#   ./redeploy.sh --env     restart only (after editing .env; no rebuild)
set -euo pipefail
cd "$(dirname "$0")"

NAME=matchmaker
PORT=8000

if [[ "${1:-}" != "--env" ]]; then
  echo "Building image..."
  docker build -t "$NAME" .
fi

echo "Replacing container..."
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -p "$PORT:8000" --env-file .env -v matchmaker-data:/data "$NAME" >/dev/null

echo -n "Waiting for the server"
for _ in $(seq 1 60); do
  if curl -fs -o /dev/null "http://localhost:$PORT/api/meta"; then
    echo " ready: http://localhost:$PORT (hard refresh with Cmd+Shift+R)"
    exit 0
  fi
  echo -n "."
  sleep 1
done
echo
echo "The server didn't come up within 60s. Recent logs:"
docker logs --tail 30 "$NAME"
exit 1
