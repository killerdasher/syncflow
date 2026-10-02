# Roadmap

Sequenced by user value vs. effort. Nothing here is a commitment — priorities
move.

## ✅ v1.0 (current)

Desktop: Windows 10/11, Linux (AppImage/deb/rpm), macOS (Intel + Apple
Silicon). Transfers, sync folders, chat, mDNS discovery, E2E crypto, 63-check
security suite, automated 3-OS releases.

## 🔜 Next

| Item | Notes |
|------|-------|
| Android **companion** app | Phone UI (Capacitor-wrapped React) drives the desktop over LAN: pairing-code auth on a LAN WebSocket mode of the backend. Phone shows chat/devices/transfers while the desktop is on. Build APK in CI, publish to Releases. |
| Code signing | SignPath OSS for Windows (see [code-signing.md](code-signing.md)); Apple Developer ID when budget allows (see [macos.md](macos.md)). |
| Auto-update | electron-updater against GitHub Releases — after signing exists, so updates are verifiable. |

## 🔬 Later / exploring

| Item | Notes |
|------|-------|
| Standalone Android | Native port of the protocol (X25519/Ed25519/AES-GCM, TCP framing, mDNS) so the phone works **without** the desktop. Large effort; companion first validates demand. |
| iOS | Requires a Mac + Apple Developer account ($99/yr) + Xcode; release via TestFlight/App Store. Blocked on those prerequisites. |
| Flatpak / Snap | Alternative Linux stores after the core releases are stable. |
| WAN / relay | **Not planned.** SyncFlow is deliberately LAN-only — the honest scope stays unless the threat model is redesigned. |

## Known limitations (documented, not hidden)

- glibc **2.35+** on Linux (Ubuntu 22.04 / Debian 12 / Fedora 36 era or newer)
  — set by the Electron + PyInstaller build floor.
- One instance per machine (fixed ports 18973/18974).
- Pairing is trust-on-first-use (verify devices out of band if your LAN is
  hostile).
