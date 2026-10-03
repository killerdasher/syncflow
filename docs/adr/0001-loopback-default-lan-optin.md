# ADR-0001: Loopback by default, LAN mode is opt-in without TLS

**Status:** Accepted · 2026-10-03

## Context

SyncFlow's control plane (WebSocket, port 18973) carries pairing codes and
bearer tokens. Running it on `0.0.0.0` would expose those to every device
on the LAN, and adding TLS would require a trust story (certificates are
meaningless on a home LAN without a CA, and browsers pin HSTS/public-PKIs
that a `ws://192.168.x.x` server cannot satisfy).

## Decision

- Bind `127.0.0.1` **by default**. The desktop renderer is local; nothing
  needs to listen on the network for the default single-machine use case.
- LAN is **explicit opt-in** via `SYNCFLOW_WS_HOST=0.0.0.0`.
- When LAN mode is on, authenticate with single-use 5-minute pairing codes
  → 256-bit bearer tokens (hashed at rest), and gate every non-pairing
  message behind auth. Codes are minted **loopback-only**.
- Rely on **end-to-end encryption of file/chat payloads** (ADR not needed:
  `backend/crypto/e2e.py`) for confidentiality of the actual data, rather
  than hop-by-hop TLS for control frames.

## Consequences

- ✅ Default install has zero network attack surface beyond loopback.
- ✅ LAN mode works in browsers and Android WebView (no cert prompts).
- ⚠️ In LAN mode, control frames (including the briefly-visible pairing
  code) are readable by a same-L2 attacker. Documented honestly in
  [protocol.md §14](../protocol.md#14-security-considerations-read-before-trusting-this);
  mitigated by code single-use/TTL/lockout and E2E payload encryption.
- ⚠️ File contents are E2E-encrypted, but WS transfer metadata in LAN mode
  is only token-protected. If that ever matters, the answer is a real
  transport upgrade (noise/TLS-PSK style), not certificates.
