"""WebSocket / application suite against live A (WS 18973) + B (WS 18975).

25 checks: origin policy, malformed input, input validation, chat safety,
mDNS relay, approval flows (accept/decline/cancel/subset) and liveness.
"""
import asyncio
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proto_lib import *


def setup():
    data = asyncio.run(ws_settings(WS_A, autoAccept=True, downloadPath=DEST_A))
    if data.get("type") != "settings:applied":
        print(f"FATAL: setup failed: {data}", flush=True)
        sys.exit(2)
    clean_dir(DEST_A)
    write_file(SRC_W10, b"w10 accepted payload")
    write_file(SRC_W11, b"w11 declined payload")
    write_file(SRC_W12, os.urandom(64 * 1024))
    write_file(SRC_W16[0], b"w16 file A payload")
    write_file(SRC_W16[1], os.urandom(1024))
    write_file(SRC_W16[2], b"w16 file C payload")
    write_file(SRC_W18, b"w18 single payload")


SRC_W10 = f"{ART}/w10-accept.bin"
SRC_W11 = f"{ART}/w11-decline.bin"
SRC_W12 = f"{ART}/w12-cancel.bin"
SRC_W16 = [f"{ART}/w16-a.bin", f"{ART}/w16-b.bin", f"{ART}/w16-c.bin"]
SRC_W18 = f"{ART}/w18-range.bin"


def w6_path_policy():
    r = asyncio.run(ws_settings(WS_A, downloadPath="/tmp/syncflow-pwn-ws"))
    ok(
        "W6a downloadPath outside home rejected",
        r.get("type") == "error" and "inside your home" in r.get("error", ""),
        f"resp={r}",
    )
    r2 = asyncio.run(ws_settings(WS_A, downloadPath=12345))
    ok(
        "W6b non-string downloadPath rejected",
        r2.get("type") == "error" and "Invalid download path" in r2.get("error", ""),
        f"resp={r2}",
    )
    r3 = asyncio.run(ws_settings(WS_A, downloadPath=DEST_A))
    ok(
        "W6c valid in-home downloadPath accepted",
        r3.get("type") == "settings:applied" and r3.get("downloadPath") == DEST_A,
        f"resp={r3}",
    )


def w1_evil_origin():
    async def go():
        try:
            async with WSConn(WS_A, origin="http://evil.example.com") as ws:
                await ws.send({"type": "identity:get"})
                await ws.wait("identity:info", 3)
            return True, None
        except Exception as e:
            resp = getattr(e, "response", None)
            code = getattr(resp, "status_code", None)
            if code is None:
                code = getattr(e, "status_code", None)
            return False, code

    connected, code = asyncio.run(go())
    ok(
        "W1 cross-origin browser WS rejected with HTTP 403",
        (not connected) and code == 403,
        f"connected={connected} code={code}",
    )


def w2_allowed_origins():
    async def go():
        for origin in ("http://localhost:5173", "null"):
            async with WSConn(WS_A, origin=origin) as ws:
                await ws.send({"type": "identity:get"})
                d = await ws.wait("identity:info", 4)
                if d.get("type") != "identity:info":
                    return False, origin
        return True, None

    ok_val, bad = asyncio.run(go())
    ok("W2 allowed origins (dev UI, file:// null) connect fine", ok_val, f"bad={bad}")


def w3_bad_json():
    async def go():
        async with WSConn(WS_A) as ws:
            await ws.ws.send("{invalid json")
            err = await ws.wait("error", 4)
            await ws.send({"type": "identity:get"})
            info = await ws.wait("identity:info", 4)
            return err, info

    err, info = asyncio.run(go())
    ok(
        "W3 malformed JSON gets error, session survives",
        err.get("error") == "Invalid JSON" and info.get("type") == "identity:info",
        f"err={err} info={info.get('type')}",
    )


def w4_non_dict():
    async def go():
        async with WSConn(WS_A) as ws:
            await ws.ws.send("[1,2,3]")
            err = await ws.wait("error", 4)
            await ws.send({"type": "identity:get"})
            info = await ws.wait("identity:info", 4)
            return err, info

    err, info = asyncio.run(go())
    ok(
        "W4 non-object message gets error, session survives",
        err.get("error") == "Message must be an object" and info.get("type") == "identity:info",
        f"err={err}",
    )


def w5_unknown_type():
    async def go():
        async with WSConn(WS_A) as ws:
            await ws.send({"type": "totally-unknown-type"})
            await ws.send({"type": "identity:get"})
            info = await ws.wait("identity:info", 4)
            return info

    info = asyncio.run(go())
    ok(
        "W5 unknown message type ignored, session stays usable",
        info.get("type") == "identity:info",
        f"info={info.get('type')}",
    )


def w7_injection_params():
    async def go():
        out = {}
        async with WSConn(WS_A) as ws:
            await ws.send({"type": "command:send", "targetIp": "1.2.3.4; rm -rf /",
                           "files": [f"{ART}/basic.txt"]})
            out["ip"] = await ws.wait({"error"}, 5)
            await ws.send({"type": "command:send", "targetIp": "127.0.0.1",
                           "transferId": "../evil",
                           "files": [f"{ART}/basic.txt"]})
            out["tid"] = await ws.wait({"error"}, 5)
            await ws.send({"type": "transfer:approve", "transferId": "a b"})
            out["apr"] = await ws.wait({"error"}, 5)
        return out

    out = asyncio.run(go())
    ok(
        "W7a evil targetIp rejected",
        "Invalid target address" in out["ip"].get("error", ""), f"resp={out['ip']}")
    ok(
        "W7b traversal transferId rejected",
        "Invalid transfer id" in out["tid"].get("error", ""), f"resp={out['tid']}")
    ok(
        "W7c malformed approval id rejected",
        "Invalid transfer id" in out["apr"].get("error", ""), f"resp={out['apr']}")


def w8_chat_safety():
    async def go():
        out = {}
        async with WSConn(WS_A) as ws:
            await ws.send({"type": "chat:send", "text": "A" * 10000})
            out["ack1"] = await ws.wait("chat:ack", 5)
            await ws.send({"type": "chat:history"})
            h1 = await ws.wait("chat:history", 5)
            out["len1"] = len(h1.get("messages", [])[-1].get("text", ""))

            raw = "Xin\x07\x00out\x01tail"
            await ws.send({"type": "chat:send", "text": raw})
            out["ack2"] = await ws.wait("chat:ack", 5)
            await ws.send({"type": "chat:history"})
            h2 = await ws.wait("chat:history", 5)
            out["stored2"] = h2.get("messages", [])[-1].get("text", "")

            xss = "<script>alert(1)</script>"
            await ws.send({"type": "chat:send", "text": xss})
            out["ack3"] = await ws.wait("chat:ack", 5)
            await ws.send({"type": "chat:history"})
            h3 = await ws.wait("chat:history", 5)
            out["stored3"] = h3.get("messages", [])[-1].get("text", "")
        return out

    out = asyncio.run(go())
    ok("W8a 10000-char chat capped at 4000", out["len1"] == 4000, f"len={out['len1']}")
    expected = "".join(ch for ch in "Xin\x07\x00out\x01tail" if ch.isprintable() or ch in "\n\t")[:4000].strip()
    ok(
        "W8b control chars stripped from stored chat",
        out["stored2"] == expected and out["stored2"].isprintable(),
        f"stored={out['stored2']!r} expected={expected!r}",
    )
    ok(
        "W8c XSS payload stored as inert text",
        out["stored3"] == "<script>alert(1)</script>",
        f"stored={out['stored3']!r}",
    )


def w13_broadcast_three_clients():
    async def go():
        async with WSConn(WS_A) as c1, WSConn(WS_A) as c2, WSConn(WS_A) as c3:
            await c1.send({"type": "chat:send", "text": "broadcast triple", "fromDevice": "T"})
            m1 = await c1.wait("chat:message", 5)
            m2 = await c2.wait("chat:message", 5)
            m3 = await c3.wait("chat:message", 5)
            ids = [m.get("id") for m in (m1, m2, m3)]
            return len(set(ids)) == 1 and None not in ids

    ok("W13 broadcast reaches all 3 concurrent WS clients", asyncio.run(go()))


def w14_unknown_approval():
    r = asyncio.run(ws_call(
        WS_A, {"type": "transfer:approve", "transferId": "nosuch123"},
        {"transfer:decision"}, timeout=5,
    ))
    ok(
        "W14 approving unknown transferId -> success:false (no crash)",
        r.get("success") is False,
        f"resp={r}",
    )


def w15_stable_identity():
    async def go():
        a = await ws_call(WS_A, {"type": "identity:get"}, {"identity:info"})
        b = await ws_call(WS_A, {"type": "identity:get"}, {"identity:info"})
        return a.get("deviceId"), b.get("deviceId")

    d1, d2 = asyncio.run(go())
    ok(
        "W15 deviceId stable across calls",
        isinstance(d1, str) and d1 == d2 and len(d1) == 32,
        f"d1={d1[:12] if d1 else None}...",
    )
    return d1


def w9_chat_relay(a_device_placeholder=None):
    async def go():
        binfo = await ws_call(WS_B, {"type": "identity:get"}, {"identity:info"})
        bid = binfo["deviceId"]
        async with WSConn(WS_A) as aws, WSConn(WS_B) as bws:
            dev = await wait_device(aws, bid, timeout=25)
            await aws.send({"type": "chat:send", "text": "relay-hello-9", "fromDevice": "A"})
            ack = await aws.wait("chat:ack", 6)
            msg = await bws.wait("chat:message", 12)
            return dev, ack, msg

    dev, ack, msg = asyncio.run(go())
    ok(
        "W9 chat A->B relayed E2E over mDNS-discovered peer",
        msg.get("text") == "relay-hello-9" and ack.get("type") == "chat:ack",
        f"msg={msg.get('text')!r} via={dev.get('ip')}:{dev.get('port')}",
    )


def start_raw_send(wire, path):
    box = {}

    def run():
        box["r"] = send_transfer([{"path": path, "wire": wire}], target_port=TCP_A)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


def w10_approve_accept():
    asyncio.run(ws_settings(WS_A, autoAccept=False))
    t, box = start_raw_send("w10-accept.bin", SRC_W10)

    async def go():
        async with WSConn(WS_A) as ws:
            at = await wait_awaiting(ws, 15)
            await ws.send({"type": "transfer:approve", "transferId": at["id"]})
            dec = await ws.wait("transfer:decision", 6)
            return at, dec

    at, dec = asyncio.run(go())
    t.join(60)
    r = box.get("r")
    dest = os.path.join(DEST_A, "w10-accept.bin")
    ok(
        "W10 approval: accept -> transfer completes, file written",
        dec.get("success") is True and r is not None and r.outcome == "completed"
        and os.path.exists(dest),
        f"dec={dec.get('success')} outcome={getattr(r, 'outcome', None)}",
    )


def w11_approve_decline():
    t, box = start_raw_send("w11-decline.bin", SRC_W11)

    async def go():
        async with WSConn(WS_A) as ws:
            at = await wait_awaiting(ws, 15)
            await ws.send({"type": "transfer:decline", "transferId": at["id"]})
            dec = await ws.wait("transfer:decision", 6)
            return dec

    dec = asyncio.run(go())
    t.join(60)
    r = box.get("r")
    dest = os.path.join(DEST_A, "w11-decline.bin")
    ok(
        "W11 approval: decline -> sender informed, no file written",
        dec.get("success") is True and r is not None and r.outcome == "declined"
        and "declined" in (r.error or "") and not os.path.exists(dest),
        f"outcome={getattr(r, 'outcome', None)} err={getattr(r, 'error', None)}",
    )


def w12_cancel_awaiting():
    t, box = start_raw_send("w12-cancel.bin", SRC_W12)

    async def go():
        async with WSConn(WS_A) as ws:
            at = await wait_awaiting(ws, 15)
            await ws.send({"type": "command:cancel", "transferId": at["id"]})
            cancelled = await ws.wait("transfer:cancelled", 6)
            return at, cancelled

    at, cancelled = asyncio.run(go())
    t.join(60)
    r = box.get("r")
    dest = os.path.join(DEST_A, "w12-cancel.bin")
    ok(
        "W12 cancel while awaiting approval -> clean decline, no file",
        cancelled.get("success") is True and r is not None and r.outcome == "declined"
        and not os.path.exists(dest),
        f"cancel={cancelled.get('success')} outcome={getattr(r, 'outcome', None)}",
    )
    asyncio.run(ws_settings(WS_A, autoAccept=True))


def w16_approve_subset():
    asyncio.run(ws_settings(WS_A, autoAccept=False))

    box = {}

    def run():
        box["r"] = send_transfer(
            [
                {"path": SRC_W16[0], "wire": "w16-a.bin"},
                {"path": SRC_W16[1], "wire": "w16-b.bin"},
                {"path": SRC_W16[2], "wire": "w16-c.bin"},
            ],
            target_port=TCP_A,
        )

    t = threading.Thread(target=run, daemon=True)
    t.start()

    async def go():
        async with WSConn(WS_A) as ws:
            at = await wait_awaiting(ws, 15)
            await ws.send({"type": "transfer:approve", "transferId": at["id"], "files": [0, 2]})
            dec = await ws.wait("transfer:decision", 6)
            return at, dec

    at, dec = asyncio.run(go())
    t.join(60)
    r = box.get("r")

    final = None
    try:
        data = asyncio.run(ws_call(WS_A, {"type": "transfers:list"}, {"transfers:update"}, timeout=5))
        for entry in data.get("completed", []):
            if entry.get("id") == at["id"]:
                final = entry
    except Exception:
        pass

    a_ok = os.path.exists(os.path.join(DEST_A, "w16-a.bin"))
    b_missing = not os.path.exists(os.path.join(DEST_A, "w16-b.bin"))
    c_ok = os.path.exists(os.path.join(DEST_A, "w16-c.bin"))
    ok(
        "W16 subset approval: accept [0,2] -> only A+C written, task verified+skipped",
        dec.get("success") is True
        and r is not None and r.outcome == "completed"
        and a_ok and b_missing and c_ok
        and final is not None and final.get("status") == "completed"
        and final.get("verified") is True
        and len(final.get("files", [])) == 2
        and final.get("skipped") == 1,
        f"dec={dec.get('success')} outcome={getattr(r, 'outcome', None)} "
        f"a={a_ok} b={b_missing} c={c_ok} final={final and (final.get('status'), final.get('skipped'), len(final.get('files', [])))}",
    )
    asyncio.run(ws_settings(WS_A, autoAccept=True))


def w17_invalid_selection():
    bad_cases = [[], [0, "x"], [0, 0], [-1], [True], "nope", 5]

    async def go():
        out = []
        for sel in bad_cases:
            r = await ws_call(
                WS_A,
                {"type": "transfer:approve", "transferId": "nosuch123", "files": sel},
                {"error", "transfer:decision"},
                timeout=5,
            )
            out.append(r)
        return out

    results = asyncio.run(go())
    bad = [
        r for r in results
        if not (r.get("type") == "error" and r.get("error") == "Invalid file selection")
    ]
    ok(
        "W17 invalid file selections rejected (empty/dup/neg/bool/wrong-type)",
        not bad and len(results) == len(bad_cases),
        f"bad={bad}",
    )


def w18_out_of_range_selection():
    asyncio.run(ws_settings(WS_A, autoAccept=False))
    t, box = start_raw_send("w18-range.bin", SRC_W18)

    async def go():
        async with WSConn(WS_A) as ws:
            at = await wait_awaiting(ws, 15)
            await ws.send({"type": "transfer:approve", "transferId": at["id"], "files": [0, 99]})
            dec = await ws.wait("transfer:decision", 6)
            return at, dec

    at, dec = asyncio.run(go())
    t.join(60)
    r = box.get("r")
    dest = os.path.join(DEST_A, "w18-range.bin")
    ok(
        "W18 out-of-range selection: engine declines, no file written",
        dec.get("success") is True
        and r is not None and r.outcome == "declined"
        and not os.path.exists(dest),
        f"dec={dec.get('success')} outcome={getattr(r, 'outcome', None)} "
        f"err={getattr(r, 'error', None)}",
    )
    asyncio.run(ws_settings(WS_A, autoAccept=True))


def w0_alive():
    r = asyncio.run(ws_call(WS_A, {"type": "identity:get"}, {"identity:info"}, timeout=5))
    ok("W0 server alive after full WS suite", r.get("type") == "identity:info")


def main():
    setup()
    w6_path_policy()
    w1_evil_origin()
    w2_allowed_origins()
    w3_bad_json()
    w4_non_dict()
    w5_unknown_type()
    w7_injection_params()
    w8_chat_safety()
    w13_broadcast_three_clients()
    w14_unknown_approval()
    w15_stable_identity()
    w9_chat_relay()
    w10_approve_accept()
    w11_approve_decline()
    w12_cancel_awaiting()
    w16_approve_subset()
    w17_invalid_selection()
    w18_out_of_range_selection()
    w0_alive()
    finish("t_ws")


if __name__ == "__main__":
    main()
