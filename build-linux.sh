#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="/tmp/node-v20.18.0-linux-x64/bin:$PATH"

echo "Building SyncFlow for production..."
npx electron-vite build

echo "Building distributable packages..."
npx electron-builder --linux

echo "Build complete! Check dist/ folder."
