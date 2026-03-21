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

## Remove Docker if was used before 
```
#Remove all related to docker
sudo docker rm -f $(sudo docker ps -aq)
sudo docker rmi -f $(sudo docker images -q)
sudo docker volume rm $(sudo docker volume ls -q)
sudo docker network prune -f

# Stop all services related to docker
sudo systemctl stop docker.socket
sudo systemctl stop docker.service

# unistall Packages
sudo dnf remove -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

## Installation & Setup

1. Install dependencies:
```bash
   # Install Podman and Python 3
   pip3 install PyYAML Jinja2
```

2. Pull this repository to the user that will execute the quadlets.

3. Set the environment variable (permanently):
```bash
   echo 'export SRC_PROJECT_PODMAN_NETBIRD=~/podman-netbird' >> ~/.bashrc && source ~/.bashrc
```

4. Run the system check script — this must complete successfully before proceeding:
```bash
   python3 $SRC_PROJECT_PODMAN_NETBIRD/helper_scripts/check_system_status.py
```

5. Set up directories.  
   > To access `/opt` as a standard user, ask your administrator or create the directories as a superuser:
```bash
   sudo -u YourUsername mkdir /opt/configurations
   sudo -u YourUsername mkdir /opt/storage
   python3 $SRC_PROJECT_PODMAN_NETBIRD/helper_scripts/setup_directories.py
```

6. Choose one of the examples, update the files, and copy them:
```
   configs  → $SRC_PROJECT_PODMAN_NETBIRD/output/configurations
   quadlets → $SRC_PROJECT_PODMAN_NETBIRD/output/quadlets
```

OR

  Build files:
  -  Configurations files: python3 config_generations.py --prod-yml  $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/prod.yml --templates-yml $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/template_builds.yml  --src-project $SRC_PROJECT_PODMAN_NETBIRD
     --overdrive if files exists and requires overwrite
  -  Network Quadlets python3 network_quadlets_generations.py  --prod-yml  $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/prod.yml --templates-yml $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/template_builds.yml  --src-project  $SRC_PROJECT_PODMAN_NETBIRD
     --overdrive
  - Volume Quadlets python3 volume_quadlets_generations.py --prod-yml  $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/prod.yml --templates-yml $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/template_builds.yml  --src-project  $SRC_PROJECT_PODMAN_NETBIRD
    --overdrive
  -To build Containers Quadlet python3 quadlets_generations.py --prod-yml  $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/prod.yml --templates-yml $SRC_PROJECT_PODMAN_NETBIRD/configurations_build_settings/template_builds.yml  --src-project  $SRC_PROJECT_PODMAN_NETBIRD
  --overdrive
7. Push files to the correct directories:
```bash
   python3 $SRC_PROJECT_PODMAN_NETBIRD/helper_scripts/push_configurations_quadlets.py \
     --prod-yml prod.yml \
     --default-rl \
     --source-path $SRC_PROJECT_PODMAN_NETBIRD
```

8. Start all services using the quadlets manager:
```bash
   python3 $SRC_PROJECT_PODMAN_NETBIRD/helper_scripts/quadlets_manager.py
```
   > **Start order:** always start **volumes and networks** first, then **containers**.  
   > Depending on your example, the recommended startup sequence is:  
   > `Databases → Keycloak → Netbird components → Traefik`

## To do
   
  - Fix the generations of configurations and quadlets from templates and rebuild scripts to smaller parts run by one.

 -  Backups Scripts and test it.

 -  Migration script for existing configurations.

 - Custom TLS certificate.

 -  Mulptiple Proxies.

 - Log exporter helper to OTLP (Open telemetry).

