# Netbird on Podman — Self-Hosted, Control in Your Hands!

Supports rootless Netbird configurations with 3 examples:

- **Example 1** — Standalone Netbird with built-in IDP (DEX) and Let's Encrypt with automatic cert renewal *(custom — check quadlet files to edit)*.
- **Example 2** — Netbird with Keycloak on Postgres as an additional configuration, and Let's Encrypt with automatic cert renewal *(custom — check quadlet files to edit)*.
- **Example 3** — Netbird with Postgres, Keycloak on Postgres as an additional configuration, and Let's Encrypt with automatic cert renewal *(custom — check quadlet files to edit)*.

---

## ⚠️ Important Notes

- This setup uses **Traefik** and has been tested with the latest version of Podman.
- **SQLite** can cause issues over the long term and is therefore replaced by **Postgres**.
- You **cannot** fully disable the IDP DEX — avoid doing so, as it will cause issues. Keycloak can be added as an *additional* IDP but not as a replacement.
- **High Availability (HA) is not supported** due to limitations in `netbird-server`. If you need HA, please contact the Netbird team.
  However, it is possible to split the proxies and STUN server to distribute traffic without requiring HA on the server and dashboard — see:
  [Scaling Your Self-Hosted Deployment](https://docs.netbird.io/selfhosted/maintenance/scaling/scaling-your-self-hosted-deployment)

---

## Remove Docker (if previously used)

```bash
# Remove all containers, images, volumes, and networks
sudo docker rm -f $(sudo docker ps -aq)
sudo docker rmi -f $(sudo docker images -q)
sudo docker volume rm $(sudo docker volume ls -q)
sudo docker network prune -f

# Stop all Docker-related services
sudo systemctl stop docker.socket
sudo systemctl stop docker.service

# Uninstall Docker packages
sudo dnf remove -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

---

## Installation & Setup

### Step 1 — Install Dependencies

```bash
# Install Podman and Python 3
pip3 install PyYAML Jinja2
```

### Step 2 — System User & Firewall Setup

Enable lingering for the Podman service user so its services survive logout, configure the firewall, and set up the runtime directory:

```bash
# Enable lingering for the podmanadm user (keeps user services alive after logout)
sudo loginctl enable-linger podmanadm

# Open required firewall ports
sudo firewall-cmd --add-port=3478/udp --permanent   # STUN/TURN
sudo firewall-cmd --add-port=80/tcp --permanent     # HTTP
sudo firewall-cmd --add-port=443/tcp --permanent    # HTTPS
sudo firewall-cmd --reload

# Set XDG_RUNTIME_DIR so rootless Podman can find its socket
echo 'export XDG_RUNTIME_DIR=/run/user/$(id -u)' >> /home/podmanadm/.bashrc
echo 'export XDG_RUNTIME_DIR=/run/user/$(id -u)' >> /home/podmanadm/.bash_profile

# Enable and start the Podman user socket
systemctl --user start podman.socket
systemctl --user enable podman.socket
systemctl --user status podman.socket

# Verify socket path
systemctl --user show podman.socket --property=Listen | cut -d= -f2 | awk '{print $1}'
```

### Step 3 — Clone Repository

Pull this repository as the user that will execute the quadlets:

```bash
git clone https://github.com/your-repo/podman-netbird.git ~/podman-netbird
```

### Step 4 — Set Environment Variable

```bash
# Set the source project variable permanently
echo 'export SRC_PROJECT_PODMAN_NETBIRD=~/podman-netbird' >> ~/.bashrc && source ~/.bashrc
```

### Step 5 — Run System Check

This must complete successfully before proceeding:

```bash
python3 $SRC_PROJECT_PODMAN_NETBIRD/helper_scripts/check_system_status.py
```

### Step 6 — Set Up Directories

> To access `/opt` as a standard user, ask your administrator or create the directories as a superuser.

```bash
# Create directories with correct ownership and permissions
sudo mkdir /opt/configurations
sudo mkdir /opt/storage
sudo chown podmanadm:podmanadm /opt/storage
sudo chown podmanadm:podmanadm /opt/configurations
sudo chmod 755 /opt/storage
sudo chmod 755 /opt/configurations

# Run the helper script to set up additional subdirectories
python3 $SRC_PROJECT_PODMAN_NETBIRD/helper_scripts/setup_directories.py
```

### Step 7 — Configure and Build Files

**Option A: Copy pre-built example files**

```
configs  → $SRC_PROJECT_PODMAN_NETBIRD/output/configurations
quadlets → $SRC_PROJECT_PODMAN_NETBIRD/output/quadlets
```

**Option B: Build from templates**

```bash
# 1. Generate configuration files
python3 config_generations.py \
  --prod-yml  $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/prod.yml \
  --templates-yml $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/template_builds.yml \
  --src-project $SRC_PROJECT_PODMAN_NETBIRD
  # Add --overdrive to overwrite existing files

# 2. Generate network quadlets
python3 network_quadlets_generations.py \
  --prod-yml  $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/prod.yml \
  --templates-yml $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/template_builds.yml \
  --src-project  $SRC_PROJECT_PODMAN_NETBIRD
  # Add --overdrive to overwrite existing files

# 3. Generate volume quadlets
python3 volume_quadlets_generations.py \
  --prod-yml  $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/prod.yml \
  --templates-yml $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/template_builds.yml \
  --src-project  $SRC_PROJECT_PODMAN_NETBIRD
  # Add --overdrive to overwrite existing files

# 4. Generate container quadlets
python3 quadlets_generations.py \
  --prod-yml  $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/prod.yml \
  --templates-yml $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/template_builds.yml \
  --src-project  $SRC_PROJECT_PODMAN_NETBIRD
  # Add --overdrive to overwrite existing files
```

### Step 8 — Push Files to Correct Directories

```bash
python3 $SRC_PROJECT_PODMAN_NETBIRD/helper_scripts/push_configurations_quadlets.py \
  --prod-yml prod.yml \
  --default-rl \
  --source-path $SRC_PROJECT_PODMAN_NETBIRD
```

### Step 9 — Start Services

> **Start order:** always start **volumes and networks** first, then **containers**.
> Recommended startup sequence: `Databases → Keycloak → Netbird components → Traefik`

#### Networks

```bash
# Always required
systemctl --user start network-netbird

# Only when using Postgres with Netbird
systemctl --user start network-netbird-postgres

# Only when using Keycloak
systemctl --user start network-keycloak-postgres
systemctl --user start network-keycloak-traefik
```

Verify networks:

```
$ podman network ls

NETWORK ID    NAME                 DRIVER
6482d98eaa14  keycloak-postgres    bridge
5fbbef0b304a  keycloak-tf-network  bridge
5b1f7b797f28  netbird-db-postgres  bridge
19d1f9dcecfe  netbird-tf-network   bridge
2f259bab93aa  podman               bridge
```

#### Volumes

```bash
# Always required
systemctl --user start netbird_data-volume.service
systemctl --user start netbird_traefik_letsencrypt-volume.service

# Only when using Postgres with Netbird
systemctl --user start postgres_data_netbird-volume.service

# Only when using Keycloak
systemctl --user start postgres_data-volume.service
```

Verify volumes:

```
$ podman volume ls

DRIVER      VOLUME NAME
local       postgres_data_netbird
local       netbird_data
local       netbird_traefik_letsencrypt
local       postgres_data
```

#### Containers (Quadlets)

```bash
# Only when using Postgres with Netbird
systemctl --user start postgres-db-netbird

# Only when using Keycloak
systemctl --user start postgres-db

# Only when using Keycloak
systemctl --user start keycloak-manager

# Always required
systemctl --user start netbird-server
systemctl --user start netbird-dashboard
systemctl --user start netbird-traefik
```

---

## ⚠️ Known Issues & Fixes

> Review all containers and configuration builds after applying these fixes.

- **`False` value in Keycloak manager config env file** — check the environment file for boolean values that may be incorrectly set as strings.
- **`kc_DB` typo** — value should be `postgres`, not `posrtgres`.
- **Trailing space in Postgres connection string** — remove any extra whitespace in the Postgres configuration.
- **`netbird_traefik_letsencrypt`** — verify the Let's Encrypt volume is correctly mounted and Traefik has write access.

---

## Backup & Recovery

### Database Backups

Use the provided helper scripts to back up your databases. Run these regularly or set up a cron job.

```bash
# Backup Keycloak database (single database)
$SRC_PROJECT_PODMAN_NETBIRD/helper_scripts/pg_backup.sh \
  postgres-db keycloak /opt/storage/dump_databases keycloak

# Backup Netbird Postgres database (full dump)
$SRC_PROJECT_PODMAN_NETBIRD/helper_scripts/pg_backup.sh \
  postgres-db-netbird postgres /opt/storage/dump_databases --dump-all
```

### Full System Backup

```bash
# Create a full backup of all configuration and storage
$SRC_PROJECT_PODMAN_NETBIRD/helper_scripts/full_backup.sh /opt/storage/backup
```

### Verify Backup Integrity

```bash
# Check that a backup archive is valid and readable
$SRC_PROJECT_PODMAN_NETBIRD/helper_scripts/check_backup.sh \
  /opt/storage/backup/backup_2026-03-25.gz
```

---

## Keycloak as Additional Identity Provider for Netbird

> Keycloak **supplements** (does not replace) the built-in DEX IDP.

### Step 1: Create a Realm in Keycloak

1. Go to **Manage realms** → **Create Realm**.
2. Set **Realm name** to: `netbird`
3. Make sure the correct realm is selected after creation.

### Step 2: Create a User in Keycloak

> Make sure the `netbird` realm is selected throughout this step.

1. Click **Users** (left-hand menu) → **Create new user**.
2. Fill in: **Username** (e.g., `netbird`), **Email** address.
3. Click **Create**.
4. In **Details** → **Required user actions** → select **Configure OTP**.
5. Click the **Credentials** tab → **Set password**.
6. Enter the password and set **Temporary** to `Off`. Click **Save**.

### Step 3: Start Creating a Client in Keycloak

1. Click **Clients** → **Create client**.
2. Set **Client type**: `OpenID Connect`, **Client ID**: `netbird`.
3. Click **Next**.
4. On **Capability config**: enable **Client authentication**. Click **Next**.
5. On the **Login settings** page: do **NOT** click Save yet — you will add the redirect URI in Step 4.

### Step 4: Get the Redirect URL from Netbird

1. Open a new tab and log in to your **Netbird Dashboard**.
2. Navigate to **Settings** → **Identity Providers**.
3. Click **Add Identity Provider**.
4. Select **Keycloak** (or **Generic OIDC** if Keycloak is not listed).
5. Fill in the fields (you can leave **Client Secret** empty for now).
6. Copy the **Redirect URL** displayed by Netbird — do **NOT** click Add Provider yet.

### Step 5: Complete Client Configuration in Keycloak

1. Return to the **Keycloak Admin Console** tab.
2. On the **Login settings** page, under **Valid redirect URIs**: paste the redirect URL copied from Netbird.
3. Under **Valid post logout redirect URIs**: enter your Netbird domain.
4. Click **Save**.
5. Go to the **Credentials** tab and copy the **Client secret** — you will need this in Step 6.

### Step 6: Complete Netbird Setup

1. Return to the **Netbird** tab.
2. Paste the **Client secret** copied from Step 5.
3. Click **Add Provider**.

### Step 7: Test the Connection

1. Log out of the Netbird Dashboard.
2. On the login page, you should see a **"Keycloak"** button.
3. Click it and authenticate with the user credentials created in Step 2.
4. You should be redirected back to Netbird and logged in successfully.

---

## To Do

- [ ] Fix the generation of configurations and quadlets from templates; rebuild scripts into smaller parts run by a single entry point.
- [ ] Migration script for existing configurations. 
- [ ] Custom TLS certificate support.
- [ ] Multiple Proxies support.
- [ ] Log exporter helper to OTLP (OpenTelemetry)