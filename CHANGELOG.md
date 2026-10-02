# Changelog

All notable changes to SyncFlow are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] — Unreleased

First public release.

### Added

- **Device discovery**: mDNS/Bonjour auto-discovery plus manual IP add
- **File transfer**: chunked LAN TCP transfer up to 10 GB with per-chunk
  SHA-256 verification and blockchain-style chaining; approval/auto-accept
- **Sync folders**: pair a local folder with a device; push on demand or on an
  interval (1/5/15 min), delivered into a peer-configured destination folder
- **E2E chat**: encrypted chat relayed between devices, persistent history
- **Security**: AES-256-GCM, Ed25519 signatures, X25519 key exchange,
  trust-on-first-use pinning with Settings → Pinned Devices (forget support)
- **Notifications**: desktop notifications for transfers and chat
- **Persistence**: transfer history and chat log survive restarts; close-to-tray
- **Platform**: Linux (AppImage + deb + rpm), Windows 10/11 (NSIS installer +
  portable), macOS (dmg, Intel + Apple Silicon)
- **Quality**: 63-check security test suite (`backend/tests/run_all.sh`),
  TypeScript typecheck, CI on every push
