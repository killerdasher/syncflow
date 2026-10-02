# Networking & Firewall Guide

SyncFlow is **LAN-only**: devices must be on the same local network (same
router/Wi-Fi). No internet access is required or used.

## Ports

| Port | Protocol | Bound to | Purpose |
|------|----------|----------|---------|
| `18974` | TCP | all interfaces | Transfers + chat (E2E encrypted) |
| `5353` | UDP | mDNS multicast | Device discovery |
| `18973` | TCP | `127.0.0.1` only | Local UI ↔ backend (never exposed) |

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

> SyncFlow pins peer keys trust-on-first-use (Settings → Pinned Devices).
> If a device is legitimately reinstalled, use **Forget** on the other side
> to re-pin.
