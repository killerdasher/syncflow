@echo off
title SyncFlow Launcher
echo Starting SyncFlow...
cd /d "%~dp0"

REM Check for Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo Node.js not found!
    echo Please install Node.js from https://nodejs.org
    echo Version 20 or higher required.
    pause
    exit /b 1
)

REM Check for Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found!
    echo Please install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

REM Install Python deps if venv missing
if not exist "backend\venv" (
    echo Setting up Python environment...
    cd backend
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
    cd ..
)

REM Install Node deps if missing
if not exist "node_modules" (
    echo Installing dependencies...
    call npm install
)

echo Starting SyncFlow application...
call npx electron-vite dev
pause
