#!/usr/bin/env bash
# Upload heavy catalog assets to the VDS. JSON/HTML stay on GitHub for old app builds.
#
# Usage:
#   export ZSTORE_CDN_HOST=root@193.233.216.247
#   export ZSTORE_CDN_PATH=/var/www/zstore-catalog
#   ./deploy/sync_cdn.sh
#
# Requires rsync over SSH. Run from repo root after build_lite.py.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${ZSTORE_CDN_HOST:?set ZSTORE_CDN_HOST, e.g. root@your.vds}"
DEST="${ZSTORE_CDN_PATH:-/var/www/zstore-catalog}"

DIRS=(
  icons
  shots
  screenshots
  about
)

RSYNC=(rsync -avz --delete --progress)

for dir in "${DIRS[@]}"; do
  if [[ -d "$ROOT/$dir" ]]; then
    "${RSYNC[@]}" "$ROOT/$dir/" "$HOST:$DEST/$dir/"
  fi
done

for sub in covers icons screenshots videos; do
  if [[ -d "$ROOT/d0e4/$sub" ]]; then
    mkdir -p "$DEST/d0e4/$sub" 2>/dev/null || true
    "${RSYNC[@]}" "$ROOT/d0e4/$sub/" "$HOST:$DEST/d0e4/$sub/"
  fi
done

echo "Synced to $HOST:$DEST (CDN base should match ZSTORE_CDN_BASE)"
