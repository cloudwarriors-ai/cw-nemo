#!/usr/bin/env bash
set -euo pipefail
EXT_DIR="${1:?usage: install-extensions.sh <extensions-dir>}"
for pkg in "$EXT_DIR"/*/package.json; do
  dir="$(dirname "$pkg")"
  if jq -e '.dependencies // empty | length > 0' "$pkg" >/dev/null 2>&1; then
    echo "[cw] installing deps for $(basename "$dir")"
    (cd "$dir" && npm install --omit=dev)
  fi
done
