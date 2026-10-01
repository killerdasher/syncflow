"""Shared helpers for the SyncFlow security suites (real live instances).

Run from anywhere: sys.path points at the backend package next to tests/.
"""
import asyncio
import json
import os
import socket
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from crypto.blockchain import TransferChain, sha256_str
from crypto.e2e import (
    DeviceIdentityKeys,
    PeerTrustStore,
    handshake_complete,
    handshake_offer,
)

ART = "/tmp/opencode"
os.makedirs(ART, exist_ok=True)

HOST = "127.0.0.1"
TCP_A, TCP_B, TCP_MITM = 19974, 19975, 19976
# Deliberately off the app's defaults (18973/18974/18975) so a running
# SyncFlow instance never collides with the test instances.
WS_A, WS_B = 18993, 18995

# Portable (CI-safe): derive from the invoking user's home
HOME_DIR = os.path.realpath(os.path.expanduser("~"))
DEST_A = os.path.join(HOME_DIR, "Downloads", "SyncFlow-testA")
DEST_B = os.path.join(HOME_DIR, "Downloads", "SyncFlow-testB")

CHUNK = 65536
JSON_MAX = 256 * 1024
FRAME_BLOB = 16 * 1024
CHUNK_BLOB = CHUNK + 64
META_BLOB = 256 * 1024

_results = []


def ok(name, cond, detail=""):
    cond = bool(cond)
    _results.append((name, cond))
    line = ("PASS " if cond else "FAIL ") + name
    if detail:
        line += f"  [{detail}]"
    print(line, flush=True)
    return cond


def finish(label):
    p = sum(1 for _, c in _results if c)
    f = len(_results) - p
    print(f'RESULTS_JSON: {{"suite": "{label}", "pass": {p}, "fail": {f}}}', flush=True)
    sys.exit(0 if f == 0 else 1)


# ---------------------------------------------------------------- sockets

def tcp_connect(host=HOST, port=TCP_A, timeout=10.0):
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    return s


def _send_raw(s, raw: bytes, timeout=10.0):
    s.settimeout(timeout)
    s.sendall(len(raw).to_bytes(4, "big") + raw)


def send_frame(s, obj: dict, timeout=10.0):
    _send_raw(s, json.dumps(obj).encode(), timeout)


def send_blob(s, blob: bytes, timeout=10.0):
    _send_raw(s, blob, timeout)


def _recv_exact(s, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("peer closed")
        buf += chunk
    return bytes(buf)


def recv_raw(s, max_len, timeout=10.0) -> bytes:
    s.settimeout(timeout)
    hdr = _recv_exact(s, 4)
    n = int.from_bytes(hdr, "big")
    if n <= 0 or n > max_len:
        raise ValueError(f"frame size {n} out of range (max {max_len})")
    return _recv_exact(s, n)


def recv_json(s, timeout=10.0, max_len=JSON_MAX):
    raw = recv_raw(s, max_len, timeout)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("message must be a JSON object")
    return data


def closed_within(s, timeout) -> bool:
    s.settimeout(timeout)
    try:
        return s.recv(1) == b""
    except socket.timeout:
        return False
    except OSError:
        return True


def decrypt_json(session, blob) -> dict:
    data = json.loads(session.decrypt(blob))
    if not isinstance(data, dict):
        raise ValueError("decrypted payload is not an object")
    return data


# ---------------------------------------------------------------- files

def sanitize_filename(name: str) -> str:
    name = str(name).replace("\\", "/")
    name = name.split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable())
    name = name.strip().lstrip(".").strip()
    if not name or name in (".", ".."):
        name = "file"
    stem, ext = os.path.splitext(name)
    reserved = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
    if stem.lower() in reserved:
        name = "_" + name
    if len(name) > 200:
        stem, ext = os.path.splitext(name)
        name = stem[:180] + ext[:20]
    return name


def clean_dir(d):
    os.makedirs(d, exist_ok=True)
    for entry in os.listdir(d):
        p = os.path.join(d, entry)
        try:
            if os.path.isfile(p):
                os.unlink(p)
        except OSError:
            pass


def write_file(path, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def file_sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- identity

def test_identity(sub="sfT"):
    return DeviceIdentityKeys(os.path.join(ART, sub, "identity"))


def trust_for(sub="sfT"):
    return PeerTrustStore(os.path.join(ART, sub, "peers.json"))


def wipe(sub):
    import shutil
    shutil.rmtree(os.path.join(ART, sub), ignore_errors=True)


# ---------------------------------------------------------------- handshake

def handshake_client(s, identity, record=None, backdate=None, tamper_sig=False, timeout=10.0):
    """Perform the offer/accept exchange on an open socket.

    Returns (ok, response, session). record(raw_bytes) captures the raw
    server->client accept frame (for leak checks).
    """
    offer, session = handshake_offer(identity)
    offer["security"] = "e2e-blockchain-v1"
    if backdate:
        offer["timestamp"] -= backdate
    if tamper_sig:
        sig = offer["signature"]
        offer["signature"] = ("A" if sig[:1] != "A" else "B") + sig[1:]
    send_frame(s, offer, timeout)
    raw = recv_raw(s, JSON_MAX, timeout)
    if record:
        record(raw)
    response = json.loads(raw)
    if not isinstance(response, dict):
        return False, {}, session
    okv = handshake_complete(identity, response, session, initiator=True)
    return okv, response, session


class SenderResult(dict):
    """dict with attribute access for convenience."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            return None


def send_transfer(
    files,
    target_host=HOST,
    target_port=TCP_A,
    transfer_id=None,
    sender_name="Sender",
    identity=None,
    trust=None,
    expected_device_id=None,
    backdate_offer=None,
    tamper_offer_sig=False,
    tamper_chunk=None,            # (file_index, chunk_index) -> flip ciphertext byte
    chunk_signer_identity=None,
    header_name=None,             # sign block headers under a different file name
    declared_sizes=None,          # {file_index: size_declared_in_meta}
    record_recv=None,             # callable(raw) on every server->client frame
    decision_timeout=90.0,
    stream_timeout=30.0,
    send_complete=True,
    dest_folder=None,             # optional sync-folder name (receiver maps it)
):
    """Mirror of the hardened engine sender, with attack hooks.

    files: list of {"path": local file, "wire": attacker-chosen wire name}
    """
    identity = identity or test_identity()
    trust = trust if trust is not None else trust_for()
    transfer_id = transfer_id or f"t-{uuid.uuid4().hex[:16]}"
    declared_sizes = declared_sizes or {}
    res = SenderResult(outcome="error", error="", transfer_id=transfer_id, stage="connect")

    s = None
    try:
        s = tcp_connect(target_host, target_port, timeout=10.0)

        res.stage = "handshake"
        okv, response, session = handshake_client(
            s, identity, record=record_recv,
            backdate=backdate_offer, tamper_sig=tamper_offer_sig,
        )
        if not okv:
            res.update(outcome="handshake_failed", error="response signature/freshness invalid")
            return res
        if record_recv:
            pass  # already recorded accept frame

        if expected_device_id:
            res.stage = "device_id"
            actual = sha256_str(str(response.get("signingPub", "")))[:32]
            if actual != expected_device_id:
                res.update(outcome="device_id_mismatch",
                           error="Peer identity does not match the selected device (possible MITM)")
                return res

        res.stage = "pin"
        pin_ok, pin_why = trust.check(
            f"{target_host}:{target_port}", str(response.get("signingPub", ""))
        )
        if not pin_ok:
            res.update(outcome="pin_changed", error=str(pin_why))
            return res

        if response.get("status") != "accepted":
            res.update(outcome="rejected", error=str(response.get("error", "Transfer rejected")))
            return res

        res.stage = "meta"
        meta = {
            "kind": "transfer",
            "transferId": transfer_id,
            "senderName": sender_name,
            "files": [
                {
                    # raw wire name: the RECEIVER must sanitize it (we test that)
                    "name": os.path.basename(f["wire"]),
                    "size": declared_sizes.get(i, os.path.getsize(f["path"])),
                }
                for i, f in enumerate(files)
            ],
        }
        if dest_folder:
            meta["destFolder"] = dest_folder
        send_blob(s, session.encrypt(json.dumps(meta).encode()), stream_timeout)

        res.stage = "decision"
        raw = recv_raw(s, META_BLOB, decision_timeout)
        if record_recv:
            record_recv(raw)
        decision = decrypt_json(session, raw)
        if decision.get("status") != "accepted":
            res.update(
                outcome="declined",
                error=str(decision.get("error") or "Transfer declined by receiver"),
                reason=str(decision.get("reason", "user")),
            )
            return res

        signer = chunk_signer_identity or identity
        for i, f in enumerate(files):
            res.stage = f"file{i}"
            path = f["path"]
            size = os.path.getsize(path)
            declared = declared_sizes.get(i, size)
            canon = sanitize_filename(os.path.basename(f["wire"]))

            send_blob(
                s,
                session.encrypt(json.dumps({
                    "type": "file_meta", "name": canon, "size": declared,
                }).encode()),
                stream_timeout,
            )

            chain = TransferChain(transfer_id, header_name or canon, signer.signing_pub_b64)
            idx = 0
            with open(path, "rb") as fh:
                while True:
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    block = chain.append_chunk(chunk, signer=signer)
                    frame = {"header": block.header(), "sig": block.signature}
                    enc_frame = session.encrypt(json.dumps(frame).encode())
                    enc_chunk = session.encrypt(chunk)
                    if tamper_chunk == (i, idx):
                        b = bytearray(enc_chunk)
                        b[-1] ^= 0x01
                        enc_chunk = bytes(b)
                    send_blob(s, enc_frame, stream_timeout)
                    send_blob(s, enc_chunk, stream_timeout)
                    idx += 1

            send_blob(s, session.encrypt(json.dumps(chain.wire_manifest()).encode()), stream_timeout)

            raw = recv_raw(s, META_BLOB, stream_timeout)
            if record_recv:
                record_recv(raw)
            ack = decrypt_json(session, raw)
            if not ack.get("verified"):
                res.update(outcome="integrity_failed", error=str(ack.get("reason", "verification failed")))
                return res

        if send_complete:
            res.stage = "complete"
            send_blob(
                s,
                session.encrypt(json.dumps({"type": "transfer_complete", "verified": True}).encode()),
                stream_timeout,
            )
        res.update(outcome="completed", error="")
        return res

    except (ConnectionError, OSError) as e:
        if res.stage == "handshake":
            res.update(outcome="handshake_failed", error=f"peer closed: {e}")
        else:
            res.update(outcome="conn_error", error=f"{res.stage}: {e}")
        return res
    except ValueError as e:
        res.update(outcome="error", error=f"{res.stage}: {e}")
        return res
    finally:
        if s:
            try:
                s.close()
            except OSError:
                pass


def raw_chat(text, target_host=HOST, target_port=TCP_A, identity=None, sender_name="ChatBot", timeout=10.0):
    identity = identity or test_identity()
    s = None
    try:
        s = tcp_connect(target_host, target_port, timeout=10.0)
        okv, response, session = handshake_client(s, identity, timeout=timeout)
        if not okv or response.get("status") != "accepted":
            return {"ok": False, "error": "handshake failed"}
        meta = {"kind": "chat", "text": text, "fromDevice": sender_name, "ts": time.time()}
        send_blob(s, session.encrypt(json.dumps(meta).encode()), timeout)
        raw = recv_raw(s, META_BLOB, timeout)
        return decrypt_json(session, raw)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        if s:
            try:
                s.close()
            except OSError:
                pass


# ---------------------------------------------------------------- websocket

def _ws_mod():
    import websockets
    return websockets


class WSConn:
    def __init__(self, port, origin=None, max_size=2_000_000):
        self.port = port
        self.origin = origin
        self.max_size = max_size
        self.ws = None

    async def __aenter__(self):
        websockets = _ws_mod()
        kwargs = {"max_size": self.max_size}
        if self.origin is not None:
            kwargs["origin"] = self.origin
        self.ws = await websockets.connect(f"ws://127.0.0.1:{self.port}", **kwargs)
        return self

    async def __aexit__(self, *exc):
        try:
            await self.ws.close()
        except Exception:
            pass

    async def send(self, msg: dict):
        await self.ws.send(json.dumps(msg))

    async def wait(self, expect, timeout=8.0):
        if isinstance(expect, str):
            expect = {expect}
        deadline = time.time() + timeout
        while True:
            rem = deadline - time.time()
            if rem <= 0:
                raise TimeoutError(f"no {sorted(expect)} within {timeout}s")
            raw = await asyncio.wait_for(self.ws.recv(), rem)
            if not isinstance(raw, str):
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("type") in expect:
                return data

    async def try_wait(self, expect, timeout=8.0):
        try:
            return await self.wait(expect, timeout)
        except (TimeoutError, asyncio.TimeoutError, asyncio.CancelledError):
            return None


async def ws_call(port, msg, expect, timeout=8.0, origin=None):
    async with WSConn(port, origin=origin) as ws:
        await ws.send(msg)
        return await ws.wait(expect, timeout)


async def ws_settings(port, **settings):
    return await ws_call(
        port, {"type": "settings:apply", **settings},
        {"settings:applied", "error"}, timeout=6,
    )


async def wait_device(ws, device_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        await ws.send({"type": "devices:list"})
        data = await ws.wait({"devices:update"}, timeout=5)
        for dev in data.get("devices", []):
            if dev.get("id") == device_id:
                return dev
        await asyncio.sleep(1.0)
    raise TimeoutError(f"device {device_id[:12]} not discovered within {timeout}s")


async def wait_awaiting(ws, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        await ws.send({"type": "transfers:list"})
        data = await ws.wait({"transfers:update"}, timeout=4)
        for t in data.get("active", []):
            if t.get("status") == "awaiting":
                return t
    raise TimeoutError("no transfer entered 'awaiting' state")


async def wait_completed_status(ws, transfer_id, statuses=("completed", "failed", "cancelled"), timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        await ws.send({"type": "transfers:list"})
        data = await ws.wait({"transfers:update"}, timeout=4)
        for t in data.get("completed", []):
            if t.get("id") == transfer_id and t.get("status") in statuses:
                return t
        for t in data.get("active", []):
            if t.get("id") == transfer_id and t.get("status") in statuses:
                return t
        await asyncio.sleep(0.1)
    raise TimeoutError(f"transfer {transfer_id} never reached {statuses}")
