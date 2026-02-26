#!/bin/bash
set -e

NAME="nginx-netbird"
IMAGE="docker.io/library/nginx:stable"
NETWORK="netbird-net"

# Katalogi lokalne
CONF_DIR="$HOME/podman-netbird/nginx_configuration"
CERTS_DIR="$HOME/podman-netbird/certs"

# Porty (HTTPS)
HTTP_PORT="80:80"
HTTPS_PORT="443:443"

echo "➡️ Starting $NAME with SSL..."

# Sprawdź katalogi
if [[ ! -f "$CONF_DIR/nginx_conf.conf" ]]; then
  echo "❌ Brak pliku konfiguracyjnego: $CONF_DIR/nginx_conf.conf"
  exit 1
fi

if [[ ! -f "$CERTS_DIR/fullchain.pem" || ! -f "$CERTS_DIR/privkey.pem" ]]; then
  echo "❌ Brak certyfikatów w $CERTS_DIR"
  exit 1
fi

# Usuń stary kontener jeśli istnieje
if podman ps -a --format '{{.Names}}' | grep -q "^${NAME}$"; then
  echo "ℹ️ Kontener istnieje — restart"
  podman stop "$NAME" || true
  podman rm "$NAME" || true
fi

# Uruchom kontener nginx z SSL
podman run -d \
  --name "$NAME" \
  --network "$NETWORK" \
  -p "$HTTP_PORT" \
  -p "$HTTPS_PORT" \
  -v "$CONF_DIR:/etc/nginx/conf.d:ro,Z" \
  -v "$CERTS_DIR/fullchain.pem:/etc/nginx/ssl/fullchain.pem:ro,Z" \
  -v "$CERTS_DIR/privkey.pem:/etc/nginx/ssl/privkey.pem:ro,Z" \
  "$IMAGE"

echo "✅ $NAME uruchomiony"
podman ps --filter name="$NAME"
