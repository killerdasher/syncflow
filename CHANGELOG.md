# Changelog

All notable changes to SyncFlow are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Device verification (SAS)**: 16-icon out-of-band fingerprint in
  Settings → Pinned Devices → Verify — compare on both ends to rule out a
  pairing-time man-in-the-middle; hex fingerprint fallback
- **Subset approval**: accepting an incoming transfer can now pick which
  files to take (checkbox list); only those are transferred, skipped files
  are counted on the card
- **Wire protocol specification** (`docs/protocol.md`): framing, discovery,
  pairing/auth, exhaustive message catalogue, E2E flow, error catalogue,
  limits and an honest versioning policy
- **Architecture decision records** (`docs/adr/`): loopback-by-default,
  frozen SAS/versioning, upload staging/resume
- **Deterministic fuzz suite** (`backend/tests/t_fuzz`, 10 checks): seeded
  garbage/structural/type-confusion WS frames, oversized frames, hostile
  TCP length prefixes and non-handshake payloads — every case must end in a
  sanitized `error` frame or a clean close, never a hang or a traceback;
  suite total now 147 checks
- Code of Conduct (Contributor Covenant 2.1)

### Fixed

- **WS bridge swallowed no-op `settings:apply`** (no reply at all) and
  coerced non-bool `autoAccept` values (`bool("no")` is `True`) — now every
  request is answered and field types are validated strictly
- **WS bridge crashed on absurdly large JSON integers** (Python's
  int-digit `ValueError` escaped the narrow `except`); the connection died
  instead of returning `error: invalid JSON`
- Broken GitHub README badge (shields has no `/attestations` endpoint)
  now renders a valid SLSA-provenance badge linking to the real
  attestation page; roadmap auto-update row corrected

### Changed

- `run_all.sh` counts a crashed suite as a failure instead of letting it
  read as green
- Dead `device:removed` WS case removed (mirrors undocumented reality;
  see `docs/protocol.md` §6.5)

## [1.1.1] — 2026-10-03

### Added

- **Android companion APK on every release**: the Android APK is built by CI
  on each tag and published with the desktop artifacts (signed with the
  release keystore, covered by `SHA256SUMS.txt` and provenance attestation)
- **Upload resume-after-interrupt**: a dropped connection keeps staged bytes
  for 30 minutes; the companion asks `transfer:upload:resume`, skips
  completed files, and appends to the partial file — no more re-sending a
  8 GB file because Wi-Fi blinked
- **Companion receive push**: phone pulls files from the desktop over the
  authenticated WebSocket, verifies SHA-256, saves via the system share
  sheet; **QR connect** (in-app camera scan, system-camera deep link,
  manual entry) and **local notifications** for new activity

### Changed

- Tailwind CSS 4 and React 19 (build-time only, pixel-verified against v3)
- Companion web CSP now lists explicit `ws://*:*`/`http://*:*` sources —
  Chromium treats omitted-port sources as default-port-only, which blocked
  every LAN WebSocket from browsers and the Android WebView

## [1.1.0] — 2026-10-03

### Added

- **LAN mode with pairing codes**: opt-in `SYNCFLOW_WS_HOST` bind, 8-char
  single-use codes (5-minute TTL, 5-attempt lockout), hashed bearer tokens;
  Settings → Network shows the code + QR for phone pairing
- **Mobile companion mode**: the same renderer runs in a browser/WebView
  against the desktop backend over LAN (transport shim, device picker,
  chat, transfers, settings)
- **Incoming-transfer approval prompt** with 60s timeout and auto-accept
  setting; **pinned devices** management with forget
- **Tray icon, window-wide drag-and-drop, live auto-update checks**
  (electron-updater against GitHub Releases)
- **One-click launch**: desktop/Start-Menu shortcuts on Windows, menu entry
  for AppImage, `.desktop` for deb/rpm
- Provenance attestations + `SHA256SUMS.txt` for every release

### Security

- Signed + freshness-checked handshakes, TOFU identity pinning, encrypted
  metadata, per-chunk verification, origin-checked control plane
- 130-check security suite (`backend/tests/run_all.sh`) incl. dedicated
  attack, crypto, LAN-auth, upload and download suites

## [1.0.0] — 2026-10-02

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
