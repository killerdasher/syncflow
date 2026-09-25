@echo off
title SyncFlow - Windows Build
cd /d "%~dp0"

echo Building SyncFlow for Windows...
call npx electron-vite build
call npx electron-builder --win

echo Build complete! Check dist\ folder.
pause
