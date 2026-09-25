# SyncFlow

Cross-device file sync application with a navy blue/aqua theme and animated UI.

## Requirements

- **Node.js** 20+
- **Python** 3.11+

## Quick Start (Linux / Parrot OS)

```bash
cd syncflow
./start-dev.sh
```

## Quick Start (Windows)

Double-click `start-windows.bat`

Or manually:
```cmd
cd syncflow
start-windows.bat
```

## First-Time Setup

### Linux
```bash
cd syncflow/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..
npm install
```

### Windows
```cmd
cd syncflow\backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cd ..
npm install
```

## Build for Distribution

### Linux
```bash
./build-linux.sh
```
Output: `dist/` folder (AppImage + deb)

### Windows
```cmd
build-windows.bat
```
Output: `dist\` folder (EXE installer + portable)

## Architecture

```
SyncFlow/
├── electron/          # Electron main process (TypeScript)
├── src/               # React frontend (TypeScript + Tailwind)
│   ├── components/    # UI components
│   ├── stores/        # Zustand state management
│   ├── hooks/         # Custom React hooks
│   └── lib/           # Types and constants
├── backend/           # Python backend
│   ├── discovery/     # mDNS device discovery (zeroconf)
│   ├── transfer/      # File transfer engine (TCP + chunking)
│   ├── networking/    # TCP server/client, relay client
│   ├── crypto/        # AES-256 encryption + key management
│   └── relay/         # Standalone relay server for WAN
└── build/             # App icons
```

## Features

- **Device Discovery**: Automatic LAN discovery via mDNS/Bonjour
- **File Transfer**: Chunked TCP transfer with resume support (up to 10GB)
- **Auto-Sync**: Continuous folder synchronization with filesystem watching
- **Encryption**: AES-256-GCM + TLS 1.3
- **WAN Relay**: Self-hosted relay server for internet transfers
- **Dark Theme**: Navy blue + dark aqua with animated particles and glass morphism

## Technology Stack

| Layer | Tech |
|-------|------|
| UI | Electron + React 18 + TypeScript |
| Styling | TailwindCSS 3 |
| State | Zustand |
| Animation | Framer Motion |
| Backend | Python 3.13 (asyncio) |
| Discovery | zeroconf (mDNS) |
| Transfer | Custom TCP protocol |
| Encryption | cryptography (AES-256-GCM) |
| Build | electron-vite + electron-builder |
