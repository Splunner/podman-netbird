#!/bin/bash
set -e

NETWORK_NAME="netbird-net"
DRIVER="bridge"

echo "➡️ Checking network: $NETWORK_NAME"

if podman network exists "$NETWORK_NAME"; then
  echo "ℹ️ Network $NETWORK_NAME already exits."
else
  echo "➕ Creating network $NETWORK_NAME"
  podman network create \
    --driver "$DRIVER" \
    "$NETWORK_NAME"
fi

echo "✅ Success!"
podman network ls | grep "$NETWORK_NAME"
