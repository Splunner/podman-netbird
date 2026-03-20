#!/usr/bin/env bash
# =============================================================================
# Let's Encrypt certificate generation via Cloudflare DNS-01 challenge
#
# Supported distros: Fedora, RHEL, CentOS Stream, AlmaLinux, Rocky Linux,
#                    Debian, Ubuntu
#
# Usage:
#   ./cloudflare-certbot.sh [OPTIONS]
#
# Required options:
#   -t, --token     <token>      Cloudflare API Token (Zone.DNS Edit permission)
#   -z, --zone-id   <zone-id>    Cloudflare Zone ID (Dashboard → Overview)
#   -d, --domain    <domain>     Primary domain, e.g. example.com
#   -e, --email     <email>      E-mail address for Let's Encrypt account
#
# Optional options:
#   -x, --extra     <domains>    Extra domains, comma-separated
#                                e.g. "www.example.com,api.example.com"
#   -s, --staging                Use Let's Encrypt staging env (for testing)
#   -i, --install-deps           Auto-install missing dependencies
#   -h, --help                   Show this help message
#
# Examples:
#   # Single domain
#   sudo ./cloudflare-certbot.sh \
#       --token   "abc123..." \
#       --zone-id "def456..." \
#       --domain  "example.com" \
#       --email   "admin@example.com"
#
#   # Wildcard + www + staging test
#   sudo ./cloudflare-certbot.sh \
#       --token   "abc123..." \
#       --zone-id "def456..." \
#       --domain  "example.com" \
#       --extra   "*.example.com,www.example.com" \
#       --email   "admin@example.com" \
#       --staging
#
#   # Auto-install dependencies on first run
#   sudo ./cloudflare-certbot.sh --install-deps \
#       --token   "abc123..." \
#       --zone-id "def456..." \
#       --domain  "example.com" \
#       --email   "admin@example.com"
# =============================================================================

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────────
# Terminal colors
# ──────────────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()   { echo -e "${GREEN}[ OK ]${RESET}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
die()  { echo -e "${RED}[ERR ]${RESET}  $*" >&2; exit 1; }
step() { echo -e "\n${BOLD}──── $* ────${RESET}"; }

# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────
CF_API_TOKEN=""
CF_ZONE_ID=""
DOMAIN=""
EXTRA_DOMAINS=""
EMAIL=""
STAGING=false
INSTALL_DEPS=false
CERT_DIR="/etc/letsencrypt/live"

# ──────────────────────────────────────────────────────────────────────────────
# Help / usage
# ──────────────────────────────────────────────────────────────────────────────
usage() {
  sed -n '/^# Usage:/,/^# ====/p' "$0" | sed 's/^# \?//'
  exit 0
}

# ──────────────────────────────────────────────────────────────────────────────
# Parse command-line arguments
# ──────────────────────────────────────────────────────────────────────────────
parse_args() {
  [[ $# -eq 0 ]] && usage

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -t|--token)        CF_API_TOKEN="$2";   shift 2 ;;
      -z|--zone-id)      CF_ZONE_ID="$2";     shift 2 ;;
      -d|--domain)       DOMAIN="$2";         shift 2 ;;
      -e|--email)        EMAIL="$2";          shift 2 ;;
      -x|--extra)        EXTRA_DOMAINS="$2";  shift 2 ;;
      -s|--staging)      STAGING=true;        shift   ;;
      -i|--install-deps) INSTALL_DEPS=true;   shift   ;;
      -h|--help)         usage ;;
      *) die "Unknown option: $1  (use --help for usage)" ;;
    esac
  done
}

# ──────────────────────────────────────────────────────────────────────────────
# Detect OS family and package manager
# ──────────────────────────────────────────────────────────────────────────────
detect_os() {
  if [[ -f /etc/os-release ]]; then
    # shellcheck source=/dev/null
    source /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_LIKE="${ID_LIKE:-}"
  else
    die "Cannot detect OS – /etc/os-release not found."
  fi

  # Determine package manager family
  if echo "$OS_ID $OS_LIKE" | grep -qiE "rhel|fedora|centos|almalinux|rocky|ol"; then
    PKG_FAMILY="rhel"
  elif echo "$OS_ID $OS_LIKE" | grep -qiE "debian|ubuntu"; then
    PKG_FAMILY="debian"
  else
    PKG_FAMILY="unknown"
  fi

  log "Detected OS : ${PRETTY_NAME:-$OS_ID}"
  log "PKG family  : $PKG_FAMILY"
}

# ──────────────────────────────────────────────────────────────────────────────
# Install dependencies – Fedora / RHEL family
# ──────────────────────────────────────────────────────────────────────────────
install_deps_rhel() {
  step "Installing dependencies (Fedora / RHEL family)"

  # Choose dnf or yum (older RHEL / CentOS 7)
  local pm
  command -v dnf &>/dev/null && pm="dnf" || pm="yum"

  # Enable EPEL on non-Fedora distros (certbot and jq live there)
  if [[ "$OS_ID" != "fedora" ]]; then
    log "Enabling EPEL repository..."
    $pm install -y epel-release \
      || warn "epel-release not found, trying epel-next-release"
    dnf install -y epel-next-release 2>/dev/null || true
  fi

  # Enable CRB (CodeReady Builder) on RHEL 9 / AlmaLinux / Rocky
  # Required for some EPEL dependencies
  if echo "$OS_ID" | grep -qiE "almalinux|rocky|rhel"; then
    log "Enabling CRB repository..."
    dnf config-manager --set-enabled crb 2>/dev/null \
      || subscription-manager repos \
           --enable "codeready-builder-for-rhel-9-$(arch)-rpms" 2>/dev/null \
      || warn "Could not enable CRB – continuing anyway"
  fi

  # Install certbot via snap (recommended upstream method for RHEL family)
  if ! command -v certbot &>/dev/null; then
    log "Installing certbot via snapd..."
    $pm install -y snapd 2>/dev/null || true

    if command -v snap &>/dev/null; then
      systemctl enable --now snapd.socket 2>/dev/null || true
      sleep 3   # snapd needs a moment on first start
      ln -sf /var/lib/snapd/snap /snap 2>/dev/null || true
      snap install --classic certbot
      ln -sf /snap/bin/certbot /usr/local/bin/certbot 2>/dev/null || true
    else
      # Fallback: install certbot directly from EPEL via dnf/yum
      warn "snapd unavailable – falling back to $pm certbot package (EPEL)"
      $pm install -y certbot
    fi
  else
    ok "certbot already installed: $(certbot --version 2>&1)"
  fi

  # Install curl (usually present) and jq
  log "Installing curl and jq..."
  $pm install -y curl jq

  ok "All dependencies installed (RHEL family)"
}

# ──────────────────────────────────────────────────────────────────────────────
# Install dependencies – Debian / Ubuntu family
# ──────────────────────────────────────────────────────────────────────────────
install_deps_debian() {
  step "Installing dependencies (Debian / Ubuntu family)"
  apt-get update -qq
  apt-get install -y certbot curl jq
  ok "All dependencies installed (Debian family)"
}

# ──────────────────────────────────────────────────────────────────────────────
# Dispatch dependency installation based on detected OS
# ──────────────────────────────────────────────────────────────────────────────
install_deps() {
  [[ "$INSTALL_DEPS" == false ]] && return
  [[ $EUID -ne 0 ]] && die "Root privileges required to install dependencies. Run with sudo."

  detect_os

  case "$PKG_FAMILY" in
    rhel)   install_deps_rhel ;;
    debian) install_deps_debian ;;
    *)      warn "Unknown OS family – skipping auto-install." \
              "Install certbot, curl and jq manually." ;;
  esac
}

# ──────────────────────────────────────────────────────────────────────────────
# Validate configuration and required tools
# ──────────────────────────────────────────────────────────────────────────────
validate() {
  step "Validating configuration"

  [[ -z "$CF_API_TOKEN" ]] && die "Cloudflare API token is required  (--token)"
  [[ -z "$CF_ZONE_ID"   ]] && die "Cloudflare Zone ID is required    (--zone-id)"
  [[ -z "$DOMAIN"       ]] && die "Primary domain is required        (--domain)"
  [[ -z "$EMAIL"        ]] && die "E-mail address is required        (--email)"

  # Basic domain format validation
  [[ "$DOMAIN" =~ ^[a-zA-Z0-9*._-]+\.[a-zA-Z]{2,}$ ]] \
    || die "Invalid domain format: '$DOMAIN'"

  # Check that all required binaries are present
  local missing=()
  for cmd in certbot curl jq; do
    command -v "$cmd" &>/dev/null || missing+=("$cmd")
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo ""
    echo -e "  ${RED}Missing tools: ${missing[*]}${RESET}"
    echo ""
    echo "  Install on Fedora / RHEL:"
    echo "    sudo dnf install -y epel-release"
    echo "    sudo dnf install -y certbot curl jq"
    echo ""
    echo "  Install on Debian / Ubuntu:"
    echo "    sudo apt install -y certbot curl jq"
    echo ""
    echo "  Or re-run with --install-deps to let this script do it:"
    echo "    sudo $0 --install-deps [... other args ...]"
    die "Aborting – install missing tools first."
  fi

  ok "All configuration checks passed"
}

# ──────────────────────────────────────────────────────────────────────────────
# Cloudflare API helper
# ──────────────────────────────────────────────────────────────────────────────
cf_api() {
  local method="$1" path="$2" data="${3:-}"
  curl -sf -X "$method" \
    "https://api.cloudflare.com/client/v4${path}" \
    -H "Authorization: Bearer ${CF_API_TOKEN}" \
    -H "Content-Type: application/json" \
    ${data:+--data "$data"}
}

# Verify the API token has access to the given zone before starting certbot
verify_cf_token() {
  step "Verifying Cloudflare API token"
  local resp
  resp=$(cf_api GET "/zones/${CF_ZONE_ID}") \
    || die "Cloudflare API request failed – check your token and zone ID."

  echo "$resp" | jq -e '.success' &>/dev/null \
    || die "Cloudflare API error: $(echo "$resp" | jq -r '.errors[0].message // "unknown"')"

  ok "Token valid – zone: $(echo "$resp" | jq -r '.result.name')"
}

# ──────────────────────────────────────────────────────────────────────────────
# Certbot manual hooks
# These scripts are written to temp files and passed to certbot via
# --manual-auth-hook and --manual-cleanup-hook flags.
# Certbot sets $CERTBOT_DOMAIN and $CERTBOT_VALIDATION automatically.
# ──────────────────────────────────────────────────────────────────────────────
AUTH_HOOK=""
CLEANUP_HOOK=""
ID_FILE="/tmp/cf_dns_record_ids_$$.txt"   # stores created record IDs between hooks

write_hooks() {
  AUTH_HOOK=$(mktemp /tmp/cf_auth_XXXX.sh)
  CLEANUP_HOOK=$(mktemp /tmp/cf_cleanup_XXXX.sh)

  # ── auth-hook: runs BEFORE Let's Encrypt checks the DNS record ──────────
  cat > "$AUTH_HOOK" <<EOF
#!/usr/bin/env bash
set -euo pipefail

CF_API_TOKEN="${CF_API_TOKEN}"
CF_ZONE_ID="${CF_ZONE_ID}"
ID_FILE="${ID_FILE}"
RECORD_NAME="_acme-challenge.\${CERTBOT_DOMAIN}"

echo "[AUTH-HOOK] Adding TXT: \${RECORD_NAME} = \${CERTBOT_VALIDATION}"

resp=\$(curl -sf -X POST \\
  "https://api.cloudflare.com/client/v4/zones/\${CF_ZONE_ID}/dns_records" \\
  -H "Authorization: Bearer \${CF_API_TOKEN}" \\
  -H "Content-Type: application/json" \\
  --data "{\"type\":\"TXT\",\"name\":\"\${RECORD_NAME}\",\"content\":\"\${CERTBOT_VALIDATION}\",\"ttl\":60}")

echo "\$resp" | jq -e '.success' &>/dev/null \\
  || { echo "[AUTH-HOOK] ERROR: \$resp" >&2; exit 1; }

record_id=\$(echo "\$resp" | jq -r '.result.id')
echo "\${record_id}" >> "\${ID_FILE}"
echo "[AUTH-HOOK] Record created (id=\${record_id}) – waiting 25s for DNS propagation..."

# Give DNS time to propagate before the ACME server queries it
sleep 25
EOF

  # ── cleanup-hook: runs AFTER Let's Encrypt verifies the challenge ────────
  cat > "$CLEANUP_HOOK" <<EOF
#!/usr/bin/env bash
set -euo pipefail

CF_API_TOKEN="${CF_API_TOKEN}"
CF_ZONE_ID="${CF_ZONE_ID}"
ID_FILE="${ID_FILE}"

[[ -f "\${ID_FILE}" ]] || { echo "[CLEANUP-HOOK] No IDs file, nothing to clean."; exit 0; }

echo "[CLEANUP-HOOK] Removing TXT records..."
while IFS= read -r record_id; do
  [[ -z "\$record_id" ]] && continue
  resp=\$(curl -sf -X DELETE \\
    "https://api.cloudflare.com/client/v4/zones/\${CF_ZONE_ID}/dns_records/\${record_id}" \\
    -H "Authorization: Bearer \${CF_API_TOKEN}" \\
    -H "Content-Type: application/json")
  if echo "\$resp" | jq -e '.success' &>/dev/null; then
    echo "[CLEANUP-HOOK] Deleted record id=\${record_id}"
  else
    echo "[CLEANUP-HOOK] WARNING: Failed to delete id=\${record_id}" >&2
  fi
done < "\${ID_FILE}"

rm -f "\${ID_FILE}"
echo "[CLEANUP-HOOK] Done."
EOF

  chmod +x "$AUTH_HOOK" "$CLEANUP_HOOK"
}

# Remove all temp files on script exit (including on error)
cleanup() {
  rm -f "$AUTH_HOOK" "$CLEANUP_HOOK" "$ID_FILE"
}
trap cleanup EXIT

# ──────────────────────────────────────────────────────────────────────────────
# Run certbot with the Cloudflare hooks
# ──────────────────────────────────────────────────────────────────────────────
run_certbot() {
  step "Running certbot (DNS-01 challenge)"

  # Build domain arguments: primary + optional extras
  local domain_args="-d ${DOMAIN}"
  if [[ -n "$EXTRA_DOMAINS" ]]; then
    IFS=',' read -ra extras <<< "$EXTRA_DOMAINS"
    for d in "${extras[@]}"; do
      domain_args+=" -d ${d// /}"   # trim accidental spaces
    done
  fi

  # Staging flag issues test certificates (not trusted by browsers)
  local staging_flag=""
  if $STAGING; then
    staging_flag="--staging"
    warn "STAGING MODE – certificate will NOT be trusted by browsers!"
  fi

  log "Domains  : ${DOMAIN}${EXTRA_DOMAINS:+, $EXTRA_DOMAINS}"
  log "E-mail   : ${EMAIL}"
  log "Staging  : ${STAGING}"

  # shellcheck disable=SC2086
  certbot certonly \
    --non-interactive \
    --agree-tos \
    --email "${EMAIL}" \
    --preferred-challenges dns-01 \
    --manual \
    --manual-auth-hook    "${AUTH_HOOK}" \
    --manual-cleanup-hook "${CLEANUP_HOOK}" \
    --manual-public-ip-logging-ok \
    $domain_args \
    $staging_flag
}

# ──────────────────────────────────────────────────────────────────────────────
# Print success summary with file paths and renewal instructions
# ──────────────────────────────────────────────────────────────────────────────
print_summary() {
  echo ""
  ok "Certificate issued successfully!"
  echo -e "\n${BOLD}Certificate paths:${RESET}"
  echo "  Full chain : ${CERT_DIR}/${DOMAIN}/fullchain.pem"
  echo "  Private key: ${CERT_DIR}/${DOMAIN}/privkey.pem"

  echo -e "\n${BOLD}nginx config snippet:${RESET}"
  echo "  ssl_certificate     ${CERT_DIR}/${DOMAIN}/fullchain.pem;"
  echo "  ssl_certificate_key ${CERT_DIR}/${DOMAIN}/privkey.pem;"

  echo -e "\n${BOLD}Apache config snippet:${RESET}"
  echo "  SSLCertificateFile    ${CERT_DIR}/${DOMAIN}/fullchain.pem"
  echo "  SSLCertificateKeyFile ${CERT_DIR}/${DOMAIN}/privkey.pem"

  echo -e "\n${YELLOW}Auto-renewal – systemd timer (recommended):${RESET}"
  echo "  systemctl enable --now certbot-renew.timer"
  echo "  systemctl status certbot-renew.timer"

  echo -e "\n${YELLOW}Auto-renewal – cron fallback:${RESET}"
  echo "  echo '0 3 * * * root certbot renew --quiet' > /etc/cron.d/certbot"
  echo ""
}

# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
main() {
  echo -e "\n${BOLD}╔══════════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}║  Let's Encrypt – Cloudflare DNS-01 Challenge ║${RESET}"
  echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}\n"

  parse_args "$@"
  install_deps       # runs only when --install-deps flag is passed
  validate
  verify_cf_token
  write_hooks
  run_certbot
  print_summary
}

main "$@"