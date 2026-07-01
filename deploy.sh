#!/usr/bin/env bash
# Deploy melia-facebook-ads to the Hetzner box as the `fb-worker` systemd service.
#
# Mirrors how google-ads' ads-worker is actually deployed (copy + editable
# install + restart), but captured as a script instead of tribal knowledge
# (see PLAN.md §8). Uses tar-over-ssh (works from Windows Git Bash — no rsync
# needed). Run from the repo root on the local machine:
#
#   ./deploy.sh
#
# The box's /opt/facebook-ads/.env is NEVER synced (secrets) — create it once
# on the box from .env.example.
set -euo pipefail

BOX="${FB_DEPLOY_HOST:-root@crm.kvadra.me}"
KEY="${FB_DEPLOY_KEY:-$HOME/.ssh/id_ed25519}"
DEST="/opt/facebook-ads"

echo ">> shipping source to $BOX:$DEST (tar over ssh)"
tar czf - \
  --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.git' --exclude='.env' --exclude='*.log' \
  --exclude='research' --exclude='.pytest_cache' --exclude='.ruff_cache' \
  . | ssh -i "$KEY" "$BOX" "mkdir -p $DEST && tar xzf - -C $DEST"

echo ">> installing deps, migrating, (re)starting fb-worker"
ssh -i "$KEY" "$BOX" bash -s <<'REMOTE'
set -euo pipefail
cd /opt/facebook-ads
if [ ! -f .env ]; then echo "ERROR: /opt/facebook-ads/.env missing — create it from .env.example"; exit 1; fi
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -e .
.venv/bin/alembic upgrade head
install -m644 fb-worker.service /etc/systemd/system/fb-worker.service
systemctl daemon-reload
systemctl enable fb-worker >/dev/null 2>&1 || true
systemctl restart fb-worker
sleep 2
systemctl --no-pager status fb-worker | head -6
REMOTE

echo ">> done."
