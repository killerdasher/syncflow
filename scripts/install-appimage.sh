#!/usr/bin/env bash
# SyncFlow AppImage -> desktop + application-menu shortcut (user-level, no root).
#
# AppImages cannot install menu entries themselves (no installer step), so
# this script does it: copies the icon, writes a freedesktop .desktop entry
# pointing at YOUR copy of the AppImage, and refreshes the menu database.
#
# Usage:
#   ./install-appimage.sh                       # auto-finds SyncFlow*.AppImage
#   ./install-appimage.sh /path/SyncFlow.AppImage
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"

img="${1:-}"
if [ -z "$img" ]; then
  for d in "$here" "$PWD" "$HOME/Downloads" "$HOME/Desktop" "$HOME/.local/bin"; do
    cand=$(ls -1t "$d"/SyncFlow*.AppImage 2>/dev/null | head -1 || true)
    if [ -n "${cand:-}" ]; then img="$cand"; break; fi
  done
fi
if [ -z "${img:-}" ] || [ ! -f "$img" ]; then
  echo "error: AppImage not found." >&2
  echo "usage: $0 /path/to/SyncFlow-x86_64.AppImage" >&2
  exit 1
fi
img="$(readlink -f "$img")"
chmod +x "$img"

apps="$HOME/.local/share/applications"
icondir="$HOME/.local/share/icons/hicolor/1024x1024/apps"
mkdir -p "$apps" "$icondir"

icon_name=""
icon_src="$here/syncflow-icon.png"
if [ -f "$icon_src" ]; then
  cp "$icon_src" "$icondir/syncflow.png"
  icon_name="syncflow"
else
  # Fallback: pull the embedded .DirIcon out of the AppImage itself
  tmp="$(mktemp -d)"
  if (cd "$tmp" && "$img" --appimage-extract .DirIcon >/dev/null 2>&1) \
     && [ -f "$tmp/squashfs-root/.DirIcon" ]; then
    if cp "$tmp/squashfs-root/.DirIcon" "$icondir/syncflow.png" 2>/dev/null; then
      icon_name="syncflow"
    fi
  fi
  rm -rf "$tmp"
fi

desktop="$apps/syncflow.desktop"
{
  echo "[Desktop Entry]"
  echo "Type=Application"
  echo "Name=SyncFlow"
  echo "Comment=Cross-device E2E encrypted file sync and chat"
  printf 'Exec="%s"\n' "$img"
  printf 'Icon=%s\n' "$icon_name"
  echo "Terminal=false"
  echo "Categories=Utility;"
  echo "Keywords=file;sync;transfer;chat;lan;e2e;"
  echo "StartupWMClass=syncflow"
} > "$desktop"

command -v update-desktop-database >/dev/null 2>&1 \
  && update-desktop-database "$apps" 2>/dev/null || true

echo "SyncFlow shortcut installed (no root needed):"
echo "  menu entry : $desktop"
if [ -n "$icon_name" ]; then
  echo "  icon       : $icondir/syncflow.png"
else
  echo "  icon       : (not found — kept generic; extract this script next to syncflow-icon.png)"
fi
echo "  launches   : $img"
echo
echo "Open it from your application menu (search \"SyncFlow\"), or run:"
echo "  $img"
