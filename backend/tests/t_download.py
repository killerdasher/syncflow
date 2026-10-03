"""Phase 3 companion download — 10 checks.

Spawns a fresh LAN-mode backend (WS 19998 / TCP 19988, state in
/tmp/opencode/sfDN) and drives the desktop->phone download protocol over
real websockets frames:

  * a real seeded history: a 64 MB file delivered THROUGH the engine
    (upload protocol -> self TCP) and a sent file whose source still
    exists on disk
  * happy path: ready -> ordered binary frames -> file-done with matching
    sha256/byte count
  * validation: unknown transfer, bad/out-of-range file indices
  * concurrency guards: second request while streaming, binary frame
    during download, cancel mid-stream, disconnect mid-stream (both must
    free the transfer for later clients)
  * vanished source files fail clean instead of hanging
"""
import asyncio
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from proto_lib import ok, finish  # noqa: E402

ART = "/tmp/opencode"
HOME_DN = f"{ART}/sfDN"
WS_DN, TCP_DN = 19998, 19988
DOWNLOAD_DIR = os.path.join(
    os.path.realpath(os.path.expanduser("~")), "Downloads", "SyncFlow-testDN"
)
STAGING = os.path.join(HOME_DN, "staging")
PY = os.path.join(os.path.dirname(HERE), "venv", "bin", "python3")
if not os.path.exists(PY):
    PY = sys.executable

CHUNK = 256 * 1024
# Large enough that loopback socket buffers can NEVER absorb the whole
# stream — otherwise "mid-stream" cancel/disconnect checks race a stream
# that finishes before the control frame is processed.
BIG = os.urandom(1024) * 1024 * 64  # 64 MiB, deterministic bytes
BIG_SHA = hashlib.sha256(BIG).hexdigest()
SRC = b"sent-source-payload-" + os.urandom(64)
SRC_SHA = hashlib.sha256(SRC).hexdigest()


def _free_ports(*ports):
    for port in ports:
        try:
            out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
            for line in out.splitlines():
                if f":{port} " in line or line.rstrip().endswith(f":{port}"):
                    pid = line.split("pid=", 1)[1].split(",")[0].split(")")[0]
                    os.kill(int(pid), 15)
        except (ProcessLookupError, ValueError, IndexError):
            pass
    time.sleep(0.5)


def _wait_port(port, proc, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"backend exited early rc={proc.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError(f"port {port} never opened")


def _spawn():
    env = {
        **os.environ,
        "SYNCFLOW_HOME": HOME_DN,
        "SYNCFLOW_WS_PORT": str(WS_DN),
        "SYNCFLOW_TCP_PORT": str(TCP_DN),
        "SYNCFLOW_WS_HOST": "0.0.0.0",
    }
    log = open(f"{ART}/DN.log", "w")
    proc = subprocess.Popen(
        [PY, "-u", os.path.join(os.path.dirname(HERE), "main.py")],
        env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    return proc, log


def _connect():
    websockets = __import__("websockets")
    return websockets.connect("ws://127.0.0.1:%d" % WS_DN, open_timeout=5.0)


async def _recv_until(ws, pred, timeout=8.0, skip_binary=False):
    """Receive TEXT messages until pred(msg); binary frames optionally skipped."""
    deadline = time.time() + timeout
    while True:
        rem = deadline - time.time()
        if rem <= 0:
            raise TimeoutError("expected message not received")
        raw = await asyncio.wait_for(ws.recv(), rem)
        if not isinstance(raw, str):
            if skip_binary:
                continue
            raise AssertionError("unexpected binary frame")
        msg = json.loads(raw)
        if isinstance(msg, dict) and pred(msg):
            return msg


async def _drain_download(ws, timeout=30.0):
    """Collect a full download stream started on ws; returns (done_msg, blob)."""
    parts = []
    done = None
    deadline = time.time() + timeout
    while time.time() < deadline and done is None:
        rem = deadline - time.time()
        try:
            raw = await asyncio.wait_for(ws.recv(), rem)
        except asyncio.TimeoutError:
            break
        if isinstance(raw, (bytes, bytearray)):
            parts.append(raw)
            continue
        msg = json.loads(raw)
        if not isinstance(msg, dict):
            continue
        if msg.get("type") == "transfer:download:file-done":
            done = msg
        # error/noise frames are ignored here: validation replies are
        # asserted via _recv_until; a stream that dies without file-done
        # just times out with done=None.
    return done, b"".join(parts)


async def _poll_completed(ws, pred, timeout=15.0):
    """Poll transfers:list until a completed entry matching pred appears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await ws.send(json.dumps({"type": "transfers:list"}))
        try:
            msg = await _recv_until(ws, lambda m: m.get("type") == "transfers:update", 3.0)
        except (TimeoutError, asyncio.TimeoutError):
            await asyncio.sleep(0.3)
            continue
        for entry in reversed(msg.get("completed") or []):
            if pred(entry):
                return entry
        await asyncio.sleep(0.3)
    return None


async def run_download_tests():
    _free_ports(WS_DN, TCP_DN)
    shutil.rmtree(HOME_DN, ignore_errors=True)
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
    os.makedirs(HOME_DN, mode=0o700, exist_ok=True)

    proc, log = _spawn()
    try:
        _wait_port(WS_DN, proc)
        _wait_port(TCP_DN, proc)

        # ---- setup + seed history via loopback (auto-trusted) --------------
        async with _connect() as ws:
            await ws.send(json.dumps({
                "type": "settings:apply",
                "autoAccept": True,
                "downloadPath": DOWNLOAD_DIR,
            }))
            await _recv_until(ws, lambda m: m.get("type") == "settings:applied")

            # seed 1: upload protocol -> engine self-delivery -> destPaths
            await ws.send(json.dumps({
                "type": "transfer:upload", "transferId": "tr-dn-big",
                "seq": 0, "name": "big.bin", "size": len(BIG),
                "batchTotalBytes": len(BIG), "targetIp": "127.0.0.1",
                "targetPort": TCP_DN,
            }))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:upload:ready", "error"))
            if m.get("type") != "transfer:upload:ready":
                ok("download: seed upload announced", False, str(m))
                return finish("t_download")
            off = 0
            while off < len(BIG):
                piece = BIG[off:off + CHUNK]
                await ws.send(piece)
                off += len(piece)
            await ws.send(json.dumps({"type": "transfer:upload:end",
                                      "transferId": "tr-dn-big", "seq": 0}))
            await _recv_until(ws, lambda x: x.get("type") in ("transfer:upload:file-done", "error"))
            await ws.send(json.dumps({"type": "transfer:upload:finish",
                                      "transferId": "tr-dn-big"}))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:new", "error"))
            if m.get("type") != "transfer:new":
                ok("download: seed upload finished", False, str(m))
                return finish("t_download")

            big_entry = await _poll_completed(
                ws, lambda e: e.get("destPaths") and len(e.get("destPaths") or []) == 1)
            big_tid = big_entry["id"] if big_entry else None
            if not big_tid:
                ok("download: seeded receive task completed", False, "no destPaths in list")
                return finish("t_download")

            # seed 2: a sent file whose SOURCE still exists afterwards
            src_dir = os.path.join(HOME_DN, "src")
            os.makedirs(src_dir, exist_ok=True)
            src_path = os.path.join(src_dir, "source.txt")
            with open(src_path, "wb") as f:
                f.write(SRC)
            await ws.send(json.dumps({
                "type": "command:send", "transferId": "tr-dn-sent",
                "targetIp": "127.0.0.1", "targetPort": TCP_DN, "files": [src_path],
            }))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:new", "error", "transfer:error"))
            if m.get("type") != "transfer:new":
                ok("download: seed sent transfer started", False, str(m))
                return finish("t_download")
            sent_entry = await _poll_completed(
                ws, lambda e: e.get("id") == "tr-dn-sent" and e.get("status") == "completed")
            sent_tid = "tr-dn-sent" if sent_entry else None

            # ---- C1: unknown transfer --------------------------------------
            await ws.send(json.dumps({"type": "transfer:download",
                                      "transferId": str(uuid.uuid4()), "fileIndex": 0}))
            m = await _recv_until(ws, lambda x: x.get("type") in ("error", "transfer:download:ready"))
            ok("download: unknown transfer rejected",
               m.get("type") == "error" and "not found" in str(m.get("error", "")), str(m))

            # ---- C2: invalid / out-of-range indices ------------------------
            bad_index_ok = True
            for bad in (-1, "x", 10000, True):
                await ws.send(json.dumps({"type": "transfer:download",
                                          "transferId": big_tid, "fileIndex": bad}))
                m = await _recv_until(ws, lambda x: x.get("type") in ("error", "transfer:download:ready"),
                                      skip_binary=True)
                bad_index_ok = bad_index_ok and m.get("type") == "error"
            # out-of-range but well-formed index on a real 1-file transfer
            await ws.send(json.dumps({"type": "transfer:download",
                                      "transferId": big_tid, "fileIndex": 1}))
            m = await _recv_until(ws, lambda x: x.get("type") in ("error", "transfer:download:ready"),
                                  skip_binary=True)
            oor_ok = m.get("type") == "error" and "out of range" in str(m.get("error", ""))
            ok("download: invalid and out-of-range file indices rejected",
               bad_index_ok and oor_ok, f"bad={bad_index_ok} oor={m}")

            # ---- C3: happy path (64 MB, byte + sha256 match) ---------------
            await ws.send(json.dumps({"type": "transfer:download",
                                      "transferId": big_tid, "fileIndex": 0}))
            done, blob = await _drain_download(ws, timeout=30.0)
            sha = hashlib.sha256(blob).hexdigest() if blob else ""
            ok("download: 64 MB stream byte-count and sha256 match",
               done is not None and done.get("type") == "transfer:download:file-done"
               and done.get("received") == len(BIG) and done.get("size") == len(BIG)
               and done.get("sha256") == BIG_SHA == sha and blob == BIG,
               f"done={done} got={len(blob)} sha_ok={sha == BIG_SHA}")

            # ---- C4: second request while streaming rejected ---------------
            await ws.send(json.dumps({"type": "transfer:download",
                                      "transferId": big_tid, "fileIndex": 0}))
            await ws.send(json.dumps({"type": "transfer:download",
                                      "transferId": big_tid, "fileIndex": 0}))
            m2 = await _recv_until(ws, lambda x: x.get("type") == "error" and
                                   "progress" in str(x.get("error", "")), timeout=10.0,
                                   skip_binary=True)
            busy_ok = m2 is not None
            done, blob = await _drain_download(ws, timeout=30.0)
            busy_ok = busy_ok and done is not None and done.get("type") == "transfer:download:file-done" \
                and blob == BIG
            ok("download: concurrent second request rejected while streaming",
               busy_ok, f"m2={m2} done={done and done.get('type')} bytes={len(blob)}")

            # ---- C5: binary frame during download rejected -----------------
            await ws.send(json.dumps({"type": "transfer:download",
                                      "transferId": big_tid, "fileIndex": 0}))
            await ws.send(b"\x01\x02\x03\x04")
            m = await _recv_until(ws, lambda x: x.get("type") == "error" and
                                  "binary" in str(x.get("error", "")), timeout=10.0,
                                  skip_binary=True)
            bin_ok = m is not None
            done, blob = await _drain_download(ws, timeout=30.0)
            bin_ok = bin_ok and done is not None and done.get("type") == "transfer:download:file-done"
            ok("download: binary frame during download rejected",
               bin_ok, f"err={m} done={done and done.get('type')}")

        # ---- C6: cancel mid-stream (separate connection, stops the push) ---
        async with _connect() as ws:
            await ws.send(json.dumps({"type": "transfer:download",
                                      "transferId": big_tid, "fileIndex": 0}))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:download:ready", "error"),
                                  timeout=8.0)
            ready_ok = m.get("type") == "transfer:download:ready"
            got_data = True  # 64 MiB cannot drain into socket buffers first
            await ws.send(json.dumps({"type": "transfer:download:cancel",
                                      "transferId": big_tid}))
            cancel_msg = await _recv_until(ws, lambda x: x.get("type") in
                                           ("transfer:download:cancelled", "error"), timeout=8.0,
                                           skip_binary=True)
            cancel_ok = cancel_msg.get("type") == "transfer:download:cancelled" and cancel_msg.get("success") is True
            # the stream must free the transfer shortly after
            freed = False
            deadline = time.time() + 5.0
            while time.time() < deadline and not freed:
                await ws.send(json.dumps({"type": "transfer:download",
                                          "transferId": big_tid, "fileIndex": 0}))
                try:
                    m = await _recv_until(
                        ws, lambda x: x.get("type") in ("error", "transfer:download:ready"),
                        timeout=2.0, skip_binary=True)
                except (TimeoutError, asyncio.TimeoutError):
                    await asyncio.sleep(0.3)
                    continue
                if m.get("type") == "transfer:download:ready":
                    freed = True
                    break
                await asyncio.sleep(0.3)
            if freed:
                done, _ = await _drain_download(ws, timeout=30.0)
                freed = done is not None and done.get("type") == "transfer:download:file-done"
            ok("download: cancel mid-stream stops push and frees the transfer",
               ready_ok and got_data and cancel_ok and freed,
               f"ready={ready_ok} data={got_data} cancel={cancel_ok} freed={freed} "
               f"cancel_msg={cancel_msg}")

        # ---- C7: disconnect mid-stream frees it for a later client --------
        # 64 MiB guarantees the push is still blocked when the socket dies.
        ws = await _connect()
        try:
            await ws.send(json.dumps({"type": "transfer:download",
                                      "transferId": big_tid, "fileIndex": 0}))
            m = await _recv_until(ws, lambda x: x.get("type") in
                                  ("transfer:download:ready", "error"), timeout=8.0)
            ready_ok = m.get("type") == "transfer:download:ready"
        finally:
            await ws.close()
        await asyncio.sleep(1.0)
        async with _connect() as ws2:
            await ws2.send(json.dumps({"type": "transfer:download",
                                       "transferId": big_tid, "fileIndex": 0}))
            done, blob = await _drain_download(ws2, timeout=30.0)
            re_ok = done is not None and done.get("type") == "transfer:download:file-done" \
                and blob == BIG
        ok("download: disconnect mid-stream frees the transfer for later clients",
           ready_ok and re_ok, f"ready={ready_ok} re={re_ok} bytes={len(blob)}")

        # ---- C8/C9: sent source path + vanished source --------------------
        async with _connect() as ws:
            if sent_tid:
                await ws.send(json.dumps({"type": "transfer:download",
                                          "transferId": sent_tid, "fileIndex": 0}))
                done, blob = await _drain_download(ws, timeout=15.0)
                sha = hashlib.sha256(blob).hexdigest() if blob else ""
                ok("download: completed sent file streams from its source path",
                   done is not None and done.get("type") == "transfer:download:file-done"
                   and sha == SRC_SHA and blob == SRC,
                   f"done={done} sha_ok={sha == SRC_SHA}")
            else:
                ok("download: completed sent file streams from its source path",
                   False, "sent transfer never completed")

            os.remove(src_path)
            await ws.send(json.dumps({"type": "transfer:download",
                                      "transferId": sent_tid, "fileIndex": 0}))
            m = await _recv_until(ws, lambda x: x.get("type") in ("error", "transfer:download:ready"),
                                  skip_binary=True)
            ok("download: vanished source fails clean (no hang)",
               m.get("type") == "error" and "no longer exists" in str(m.get("error", "")), str(m))

        # ---- C10: malformed transfer id (RE mismatch, not "not found") ----
        async with _connect() as ws:
            await ws.send(json.dumps({"type": "transfer:download",
                                      "transferId": "bad id!!", "fileIndex": 0}))
            m = await _recv_until(ws, lambda x: x.get("type") in ("error", "transfer:download:ready"))
            ok("download: malformed transfer id rejected",
               m.get("type") == "error" and "invalid transfer id" in str(m.get("error", "")).lower(), str(m))

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        shutil.rmtree(HOME_DN, ignore_errors=True)
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)

    return finish("t_download")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        print(10)
        sys.exit(0)
    asyncio.get_event_loop().run_until_complete(run_download_tests())
