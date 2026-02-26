#!/bin/bash
set -e

read -rp "Provide domains (ex: example.com): " DOMAIN

if [[ -z "$DOMAIN" ]]; then
  echo "❌ Domain can not be empty"
  exit 1
fi

CERT_DIR="$HOME/podman-netbird/certs"



   openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout "$CERT_DIR/privkey.pem" \
  -out "$CERT_DIR/fullchain.pem" \
  -subj "/C=PL/ST=PL/L=PL/O=Dev/CN=$DOMAIN"

 chmod 600 "$CERT_DIR/privkey.pem"
 chmod 644 "$CERT_DIR/fullchain.pem"

echo
echo "✅ Certyfikat wygenerowany:"
echo "  $CERT_DIR/fullchain.pem"
echo "  $CERT_DIR/privkey.pem"
