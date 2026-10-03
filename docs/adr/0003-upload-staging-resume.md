# ADR-0003: Upload staging with orphan-based resume

**Status:** Accepted · 2026-10-03

## Context

The companion streams files to the desktop over WebSocket. Wi-Fi blips and
app backgrounding kill sockets mid-transfer; before resume support, an
8 GB file had to restart from zero. Constraints: resume must not become a
disk-fill vector, must not survive restarts with stale state, and must not
let a peer append into a *different* file's staging area (the classic
"resume mix-up" bug).

## Decision

- Every upload is **staged on disk** (`$SYNCFLOW_HOME/staging/<transferId>/…`,
  dir 0700) before the engine ever sees it; a disconnect leaves the staged
  bytes as an **orphan**, not a live session.
- Orphans: TTL `SYNCFLOW_UPLOAD_RESUME_SEC` (default 1800 s), max **8**
  (LRU evict), lazy sweeper every 2 s, **staging wiped at boot**.
- Resume is an **explicit handshake**: `transfer:upload:resume` →
  `resume:ready {nextSeq, partial, resumable}` with staged sizes
  re-verified against the announce; only then does the next
  `transfer:upload` open the partial file in append mode (`resumeFrom`).
  A plain announce auto-rejoins only when it lines up exactly (next seq,
  no partial).
- **Changed file list ⇒ abort** (`Upload resume mismatch`): hashes are
  computed later (TCP leg), so during staging the *only* thing tying bytes
  to a file is its name+size+position — those must match or the bytes are
  discarded.

## Consequences

- ✅ Bounded disk usage (TTL + LRU + boot wipe), no unauthenticated
  long-lived server state.
- ✅ Correctness pinned by `t_upload` (18 checks) incl. keep-partial,
  append-e2e SHA proof, skip-completed, changed-list abort, TTL sweep, and
  bridge-test step 9 (stage → drop → resume → SHA match).
- ⚠️ Resume trusts name+size during staging (no hash until the TCP leg) —
  accepted because staged bytes are only ever handed to the engine that
  then verifies the full chain/manifest end-to-end before writing final
  files.
