# Security Policy

## Reporting a Vulnerability

If you discover a security issue in SyncFlow, please report it privately:

- Use **GitHub → Security → Report a vulnerability** (private advisory) on this
  repository. Maintainers are notified immediately and the report stays hidden
  until a fix ships.
- For non-sensitive bugs (crashes, UI issues), a normal GitHub issue is fine.

Please include: affected version/OS, reproduction steps, and impact.

## What SyncFlow Protects Against

- **E2E encryption on the wire**: AES-256-GCM, Ed25519 signatures, X25519 key
  exchange, trust-on-first-use pinning, per-chunk SHA-256 chaining.
- **Local-only control plane**: the WebSocket bridge (port 18973) binds
  `127.0.0.1` only and enforces a browser origin allowlist.
- **No telemetry**: SyncFlow makes no internet connections. All traffic is
  LAN-local between paired devices.

## What SyncFlow Does NOT Claim

- There is **no TLS layer** and **no WAN relay** — transport is a direct LAN
  TCP connection protected by application-layer E2E encryption.
- Peers are trust-on-first-use: verify the device pairing out-of-band if you
  face an active MITM on your network.

- **LAN mode (`SYNCFLOW_WS_HOST`) is opt-in.** The control plane binds
  loopback-only by default. When enabled, remote clients must exchange a
  single-use, 5-minute pairing code issued on the desktop for a bearer
  token (5 wrong attempts = 5-minute lockout); unauthenticated sockets can
  only run the pairing/auth handshake. Tokens are stored hashed in an
  owner-only `pairing.json`. Phase 0 of the mobile plan — covered by the
  `t_lan_auth` suite (27 checks).

The latest audit — findings, attack journal, seals and residual risks — is in
[docs/security-audit.md](docs/security-audit.md). The full threat model,
hardening notes and 134-check security test evidence are in
[SECURITY_REPORT.md](SECURITY_REPORT.md). The wire protocol (transports,
pairing/auth, message catalogue, crypto profile, error catalogue, versioning
policy) is specified in [docs/protocol.md](docs/protocol.md).

## Supported Versions

Only the **latest release** receives fixes. Older builds may be affected —
please upgrade before reporting an issue present in a current release.
