"""Deterministic fuzzing of the WS control plane + TCP data plane.

Ten bounded, seeded (reproducible) mutation groups against live instance A.
The contract under fuzz is always the same: a well-behaved failure - a
sanitized {"type":"error", ...} frame or a clean close - never a hang,
never a server crash, never an unhandled traceback in the server log.
Group F10 scans ONLY the A.log bytes appended since this suite started, so
earlier suites cannot poison the verdict.

Run under run_all.sh (last suite, servers already up).
"""

import asyncio
import json
import os
import random
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proto_lib import *  # noqa: F401,F403

SEED = 0xC0FFEE
ITER = 40  # per WS mutation group
RNG = random.Random(SEED)
A_LOG = os.path.join(ART, "A.log")


def log_mark() -> int:
    try:
        return os.path.getsize(A_LOG)
    except OSError:
        return -1


def new_tracebacks(mark: int) -> int:
    """Tracebacks appended to A.log after `mark` (-1 => no log at all)."""
    if mark < 0:
        return -1
    try:
        with open(A_LOG, "rb") as f:
            f.seek(mark)
            return f.read().count(b"Traceback (most recent call last)")
    except OSError:
        return -1


async def recv_any(ws, timeout: float = 3.0):
    """-> ('frame', dict) | ('closed', None) | ('timeout', None) | ('other', None)"""
    try:
        raw = await asyncio.wait_for(ws.ws.recv(), timeout)
    except TimeoutError:
        return "timeout", None
    except Exception:
        return "closed", None
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            return "other", None
        if isinstance(data, dict):
            return "frame", data
        return "other", None
    return "other", None  # server binary frame (unexpected here)


def _rand_junk() -> str:
    # Always invalid JSON: leading 'f', unterminated brace at the end.
    return "fuzz-" + RNG.randbytes(12).hex() + "{"


async def f1_garbage_text() -> list:
    """Random invalid-JSON text frames -> sanitized error, connection kept."""
    bad = []
    async with WSConn(WS_A) as ws:
        for _ in range(ITER):
            await ws.ws.send(_rand_junk())
            kind, data = await recv_any(ws, 3.0)
            if kind != "frame" or data.get("type") != "error" or data.get("error") != "invalid JSON":
                bad.append((kind, data))
                if kind != "frame":
                    break  # connection died - nothing left to fuzz here
    return bad


async def f2_structural() -> list:
    """Structurally hostile JSON: non-objects, bad type fields, deep/huge."""
    deep = {"type": "identity:get", "x": []}
    cur = deep["x"]
    for _ in range(1500):
        cur.append([])
        cur = cur[-1]
    control_text = chr(0) + chr(1) + " evil"
    payloads = [
        "[]",
        '"just a string"',
        "12345",
        "null",
        "true",
        "false",
        json.dumps({"type": None}),
        json.dumps({"type": 42}),
        json.dumps({"type": ["identity:get"]}),
        # Built by hand: json.dumps itself refuses >4300-digit ints.
        '{"type":"identity:get","big":' + "9" * 4500 + "}",
        '{"type":"identity:get","type":"devices:list"}',  # duplicate key: last wins
        json.dumps(deep),
        json.dumps({"type": "chat:send", "text": control_text}),
    ]
    bad = []
    async with WSConn(WS_A) as ws:
        for payload in payloads:
            await ws.ws.send(payload)
            kind, data = await recv_any(ws, 4.0)
            if kind != "frame":
                bad.append((payload[:60], kind))
                if kind != "timeout":
                    break
    return bad


# Known message types fed wrong-shaped fields. Every one must produce a
# frame (validation error or a legitimate reply) - silence means the
# handler swallowed an exception. Payloads are chosen so they can never
# mutate state: bad shapes fail validation before any side effect, and the
# near-valid rows (missing file, missing transfer) fail without tasks.
TYPE_CONFUSION = [
    {"type": "command:send", "targetIp": 1, "files": []},
    {"type": "command:send", "targetIp": "1.2.3.4", "files": {"x": 1}},
    {"type": "command:send", "targetIp": "1.2.3.4", "files": ["/nonexistent/fz"], "transferId": "fz1"},
    {"type": "command:send", "targetIp": "1.2.3.4", "files": "etc/passwd", "transferId": "fz2"},
    {"type": "command:cancel", "transferId": {"a": 1}},
    {"type": "command:cancel", "transferId": "fz-missing"},
    {"type": "chat:send", "text": {"a": 1}},
    {"type": "chat:send", "text": 123},
    {"type": "identity:sas", "peerDeviceId": "../../etc/passwd"},
    {"type": "identity:sas", "peerDeviceId": 123},
    {"type": "peers:forget", "key": 123},
    {"type": "peers:forget", "key": "no such key!!"},
    {"type": "settings:apply", "downloadPath": []},
    {"type": "settings:apply", "deviceName": {"x": 1}},
    {"type": "transfer:approve", "transferId": "fz-none", "files": {"0": 1}},
    {"type": "transfer:decline", "transferId": [1, 2]},
    {"type": "transfer:download", "transferId": "fz-none", "fileIndex": "one"},
    {"type": "transfer:download:cancel", "transferId": 123},
    {"type": "transfer:upload:end", "transferId": "fz-none"},
    {"type": "transfer:upload:finish", "transferId": 123},
    {"type": "identity:get", "extra": [1, 2, 3]},
    {"type": "devices:list", "devices": "evil"},
    {"type": "transfers:list", "limit": "all"},
    {"type": "chat:history", "messages": "evil"},
    {"type": "peers:list", "filter": None},
]


async def f3_type_confusion() -> list:
    bad = []
    async with WSConn(WS_A) as ws:
        for msg in TYPE_CONFUSION:
            await ws.send(msg)
            kind, data = await recv_any(ws, 4.0)
            if kind != "frame":
                bad.append((msg.get("type"), kind))
                if kind != "timeout":
                    break
            elif "Traceback" in str(data.get("error", "")):
                bad.append((msg.get("type"), "traceback leaked"))
    return bad


async def f4_oversized() -> str:
    """Frame above the 1 MiB WS cap -> connection must be dropped (1009)."""
    async with WSConn(WS_A, max_size=2_000_000) as ws:
        await ws.ws.send("x" * 1_200_000)
        kind, _ = await recv_any(ws, 5.0)
        return kind


async def f5_binary_frames() -> list:
    """Binary frames with no active upload/download -> sanitized error."""
    bad = []
    async with WSConn(WS_A) as ws:
        for _ in range(5):
            await ws.ws.send(os.urandom(RNG.randint(1, 512)))
            kind, data = await recv_any(ws, 3.0)
            if kind != "frame" or data.get("type") != "error":
                bad.append((kind, data))
                if kind != "frame":
                    break
    return bad


def tcp_roundtrip(payload: bytes, wait: float = 5.0):
    """Send payload (+ EOF), report ('closed', elapsed) or ('hung', ...)."""
    s = socket.create_connection(("127.0.0.1", TCP_A), timeout=5.0)
    s.settimeout(wait)
    t0 = time.time()
    try:
        if payload:
            s.sendall(payload)
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        deadline = t0 + wait
        while time.time() < deadline:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                return "hung", time.time() - t0
            except (ConnectionResetError, OSError):
                return "closed", time.time() - t0  # RST still = server reacted
            if not chunk:
                return "closed", time.time() - t0
        return "hung", time.time() - t0
    finally:
        try:
            s.close()
        except OSError:
            pass


def f6_tcp_garbage() -> list:
    bad = []
    for _ in range(30):
        kind, took = tcp_roundtrip(os.urandom(64), wait=5.0)
        if kind != "closed" or took > 4.5:
            bad.append((kind, round(took, 2)))
    return bad


def f7_tcp_bad_length() -> list:
    """Length prefixes that must be rejected BEFORE any allocation."""
    bad_lens = [0, 0xFFFFFFFF, (1 << 31), 262145, 65536 + 999_999]
    bad = []
    for _ in range(20):
        n = RNG.choice(bad_lens)
        body = os.urandom(16)
        kind, took = tcp_roundtrip(n.to_bytes(4, "big") + body, wait=5.0)
        if kind != "closed" or took > 4.5:
            bad.append((hex(n), kind, round(took, 2)))
    return bad


def f8_tcp_framed_json() -> list:
    """4-byte-prefixed bodies that are not a valid e2e handshake."""
    bodies = [
        b'{"type":',                 # truncated JSON
        b"null",                     # not an object
        b"[1,2,3]",                  # not an object
        b'"str"',                    # not an object
        b"{}",                       # missing type
        b'{"type":"e2e_offer"}',     # right type, no fields
        b'{"type":5}',               # wrong type field
    ]
    bad = []
    for body in bodies:
        kind, took = tcp_roundtrip(len(body).to_bytes(4, "big") + body, wait=5.0)
        if kind != "closed" or took > 4.5:
            bad.append((body[:30], kind, round(took, 2)))
    return bad


async def f9_alive() -> dict:
    r1 = await ws_call(WS_A, {"type": "identity:get"}, {"identity:info"}, timeout=5)
    r2 = await ws_call(WS_A, {"type": "transfers:list"}, {"transfers:update"}, timeout=5)
    return {"identity": r1.get("type"), "transfers": r2.get("type")}


async def main():
    mark = log_mark()

    bad = await f1_garbage_text()
    ok(
        f"F1 WS garbage text -> {ITER}x 'invalid JSON' errors, connection survives",
        not bad, f"bad={bad[:2]}",
    )

    bad = await f2_structural()
    ok("F2 structural JSON (non-object/bad type/deep/huge-int/dup-key) -> frames",
       not bad, f"bad={bad[:3]}")

    bad = await f3_type_confusion()
    ok(f"F3 type-confusion on {len(TYPE_CONFUSION)} known messages -> every one frames",
       not bad, f"bad={bad[:3]}")

    kind = await f4_oversized()
    ok("F4 1.2 MB frame over the 1 MiB cap -> connection dropped", kind == "closed",
       f"kind={kind}")

    bad = await f5_binary_frames()
    ok("F5 stray binary frames -> 'error' replies (no upload session)", not bad,
       f"bad={bad[:2]}")

    bad = f6_tcp_garbage()
    ok("F6 TCP random bytes -> clean close, no hang", not bad, f"bad={bad[:3]}")

    bad = f7_tcp_bad_length()
    ok("F7 TCP hostile length prefixes rejected pre-allocation, no hang",
       not bad, f"bad={bad[:3]}")

    bad = f8_tcp_framed_json()
    ok("F8 TCP framed non-handshake JSON bodies -> clean close, no hang",
       not bad, f"bad={bad[:3]}")

    alive = await f9_alive()
    ok("F9 server alive after fuzz (identity + transfers still served)",
       alive.get("identity") == "identity:info" and alive.get("transfers") == "transfers:update",
       f"{alive}")

    tb = new_tracebacks(mark)
    ok("F10 zero new tracebacks in A.log during fuzz", tb == 0, f"new_tracebacks={tb}")

    finish("t_fuzz")


if __name__ == "__main__":
    asyncio.run(main())
