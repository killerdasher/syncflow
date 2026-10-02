# macOS Setup & First Run

SyncFlow ships as a **dmg** for both **Intel** and **Apple Silicon** Macs,
built by CI. Artifacts are currently **unsigned** (no Apple Developer ID yet),
so macOS shows a Gatekeeper warning on first open.

## Install (unsigned build)

1. Download `SyncFlow-<version>.dmg` (or `SyncFlow-<version>-arm64.dmg` on
   Apple Silicon) from the GitHub Releases page.
2. Open the dmg and drag **SyncFlow** into **Applications**.
3. First launch — pick ONE of these:
   - **Easiest:** right-click (or Control-click) the app → **Open** → **Open**
     again in the dialog. (The menu bar shows "Open" only the first time.)
   - **Terminal alternative:**
     ```bash
     xattr -cr /Applications/SyncFlow.app
     open /Applications/SyncFlow.app
     ```

## Firewall

On first run macOS may ask whether to accept incoming connections — choose
**Allow**. SyncFlow needs inbound TCP `18974` + UDP `5353` (see
[docs/networking.md](networking.md)).

## Why the warning?

Unsigned apps cost **$99/year** (Apple Developer ID) to sign + notarize.
SyncFlow is free and ad-free, so v1 ships unsigned. The release workflow is
already signing-ready: once a Developer ID certificate + notary credentials
exist as repository secrets, releases become signed + notarized with no code
changes.

## Requirements

- macOS 11 (Big Sur) or newer — Electron 33 baseline
- Both Macs on the same LAN
