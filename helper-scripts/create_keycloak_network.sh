#!/usr/bin/env bash

NETWORK_NAME="keycloak-net"

if ! podman network exists "$NETWORK_NAME"; then
  podman network create "$NETWORK_NAME"
  echo "Network created: $NETWORK_NAME"
else
  echo "Network $NETWORK_NAME already exists"
fi
