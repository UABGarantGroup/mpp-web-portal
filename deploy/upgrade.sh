#!/usr/bin/env bash
# ==============================================================================
# Production Server Upgrade Script from GitHub
# Project: MS Project Centralized Resource & Template Hub (MPP Web Portal)
# Usage:   sudo bash deploy/upgrade.sh [branch_name]
# Example: sudo bash deploy/upgrade.sh main
#          sudo bash deploy/upgrade.sh feat/mssql-migration
# ==============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/mpp-portal}"
TARGET_BRANCH="${1:-}"

# Check root / sudo
if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] Please run as root or with sudo: sudo bash deploy/upgrade.sh"
    exit 1
fi

echo "=================================================================="
echo " MPP Web Portal - Server Upgrade from GitHub"
echo "=================================================================="

# Detect application directory
if [ ! -d "${APP_DIR}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

cd "${APP_DIR}"
echo "[1/6] Application directory: ${APP_DIR}"

# Ensure it's a git repository
if [ ! -d ".git" ]; then
    echo "[ERROR] ${APP_DIR} is not a git repository. Cannot pull updates."
    exit 1
fi

# Detect current branch if no branch argument passed
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ -z "${TARGET_BRANCH}" ]; then
    if [ "${CURRENT_BRANCH}" = "master" ] || [ "${CURRENT_BRANCH}" = "HEAD" ]; then
        TARGET_BRANCH="main"
    else
        TARGET_BRANCH="${CURRENT_BRANCH}"
    fi
fi
echo "[2/6] Target branch: ${TARGET_BRANCH} (Current branch: ${CURRENT_BRANCH})"

# 3. Securely backup .env
if [ -f ".env" ]; then
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    cp .env ".env.backup_${TIMESTAMP}"
    chmod 600 ".env.backup_${TIMESTAMP}"
    echo "[3/6] Backed up .env to .env.backup_${TIMESTAMP}"
else
    echo "[WARNING] No .env found in ${APP_DIR}!"
fi

# 4. Pull latest updates from GitHub
echo "[4/6] Pulling latest changes from origin/${TARGET_BRANCH}..."
git fetch origin

# Switch branch if requested branch differs
if [ "${CURRENT_BRANCH}" != "${TARGET_BRANCH}" ]; then
    git checkout -B "${TARGET_BRANCH}" "origin/${TARGET_BRANCH}"
fi

# Pull latest code
git pull origin "${TARGET_BRANCH}"
echo "[OK] Git pull successful. Latest commit: $(git log -1 --oneline)"

# 5. Detect compose file configuration
COMPOSE_FILE="docker-compose.yml"
if [ -f ".env" ]; then
    if grep -q "MSSQL_HOST=" .env && ! grep -q "^#\s*MSSQL_HOST=" .env && grep -v "^MSSQL_HOST=$" .env | grep -q "MSSQL_HOST="; then
        echo "Detected external Microsoft SQL Server configuration in .env."
        COMPOSE_FILE="docker-compose.external-db.yml"
    fi
fi

if [ -f "docker-compose.override.yml" ]; then
    COMPOSE_CMD="docker compose -f ${COMPOSE_FILE} -f docker-compose.override.yml"
else
    COMPOSE_CMD="docker compose -f ${COMPOSE_FILE}"
fi

echo "[5/6] Building and restarting containers using ${COMPOSE_FILE}..."
${COMPOSE_CMD} up -d --build

# 6. Verify health
echo "[6/6] Verifying backend container health..."
ATTEMPTS=0
MAX_ATTEMPTS=20
HEALTHY=0

while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
    ATTEMPTS=$((ATTEMPTS + 1))
    if curl -s -f http://127.0.0.1:8000/health > /dev/null 2>&1; then
        HEALTHY=1
        break
    fi
    sleep 2
done

echo ""
echo "=================================================================="
if [ $HEALTHY -eq 1 ]; then
    echo " UPGRADE COMPLETED SUCCESSFULLY!"
    echo " - Current Version: $(curl -s http://127.0.0.1:8000/health | grep -o '\"version\":[^,}]*' || echo 'OK')"
    echo " - Container Status:"
    ${COMPOSE_CMD} ps
else
    echo " [WARNING] Backend container did not respond to /health check within 40 seconds."
    echo " Showing recent backend logs:"
    ${COMPOSE_CMD} logs --tail=30 backend
fi
echo "=================================================================="
