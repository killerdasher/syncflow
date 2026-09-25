#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Self-locating Node (checks common install locations)
if command -v node >/dev/null 2>&1; then
  :
elif [ -x "$HOME/.local/node-v20.18.0-linux-x64/bin/node" ]; then
  export PATH="$HOME/.local/node-v20.18.0-linux-x64/bin:$PATH"
elif [ -x "/tmp/node-v20.18.0-linux-x64/bin/node" ]; then
  export PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH"
else
  echo "Node.js not found. Install Node 20+ first." >&2
  exit 1
fi

echo "Building SyncFlow for production..."
npx electron-vite build

echo "Building distributable packages..."
npx electron-builder --linux

echo "Build complete! Check dist/ folder."
