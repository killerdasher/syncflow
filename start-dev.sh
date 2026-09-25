#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Locate Node.js: permanent install first, then temp dir, then system PATH
for NODE_DIR in "$HOME/.local/node-v20.18.0-linux-x64/bin" "/tmp/node-v20.18.0-linux-x64/bin"; do
  if [ -x "$NODE_DIR/node" ]; then
    export PATH="$NODE_DIR:$PATH"
    break
  fi
done

if ! command -v node &>/dev/null; then
  echo "Node.js not found. Install Node.js 20+ from https://nodejs.org"
  exit 1
fi

if [ ! -d "node_modules" ]; then
  echo "Installing dependencies (first run)..."
  npm install
fi

if [ ! -x "backend/venv/bin/python3" ]; then
  echo "Creating Python venv (first run)..."
  python3 -m venv backend/venv
  backend/venv/bin/pip install -r backend/requirements.txt
fi

echo "Starting SyncFlow (node $(node --version))..."
npx electron-vite dev
