# SyncFlow

Peer-to-peer **file transfer, sync folders and chat** for your local network —
with real end-to-end encryption and no cloud, no accounts, no telemetry.

<p align="center">
  <img src="docs/screenshots/dashboard.png" alt="SyncFlow dashboard — send files and LAN devices" width="49%">
  <img src="docs/screenshots/chat.png" alt="End-to-end encrypted chat" width="49%">
</p>
<p align="center">
  <img src="docs/screenshots/transfers.png" alt="Transfer history with chain verification" width="49%">
  <img src="docs/screenshots/settings.png" alt="Security settings and pinned devices" width="49%">
</p>

## Download

Grab the latest build for your OS from the **[Releases](../../releases)** page:

| OS | Artifact |
|----|----------|
| **Linux** | `SyncFlow-x.y.z.AppImage` (nearly all distros) · `.deb` (Debian/Ubuntu/Mint) · `.rpm` (Fedora/openSUSE) |
| **Windows 10/11** | `SyncFlow Setup x.y.z.exe` (installer) · `SyncFlow-x.y.z.exe` (portable) |
| **macOS** | `SyncFlow-x.y.z.dmg` (Intel) · `SyncFlow-x.y.z-arm64.dmg` (Apple Silicon) |

All releases include `SHA256SUMS.txt` and GitHub build-provenance
attestations (`gh attestation verify <file> --repo <owner>/syncflow`).
Unsigned builds: Windows shows a SmartScreen note (More info → Run anyway) —
see [docs/code-signing.md](docs/code-signing.md); macOS first-run steps in
[docs/macos.md](docs/macos.md).

## Quick Start (from source)

**Linux / macOS**
```bash
./start-dev.sh
```
**Windows** — double-click `start-windows.bat`

First-time setup, per OS: see [README Development Setup](#development-setup)
below. Portable Windows folder (no install): [docs/windows-setup.md](docs/windows-setup.md).

## Development Setup

Requirements: **Node 20+**, **Python 3.11+**.

```bash
git clone <repo-url> && cd syncflow

# Backend
cd backend && python3 -m venv venv && source venv/bin/activate \
  && pip install -r requirements.txt && cd ..    # Windows: venv\Scripts\activate

npm install
./start-dev.sh                                   # Windows: start-windows.bat
```

## Two-Device LAN Test

1. Connect both machines to the **same network** (same router/Wi-Fi).
2. Start SyncFlow on both (source build, AppImage, installer — any).
3. Wait ~5s — each dashboard shows the other under **Devices** (mDNS discovery).
   - Not discovered? **Add Device** → enter the peer's LAN IP (`hostname -I`).
4. **Send Files** on machine A → pick files → send.
5. Machine B gets an amber **approval card** — **✓ Accept** (or enable
   **Auto-accept transfers** in Settings to skip prompts permanently).
6. File lands in `~/Downloads/SyncFlow/` (Windows: `Downloads\SyncFlow\`),
   card shows **Chain verified**.
7. **Chat** tab: messages relay between both devices with hash badges.

**Firewall:** TCP `18974` + UDP `5353` must be reachable **inbound on both
devices** — one-way-only chat/files almost always means a firewall block.
Per-OS rules: **[docs/networking.md](docs/networking.md)**.

**Expected first-run state:** "0 of 0 connected / No devices discovered yet"
is normal until a peer is online.

## Build for Distribution

```bash
./build-backend.sh     # Python backend → self-contained binary (PyInstaller)
./build-linux.sh       # Linux: AppImage + deb          (also builds backend)
build-windows.bat      # Windows: NSIS installer + portable
```

Releases are built automatically by CI: push a tag `vX.Y.Z` (matching
`package.json`) and the **Release** workflow produces all OS artifacts, then
opens a **draft** GitHub Release for review.

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
│   ├── relay/         # Standalone relay module (not wired into the UI)
│   └── tests/         # Security suite (run_all.sh, 63 checks)
├── build/             # App icons
└── docs/              # Setup, networking, signing, roadmap
```

Packaged apps embed the backend as a **native binary** (PyInstaller, built by
`build-backend.sh`) — no Python install needed on user machines.

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
> See [SECURITY_REPORT.md](SECURITY_REPORT.md) for the full threat model and
> test evidence, and [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Tests

```bash
backend/tests/run_all.sh    # 63 checks against fresh live instances, ~5 min
npx tsc --noEmit            # typecheck
python backend/tests/smoke_windows.py   # portable backend smoke (any OS)
```

CI runs the full suite plus Windows/macOS smokes on every push.

## Technology Stack

| Layer | Tech |
|-------|------|
| UI | Electron + React 18 + TypeScript |
| Styling | TailwindCSS 3 |
| State | Zustand |
| Animation | Framer Motion |
| Backend | Python 3.13 (asyncio), packaged via PyInstaller |
| Discovery | zeroconf (mDNS) |
| Transfer | Custom TCP protocol |
| Encryption | cryptography (AES-256-GCM, Ed25519, X25519) |
| Build | electron-vite + electron-builder, GitHub Actions matrix |

## Platform Notes

- **Linux**: glibc **2.35+** (Ubuntu 22.04, Debian 12, Fedora 36 or newer equivalents)
- **Windows**: 10/11 x64; allow the firewall prompt on first run
- **macOS**: 11+ · [first-run guide](docs/macos.md)
- Roadmap & known limitations: [docs/roadmap.md](docs/roadmap.md)

## Contributing & License

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Released under the [MIT License](LICENSE).
