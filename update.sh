#!/usr/bin/env bash
set -e

APP_DIR="/opt/mediana"
cd "$APP_DIR"

# Allow git operations in this directory
git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'main')"
if [ "$BRANCH" = "HEAD" ] || [ -z "$BRANCH" ]; then
    BRANCH="main"
fi

# Fetch latest commits from GitHub
git fetch origin "$BRANCH" --quiet

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] New commit found on $BRANCH ($LOCAL -> $REMOTE). Updating..."

    # Hard reset ensures clean sync even if local files were touched
    git reset --hard "origin/$BRANCH"

    # Install/update packages if requirements.txt changed
    if git diff --name-only "$LOCAL" "$REMOTE" | grep -q "^requirements.txt$"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] requirements.txt changed. Installing dependencies..."
        python3 -m pip install -r requirements.txt --quiet
    fi

    # Restart site service
    if systemctl is-active --quiet mediana; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restarting mediana.service..."
        systemctl restart mediana
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restart complete."
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting mediana.service..."
        systemctl start mediana || true
    fi
fi
