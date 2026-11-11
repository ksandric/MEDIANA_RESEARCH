#!/usr/bin/env bash
set -e

APP_DIR="/opt/mediana"

echo "=== Setting up Mediana Research auto-update and service ==="

cd "$APP_DIR"
chmod +x "$APP_DIR/update.sh"

# Install systemd service for running the site
cp "$APP_DIR/mediana.service" /etc/systemd/system/mediana.service

# Install systemd service and timer for auto-updating from git
cp "$APP_DIR/mediana-update.service" /etc/systemd/system/mediana-update.service
cp "$APP_DIR/mediana-update.timer" /etc/systemd/system/mediana-update.timer

# Reload systemd configuration
systemctl daemon-reload

# Enable and start the web application
systemctl enable --now mediana.service

# Enable and start the 1-minute auto-update timer
systemctl enable --now mediana-update.timer

echo ""
echo "=== Setup complete! ==="
echo ""
systemctl status mediana.service --no-pager
echo ""
systemctl status mediana-update.timer --no-pager
