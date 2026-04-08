#!/bin/bash
# ============================================
# Deploy Course RAG to Oracle Cloud VPS
# ============================================
# Usage:
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh <VPS_IP> [SSH_KEY_PATH]
#
# Example:
#   ./scripts/deploy.sh 129.153.xx.xx ~/.ssh/oracle_key

set -euo pipefail

VPS_IP="${1:?Usage: ./scripts/deploy.sh <VPS_IP> [SSH_KEY_PATH]}"
SSH_KEY="${2:-~/.ssh/id_rsa}"
VPS_USER="ubuntu"
APP_DIR="/opt/courserag"

SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no $VPS_USER@$VPS_IP"
SCP_CMD="scp -i $SSH_KEY -o StrictHostKeyChecking=no"

echo "=========================================="
echo "  Deploying Course RAG to $VPS_IP"
echo "=========================================="

# ── 1. Sync project files ──
echo "[1/5] Syncing project files..."
rsync -avz --delete \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='tmp' \
    --exclude='tests' \
    --exclude='.pytest_cache' \
    --exclude='*.pyc' \
    --exclude='.gemini' \
    --exclude='data/chroma_db' \
    --exclude='data/sessions.db' \
    --exclude='data/checkpoints.db' \
    ./ "$VPS_USER@$VPS_IP:$APP_DIR/"

# ── 2. Ensure .env and credentials are present ──
echo "[2/5] Syncing secrets..."
$SCP_CMD .env "$VPS_USER@$VPS_IP:$APP_DIR/.env"
$SCP_CMD credentials/oauth_credentials.json "$VPS_USER@$VPS_IP:$APP_DIR/credentials/" 2>/dev/null || echo "  (No oauth_credentials.json found locally, skipping)"
$SCP_CMD credentials/token.pickle "$VPS_USER@$VPS_IP:$APP_DIR/credentials/" 2>/dev/null || echo "  (No token.pickle found locally, skipping)"

# ── 3. Deploy Caddyfile ──
echo "[3/5] Deploying Caddyfile..."
$SCP_CMD Caddyfile "$VPS_USER@$VPS_IP:/tmp/Caddyfile"
$SSH_CMD "sudo cp /tmp/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy"

# ── 4. Build & Start Docker ──
echo "[4/5] Building and starting Docker containers..."
$SSH_CMD "cd $APP_DIR && docker compose up -d --build"

# ── 5. Verify ──
echo "[5/5] Verifying deployment..."
sleep 5
HEALTH=$($SSH_CMD "curl -sf http://localhost:8000/api/health" 2>/dev/null || echo "FAILED")
echo "  Health check: $HEALTH"

echo ""
echo "=========================================="
echo "  Deployment Complete!"
echo "=========================================="
echo ""
echo "  App: https://YOUR_SUBDOMAIN.duckdns.org"
echo "  Logs: $SSH_CMD 'cd $APP_DIR && docker compose logs -f'"
echo ""
