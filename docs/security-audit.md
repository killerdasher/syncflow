# SyncFlow Security Audit — 2026-10-03

**Status:** complete, all findings sealed · **Suite:** 124/124 checks green on
Ubuntu, Windows and macOS CI · **Dependencies:** `npm audit` 0 vulnerabilities,
`pip-audit` 0 known vulnerabilities

This document records what was audited, how it was attacked, what was found,
what was fixed, and — honestly — what residual risk remains. Threat model and
earlier test evidence: [SECURITY_REPORT.md](../SECURITY_REPORT.md).
Vulnerability disclosure: [SECURITY.md](../SECURITY.md).

## 1. Scope

| Surface | What was examined |
|---|---|
| WS control plane (loopback :18973) | Origin allowlist, malformed/oversized frames, floods, injection, replay |
| TCP transfer plane (LAN :18974) | Unauthenticated connect, protocol injection, chunk spoofing, framing bounds, plaintext leakage |
| Path & file handling | `command:send` traversal, symlink escapes, download-path confinement, filename sanitization |
| Electron shell | `nodeIntegration`/`contextIsolation`/`sandbox`, navigation lockdown, `window.open`, CSP, IPC surface |
| Secrets at rest | chat log, identity keys, trust store file permissions; logs leaking material |
| Supply chain | npm + pip dependency audits, install-script gating, lockfiles, build attestations |
| Discovery (mDNS) | Rogue advertisements, hostile TXT records, replayed service data |

**Method:** live attacks against freshly started backend instances (two per
run) + source review of every listening socket + dependency auditing.
Environment: Parrot/Linux dev machine; CI replicates the suite on
Ubuntu, Windows and macOS.

## 2. Automated evidence (124 checks)

`backend/tests/run_all.sh` boots two fresh instances (A: TCP 19974 / WS 18993,
B: TCP 19975 / WS 18995) and runs eleven suites:

| Suite | Checks | What it proves |
|---|---:|---|
| `t_net` | 7 | Declared-size frames enforced, invalid frames close cleanly, 1 MB transfer byte-identical, **zero plaintext on the wire** |
| `t_proto` | 21 | Handshake state machine, replay/freshness rejection, malformed protocol input survives, framing bounds |
| `mitm2` | 5 | Active proxy/MITM completes **without ever seeing filename or payload plaintext** |
| `t_ws` | 22 | Origin allowlist, oversized/invalid frames, download-path confinement home-only, error hygiene |
| `t_mdns_rogue` | 2 | Rogue mDNS id rejected; hostile TXT fields sanitized on store |
| `t_extra` | 6 | Oversized WS message (code 1009) doesn't kill server; cancel leaves no temp files |
| `t_attacks` | 8 | **Bind posture proven live** (loopback-only WS via `ss`; LAN-IP connect refused), TCP garbage leaks 0 bytes, 120 malformed msgs survive, field injection (peer key/shell meta/file list/transferId) rejected, state perms 0600/0700 |
| `t_crypto` | 8 | **E2E round-trip proof**: X25519 directional keys, AES-256-GCM bidirectional + tamper rejection + nonce uniqueness, Ed25519 forgery/wrong-key rejection, full signed handshake both ways, stale/forged offer rejection, identity persistence + key-file perms |
| `t_lan_auth` | 23 | **Phase 0 LAN mode + pairing**: loopback default unchanged, opt-in `0.0.0.0` bind, remote commands refused pre-pairing, local-only code minting, wrong-code/single-use/token paths, forged tokens, Capacitor origin, pairing state 0600, QR/endpoint payload (`qr`, `host`, `port`, `lanMode`, TTL); unit TTL + 5-fail lockout |
| `t_upload` | 12 | **Phase 3 companion upload**: unauth JSON/binary refused pre-pairing, announce/ready/chunk/end/finish state machine, traversal names land as bare basenames, size caps + sequence enforcement, oversized-frame abort (session dies, connection lives), cancel + disconnect staging cleanup, 600 KB two-file round trip through the engine, progress broadcasts |
| `t_download` | 10 | **Phase 3 companion download**: unknown/malformed transfers and bad file indices rejected, 64 MB stream byte-count + sha256 match, concurrent second request refused while streaming, binary frame during download refused, cancel mid-stream stops the push and frees the transfer, disconnect cleanup, sent-file source path streams, vanished source fails clean |

CI runs the full suite on Linux and the crypto proof standalone on
**Windows and macOS** (`.github/workflows/ci.yml`), so the encryption claim is
demonstrated on every shipped OS, not assumed.

## 3. Findings and seals

| # | Severity | Finding | Seal | Commit |
|---|---|---|---|---|
| 1 | **High** | Dev chain CVEs: Electron ≤41.10.5 (12 high CVEs incl. renderer RCE class), `app-builder-lib`/`builder-util-runtime` high, `esbuild`/`vite`/`electron-vite` moderate–high | Electron → 44.5.1, electron-builder → 26.15.3, vite → 6.4.3, electron-vite → 3.1.0 → `npm audit` **0** | `e06ba93` |
| 2 | **Medium** | `state/chat_log.json` world-readable (0664), state dirs 0775 | `_save_chat_log` writes via `os.open` + `os.chmod` 0600; dirs + pre-existing files forced 0700/0600 | `c773e65` |
| 3 | Low | Install scripts of npm deps could be silently gated/omitted by npm ≥11 | Workflows run `node node_modules/electron/install.js` explicitly; `allowScripts` declared for electron/esbuild/winstaller | `e06ba93` |
| 4 | Info | No desktop entry / WM_CLASS mismatch on Linux installs | deb verified (`StartupWMClass=syncflow`), `desktopName`+`syncDesktopName`, AppImage installer script shipped | `0f10b93` |

Verified clean (no fix needed): loopback-only WS bind; TCP length-prefixed
framing with hard size caps; E2E offer signature + freshness; TOFU pinning;
`sanitize_filename` + home confinement on downloads; 64-connection cap +
chat rate limit; Electron `contextIsolation`/sandbox/no-node,
`will-navigate` lockdown, `window.open` deny-all, CSP; origin allowlist;
mDNS TXT sanitization.

## 4. Attack journal (session 2026-10-03)

- **Bind posture:** `ss -ltn` proves WS listens on `127.0.0.1` only; connect
  attempts to the machine's LAN IP are actively refused (`t_attacks` A1).
- **TCP garbage:** non-handshake connections and length-framed junk receive
  zero bytes back — no banner, no error leak, no crash (8 probes).
- **Field injection:** peer key, shell metacharacters, crafted file lists and
  `transferId` overrides through the WS command surface are rejected.
- **MITM proxy:** full active proxy between two instances captures 100 KB
  containing **no filename and no payload plaintext** (`mitm2`).
- **Replay:** stale offers and forged Ed25519 signatures rejected with
  explicit anti-replay diagnostics (`t_crypto` C5).
- **WS stress:** 120 malformed messages + 1 MB frames: connection dropped
  with 1009 where appropriate, server stays up.
- **Secrets:** state files owner-only after seal; key material not present in
  logs (manual grep over A/B instance logs).

## 5. Supply chain

- `npm audit` (prod): **0 vulnerabilities** (post-seal).
- `pip-audit -r backend/requirements.txt`: **0 known vulnerabilities**.
- Lockfiles committed; Dependabot monitors npm + pip + Actions — 13 open PRs
  merged/superseded this session (cryptography ≥50.0.1, psutil ≥7.2.2,
  zeroconf ≥0.151.5, watchdog ≥6, qrcode ≥8.2, electron-vite 5, action majors).
- Releases carry `SHA256SUMS.txt` + GitHub build-provenance attestations
  (`gh attestation verify <file> --repo killerdasher/syncflow`).

## 6. Residual risks (accepted, not hidden)

1. **No TLS on the LAN.** The WS control plane is plain `ws://` on loopback;
   the TCP plane is plain TCP on the LAN — confidentiality comes from
   application-layer E2E (AES-256-GCM over authenticated X25519/Ed25519
   sessions), proven by `t_net`, `mitm2` and `t_crypto`. A LAN observer sees
   sizes and timing, never content.
2. **TOFU trust on first contact.** First pairing trusts the peer's key unless
   verified out-of-band; pinning after that (manageable in Settings).
3. **Unsigned binaries.** No code-signing certificates yet: Windows
   SmartScreen / macOS Gatekeeper prompts are expected — mitigations in
   [docs/code-signing.md](../code-signing.md) and
   [docs/macos.md](../macos.md); provenance attestations prove build origin.
4. **mDNS is advisory.** Discovery can be poisoned; the data path still
   requires a valid E2E handshake, so poisoning yields DoS at worst
   (`t_mdns_rogue` covers sanitization).
5. **No malware scanning** of transferred files (out of scope for a P2P tool).

## 7. Reproduce

```bash
backend/tests/run_all.sh            # 124 checks, fresh instances, ~5 min
backend/venv/bin/pip-audit -r backend/requirements.txt
npm audit                           # 0 vulnerabilities
npx tsc --noEmit                    # typecheck
gh attestation verify <release-file> --repo killerdasher/syncflow
```

CI runs (1)–(4) on every push; see the `CI` badge in the README.
