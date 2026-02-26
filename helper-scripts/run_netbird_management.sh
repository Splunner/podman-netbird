#!/bin/bash
set -e

NAME="netbird-management"
IMAGE="netbirdio/management:latest"
NETWORK="netbird-net"
PORT="8081:80"

# Ścieżki
BASE_DIR="$HOME/podman-netbird"
CONFIG_FILE="$BASE_DIR/management/management.json"

# Volume podmana (odpowiednik named volume z compose)
VOLUME_NAME="netbird_management"

echo "➡️ Starting $NAME..."

# Sprawdzenia
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "❌ Brak pliku konfiguracyjnego: $CONFIG_FILE"
  exit 1
fi

# Utwórz volume jeśli nie istnieje
if ! podman volume exists "$VOLUME_NAME"; then
  echo "ℹ️ Tworzę volume: $VOLUME_NAME"
  podman volume create "$VOLUME_NAME"
fi

# Usuń kontener jeśli istnieje
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
  -v "$VOLUME_NAME:/var/lib/netbird:Z" \
  -v "$CONFIG_FILE:/etc/netbird/management.json:Z" \
  "$IMAGE" \
  --port 80 \
  --log-file console \
  --log-level info \
  --disable-anonymous-metrics=false \
  --single-account-mode-domain=netbird.selfhosted \
  --dns-domain=netbird.selfhosted \
  --idp-sign-key-refresh-enabled

echo "✅ $NAME uruchomiony"
podman ps --filter name="$NAME"
