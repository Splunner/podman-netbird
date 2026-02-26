#!/bin/bash
# netbird-relay.sh - simple script to manage the Netbird Relay container

CONTAINER_NAME="netbird-relay"
IMAGE="netbirdio/relay:latest"
NETWORK="netbird-net"
PORTS=("8084:80" "3478:3478/udp")
ENV_FILE="$HOME/podman-netbird/.env/relay.env"

function start_container() {
    # Check if container is already running
    if podman ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
        echo "Container $CONTAINER_NAME is already running."
        return
    fi

    # Run the container
    podman run -d \
        --name "$CONTAINER_NAME" \
        --network "$NETWORK" \
        $(for p in "${PORTS[@]}"; do echo -n "-p $p "; done) \
        --env-file "$ENV_FILE" \
        --restart unless-stopped \
        --log-driver json-file \
        --log-opt max-size=500m \
        --log-opt max-file=2 \
        "$IMAGE"

    echo "Container $CONTAINER_NAME started."
}

function stop_container() {
    if podman ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" | grep -q "$CONTAINER_NAME"; then
        podman stop "$CONTAINER_NAME"
        echo "Container $CONTAINER_NAME stopped."
    else
        echo "Container $CONTAINER_NAME is not running."
    fi
}

function status_container() {
    podman ps -a --filter "name=$CONTAINER_NAME"
}

case "$1" in
    start)
        start_container
        ;;
    stop)
        stop_container
        ;;
    restart)
        stop_container
        start_container
        ;;
    status)
        status_container
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        ;;
esac
