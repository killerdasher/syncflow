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

## Two-Device LAN Test

1. Connect both machines to the **same network** (same router/Wi-Fi).
2. Start SyncFlow on both: `./start-dev.sh` (or install the AppImage/deb on the second machine).
3. Wait ~5s — each dashboard should show the other under **Devices** (mDNS discovery).
   - Not discovered? Use **Add Device** → enter the peer's name + LAN IP (find it with `hostname -I`).
4. Click **Send Files** on machine A → pick files → send.
5. On machine B an amber **approval card** appears — click **✓ Accept** (or ✗ Decline).
   - Skip prompts permanently: Settings → enable **Auto-accept transfers** → Save.
6. Verify: transferred file lands in `~/Downloads/SyncFlow/`, card shows **Chain verified**.
7. Chat tab: messages relay between both, each with a hash badge.

**Ports needed** (allow in firewall): TCP `18974` (transfers), UDP `5353` (mDNS discovery).
WS `18973` is localhost-only. Packaged builds require `python3` on PATH (3.13 recommended).

**Expected first-run state:** "0 of 0 connected / No devices discovered yet" is normal until a peer is online.

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
│   ├── transfer/      # File transfer engine (TCP + chunking + sync folders)
│   ├── networking/    # TCP server/client
│   ├── crypto/        # E2E crypto (AES-GCM, Ed25519, X25519) + trust store
│   ├── relay/         # Standalone relay server module (not wired into the UI)
│   └── tests/         # Security suite (run_all.sh, 63 checks)
└── build/             # App icons
```

## Features

- **Device Discovery**: Automatic LAN discovery via mDNS/Bonjour (plus manual IP add)
- **File Transfer**: Chunked TCP transfer with end-to-end encryption (up to 10 GB)
- **Sync Folders**: Pair a local folder with a device — push new/changed files manually or on an interval (1/5/15 min), routed into a folder the peer configured itself
- **Security**: AES-256-GCM end-to-end encryption, Ed25519 signatures, X25519 key exchange, trust-on-first-use pinning (manageable in Settings → Security), per-chunk SHA-256 verification with blockchain-style chaining
- **Pinned Devices**: See and forget paired devices (Settings → Security)
- **Notifications**: Desktop notifications for incoming transfers and chat (click focuses the app)
- **History**: Transfer history and chat log persist across restarts
- **Dark Theme**: Navy blue + dark aqua with animated particles and glass morphism

> **Honest scope:** transfers use a direct LAN connection with application-layer
> end-to-end encryption — there is **no TLS layer** and no WAN relay in the UI.
> See `SECURITY_REPORT.md` for the full threat model and test evidence.

## Tests

```bash
backend/tests/run_all.sh    # 63 checks against fresh live instances, ~5 min
```

Starts two backend instances on test ports, runs six suites (DoS, protocol/crypto,
active MITM proxy, WebSocket/app, rogue mDNS, extra scenarios), tears down,
prints totals. Exit 0 = all green. Typecheck with `npx tsc --noEmit`.

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
| Encryption | cryptography (AES-256-GCM, Ed25519, X25519) |
| Build | electron-vite + electron-builder |
