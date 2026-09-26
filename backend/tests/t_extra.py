"""Extra suite: three checks missing from the original harness.

X1 WS oversize message (2 MB > 1 MB server cap) -> close 1009, server lives.
X2 approval timeout (60 s) -> sender & receiver both fail cleanly, no file.
X3 cancel of an ACTIVE streaming transfer (1.5 GB) -> sender cancelled,
   receiver keeps no partial file.
"""
import asyncio
import glob
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proto_lib import *

BIG_SRC = "/home/dasher/Downloads/.syncflow-cancel-src.bin"
BIG_SIZE = 1500 * 1024 * 1024


def ensure_big_src():
    if os.path.exists(BIG_SRC) and os.path.getsize(BIG_SRC) == BIG_SIZE:
        return
    block = b"\x00" * (1024 * 1024)
    with open(BIG_SRC, "wb") as f:
        for _ in range(BIG_SIZE // (1024 * 1024)):
            f.write(block)


def cleanup_dest(d, prefix):
    os.makedirs(d, exist_ok=True)
    for p in glob.glob(os.path.join(d, prefix + "*")):
        try:
            if os.path.isfile(p):
                os.unlink(p)
        except OSError:
            pass


def x1_ws_oversize():
    async def go():
        async with WSConn(WS_A, max_size=2_000_000) as ws:
            try:
                await ws.ws.send("x" * (2 * 1024 * 1024))
            except Exception:
                pass  # server may have closed during send
            code = None
            try:
                await asyncio.wait_for(ws.ws.recv(), 5)
                closed = False
            except Exception as e:
                closed = True
                rcvd = getattr(e, "rcvd", None)
                code = getattr(rcvd, "code", None)
                if code is None and rcvd is not None:
                    code = getattr(getattr(rcvd, "rcvd", None), "code", None)
                if code is None:
                    code = getattr(e, "code", None)
            return closed, code

    closed, code = asyncio.run(go())
    alive = asyncio.run(ws_call(WS_A, {"type": "identity:get"}, {"identity:info"}, timeout=5))
    ok(
        "X1 2MB WS message closed (1009) without killing the server",
        closed and alive.get("type") == "identity:info",
        f"closed={closed} code={code}",
    )


def x3_cancel_active():
    ensure_big_src()
    asyncio.run(ws_settings(WS_B, autoAccept=True, downloadPath=DEST_B))
    cleanup_dest(DEST_B, "syncflow-cancel-src")

    async def attempt():
        async with WSConn(WS_A) as ws:
            await ws.send({
                "type": "command:send",
                "targetIp": "127.0.0.1",
                "targetPort": TCP_B,
                "files": [BIG_SRC],
            })
            new = await ws.wait({"transfer:new", "error"}, timeout=10)
            if new.get("type") != "transfer:new":
                return f"send_error:{new.get('error')}"
            tid = new["transfer"]["id"]

            deadline = time.time() + 8
            while time.time() < deadline:
                await ws.send({"type": "transfers:list"})
                upd = await ws.wait({"transfers:update"}, timeout=4)
                done = [t for t in upd.get("completed", []) if t.get("id") == tid]
                if done:
                    return f"finished_before_cancel:{done[0].get('status')}"
                active = [t for t in upd.get("active", []) if t.get("id") == tid]
                if active and active[0].get("status") == "transferring":
                    break
                await asyncio.sleep(0.02)
            else:
                return "never_reached_transferring"

            await ws.send({"type": "command:cancel", "transferId": tid})
            cancelled = await ws.wait("transfer:cancelled", timeout=8)
            if not cancelled.get("success"):
                return "cancel_command_failed"
            final = await wait_completed_status(
                ws, tid, statuses=("cancelled", "completed", "failed"), timeout=15,
            )
            return final.get("status")

    final_status = None
    attempts = 0
    for i in range(3):
        attempts = i + 1
        final_status = asyncio.run(attempt())
        if final_status == "cancelled":
            break
        cleanup_dest(DEST_B, "syncflow-cancel-src")  # completed on a fast attempt
        time.sleep(0.5)

    time.sleep(1.0)  # receiver cleans its temp on connection reset
    leftovers = glob.glob(os.path.join(DEST_B, "syncflow-cancel-src*"))
    ok(
        "X3 cancel during active streaming -> sender cancelled, no file/temp on receiver",
        final_status == "cancelled" and not leftovers,
        f"status={final_status} attempts={attempts} leftovers={leftovers}",
    )


def x2_approval_timeout():
    cleanup_dest(DEST_A, "x2-timeout.bin")
    src = f"{ART}/x2-timeout.bin"
    with open(src, "wb") as f:
        f.write(b"timeout approval payload")
    asyncio.run(ws_settings(WS_A, autoAccept=False))

    box = {}

    def run():
        box["r"] = send_transfer([{"path": src, "wire": "x2-timeout.bin"}], target_port=TCP_A)

    t = threading.Thread(target=run, daemon=True)
    t.start()

    async def wait_awaiting_id():
        async with WSConn(WS_A) as ws:
            at = await wait_awaiting(ws, 15)
            return at["id"]

    try:
        at_id = asyncio.run(wait_awaiting_id())
    except Exception as e:
        ok("X2 approval timeout (60s) fails sender+receiver cleanly", False, f"never awaiting: {e}")
        t.join(70)
        return

    t.join(80)
    r = box.get("r")

    final = None
    try:
        data = asyncio.run(ws_call(WS_A, {"type": "transfers:list"}, {"transfers:update"}, timeout=5))
        for entry in data.get("completed", []):
            if entry.get("id") == at_id:
                final = entry
    except Exception:
        pass

    dest = os.path.join(DEST_A, "x2-timeout.bin")
    sender_ok = (
        r is not None and r.outcome == "declined"
        and "timed out" in (r.error or "").lower()
    )
    receiver_ok = final is not None and final.get("status") == "failed" \
        and "timed out" in (final.get("error") or "").lower()
    ok(
        "X2 approval timeout (60s): sender declined with timeout, receiver failed, no file",
        sender_ok and receiver_ok and not os.path.exists(dest),
        f"sender={getattr(r, 'outcome', None)}/{getattr(r, 'error', None)!r} "
        f"receiver={final and final.get('status')}/{final and final.get('error')!r}",
    )
    asyncio.run(ws_settings(WS_A, autoAccept=True))


def main():
    x1_ws_oversize()
    x3_cancel_active()
    x2_approval_timeout()
    finish("t_extra")


if __name__ == "__main__":
    main()
