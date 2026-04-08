#!/bin/bash
# ============================================
# Oracle Cloud VPS — Initial Setup Script
# ============================================
# Run this ONCE on a fresh Ubuntu 22.04 ARM instance:
#   chmod +x scripts/setup_oracle.sh
#   sudo ./scripts/setup_oracle.sh
#
# Tested on: VM.Standard.A1.Flex (ARM64), Ubuntu 22.04

set -euo pipefail

echo "=========================================="
echo "  Course RAG — Oracle Cloud VPS Setup"
echo "=========================================="

# ── 1. System Updates ──
echo "[1/6] Updating system packages..."
apt-get update -y && apt-get upgrade -y

# ── 2. Install Docker ──
echo "[2/6] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    # Let the current user run docker without sudo
    usermod -aG docker ubuntu
    echo "  Docker installed: $(docker --version)"
else
    echo "  Docker already installed: $(docker --version)"
fi

# Install Docker Compose plugin
echo "  Installing Docker Compose plugin..."
apt-get install -y docker-compose-plugin 2>/dev/null || true
echo "  Docker Compose: $(docker compose version 2>/dev/null || echo 'plugin not found, using standalone')"

# ── 3. Install Caddy ──
echo "[3/6] Installing Caddy..."
if ! command -v caddy &> /dev/null; then
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y
    apt-get install -y caddy
    systemctl enable caddy
    echo "  Caddy installed: $(caddy version)"
else
    echo "  Caddy already installed: $(caddy version)"
fi

# ── 4. Configure Firewall (iptables) ──
echo "[4/6] Configuring firewall rules..."
# Oracle Cloud uses iptables by default; ensure HTTP/HTTPS are open
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT 2>/dev/null || true
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT 2>/dev/null || true
netfilter-persistent save 2>/dev/null || iptables-save > /etc/iptables/rules.v4 2>/dev/null || true
echo "  Ports 80 and 443 opened"

# ── 5. Create App Directory ──
echo "[5/6] Creating application directory..."
APP_DIR="/opt/courserag"
mkdir -p "$APP_DIR"/{data/chroma_db,credentials}
chown -R ubuntu:ubuntu "$APP_DIR"
echo "  App directory: $APP_DIR"

# ── 6. Create log directory for Caddy ──
echo "[6/6] Setting up logging..."
mkdir -p /var/log/caddy
chown caddy:caddy /var/log/caddy

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Copy your project files to $APP_DIR/"
echo "  2. Copy .env and credentials/ to $APP_DIR/"
echo "  3. Copy Caddyfile to /etc/caddy/Caddyfile"
echo "  4. Edit Caddyfile: replace YOUR_SUBDOMAIN"
echo "  5. cd $APP_DIR && docker compose up -d --build"
echo "  6. sudo systemctl reload caddy"
echo ""
echo "  Your app will be live at https://YOUR_SUBDOMAIN.duckdns.org"
echo ""
