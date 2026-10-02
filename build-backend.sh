#!/usr/bin/env bash
# Builds the Python backend as a self-contained native binary (PyInstaller, onedir).
# Used locally by build-linux.sh and in CI (release.yml / ci.yml).
# Output: backend/dist/syncflow-backend/syncflow-backend(.exe)
set -euo pipefail
cd "$(dirname "$0")/backend"

# An explicit PYTHON (e.g. CI selecting a specific architecture's interpreter)
# always wins; otherwise prefer the local venv, then python3 on PATH.
if [ -z "${PYTHON:-}" ]; then
  PYTHON="venv/bin/python"
  if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
  fi
fi

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "ERROR: Python interpreter not found: $PYTHON" >&2
  exit 1
fi

"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name syncflow-backend \
  --distpath dist \
  --workpath build \
  --specpath build \
  main.py

if [ -x "dist/syncflow-backend/syncflow-backend" ]; then
  echo "OK: backend/dist/syncflow-backend/syncflow-backend"
elif [ -f "dist/syncflow-backend/syncflow-backend.exe" ]; then
  echo "OK: backend/dist/syncflow-backend/syncflow-backend.exe"
else
  echo "ERROR: backend binary not produced" >&2
  exit 1
fi
