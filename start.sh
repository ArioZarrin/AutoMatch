#!/usr/bin/env sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created .env from .env.example."
fi

HOST_PORT_VALUE=$(awk -F= '$1 == "HOST_PORT" { print $2 }' .env | tail -n 1)
case "$HOST_PORT_VALUE" in
  ''|*[!0-9]*) HOST_PORT_VALUE=8080 ;;
esac

URL="http://127.0.0.1:${HOST_PORT_VALUE}/"
HEALTH_URL="${URL}api/health"

docker compose up -d --build

attempt=0
while [ "$attempt" -lt 60 ]; do
  if curl --fail --silent --show-error "$HEALTH_URL" >/dev/null 2>&1; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done

if [ "$attempt" -eq 60 ]; then
  echo "AutoMatch did not become healthy. Run: docker compose logs automatch" >&2
  exit 1
fi

if command -v open >/dev/null 2>&1; then
  open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 &
else
  echo "AutoMatch is ready at $URL"
fi
