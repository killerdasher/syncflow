"""Rogue mDNS advertiser suite: register hostile services next to live A.

2 checks: T17a advertisement with an invalid id is rejected outright;
T17b valid id with hostile TXT fields is stored fully sanitized.
"""
import asyncio
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proto_lib import *

from zeroconf import ServiceInfo, Zeroconf

SERVICE = "_syncflow._tcp.local."


def build(name_suffix, properties):
    return ServiceInfo(
        SERVICE,
        f"rogue-{name_suffix}.{SERVICE}",
        addresses=[socket.inet_aton("127.0.0.1")],
        port=19977,
        properties=properties,
        server=f"rogue-{name_suffix}.local.",
    )


async def poll_devices(timeout=8.0, want_id=None, reject_id=None):
    """Poll A's device list. Returns (want_found, reject_seen, last_list)."""
    deadline = time.time() + timeout
    found = False
    seen_bad = False
    last = []
    async with WSConn(WS_A) as ws:
        while time.time() < deadline:
            await ws.send({"type": "devices:list"})
            data = await ws.wait({"devices:update"}, timeout=5)
            devices = data.get("devices", [])
            last = devices
            for d in devices:
                if reject_id and (d.get("id") == reject_id or d.get("name") == "RogueOne"):
                    seen_bad = True
                if want_id and d.get("id") == want_id:
                    found = True
            if found and (reject_id is None or not seen_bad):
                # keep watching a little longer for the reject case
                if reject_id is None:
                    return True, seen_bad, devices
            await asyncio.sleep(0.5)
    return found, seen_bad, last


def main():
    zc = Zeroconf()
    bad = build("badid", {
        b"id": b"BAD ID!!",          # spaces + '!' violate ^[A-Za-z0-9_-]{1,64}$
        b"name": b"RogueOne",
        b"os": b"linux",
        b"mac": b"AA:BB:CC:DD:EE:FF",
        b"port": b"19977",
    })
    hostile = build("hostile", {
        b"id": b"rogue123",                      # valid id -> must be accepted
        b"name": b"\x1b[31mRogue\x00EVIL",       # control chars -> stripped
        b"mac": b"not-a-mac",                    # invalid mac -> unknown
        b"os": b"../../etc/passwd",              # invalid os -> unknown
        b"port": b"19977",
    })
    try:
        zc.register_service(bad)
        zc.register_service(hostile)
        found, seen_bad, devices = asyncio.run(
            poll_devices(timeout=8.0, want_id="rogue123", reject_id="BAD ID!!")
        )
        ok(
            "T17a mDNS advertisement with invalid id rejected",
            not seen_bad,
            f"bad_seen={seen_bad} (good id propagated={found})",
        )

        rogue = next((d for d in devices if d.get("id") == "rogue123"), None)
        name_ok = rogue is not None and isinstance(rogue.get("name"), str) and rogue["name"].isprintable()
        mac_ok = rogue is not None and rogue.get("mac") == "unknown"
        os_ok = rogue is not None and rogue.get("os") == "unknown"
        ok(
            "T17b hostile TXT sanitized on store (name printable, mac/os unknown)",
            found and name_ok and mac_ok and os_ok,
            f"found={found} device={rogue}",
        )
    finally:
        for svc in (bad, hostile):
            try:
                zc.unregister_service(svc)
            except Exception:
                pass
        zc.close()
    finish("t_mdns_rogue")


if __name__ == "__main__":
    main()
