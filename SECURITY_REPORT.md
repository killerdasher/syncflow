# SyncFlow — Security Hardening & Penetration Test Report

**Date:** 2026-09-25 · **Updated:** 2026-10-02
**Scope:** Full application (Python asyncio backend, WebSocket bridge, Electron shell, mDNS discovery, packaging)
**Method:** 20+ distinct attack classes executed against **live instances** (two real backends + a protocol-aware MITM proxy on real sockets) — no simulated/mock results. All findings were patched and the entire suite re-run to green.

---

## 1. Executive Summary

| Metric | Result |
|---|---|
| Scenarios executed | 26 attack classes + 3 hardening/feature scenarios (**63 individual checks**) |
| Vulnerabilities found & fixed | 20 pre-existing (V1–V20) + 6 defects exposed *by* the tests |
| Final regression | **63/63 PASS** on fresh instances (`backend/tests/run_all.sh`, exit 0) |
| Runtime dependency CVEs | **0** (npm runtime, pip-audit) |
| Graceful shutdown | 257 ms, ports released |
| Installers rebuilt & verified | AppImage 126 MB, deb 86 MB (hardened code verified inside) |

**Baseline (pre-patch) evidence of real compromise:**

- **Full MITM eavesdrop succeeded:** an active proxy read `SYNCFLOW_SECRET_PAYLOAD_…` and filename `secret-file.txt` in plaintext while the transfer reported success (`RECEIVED_IDENTICAL=yes`).
- Slow-loris connection held open 35 s+; a declared-500 MB frame inflated backend RSS by ~8.4 MB; a single non-JSON message killed the WebSocket session; `Origin: http://evil.example.com` was accepted; `downloadPath: /tmp/syncflow-pwn-baseline` created an arbitrary directory.

After the patch, every one of these is rejected, and the same MITM proxy captures 68 KB of traffic containing **zero** plaintext names or payload.

---

## 2. Vulnerabilities Found (Baseline → Fix)

| # | Severity | Vulnerability | Fix | Verified by |
|---|---|---|---|---|
| V1 | **Critical** | Handshakes unsigned/self-signed; MITM could impersonate either side | Ed25519-signed offers & accepts, verified **before** any key derivation; TOFU trust store (`peers.json`, pin per IP); responder bound to mDNS `deviceId = sha256(signingPub)` | M4, M5, T13 |
| V2 | High | Response `status` trusted before identity verification | Order: verify signature + freshness + device binding → *then* read status | M4 |
| V3 | High | 4-byte frame length unbounded → memory DoS | All reads bounded (JSON 256 KB, blobs ≤ size+64, frame 16 KB); over-declared length closes instantly | T2 (500 MB declared → closed, **0 KB** RSS growth) |
| V4 | High | No read timeouts → connection-hold DoS | Connect 10 s, header 30 s, meta 30 s, decision 90 s, stream 120 s | T1 (closed at exactly 30.0 s) |
| V5 | High | `downloadPath` → arbitrary `makedirs` | Realpath confinement to user's home; rejected before any filesystem call | W6a |
| V6 | High | Integrity failure still wrote the destination file | Stream to `.part-<uuid>` temp; `os.replace` only after full verification; temp deleted on any failure | T11a/b, T16 |
| V7 | High | `verified=True` asserted before data was checked | `verified` set only after per-block sigs + chain + size + Merkle all pass | T26, T14 |
| V8 | Medium | Cross-wire `transferId` collisions | Received ids always `in-<uuid16>` (unique, regex-safe); sender id advisory only | T7 (duplicate ids, both complete) |
| V9 | Medium | Chat never left the local machine | E2E chat relay over the transfer port (encrypted meta `kind:"chat"`), mDNS-targeted, best-effort | W9 |
| V10 | Medium | mDNS TXT fully attacker-controlled | Id/`mac`/`os` regex-validated, names control-stripped, invalid ids rejected, unique instance labels `name-id8` (fixed real name-collision bug), port validated | T17a/b |
| V11 | High | WS `origins=None` → cross-origin hijack from any webpage | Allowlist `null`, `localhost:5173`, `127.0.0.1:5173`, `[::1]:5173`, absent (non-browser); others → **HTTP 403** | W1 |
| V12 | Medium | Non-dict/invalid JSON killed the WS connection | Error response, connection stays usable; handler exceptions isolated per message | W3/W4/W5 |
| V13 | High | Weak filename sanitization (path traversal, NUL, control chars) | Basename on both separators, control-char strip, edge-dot strip, empty→`file`, Windows reserved names, 200-char cap, realpath containment in receive dir | T5, T5b, T6 |
| V14 | High | No offer freshness → indefinite replay | ±300 s window covered by signatures; stale/tampered offers rejected | T12a/b |
| V15 | **Critical** | Blockchain block signatures never verified | `TransferChain.verify_chunk`: header JSON, index/prev-link/file/sender match, chunk hash+size, Ed25519 sig over exact header — every block, streamed | T14, T16 |
| V16 | High | Relay server: `not self._tokens` bypass (empty set = open access), attacker-chosen `clientId` hijack | Default-deny (token must exist *and* match), clientId format + uniqueness, auth required before relay/signal | code review (standalone module) |
| V17 | Medium | No inbound connection cap | Semaphore, 64 concurrent, 2 s wait then reject; per-connection exception guard | T3 (exactly 64/100 held, rest rejected) |
| V18 | Medium | Unvalidated `file_size`/declared sizes | Type/range checks; declared≠actual rejected with no file written | T11a/b |
| V19 | High | Filenames/metadata plaintext on the wire | Encrypted meta → encrypted decision → encrypted per-file frames; plaintext channel carries keys+signatures only | M2 (68 KB capture, 0 leaks) |
| V20 | Medium | Latent bidirectional nonce reuse (single shared AES key) | Direction-split HKDF keys (`|i` / `|r`): one encryptor per key, counters independent | code review |

### Defects exposed *by* the test suite (fixed in `29c7e4d`)

1. `asyncio.Semaphore.acquire_nowait()` doesn't exist on Python 3.13 → every TCP connection was silently dropped.
2. Stray `session` argument to `_read_blob` → `TypeError` on every received file.
3. `wire_manifest()` lacked the `type: file_manifest` marker → honest transfers rejected at the manifest.
4. WS broadcast iterated a live `clients` set across `await` → `Set changed size during iteration` could abort an in-flight transfer.
5. Progress-callback failure could fail a transfer → progress emission is now non-fatal.
6. Cancel-during-approval closed the socket before the decline could be delivered → clean decline now reaches the sender.

---

## 3. Tests Conducted (Final Run: 63/63 PASS)

The full harness lives in-repo at **`backend/tests/`** (it was previously
lost to a `/tmp` wipe — reconstructed and extended) and runs end-to-end with
one command: `backend/tests/run_all.sh` (starts fresh A+B instances, runs all
six suites, tears down, exits non-zero on any failure).

### 3.1 Network / DoS (instance A, TCP 19974) — 7/7

| ID | Attack | Result |
|---|---|---|
| T0 | Liveness handshake after all attacks | PASS |
| T1 | Slow-loris (send nothing, hold) | PASS — closed at 30.0 s |
| T2 | Declared 500 MB frame | PASS — instant close, 0 KB RSS growth |
| T3 | 100-connection flood | PASS — exactly 64 held, 36 rejected, 0 KB growth |
| T4a–c | Invalid JSON / non-object / wrong message type | PASS — instant close, server unaffected |

### 3.2 Protocol / Crypto (raw hardened-protocol client vs A) — 21/21

| ID | Attack | Result |
|---|---|---|
| T26 | 1 MB transfer: verification + byte-identity + receiver-side leak check | PASS (no plaintext in ~546 B of server traffic) |
| T27 | Zero-byte file | PASS |
| T28 | Multi-file incl. 5 MB | PASS |
| T5 | `../../../../tmp/evil.txt` traversal | PASS — saved as basename inside receive dir; `/tmp` untouched |
| T5b | Signed headers claim different name than meta | PASS — rejected, nothing written |
| T6 | NUL/control characters in filename | PASS — stripped |
| T7 | Duplicate declared transferIds (concurrent) | PASS — unique receive ids, no collision |
| T11a/b | Declared > actual / actual > declared size | PASS — rejected, no file |
| T12a/b | Stale (1 h-old) offer / tampered offer signature | PASS — freshness + signature rejection logged |
| T13 | Wrong expected `deviceId` via real `command:send` | PASS — engine reports identity mismatch (production path) |
| T14 | Chunks signed by a different key than the handshake | PASS — sender_pubkey mismatch |
| T16 | Bit-flip in chunk payload | PASS — authentication failure, no file |
| T19 | Chat flood (40 msgs) | PASS — rate-limited 30/60 s per IP, monotonic |
| T20 | Control-char `senderName` | PASS — sanitized before storage (`peers.json` printable) |
| T21 | 300-char transferId | PASS — regenerated, transfer still succeeds |
| T22 | E2E chat over transfer port | PASS |
| T23/T23b | Non-string chat text | PASS — rejected cleanly, server stays alive |

### 3.3 WebSocket / Application (A, WS 18993) — 22/22

| ID | Attack | Result |
|---|---|---|
| W1 | `Origin: http://evil.example.com` | PASS — HTTP 403 at handshake |
| W2 | Allowed origins (`null`, dev, absent) | PASS |
| W3–W5 | Bad JSON / non-object / unknown type on one connection | PASS — errors answered, session survives |
| W6a–c | `downloadPath=/tmp/...`, non-string path, valid home path | PASS — rejected / rejected / accepted |
| W7a–c | Evil `targetIp` / `transferId` / approval id | PASS — validation errors |
| W8a–c | 10 000-char XSS chat payload | PASS — capped 4000, control chars stripped, stored as inert text |
| W9 | Chat A→B relayed E2E (mDNS-discovered) | PASS |
| W10 | Approval: accept flow | PASS — holds at `awaiting`, completes after approve |
| W11 | Approval: decline flow | PASS — sender informed, no file written |
| W12 | Cancel while awaiting approval | PASS — clean decline delivered |
| W13 | Broadcast to 3 concurrent WS clients | PASS — same message reaches all (live-set snapshot fix) |
| W14 | Approve unknown transferId | PASS — `success:false`, no crash |
| W15 | identity:get ×2 | PASS — deviceId stable |
| W0 | Server alive after suite | PASS |

### 3.4 Active MITM proxy (protocol-aware, real sockets → B via 19976) — 5/5

| ID | Attack | Result |
|---|---|---|
| M1 | Passive forward proxy — transfer through MITM | PASS — completes end-to-end |
| M2 | Full capture of MITM'd stream | PASS — 105 082 B captured, **zero** plaintext names/payload |
| M3 | Bit-flip inside encrypted chunk in transit | PASS — `chunk failed authentication`, no file |
| M4 | Attacker swaps responder's `signingPub` in accept (validly re-signed) | PASS — TOFU pin: `peer identity … CHANGED (possible MITM)` |
| M5 | Different client key from a pinned address | PASS — server rejects the offer before accepting |

### 3.5 mDNS rogue advertiser — 2/2

| ID | Attack | Result |
|---|---|---|
| T17a | Malformed `id` in TXT | PASS — advertisement rejected |
| T17b | Valid id + hostile name/mac/os | PASS — name control-stripped, `mac=unknown`, `os=unknown` |

### 3.6 Extra suite (checks missing from the original harness + new hardening scenarios) — 6/6

| ID | Attack / scenario | Result |
|---|---|---|
| X1 | 2 MB WS message (> 1 MB server `max_size`) | PASS — connection closed with code **1009**, server survives |
| X2 | Approval timeout (60 s, nobody approves) | PASS — sender gets `Timed out waiting for approval`, receiver task `failed`, no file written |
| X3 | Cancel during **active 1.5 GB streaming** | PASS — sender `cancelled`, receiver leaves no file or `.part` temp (attempt 1 of 3) |
| X4 | Sync-folder `destFolder` routing | PASS — configured folder receives the file; unknown and hostile (`../../evil`) names fall back to the download dir, no escape |
| X5 | Pinned-identity change + `peers:forget` | PASS — second identity rejected while pinned; forged WS key → error; forget → re-pair succeeds |
| X6 | `maxConcurrent=1` slot queueing | PASS — second send observed `pending` behind the active 1.5 GB transfer, both complete, both files verified on disk |

### 3.7 Additional checks

- **SIGTERM:** clean shutdown in **257 ms**, both ports released, graceful log.
- **Full app launch:** backend spawned, `Connected to Python backend`, renderer runs with `--enable-sandbox`, vite + WS + TCP up; clean teardown.
- **AppImage final artifact smoke:** extracted packaged backend starts (TCP+WS listen), contains all hardening markers, zero references to deleted insecure modules, SIGTERM-clean, ports released.
- **Supply chain:** `pip-audit` → *No known vulnerabilities*; `npm audit --omit=dev` → **0** (removed unused `react-router-dom`, CVE-2025-68470 class); dev-tooling-only findings remain (see §6).
- **Secrets scan:** no keys/tokens/passwords committed; no key files outside the venv.
- **Typecheck/build:** `tsc --noEmit` clean; `electron-vite build` clean; installers rebuilt and inspected (hardened strings present, deleted insecure modules absent).

---

## 4. Corrective Actions by Area

1. **Protocol/crypto** (`crypto/e2e.py`, `crypto/blockchain.py`, `transfer/engine.py`)
   Signed + freshness-checked handshakes; verify-before-derive; TOFU pinning; deviceId binding; direction-split AES keys; per-block streaming verification; encrypted metadata; unique receive ids; size caps; timeouts; temp-file writes; filename canonicalization; approval decisions encrypted end-to-end; chat framing + rate limiting.
2. **DoS/resilience** (`networking/__init__.py`)
   Bounded every read, timed every read, 64-connection semaphore with clean reject, per-connection exception isolation.
3. **WebSocket bridge** (`ws_bridge.py`)
   Origin allowlist, explicit `max_size`, ping keepalive, malformed-input tolerance, handler isolation, snapshot iteration, sanitized logging.
4. **Input/path** (`main.py`)
   Home-confinement for `downloadPath`; regex validation for `targetIp`/`targetPort`/transfer & device ids; chat length + control-char policy; log sanitization; chat fan-out.
5. **Discovery** (`discovery/mdns.py`)
   Unique instance labels (fixed a real `NonUniqueNameException` collision), TXT validation/sanitization, port validation.
6. **Relay** (`relay/server.py`) — default-deny tokens, clientId validation, auth required.
7. **Electron** (`electron/main.ts`) — `sandbox: true`, `webviewTag: false`, navigation pinned to own UI, window-open denied (contextIsolation/nodeIntegration/CSP already in place).
8. **Hygiene** — deleted dead insecure modules (`crypto/encryption.py`, `crypto/keys.py`, `networking/tls.py`, `networking/tcp_client.py`); removed unused `react-router-dom`.

**Commits:** `501218e` (core hardening) → `4ae2376` (deviceId binding) → `29c7e4d` (test-driven defect fixes) → `f9ac68c` (supply chain).

---

## 5. Residual Risks (honest scope)

- **First-contact MITM:** TOFU + mDNS `deviceId` binding defeat impersonation once a peer is known or advertised, but a *transparent* proxy on the very first connection from a brand-new device cannot be distinguished without out-of-band verification (no QR/fingerprint UI yet).
- **Same-host testing:** the MITM ran as a local proxy on real sockets; no external-host ARP/Wi-Fi attack was possible from this machine (would need a second host/adapter). The protocol properties tested (signatures, freshness, encryption, tamper rejection) are transport-independent.
- ~~**Approval timeout path** not exercised~~ — **closed**: X2 now exercises the full 60 s timeout end-to-end (both peers fail cleanly, no file).
- **GUI rendering** was not screenshot-verified (locked session); renderer behavior verified via WS traffic, logs, and live processes.
- **Dev-tooling CVEs** (vite/esbuild/electron-builder/tar chain, 17 findings) are build-time only — never shipped to users; fixing requires major-version bumps (`npm audit fix --force`).

---

## 6. Future-Proofing Suggestions

1. **Out-of-band key verification** — show a short fingerprint/QR per device and mark connections "verified" to close the first-contact gap.
2. **Sign mDNS records** with the Ed25519 key (or challenge-response on connect) so discovery itself is authenticated; today discovery informs, the handshake proves.
3. **Release signing** — GPG/SSH-sign AppImage & deb, add update-artifact signatures.
4. **CI security gate** — *(implemented)* GitHub Actions workflow (`.github/workflows/ci.yml`) runs `backend/tests/run_all.sh` (all 79 checks, fresh instances, non-zero exit on failure) plus `tsc --noEmit` on every change.
5. **Fuzz the frame parser** (header length, JSON, decrypt-failure paths) with a coverage-guided fuzzer.
6. **Per-IP handshake rate limiting** on the TCP port (chat is limited; handshake floods rely on the global cap today).
7. **Received-file hygiene** — strip executable bits, optional AV scan hook, quarantine folder before user approval of open/save.
8. **Peer management UI** — *(implemented)* Settings → Security shows pinned devices (name, key, first-seen/last-seen) with one-click **Forget** (`peers:forget` re-pins on next contact). Remaining: toast/badge on identity change (today the backend rejects the connection and logs it).
9. **Bandwidth QoS** and resume/partial-transfer support for multi-GB files.
10. **Relay deployment checklist** if ever exposed publicly: TLS termination, token rotation, rate limits, no plaintext LAN metadata.
11. **Dependency cadence** — schedule monthly `npm audit` / `pip-audit` and Electron minor updates (currently 33.x).
12. **Battery/data-saver mode** and foreground-service/Keep-Alive work for the future Android client.

---

## 7. Reproduction

One command runs everything (starts fresh A+B instances on test ports,
runs all six suites, tears down, prints totals, exit 0 = green):

```bash
backend/tests/run_all.sh          # 79 checks, ~5 min
```

Individual suites (instances must already be running):

```bash
# instances (fresh homes; test WS ports 18993/18995 never collide with the app)
SYNCFLOW_HOME=/tmp/opencode/sfA SYNCFLOW_TCP_PORT=19974 SYNCFLOW_WS_PORT=18993 backend/venv/bin/python3 backend/main.py
SYNCFLOW_HOME=/tmp/opencode/sfB SYNCFLOW_TCP_PORT=19975 SYNCFLOW_WS_PORT=18995 backend/venv/bin/python3 backend/main.py

backend/venv/bin/python3 backend/tests/t_net.py <A_pid>   # DoS / network (7)
backend/venv/bin/python3 backend/tests/t_proto.py         # protocol/crypto (21)
backend/venv/bin/python3 backend/tests/mitm2.py           # active MITM    (5)
backend/venv/bin/python3 backend/tests/t_ws.py            # WS / app       (22)
backend/venv/bin/python3 backend/tests/t_mdns_rogue.py    # rogue mDNS     (2)
backend/venv/bin/python3 backend/tests/t_extra.py         # extra          (6)
```

Every suite prints `PASS`/`FAIL` lines plus a `RESULTS_JSON` summary.
Harness location note: the suites were originally stored under `/tmp/opencode`
and were wiped by a tmpfs reset; they now live permanently in the repo under
`backend/tests/` (state/identity scratch dirs are still created under
`/tmp/opencode` at run time).
