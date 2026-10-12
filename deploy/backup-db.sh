#!/usr/bin/env bash
# ==============================================================================
# Daily Automated PostgreSQL Backup Script for MPP Web Portal
# Installed to: /etc/cron.daily/mpp-portal-backup
# ==============================================================================

set -euo pipefail

APP_DIR="/opt/mpp-portal"
BACKUP_DIR="/var/backups/mpp-portal"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/mpp_hub_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

cd "${APP_DIR}"
docker compose exec -T db pg_dump -U postgres mpp_hub | gzip > "${BACKUP_FILE}"
chmod 600 "${BACKUP_FILE}"

# Prune backups older than 30 days
find "${BACKUP_DIR}" -type f -name "mpp_hub_*.sql.gz" -mtime +30 -delete
