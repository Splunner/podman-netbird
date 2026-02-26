#!/usr/bin/env bash

CONTAINER_NAME="keycloak-db-postgres"

if ! podman container exists "$CONTAINER_NAME"; then
  podman run -d \
    --name "$CONTAINER_NAME" \
    --network keycloak-net \
    --env-file "$HOME/podman-netbird/.env/.env-keycloak-postgres" \
    -e PGDATA=/var/lib/postgresql/data/data \
    -v "$HOME/podman-netbird/postgres-db:/var/lib/postgresql/data:Z" \
    -p 5432:5432 \
    docker.io/postgres:15

  echo "Container $CONTAINER_NAME started"
else
  echo "Container $CONTAINER_NAME already exists"
fi
