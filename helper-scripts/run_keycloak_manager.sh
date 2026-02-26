#!/usr/bin/env bash

CONTAINER_NAME="keycloak-manager"

if ! podman container exists "$CONTAINER_NAME"; then
  podman run -d \
    --name "$CONTAINER_NAME" \
    --network keycloak-net \
    -p 8089:8080 \
    --userns=keep-id \
    --env-file "$HOME/podman-netbird/.env/.env-keycloak-postgres" \
    quay.io/keycloak/keycloak:26.5.2 \
    start

  echo "Container $CONTAINER_NAME started"
else
  echo "Container $CONTAINER_NAME already exists"
fi
