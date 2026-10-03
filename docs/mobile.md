# Mobile releases — Android & iOS (full plan)

Everything below is predicted work for the v1.0 line: what exists, what must
be built, what it costs, and where it can block. Companion app first (phone
UI drives a desktop over LAN); a standalone protocol port stays "later" —
see [roadmap.md](roadmap.md).

## Where v1.0 stands

Desktop releases are live (Windows/Linux/macOS, checksums + attestations).
A readiness survey found **three blockers** for any phone client — none of
the companion plumbing exists yet:

| # | Blocker | Evidence |
|---|---------|----------|
| 1 | WS bridge binds `127.0.0.1` only — a phone cannot connect | `backend/ws_bridge.py:42` |
| 2 | No WS authentication at all; only an Origin allowlist that would **403 Capacitor** origins (`capacitor://localhost`, `https://localhost`) | `backend/ws_bridge.py:11-17`, `_handle_client` has no auth |
| 3 | Renderer transport is 100% Electron IPC — in a browser/Capacitor the UI silently does nothing | `src/hooks/useWebSocket.ts:34-42` |

Also: `index.html` CSP only allows `ws://127.0.0.1:*`; `command:send` takes
absolute desktop paths; Sync/Storage/Settings use desktop fs dialogs; the
frameless `TitleBar` is desktop chrome.

**Good news:** the renderer is a clean Vite/React SPA — no router, no
`electron` imports in `src/`, every Electron call guarded behind
`window.electronAPI` (some browser fallbacks already exist in
`src/App.tsx:99-172`). Zustand stores and all deps (react, framer-motion,
lucide-react) are web-safe. The same app reuses fine under Capacitor with a
transport shim.

## Architecture (decided)

- **Companion**: Capacitor 8 wraps the existing React app. A
  `window.electronAPI`-compatible shim speaks raw WebSocket to the
  backend's new LAN mode; pairing code → per-device token.
- **Not doing** (for now): FCM push (desktop can't reach Google), sync
  folders / storage / file-path send on the phone (desktop-fs concepts),
  native UI rewrite.
- **Standalone Android** (phone runs the full protocol) remains a later
  large effort; companion validates demand first.

## Phase 0 — Backend: LAN mode + pairing-code auth (prerequisite) — **LANDED 2026-10-03** (`SYNCFLOW_WS_HOST`, `backend/pairing.py`, `t_lan_auth` 27 checks, suite 134/134)

All desktop-relevant; lands on `main` with tests.

| Item | Detail |
|------|--------|
| Opt-in LAN bind | `SYNCFLOW_WS_HOST` env (default `127.0.0.1`); print bind address at startup (`backend/ws_bridge.py`) |
| Pairing-code flow | Desktop UI: **Settings → Network → Pair a mobile device** (sends `pairing:generate`; card shows code + 5-min countdown + QR + `ws://host:port`, warns if LAN mode off) → short code (8 chars base32, 5 min TTL, single use, rate-limited, lockout after 5 wrong attempts). Phone connects, sends `pairing:{code}` **before any other command**; on success server issues a 32-byte token (`secrets.token_urlsafe`), stored server-side per token + on the phone |
| Subsequent connects | `auth:{token}` handshake; unauthenticated sockets may only send `pairing:`/`auth:` — everything else rejected |
| Origin allowlist | Add Capacitor origins (`capacitor://localhost`, `https://localhost`, `http://localhost` served builds) — but origin is **not** the auth mechanism anymore; auth is code/token |
| Templates to reuse | `backend/relay/server.py:19-57` already has token issue/verify (`auth` → `auth_ok`) — port that pattern |
| Docs | Update `docs/networking.md` (table row for LAN mode), `SECURITY.md` threat model, README limitation bullet |
| Tests | Extend the 134-check suite: happy pairing, wrong-code lockout, token replay, unauthenticated command rejection, LAN-vs-loopback bind, Capacitor origin acceptance, loopback default unchanged |

Estimated: 1–2 working sessions. Risk: low — opt-in, defaults preserve
today's behavior exactly.

## Phase 1 — Renderer transport shim — **LANDED 2026-10-03**
(`src/lib/bridge.ts` shim + `ConnectScreen`, `build:web`/`dev:web`,
CSP widened only in the web config, feature gating, and
`scripts/test-bridge.mjs` — a 9-step live auth/upload/download/QR/resume test wired into CI plus
a Chrome-headless render smoke of `dist-web`.)

| Item | Detail |
|------|--------|
| `src/lib/bridge.ts` | When `!window.electronAPI`: construct a compatible object (`send`, `onMessage`, `onStatus`, `window.*` no-ops) over one raw WS |
| First-run connect screen | Enter `ws://192.168.x.x:18973` + pairing code; persist address/token in `localStorage` |
| `build:web` script | Plain renderer build (electron-vite already builds the renderer from repo root — verify output path, add `vite build` fallback if needed) |
| CSP | Widen `connect-src` for mobile builds (`ws://*:*` — ports must be explicit, a bare `ws://*` matches only port 80 in Chromium — guarded by build-time flag, or Capacitor-only `index.html`) |
| Feature gating | Detect companion mode → hide TitleBar, Sync-Folders, Storage-`open`, Settings `openDirectory`; chat/transfers/dashboard/settings peers work as-is |
| File send | Companion **cannot** pass desktop paths (backend rejects non-existent files, `backend/main.py:131-137`). Phone→desktop uploads land in Phase 3 as chunked `transfer:upload` |

Estimated: 1–2 sessions. Verifiable in plain Chrome before any Android
tooling exists (connect to a LAN-mode desktop).

## Phase 2 — Android APK + CI release — **LANDED 2026-10-03**

| Item | Detail |
|------|--------|
| Scaffold | `npm i -D @capacitor/cli` + `@capacitor/core @capacitor/android`; `npx cap add android`; `webDir` = renderer build output; **commit the `android/` project** |
| App id | `io.github.killerdasher.syncflow` (GitHub-style reverse DNS; changing later = new app identity, so this sticks) |
| SDK floor | minSdk **26** (Android 8), target latest (35), `compileSdk` latest — covers ~97% of devices, modern TLS/webview |
| Cleartext LAN | `ws://192.168.x.x` is cleartext → `android:usesCleartextTraffic="true"` scoped by a **network security config** allowing cleartext only to private LAN ranges (RFC1918) |
| Permissions | `INTERNET` only. No storage permission — saves go through SAF/Storage Access Framework |
| CI workflow | `.github/workflows/mobile.yml` (tag + manual): `ubuntu-latest`, Temurin JDK 21, Android SDK (preinstalled / `android-actions/setup-android`), `npm ci` → `build:web` → `npx cap sync android` → `gradlew assembleRelease` → upload `SyncFlow-<v>.apk` |
| Signing | Generate an Android keystore once; store **base64 keystore + passwords as GitHub Actions secrets** (Encrypted secrets). Back up the keystore **outside** GitHub — losing it = cannot update the app. Alternative: publish unsigned/debug-signed APKs for v0.x and defer real signing (updates then require reinstall with same key — decide before first install in the wild) |
| Distribution | **GitHub Releases first** (sideload: Settings → install unknown apps). Upload via `gh release upload`, add to `SHA256SUMS.txt`, extend the attestation step (`subject-path` already globs `release-files/**` — include the APK) |
| Play Store (later, optional) | $25 one-time, AAB (`bundleRelease`), Play App Signing (upload key managed by Google), Privacy Policy URL + Data-safety form (LAN-only, no data collection — easy), store listing screenshots |
| Device testing | Manual install on your phone (Parrot↔phone on same LAN); optional emulator screenshot job in CI later |

Landed: `capacitor.config.ts` + committed `android/` (minSdk 26, cleartext
network-security config, `allowBackup=false`), branded icons via
`@capacitor/assets`, versionCode/versionName synced from `package.json`,
release keystore (RSA-4096) generated → GH secrets + **local backup at
`~/.local/syncflow-android-keystore/`** (back it up again off-machine!),
`mobile.yml` builds signed `SyncFlow-<v>-android.apk` on `workflow_dispatch`
and via `workflow_call` from `release.yml` — tag releases fold the APK into
`release-files/` so SHA256SUMS + provenance cover it. Verified: APK artifact
built in CI and its signing cert matches the release keystore.
External deps: none for sideload; $25 only if Play Store.

## Phase 3 — Phone-native features — **LANDED 2026-10-03 (upload + receive + QR connect + notifications)**

| Item | Detail |
|------|--------|
| Phone→desktop upload | **LANDED (incl. resume)** — `transfer:upload/end/finish` control frames + 256 KiB binary chunks over the authed WS (`backend/upload.py`), 8 GiB/file cap (`SYNCFLOW_MAX_UPLOAD_MB`), strict seq/size enforcement, per-connection sessions, staging under `$SYNCFLOW_HOME/staging` (0700), hand-off to the engine → target peer. **Resume-after-interrupt:** a disconnect keeps staged bytes as an orphan (completed files + partial, `SYNCFLOW_UPLOAD_RESUME_SEC` TTL, default 1800 s, max 8 LRU; boot wipes staging); `transfer:upload:resume` → `resume:ready{nextSeq, partial, resumable}`, the next announce appends from `resumeFrom` ("ab"), a changed file list aborts, cancel/expiry/boot clear it, and a plain announce may rejoin only when it lines up (next seq, no partial). Renderer: `src/lib/upload.ts` streams picked `File` blobs with socket backpressure, fails fast on socket loss, waits for reconnect and retries bounded (resume query → skip completed → seek), card progress via `transfer:progress`; cancel reuses `command:cancel`. Proven by `t_upload` (18 checks) + bridge-test steps 6 and 9 (sha256 round trips). |
| Desktop→phone receive | **LANDED** — `transfer:download{transferId,fileIndex}` → `ready` → 256 KiB binary frames → `file-done{received,sha256}` (`backend/download.py`); paths resolved **server-side** from the engine task table (client never sends a path), one stream per connection AND per transfer, per-2 MB loop yields so cancel/detach stay responsive, `command:cancel` fallback. Renderer: `src/lib/download.ts` reassembles + verifies counts/sha, saves via Capacitor Filesystem cache + **system share sheet** (native) or anchor download (web); `TransferCard` shows a companion-only **Save to device** button; `transfers:update` history sync seeds the list on connect. Proven by `t_download` (10 checks) + bridge-test step 7 (sha256 round trip). |
| QR connect | **LANDED** — three paths: (1) in-app camera scan (ML Kit, `Scan QR` on ConnectScreen → `syncflow://pair` payload), (2) system-camera deep link (`syncflow` scheme intent in the Android manifest / iOS URL type → `appUrlOpen` → auto-pair), (3) manual entry. Parser `src/lib/qr.ts` rejects foreign schemes/hostile hosts (bridge-test step 8). |
| Notifications | **LANDED (foreground)** — ConnectScreen requests permission inside the connect gesture; native builds schedule OS local notifications via `@capacitor/local-notifications` (Android WebView has no Web Notification API), tap maps to navigation. **No background push** (no FCM relay on a LAN-only desktop) — documented limitation, not hidden |
| Chat / devices / transfers / settings peers | Already work through the Phase 1 shim |

Remaining (optional): Play-Store distribution. Estimated: 1 session (plus the $25 Play-console fee).

## Phase 4 — iOS — **Path A LANDED 2026-10-03** (compile-check only; Path B awaits the $99 Apple Developer account)

**Predicted prerequisites (the real blocker):**

| Need | Cost | Why |
|------|------|-----|
| Apple Developer Program | **$99/year** | Device installs > 7 days, TestFlight, App Store. Free Apple ID = simulator + 7-day dev installs only |
| Mac | $0 if using GitHub `macos-*` runners | Xcode preinstalled; `cap add ios` + `xcodebuild` run there; `ios/` project committed from CI |
| Certs in CI | $0 | Distribution cert (.p12) + provisioning profile as secrets; App Store Connect API key for upload |

**Path A (now, $0):** ✅ `.github/workflows/ios.yml` — CI job on `macos-latest` builds the iOS project and a
simulator `.app` on every main push (shared `App` scheme committed; SPM template ships no workspace, so CI builds `-project App.xcodeproj`) — keeps the iOS target compiling, no
signing. Release artifacts: none yet. This is "iOS is building" honesty,
not a shippable app.

**Path B (when $99 + Apple ID exist):**
1. Create App ID, distribution cert + provisioning profile → GH secrets.
2. CI: `xcodebuild archive` → export `.ipa` → attach to the GitHub release.
3. Upload to TestFlight (`altool` / App Store Connect API key), internal
   testing first (auto-expiring profiles → keep CI re-signing on tag).
4. App Store later: reviewers may flag **"requires external hardware"**
   (Guideline 2.1) — response ready: description states the desktop
   requirement + screenshots show both. Companion-without-account needs an
   account-deletion story only if accounts exist (they don't — LAN pairing).

**iOS-specific gotchas (predicted, must be handled):**
- `NSLocalNetworkUsageDescription` — iOS 14+ prompts before any LAN
  connection; missing string = silent failure.
- ATS: `NSAllowsLocalNetworking` exception so `ws://192.168.x.x` isn't
  blocked.
- No Bonjour needed initially (phone types the IP) — if mDNS discovery is
  added later, `NSBonjourServices` declaration required.
- Same Capacitor web build as Android — zero extra renderer work.

Estimated: Path A = 1 session; Path B = 1 session + Apple admin time.
Blocker: account, not code.

## Release engineering integration

- Same tag (`vX.Y.Z`) versions web build, `versionName`, and desktop.
- `mobile.yml` runs on tag alongside `release.yml`; on completion uploads
  `SyncFlow-<v>.apk` (and later `.ipa`) into the existing draft release
  with `gh release upload`.
- `SHA256SUMS.txt` regenerated to include mobile artifacts; attestation
  step already globs all of `release-files/**` → mobile files get signed
  provenance too.
- README: add Android badge/link under the desktop downloads once the
  first APK ships. — **DONE 2026-10-03** (v1.1.1 published, Android
  for-the-badge added next to the desktop Download badge, platform badge
  now lists Android).

## Predicted timeline & effort

| Phase | Effort | Blocked on |
|-------|--------|-----------|
| 0 — backend LAN + pairing | 1–2 sessions | nothing |
| 1 — transport shim | 1–2 sessions | Phase 0 |
| 2 — Android APK + CI | 1–2 sessions | Phase 1; signing-key decision |
| 3 — uploads/receive | 2–3 sessions | Phase 2 in use |
| 4 iOS Path A (CI compile) | 1 session | nothing |
| 4 iOS Path B (TestFlight) | 1 session + admin | **$99 Apple Developer Program** |

Whole Android companion line ≈ one focused week of sessions; iOS shipping
is one Apple-account away after that.

## Decision points (defaults in bold)

1. **Package id:** `io.github.killerdasher.syncflow` — final once published.
2. **minSdk:** **26**; 24 possible if old phones matter.
3. **v0.x distribution:** **GitHub Releases sideload**; Play Store when
   there's a reason ($25).
4. **Signing:** **CI secret keystore, user holds the backup** — vs
   unsigned v0.x until v1 mobile. Must be decided before first install
   circulates (key continuity).
5. **iOS:** **Path A now**, Path B when the Apple account exists.
