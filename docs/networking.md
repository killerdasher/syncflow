# Networking & Firewall Guide

SyncFlow is **LAN-only**: devices must be on the same local network (same
router/Wi-Fi). No internet access is required or used.

## Ports

| Port | Protocol | Bound to | Purpose |
|------|----------|----------|---------|
| `18974` | TCP | all interfaces | Transfers + chat (E2E encrypted) |
| `5353` | UDP | mDNS multicast | Device discovery |
| `18973` | TCP | `127.0.0.1` only (default) | Local UI ↔ backend |

### LAN mode (opt-in, mobile companion)

By default the control plane never leaves loopback — remote machines cannot
connect at all. Phase 0 adds an **opt-in** LAN bind for the upcoming mobile
companion:

```bash
SYNCFLOW_WS_HOST=0.0.0.0 ./start-dev.sh     # or export before launching the app
```

- The backend logs `WebSocket bridge listening on ws://0.0.0.0:18973` plus a
  LAN-mode warning at startup.
- **Remote clients must pair**: on the desktop open **Settings → Network →
  Pair a mobile device** and click *Generate pairing code* (the card shows the
  code, a 5-minute countdown, a QR and `ws://host:port`; headless users can
  still send `{"type":"pairing:generate"}` over loopback instead). The code is
  **8 characters, valid 5 min, single use**. The client sends
  `{"type":"pairing","code":"..."}` first and receives a **bearer token**;
  every later connection starts with `{"type":"auth","token":"..."}`. Five
  wrong codes lock pairing for 5 min.
- Unauthenticated remote sockets may only send `pairing`/`auth` — all other
  messages get `{"type":"auth_required"}`.
- Origins `capacitor://localhost`, `http://localhost`, `https://localhost`
  are accepted for the companion webview (origin is not the auth mechanism).
- State lives in `pairing.json` next to the chat log (owner-only `0600`).
- Firewall: opening LAN mode does **not** change port 18973's role for the
  desktop itself; the transfer plane (18974) works exactly as before.

**Both devices must allow inbound TCP `18974` + UDP `5353`** — discovery and
outbound-initiated connections can work while inbound is blocked, which shows
up as *"one-way chat/transfer works, the other direction silently fails."*

## Linux

### Ubuntu / Debian / Parrot (ufw)

```bash
sudo ufw allow from 192.168.0.0/24 to any port 18974 proto tcp   # adjust subnet to yours
sudo ufw allow from 192.168.0.0/24 to any port 5353 proto udp
sudo ufw status
```

Find your subnet with `ip -4 addr show` (e.g. `192.168.1.0/24`).

### Fedora / RHEL (firewalld)

```bash
sudo firewall-cmd --permanent --add-port=18974/tcp
sudo firewall-cmd --permanent --add-port=5353/udp
sudo firewall-cmd --reload
```

### Arch (nftables/ufw)

If you maintain raw nftables rules, accept LAN traffic to `18974/tcp` and
`5353/udp` on your LAN interface.

## Windows 10 / 11

Windows prompts **"Allow access"** on first run — choose your network type
(Private). If you dismissed the prompt:

1. Windows Security → Firewall & network protection → **Allow an app through firewall**
2. Add `SyncFlow.exe` (or `python.exe` for dev mode) — check **Private**.

## macOS

The built-in Application Firewall (System Settings → Network → Firewall) may
prompt on first run — allow incoming for **SyncFlow**. No other config needed.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Devices never appear | UDP 5353 blocked, or devices on different subnets/AP isolation |
| Chat/files work one direction only | Inbound TCP 18974 blocked on the receiving device |
| Works, then stops after IP change | Re-add device with **Add Device** (manual IP) — pins are keyed by IP |
| mDNS works but manual IP doesn't | Firewall rule missing (rules above) |
| Message stuck *Sending…* | Target unreachable — it retries automatically (24h); click the device's **Test connection** for the concrete error |
| Message *Delivery failed* | Target refused TCP 18974 after all retries — open the firewall rules above on that machine, then **Retry** |

### Chat sends but the other side never sees it

Classic split: **file transfers work, chat doesn't** (or chat works only one
way). Chat travels the same port as files but opens a *fresh connection per
message*, so it is the first thing to break when:

1. **The receiver's firewall blocks inbound 18974** — run the ufw/firewalld
   rules above on the *receiving* machine and use **Test connection** on the
   device card to verify.
2. **The peer was added manually (by IP)** — older versions relayed chat only
   to mDNS-discovered devices. SyncFlow now registers manual peers
   (`peers:add`) and queues every undelivered message in a backend outbox with
   automatic retry, so the chat arrives as soon as the path opens.
3. **mDNS is blocked (UDP 5353) but you added the device by IP** — discovery
   shows nothing, yet chat still works through the manual peer list.

Quick check on the receiving machine:

```bash
sudo ss -ltnp | grep 18974     # backend listening on 0.0.0.0, not just 127.0.0.1
sudo ufw status                # 18974/tcp allowed from your LAN subnet
```

If the app reports *Not sent — backend offline*, the local backend itself is
down — start the app (or `python backend/main.py`) and the outbox will flush
pending messages automatically.

> SyncFlow pins peer keys trust-on-first-use (Settings → Pinned Devices).
> If a device is legitimately reinstalled, use **Forget** on the other side
> to re-pin.
