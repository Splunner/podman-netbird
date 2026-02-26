#!/bin/bash
set -e

NAME="netbird-dashboard"
IMAGE="netbirdio/dashboard:latest"
NETWORK="netbird-net"
PORT="8080:80"
ENV_FILE="$HOME/podman-netbird/.env/dashboard.env"

echo "➡️ Starting $NAME..."

# Sprawdź czy env-file istnieje
if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ Brak pliku env: $ENV_FILE"
  exit 1
fi

# Usuń kontener jeśli już istnieje
if podman ps -a --format '{{.Names}}' | grep -q "^${NAME}$"; then
  echo "ℹ️ Kontener istnieje — restart"
  podman stop "$NAME" || true
  podman rm "$NAME" || true
fi

# Uruchom kontener
podman run -d \
  --name "$NAME" \
  --restart unless-stopped \
  --network "$NETWORK" \
  -p "$PORT" \
  --env-file "$ENV_FILE" \
  --log-driver json-file \
  --log-opt max-size=500m \
  --log-opt max-file=2 \
  "$IMAGE"

echo "✅ $NAME uruchomiony"
podman ps --filter name="$NAME"
