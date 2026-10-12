#!/usr/bin/env bash
# ==============================================================================
# Ubuntu Server LTS (22.04 / 24.04) Hyper-V VM Provisioning Script
# Project: MS Project Centralized Resource & Template Hub (MPP Web Portal)
# Usage:   sudo bash deploy/ubuntu-vm-install.sh
# ==============================================================================

set -euo pipefail

APP_DIR="/opt/mpp-portal"
BACKUP_DIR="/var/backups/mpp-portal"
REPO_URL="https://github.com/UABGarantGroup/mpp-web-portal.git"

echo "=================================================================="
echo " 1. Installing System Packages & Hyper-V Integration Services"
echo "=================================================================="
apt-get update -y
apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    nginx \
    ufw \
    openssl \
    linux-cloud-tools-virtual \
    linux-tools-virtual || true

echo "=================================================================="
echo " 2. Installing Docker Engine & Docker Compose Plugin"
echo "=================================================================="
if ! command -v docker &> /dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    echo "[OK] Docker Engine installed."
else
    echo "[OK] Docker Engine is already installed."
fi

echo "=================================================================="
echo " 3. Deploying Application Code to ${APP_DIR}"
echo "=================================================================="
if [ ! -d "${APP_DIR}/.git" ]; then
    mkdir -p "${APP_DIR}"
    git clone "${REPO_URL}" "${APP_DIR}"
else
    cd "${APP_DIR}"
    git pull origin main
fi

cd "${APP_DIR}"

echo "=================================================================="
echo " 4. Preparing Secure .env Configuration"
echo "=================================================================="
if [ ! -f "${APP_DIR}/.env" ]; then
    RAND_SECRET=$(openssl rand -hex 32)
    RAND_DB_PASS=$(openssl rand -hex 16)
    RAND_EMERG_PASS="Garant_Onboarding_$(openssl rand -hex 4)!"

    cat > "${APP_DIR}/.env" <<EOF
# ==============================================================================
# PRODUCTION ENVIRONMENT (.env) - DO NOT COMMIT OR EXPOSE
# ==============================================================================
ENVIRONMENT=production
SECRET_KEY=${RAND_SECRET}

# PostgreSQL Database Password (used by docker-compose.yml)
POSTGRES_PASSWORD=${RAND_DB_PASS}

# Mandatory Authentication & Emergency Onboarding Admin
AUTH_ENABLED=true
EMERGENCY_ADMIN_USERNAME=emergency_admin
EMERGENCY_ADMIN_PASSWORD=${RAND_EMERG_PASS}

# Microsoft Entra ID (Azure AD) App Registration Credentials
AZURE_AD_TENANT_ID=
AZURE_AD_CLIENT_ID=
AZURE_AD_CLIENT_SECRET=
INITIAL_ADMIN_EMAIL=
EOF
    chmod 600 "${APP_DIR}/.env"
    echo "[IMPORTANT] Created ${APP_DIR}/.env with restricted 600 permissions."
    echo "            Generated Emergency Admin Password: ${RAND_EMERG_PASS}"
    echo "            Please edit ${APP_DIR}/.env to add your AZURE_AD_* credentials."
else
    chmod 600 "${APP_DIR}/.env"
    echo "[OK] Existing ${APP_DIR}/.env preserved (permissions set to 600)."
fi

echo "=================================================================="
echo " 5. Configuring NGINX Reverse Proxy (HTTP/HTTPS)"
echo "=================================================================="
# Generate a fallback self-signed TLS certificate if corporate cert is not yet installed
mkdir -p /etc/nginx/ssl
if [ ! -f /etc/nginx/ssl/mpp-portal.crt ]; then
    VM_IP=$(hostname -I | awk '{print $1}')
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/mpp-portal.key \
        -out /etc/nginx/ssl/mpp-portal.crt \
        -subj "/C=LT/ST=Klaipeda/L=Klaipeda/O=Garant Group/CN=${VM_IP:-mpp.local}" \
        -addext "subjectAltName=IP:${VM_IP:-127.0.0.1},DNS:localhost" 2>/dev/null || \
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/mpp-portal.key \
        -out /etc/nginx/ssl/mpp-portal.crt \
        -subj "/C=LT/ST=Klaipeda/L=Klaipeda/O=Garant Group/CN=mpp.local"
    chmod 600 /etc/nginx/ssl/mpp-portal.key
fi

cp "${APP_DIR}/deploy/nginx/mpp-portal.conf" /etc/nginx/sites-available/mpp-portal.conf
ln -sf /etc/nginx/sites-available/mpp-portal.conf /etc/nginx/sites-enabled/mpp-portal.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "=================================================================="
echo " 6. Configuring UFW Firewall (SSH, HTTP 80, HTTPS 443)"
echo "=================================================================="
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "=================================================================="
echo " 7. Configuring Daily Automated PostgreSQL Backups"
echo "=================================================================="
mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"
cp "${APP_DIR}/deploy/backup-db.sh" /etc/cron.daily/mpp-portal-backup
chmod +x /etc/cron.daily/mpp-portal-backup

echo "=================================================================="
echo " 8. Building & Starting Docker Containers"
echo "=================================================================="
cd "${APP_DIR}"
docker compose up -d --build

echo ""
echo "=================================================================="
echo " DEPLOYMENT COMPLETE!"
echo "=================================================================="
VM_IP=$(hostname -I | awk '{print $1}')
echo " - Portal URL (HTTPS): https://${VM_IP}"
echo " - Portal URL (HTTP):  http://${VM_IP}"
echo " - Config File:        ${APP_DIR}/.env"
echo " - Daily DB Backups:   ${BACKUP_DIR}"
echo ""
echo " Next Step:"
echo " 1. Put your AZURE_AD_TENANT_ID, AZURE_AD_CLIENT_ID, and AZURE_AD_CLIENT_SECRET in ${APP_DIR}/.env"
echo " 2. Run: cd ${APP_DIR} && sudo docker compose restart backend"
echo " 3. In Azure Portal -> App Registrations -> Authentication -> Web Redirect URIs, add:"
echo "    https://${VM_IP}  (or your internal DNS name, e.g. https://mpp.garantgroup.eu)"
echo "=================================================================="
