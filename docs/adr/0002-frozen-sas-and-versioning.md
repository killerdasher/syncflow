# ADR-0002: Frozen SAS derivation and protocol versioning policy

**Status:** Accepted · 2026-10-03

## Context

Out-of-band verification (the 16-icon SAS shown in Settings → Pinned
Devices → Verify) only works if **both devices derive the same sequence
forever**. A silent algorithm tweak on one side produces different icons
and teaches users to click through a genuine MITM warning. Separately, the
protocol has **no version field** today: the `security:"e2e-blockchain-v1"`
token in the handshake offer is written by the sender and not validated by
the receiver (see [protocol.md §9.1](../protocol.md#91-handshake)).

## Decision

1. **SAS algorithm is frozen** (`backend/sas.py`): sorted device-ID pair →
   SHA-256 → first 12 bytes → 16 × 6-bit codes; the renderer's icon
   alphabet (`src/lib/sas.ts`) is append-only, never reordered. Changing
   either requires a protocol version bump (decision 3).
2. **Additive-only JSON** within a protocol generation: receivers ignore
   unknown keys and unknown message types (already true in the renderer
   switch).
3. **Any breaking change** (framing, key schedule, SAS, trust semantics)
   must (a) start being *validated* by the receiver in the handshake
   `security` string — closing today's advisory gap — and (b) ship in the
   same PR as an update to `docs/protocol.md` and a test that pins the new
   behaviour.

## Consequences

- ✅ Users can trust the icon ritual; tests pin the derivation
  (`t_lan_auth` L21–L24 re-derive it independently).
- ✅ Written-down policy instead of folklore; protocol.md §13 points here.
- ⚠️ Until decision 3 is implemented, old and new builds coexist by
  ignorance, not negotiation — the known compatibility gap, tracked as
  future work.
