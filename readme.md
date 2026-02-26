### Enable Firewall

```
sudo firewall-cmd --add-port=8080/tcp --permanent

sudo firewall-cmd --add-port=5432/tcp --permanent

sudo firewall-cmd --reload
```


### Generate Certificates

bash ~/podman-netbird/helper-scripts/generate_selfsigned_certs.sh example.com



### Enable Postgres and Keycloak

```
podman-compose --env-file ~/podman-netbird/.env/.env-keycloak-postgres -f ~/podman-netbird/keycloak-compose.yml up -d
```


### Enable Netbird 

```
podman-compose --env-file ~/podman-netbird/.env/.env-netbird -f ~/podman-netbird/netbird-compose.yml up -d
```

### Enable Netbird Dashboard

```
podman run -d \
  --name netbird-dashboard \
  --restart unless-stopped \
  --network netbird-net \
  -p 127.0.0.1:8080:80 \
  --env-file ~/podman-netbird/.env/dashboard.env \
  --log-driver json-file \
  --log-opt max-size=500m \
  --log-opt max-file=2 \
  netbirdio/dashboard:latest
```

### Enable Netbird Managmenet service
```
podman run -d \
  --name netbird-management \
  --restart unless-stopped \
  --network netbird-net \
  -p 127.0.0.1:8083:80 \
  -v netbird_management:/var/lib/netbird \
  -v ~/podman-netbird/management/management.json:/etc/netbird/management.json:Z \
  --log-driver=json-file \
  --log-opt max-size=500m \
  --log-opt max-file=2 \
  netbirdio/management:latest \
  --port 80 \
  --log-file console \
  --log-level info \
  --disable-anonymous-metrics=false \
  --single-account-mode-domain=netbird.selfhosted \
  --dns-domain=netbird.selfhosted \
  --idp-sign-key-refresh-enabled
```

### Enable Nginx 

```
podman run -d \
  --name nginx-netbird \
  --network netbird-net \
  -p 80:80 \
  -v ~/podman-netbird/nginx_configuration:/etc/nginx/conf.d:ro,Z \
  docker.io/library/nginx:stable
```