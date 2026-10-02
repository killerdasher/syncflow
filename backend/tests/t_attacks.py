"""Hostile-input attack suite — fills gaps left by t_net/t_proto/t_ws.

8 checks: listener bind posture, LAN reachability of the WS control plane,
length-framed non-handshake/garbage TCP probes, WS binary + malformed bursts,
hostile field injection through the WS API, and state-file permission
hardening (owner-only keys/chat/peer trust).
"""
import asyncio
import json
import os
import socket
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proto_lib import *
import proto_lib

ART = "/tmp/opencode"
HOME_A = f"{ART}/sfA"


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 80))  # TEST-NET: route lookup only, no packet
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith("127."):
            ips.add(ip)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def a1_bind_posture():
    out = subprocess.run(["ss", "-ltn"], capture_output=True, text=True).stdout
    ws_lines = [l.strip() for l in out.splitlines() if ":18993" in l]
    tcp_lines = [l.strip() for l in out.splitlines() if ":19974" in l]
    ok(
        "A1 WS control plane listens on loopback only",
        len(ws_lines) >= 1
        and any("127.0.0.1:18993" in l for l in ws_lines)
        and not any(("0.0.0.0:18993" in l or "*:18993" in l or "[::]:18993" in l) for l in ws_lines),
        f"ws={ws_lines}",
    )
    ok(
        "A2 TCP transfer plane on all interfaces (E2E-protected by design)",
        len(tcp_lines) >= 1
        and any(("0.0.0.0:19974" in l or "*:19974" in l or "[::]:19974" in l) for l in tcp_lines),
        f"tcp={tcp_lines}",
    )


def a3_lan_ws_refused():
    async def probe(ip):
        websockets = proto_lib._ws_mod()
        try:
            await asyncio.wait_for(
                websockets.connect(f"ws://{ip}:{WS_A}", open_timeout=2.5), 3.0
            )
            return False  # connected => loopback-only promise broken
        except Exception:
            return True

    async def go():
        ips = lan_ips()
        results = {ip: await probe(ip) for ip in ips}
        return results

    results = asyncio.run(go())
    if not results:
        ok("A3 WS refuses connections from LAN addresses", True, "no non-loopback IPv4 present")
    else:
        ok(
            "A3 WS refuses connections from LAN addresses",
            all(results.values()),
            f"per-ip refused={results}",
        )


def a4_tcp_non_handshake():
    payload = b'{"type":"evil"}'

    async def go():
        reader, writer = await asyncio.open_connection(HOST, TCP_A)
        writer.write(len(payload).to_bytes(4, "big") + payload)
        await writer.drain()
        got = b""
        try:
            got = await asyncio.wait_for(reader.read(512), 6)
        except asyncio.TimeoutError:
            pass
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        # server must still serve the UI after the probe
        info = await ws_call(WS_A, {"type": "identity:get"}, {"identity:info"}, timeout=6)
        return got, info.get("type") == "identity:info"

    got, alive = asyncio.run(go())
    ok(
        "A4 non-handshake TCP frame rejected with zero data returned",
        got == b"" and alive,
        f"leaked={got[:80]!r} alive={alive}",
    )


def a5_tcp_garbage_frames():
    async def probe(blob):
        reader, writer = await asyncio.open_connection(HOST, TCP_A)
        writer.write(blob)
        await writer.drain()
        got = b""
        try:
            got = await asyncio.wait_for(reader.read(512), 5)
        except asyncio.TimeoutError:
            pass
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        return got

    async def go():
        # 4-byte length prefix claiming 4GB (out of range -> immediate close)
        huge = b"\xff\xff\xff\xff" + b"X" * 16
        # length prefix with non-UTF8 JSON body
        bad = (3).to_bytes(4, "big") + b"\xff\xfe\xfd"
        r1 = await probe(huge)
        r2 = await probe(bad)
        info = await ws_call(WS_A, {"type": "identity:get"}, {"identity:info"}, timeout=6)
        return r1, r2, info.get("type") == "identity:info"

    r1, r2, alive = asyncio.run(go())
    ok(
        "A5 garbage TCP frames (oversize/invalid-UTF8) closed, server alive",
        r1 == b"" and r2 == b"" and alive,
        f"huge={r1[:40]!r} bad={r2[:40]!r} alive={alive}",
    )


def a6_ws_binary_and_burst():
    async def go():
        async with proto_lib.WSConn(WS_A) as ws:
            await ws.ws.send(b"\xff\xfe\x00binary-frame")  # invalid UTF-8
            await ws.send({"type": 999})                    # non-string type
            for i in range(120):
                await ws.ws.send(json.dumps({"type": "evil:probe", "i": i}))
            await ws.send({"type": "identity:get"})
            resp = await ws.wait({"identity:info"}, 8)
            return resp

    resp = asyncio.run(go())
    ok(
        "A6 WS survives binary frame + 120 malformed/unknown messages, still serves",
        resp.get("type") == "identity:info",
        f"resp={resp.get('type')}",
    )


def a7_field_injection():
    async def go():
        r1 = await ws_call(WS_A, {"type": "peers:forget", "key": "../../etc/passwd"}, {"error", "peers:updated"})
        r2 = await ws_call(WS_A, {"type": "peers:forget", "key": "a" * 500}, {"error", "peers:updated"})
        r3 = await ws_call(
            WS_A,
            {"type": "command:send", "targetIp": "127.0.0.1;cat /etc/passwd", "files": ["/etc/hosts"]},
            {"error", "transfer:new", "transfer:error"},
        )
        r4 = await ws_call(
            WS_A,
            {"type": "command:send", "targetIp": "127.0.0.1", "files": "/etc/hosts"},
            {"error", "transfer:new", "transfer:error"},
        )
        r5 = await ws_call(
            WS_A,
            {"type": "command:send", "targetIp": "127.0.0.1", "files": ["/etc/hosts"],
             "transferId": "'; DROP TABLE--"},
            {"error", "transfer:new", "transfer:error"},
        )
        return r1, r2, r3, r4, r5

    r1, r2, r3, r4, r5 = asyncio.run(go())
    ok(
        "A7 hostile field injection rejected (peer key / shell meta / types / transferId)",
        r1.get("type") == "error" and "peer key" in r1.get("error", "")
        and r2.get("type") == "error" and "peer key" in r2.get("error", "")
        and r3.get("type") == "error" and "target address" in r3.get("error", "")
        and r4.get("type") == "error" and "file list" in r4.get("error", "")
        and r5.get("type") == "error" and "transfer id" in r5.get("error", ""),
        f"r1={r1.get('error')} r2={r2.get('error')} r3={r3.get('error')} "
        f"r4={r4.get('error')} r5={r5.get('error')}",
    )


def a8_state_permissions():
    # Ensure the chat log exists (first save may not have happened yet)
    asyncio.run(ws_call(WS_A, {"type": "chat:send", "text": "perm-audit probe"},
                        {"chat:ack", "chat:error", "error"}, timeout=6))

    file_expect = [
        (f"{HOME_A}/identity/signing.key", 0o600),
        (f"{HOME_A}/identity/x25519.key", 0o600),
        (f"{HOME_A}/chat_log.json", 0o600),
        (f"{HOME_A}/peers.json", 0o600),
    ]
    dir_expect = [HOME_A, f"{HOME_A}/identity"]

    bad = []
    checked = 0
    for path, want in file_expect:
        if not os.path.exists(path):
            if path.endswith("peers.json"):
                continue  # trust file only exists once a peer was pinned
            bad.append(f"missing {path}")
            continue
        mode = stat.S_IMODE(os.stat(path).st_mode)
        checked += 1
        if mode != want:
            bad.append(f"{path} mode={oct(mode)} want={oct(want)}")
    for path in dir_expect:
        if not os.path.isdir(path):
            bad.append(f"missing dir {path}")
            continue
        mode = stat.S_IMODE(os.stat(path).st_mode)
        checked += 1
        if mode & 0o077:
            bad.append(f"{path} mode={oct(mode)} leaks group/other")

    ok(
        "A8 state files owner-only (keys/chat/trust 0600, dirs 0700)",
        checked >= 3 and not bad,
        f"checked={checked} bad={bad}",
    )


if __name__ == "__main__":
    a1_bind_posture()
    a3_lan_ws_refused()
    a4_tcp_non_handshake()
    a5_tcp_garbage_frames()
    a6_ws_binary_and_burst()
    a7_field_injection()
    a8_state_permissions()
