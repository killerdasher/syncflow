"""Phase 3 chunked companion upload — 12 checks.

Spawns a fresh LAN-mode backend (WS 19996 / TCP 19986, state in
/tmp/opencode/sfUP) and drives the full upload protocol over real
websockets frames:

  * unauthenticated clients (JSON and binary) get auth_required
  * pairing then staging: announce -> ready -> binary chunks -> end ->
    file-done -> finish -> transfer:new, delivered end-to-end through
    the engine to this same instance's TCP listener (auto-accept +
    isolated download dir), sha256 verified, staging removed
  * traversal names, size caps, negative sizes, out-of-sequence seq,
    oversized frames, mid-flight cancel, and disconnect cleanup all
    behave (session aborted, connection survives, no staged leftovers)
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
HOME_UP = f"{ART}/sfUP"
WS_UP, TCP_UP = 19996, 19986
DOWNLOAD_DIR = os.path.join(
    os.path.realpath(os.path.expanduser("~")), "Downloads", "SyncFlow-testUP"
)
STAGING = os.path.join(HOME_UP, "staging")
PY = os.path.join(os.path.dirname(HERE), "venv", "bin", "python3")
if not os.path.exists(PY):
    PY = sys.executable

MAX_UPLOAD_FILE = int(os.environ.get("SYNCFLOW_MAX_UPLOAD_MB", "8192")) * 1024 * 1024
CHUNK = 256 * 1024


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
    return sorted(ips)


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
        "SYNCFLOW_HOME": HOME_UP,
        "SYNCFLOW_WS_PORT": str(WS_UP),
        "SYNCFLOW_TCP_PORT": str(TCP_UP),
        "SYNCFLOW_WS_HOST": "0.0.0.0",
    }
    log = open(f"{ART}/UP.log", "w")
    proc = subprocess.Popen(
        [PY, "-u", os.path.join(os.path.dirname(HERE), "main.py")],
        env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    return proc, log


def _connect(host, port, timeout=5.0):
    websockets = __import__("websockets")
    return websockets.connect(f"ws://{host}:{port}", open_timeout=timeout)


# Progress broadcasts are not responses to any single frame; they are
# observed passively and asserted by the happy-path check.
PROGRESS = {"seen": False}


async def _recv_until(ws, pred, timeout=8.0):
    """Receive messages until pred(msg) is true; returns the matching msg."""
    deadline = time.time() + timeout
    while True:
        rem = deadline - time.time()
        if rem <= 0:
            raise TimeoutError("expected message not received")
        raw = await asyncio.wait_for(ws.recv(), rem)
        if not isinstance(raw, str):
            continue
        msg = json.loads(raw)
        if not isinstance(msg, dict):
            continue
        if msg.get("type") == "transfer:progress":
            PROGRESS["seen"] = True
            continue
        if pred(msg):
            return msg


def _staging_dirs():
    if not os.path.isdir(STAGING):
        return set()
    return set(os.listdir(STAGING))


async def _wait_gone(rel_path, timeout=6.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not os.path.exists(rel_path):
            return True
        await asyncio.sleep(0.2)
    return not os.path.exists(rel_path)


async def _wait_file(path, sha=None, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.isfile(path):
            if sha is None:
                return True
            with open(path, "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() == sha:
                    return True
        await asyncio.sleep(0.2)
    return False


async def run_upload_tests():
    ips = lan_ips()
    lan = ips[0] if ips else None

    _free_ports(WS_UP, TCP_UP)
    shutil.rmtree(HOME_UP, ignore_errors=True)
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
    os.makedirs(HOME_UP, mode=0o700, exist_ok=True)

    proc, log = _spawn()
    try:
        _wait_port(WS_UP, proc)
        _wait_port(TCP_UP, proc)

        # ---- setup via loopback (auto-trusted, mirrors the desktop) --------
        code = None
        async with _connect("127.0.0.1", WS_UP) as ws:
            await ws.send(json.dumps({
                "type": "settings:apply",
                "autoAccept": True,
                "downloadPath": DOWNLOAD_DIR,
            }))
            await _recv_until(ws, lambda m: m.get("type") == "settings:applied")
            if lan:
                await ws.send(json.dumps({"type": "pairing:generate"}))
                resp = await _recv_until(
                    ws, lambda m: m.get("type") == "pairing:code")
                code = resp.get("code")

        # ---- C1/C2: unauthenticated control + binary ------------------------
        unauth_ok_json = unauth_ok_bin = False
        target_host = lan or "127.0.0.1"
        if lan:
            async with _connect(target_host, WS_UP) as ws:
                await ws.send(json.dumps({
                    "type": "transfer:upload", "transferId": "tr-x",
                    "seq": 0, "name": "a", "size": 1, "targetIp": "127.0.0.1",
                }))
                m = await _recv_until(ws, lambda x: x.get("type") in ("auth_required", "transfer:upload:ready"))
                unauth_ok_json = m.get("type") == "auth_required"
                await ws.send(b"\x00\x01\x02\x03")
                m = await _recv_until(ws, lambda x: x.get("type") in ("auth_required", "transfer:upload:ready"))
                unauth_ok_bin = m.get("type") == "auth_required"
        else:
            unauth_ok_json = unauth_ok_bin = True  # loopback is trusted by design
        ok("upload: unauthenticated JSON control rejected", unauth_ok_json,
           "skipped (no LAN IP, loopback is trusted by design)" if not lan else "")
        ok("upload: unauthenticated binary frame rejected", unauth_ok_bin,
           "skipped (no LAN IP, loopback is trusted by design)" if not lan else "")

        # ---- main session: pair + announce ----------------------------------
        async with _connect(target_host, WS_UP) as ws:
            if lan:
                await ws.send(json.dumps({"type": "pairing", "code": code}))
                m = await _recv_until(ws, lambda x: x.get("type") in ("pair_ok", "pair_fail"))
                if m.get("type") != "pair_ok":
                    ok("upload: pairing grants staging", False, str(m))
                    return finish("t_upload")

            # C3: announce -> ready (traversal name, sanitized server-side)
            evil = "../../../../etc/evil"
            await ws.send(json.dumps({
                "type": "transfer:upload", "transferId": "tr-up-evil",
                "seq": 0, "name": evil, "size": 5,
                "batchTotalBytes": 5, "targetIp": "127.0.0.1",
                "targetPort": TCP_UP,
            }))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:upload:ready", "error"))
            ok("upload: pairing then announce yields ready",
               m.get("type") == "transfer:upload:ready", str(m))

            # C4: traversal file uploads and lands as a bare basename
            await ws.send(b"hello")
            await ws.send(json.dumps({"type": "transfer:upload:end",
                                      "transferId": "tr-up-evil", "seq": 0}))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:upload:file-done", "error"))
            done_ok = m.get("type") == "transfer:upload:file-done"
            await ws.send(json.dumps({"type": "transfer:upload:finish",
                                      "transferId": "tr-up-evil"}))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:new", "error"))
            new_ok = m.get("type") == "transfer:new"
            landed = await _wait_file(os.path.join(DOWNLOAD_DIR, "evil"))
            sha_ok = False
            if landed:
                with open(os.path.join(DOWNLOAD_DIR, "evil"), "rb") as f:
                    sha_ok = f.read() == b"hello"
            escaped = any(
                os.path.exists(os.path.join(DOWNLOAD_DIR, p))
                for p in ("etc", "evil2")
            ) or os.path.exists("/tmp/opencode/evil")
            staging_clean = await _wait_gone(os.path.join(STAGING, "tr-up-evil"))
            ok("upload: traversal name lands as bare basename with content",
               done_ok and new_ok and landed and sha_ok and not escaped and staging_clean,
               f"done={done_ok} new={new_ok} landed={landed} sha={sha_ok} "
               f"escaped={escaped} staging_clean={staging_clean}")

            # C9: 600 KB happy path in two files, progress observed, hash match
            PROGRESS["seen"] = False
            blob1 = os.urandom(300 * 1024)
            blob2 = os.urandom(300 * 1024)
            sha1 = hashlib.sha256(blob1).hexdigest()
            sha2 = hashlib.sha256(blob2).hexdigest()
            happy_ready = True
            for seq, blob in ((0, blob1), (1, blob2)):
                await ws.send(json.dumps({
                    "type": "transfer:upload", "transferId": "tr-up-happy",
                    "seq": seq, "name": f"happy-{seq}.bin", "size": len(blob),
                    "batchTotalBytes": len(blob1) + len(blob2),
                    "targetIp": "127.0.0.1", "targetPort": TCP_UP,
                }))
                m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:upload:ready", "error"))
                if m.get("type") != "transfer:upload:ready":
                    print(f"DEBUG announce seq{seq} -> {m}", flush=True)
                happy_ready = happy_ready and m.get("type") == "transfer:upload:ready"
                off = 0
                while off < len(blob):
                    piece = blob[off:off + CHUNK]
                    await ws.send(piece)
                    off += len(piece)
                await ws.send(json.dumps({"type": "transfer:upload:end",
                                          "transferId": "tr-up-happy", "seq": seq}))
                m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:upload:file-done", "error"))
                happy_ready = happy_ready and m.get("type") == "transfer:upload:file-done"
            # a transfer:progress broadcast may still be in flight
            try:
                while not PROGRESS["seen"]:
                    raw = await asyncio.wait_for(ws.recv(), 1.0)
                    if isinstance(raw, str):
                        msg = json.loads(raw)
                        if isinstance(msg, dict) and msg.get("type") == "transfer:progress":
                            PROGRESS["seen"] = True
                        elif isinstance(msg, dict) and msg.get("type") in ("transfer:new", "transfer:error"):
                            break
            except asyncio.TimeoutError:
                pass
            progress_seen = PROGRESS["seen"]
            await ws.send(json.dumps({"type": "transfer:upload:finish",
                                      "transferId": "tr-up-happy"}))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:new", "error"))
            new_ok = m.get("type") == "transfer:new"
            f1 = await _wait_file(os.path.join(DOWNLOAD_DIR, "happy-0.bin"), sha1)
            f2 = await _wait_file(os.path.join(DOWNLOAD_DIR, "happy-1.bin"), sha2)
            staging_clean = await _wait_gone(os.path.join(STAGING, "tr-up-happy"))
            ok("upload: 600 KB two-file happy path end-to-end",
               happy_ready and new_ok and f1 and f2 and staging_clean and progress_seen,
               f"ready={happy_ready} new={new_ok} f1={f1} f2={f2} "
               f"staging={staging_clean} progress={progress_seen}")

            # C5: size cap
            await ws.send(json.dumps({
                "type": "transfer:upload", "transferId": "tr-up-cap",
                "seq": 0, "name": "big.bin", "size": MAX_UPLOAD_FILE + 1,
                "batchTotalBytes": MAX_UPLOAD_FILE + 1, "targetIp": "127.0.0.1",
            }))
            m = await _recv_until(ws, lambda x: x.get("type") in ("error", "transfer:upload:ready"))
            ok("upload: oversize file rejected by cap",
               m.get("type") == "error" and "cap" in str(m.get("error", "")), str(m))

            # C6: negative size
            await ws.send(json.dumps({
                "type": "transfer:upload", "transferId": "tr-up-neg",
                "seq": 0, "name": "neg.bin", "size": -5,
                "batchTotalBytes": 5, "targetIp": "127.0.0.1",
            }))
            m = await _recv_until(ws, lambda x: x.get("type") in ("error", "transfer:upload:ready"))
            ok("upload: negative size rejected",
               m.get("type") == "error" and "size" in str(m.get("error", "")).lower(), str(m))

            # C7: out-of-sequence announce
            await ws.send(json.dumps({
                "type": "transfer:upload", "transferId": "tr-up-seq",
                "seq": 1, "name": "s.bin", "size": 4,
                "batchTotalBytes": 8, "targetIp": "127.0.0.1",
            }))
            m = await _recv_until(ws, lambda x: x.get("type") in ("error", "transfer:upload:ready"))
            ok("upload: out-of-sequence announce rejected",
               m.get("type") == "error" and "sequence" in str(m.get("error", "")), str(m))

            # C8: oversized frame aborts session; same id can restart clean
            await ws.send(json.dumps({
                "type": "transfer:upload", "transferId": "tr-up-big",
                "seq": 0, "name": "t.bin", "size": 10,
                "batchTotalBytes": 10, "targetIp": "127.0.0.1",
            }))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:upload:ready", "error"))
            ready_ok = m.get("type") == "transfer:upload:ready"
            await ws.send(b"x" * 20)
            m = await _recv_until(ws, lambda x: x.get("type") in ("error", "transfer:upload:ready"))
            abort_ok = m.get("type") == "error"
            stage_gone = await _wait_gone(os.path.join(STAGING, "tr-up-big"))
            await ws.send(json.dumps({
                "type": "transfer:upload", "transferId": "tr-up-big",
                "seq": 0, "name": "t.bin", "size": 10,
                "batchTotalBytes": 10, "targetIp": "127.0.0.1",
            }))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:upload:ready", "error"))
            restart_ok = m.get("type") == "transfer:upload:ready"
            # clean the restarted session via cancel
            await ws.send(json.dumps({"type": "command:cancel",
                                      "transferId": "tr-up-big"}))
            m = await _recv_until(ws, lambda x: x.get("type") == "transfer:cancelled")
            cancel_ok = m.get("success") is True
            stage_gone = stage_gone and await _wait_gone(os.path.join(STAGING, "tr-up-big"))
            ok("upload: oversized frame aborts session, id restarts clean",
               ready_ok and abort_ok and restart_ok and cancel_ok and stage_gone,
               f"ready={ready_ok} abort={abort_ok} restart={restart_ok} "
               f"cancel={cancel_ok} staging={stage_gone}")

            # C10: cancel mid-transfer removes staged bytes
            await ws.send(json.dumps({
                "type": "transfer:upload", "transferId": "tr-up-can",
                "seq": 0, "name": "c.bin", "size": 100,
                "batchTotalBytes": 100, "targetIp": "127.0.0.1",
            }))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:upload:ready", "error"))
            ready_ok = m.get("type") == "transfer:upload:ready"
            await ws.send(b"y" * 50)
            await asyncio.sleep(0.2)
            await ws.send(json.dumps({"type": "command:cancel",
                                      "transferId": "tr-up-can"}))
            m = await _recv_until(ws, lambda x: x.get("type") == "transfer:cancelled")
            stage_gone = await _wait_gone(os.path.join(STAGING, "tr-up-can"))
            ok("upload: cancel mid-stream frees staging",
               ready_ok and m.get("success") is True and stage_gone,
               f"ready={ready_ok} cancelled={m.get('success')} staging={stage_gone}")

            # C11: disconnect mid-upload cleans staging (last on this socket)
            await ws.send(json.dumps({
                "type": "transfer:upload", "transferId": "tr-up-disc",
                "seq": 0, "name": "d.bin", "size": 100,
                "batchTotalBytes": 100, "targetIp": "127.0.0.1",
            }))
            m = await _recv_until(ws, lambda x: x.get("type") in ("transfer:upload:ready", "error"))
            ready_ok = m.get("type") == "transfer:upload:ready"
            await ws.send(b"z" * 10)
            await asyncio.sleep(0.2)
        stage_gone = await _wait_gone(os.path.join(STAGING, "tr-up-disc"))
        ok("upload: disconnect mid-upload cleans staging",
           ready_ok and stage_gone, f"ready={ready_ok} staging={stage_gone}")

        # No stray sessions anywhere
        ok("upload: staging root left empty",
           _staging_dirs() == set(), f"leftover={sorted(_staging_dirs())}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        shutil.rmtree(HOME_UP, ignore_errors=True)
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)

    return finish("t_upload")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        print(12)
        sys.exit(0)
    asyncio.get_event_loop().run_until_complete(run_upload_tests())
