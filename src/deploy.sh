#!/bin/bash
set -e

# ── Config ──────────────────────────────────────────────
APP_DIR="/opt/dicom-api"

echo "==> Installing Docker..."
apt-get update -qq
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

echo "==> Setting up app directory..."
mkdir -p "$APP_DIR"
cp main.py requirements.txt Dockerfile docker-compose.yml .dockerignore "$APP_DIR/"
cd "$APP_DIR"

echo "==> Starting containers..."
docker compose up -d --build

echo ""
echo "✓ Done."
docker compose ps
echo ""
echo "API is available at http://$(hostname -I | awk '{print $1}'):8000"
echo "Orthanc web UI at  http://$(hostname -I | awk '{print $1}'):8042"