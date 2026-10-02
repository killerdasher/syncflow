@echo off
title SyncFlow - Windows Build
cd /d "%~dp0"

echo Building Python backend binary (PyInstaller)...
pushd backend
set PY=venv\Scripts\python.exe
if not exist "%PY%" set PY=python
"%PY%" -m PyInstaller --noconfirm --clean --onedir --name syncflow-backend --distpath dist --workpath build --specpath build main.py
if errorlevel 1 (echo Backend build failed & pause & exit /b 1)
popd

echo Building SyncFlow for Windows...
call npx electron-vite build
call npx electron-builder --win

echo Build complete! Check dist\ folder.
pause
