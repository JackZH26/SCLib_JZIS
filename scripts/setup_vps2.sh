#!/usr/bin/env bash
# scripts/setup_vps2.sh — one-time VPS2 bootstrap for SCLib_JZIS.
#
# Run as root on VPS2 (72.62.251.29). Safe to re-run; steps are idempotent.
#
#   ssh root@72.62.251.29
#   cd /opt/SCLib_JZIS && bash scripts/setup_vps2.sh
#
# Prereqs on VPS2:
#   - Nginx already installed and serving jzis.org + asrp.jzis.org (do NOT break).
#   - DNS A record api.jzis.org -> 72.62.251.29.
#   - GCP ADC already at /root/.config/gcloud/application_default_credentials.json.
#
# This script does NOT touch the existing jzis.org server block — you must
# append the `location /sclib` block from nginx/sclib.conf by hand.

set -euo pipefail

REPO_DIR="/opt/SCLib_JZIS"
REPO_URL="https://github.com/JackZH26/SCLib_JZIS.git"

log() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m!!\033[0m %s\n' "$*" >&2; }

# 1. Install Docker + compose plugin
if ! command -v docker >/dev/null 2>&1; then
    log "Installing Docker"
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker root || true
else
    log "Docker already installed ($(docker --version))"
fi

if ! docker compose version >/dev/null 2>&1; then
    warn "docker compose plugin missing — install docker-compose-plugin from your distro"
fi

# 2. Clone or update repo
if [ ! -d "$REPO_DIR/.git" ]; then
    log "Cloning repo into $REPO_DIR"
    mkdir -p "$REPO_DIR"
    git clone "$REPO_URL" "$REPO_DIR"
else
    log "Repo exists, pulling latest"
    git -C "$REPO_DIR" pull --ff-only origin main
fi

cd "$REPO_DIR"

# 3. Create .env and credentials dir
if [ ! -f .env ]; then
    log "Creating .env from .env.example — EDIT BEFORE STARTING CONTAINERS"
    cp .env.example .env
    chmod 600 .env
else
    log ".env already present (leaving untouched)"
fi

mkdir -p credentials
if [ ! -f credentials/gcp-sa.json ]; then
    warn "credentials/gcp-sa.json missing — place GCP service account JSON there"
fi

# 4. SSL cert for api.jzis.org (only if not already present)
if [ ! -f /etc/letsencrypt/live/api.jzis.org/fullchain.pem ]; then
    log "Requesting Let's Encrypt cert for api.jzis.org"
    certbot --nginx -d api.jzis.org --non-interactive --agree-tos -m jack@jzis.org || \
        warn "certbot failed — run manually: certbot --nginx -d api.jzis.org"
else
    log "api.jzis.org cert already present"
fi

# 5. Install nginx snippet for api.jzis.org
if [ ! -f /etc/nginx/conf.d/sclib.conf ]; then
    log "Installing /etc/nginx/conf.d/sclib.conf"
    cp nginx/sclib.conf /etc/nginx/conf.d/sclib.conf
else
    log "nginx/sclib.conf already installed (leaving untouched — diff manually if changed)"
fi

warn "Reminder: append the 'location /sclib' block from nginx/sclib.conf into /etc/nginx/sites-available/jzis.org by hand."

log "nginx -t"
nginx -t

log "Reloading nginx"
systemctl reload nginx

log "Setup complete. Next steps:"
cat <<'EOF'
  1. Fill in /opt/SCLib_JZIS/.env (DB_PASSWORD, JWT_SECRET, RESEND_API_KEY, VERTEX_AI_INDEX_ENDPOINT).
  2. Place GCP service account JSON at /opt/SCLib_JZIS/credentials/gcp-sa.json.
  3. Append location /sclib block into /etc/nginx/sites-available/jzis.org and `systemctl reload nginx`.
  4. cd /opt/SCLib_JZIS && docker compose up -d
  5. docker compose ps   # verify all 4 containers healthy
EOF
