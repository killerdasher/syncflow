"""Active MITM suite: protocol-aware proxy in front of live B (TCP 19975).

The proxy listens on 127.0.0.1:19976 and forwards to B in three modes:
  forward      - byte copy (records full capture)
  flip         - flips one ciphertext byte of the first chunk
  substitute   - swaps the responder's signing key with an attacker key

Client identity note: all local clients share B's single TOFU pin slot
(pinned by source IP 127.0.0.1), so this suite uses instance A's identity
keys - the same key A's own engine uses when it later talks to B.

5 checks: M1 end-to-end through proxy, M2 zero-plaintext capture,
M3 bit-flip tamper detection, M4 responder identity substitution,
M5 TOFU pin-change rejection.
"""
import asyncio
import json
import os
import select
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proto_lib import *

MARKER = b"SYNFLOW_SECRET_PAYLOAD_"
ATTACKER = None


def attacker_identity():
    return test_identity("sfATK")


class MITMProxy(threading.Thread):
    def __init__(self, mode="forward"):
        super().__init__(daemon=True)
        self.mode = mode
        self.capture = bytearray()
        self._stop = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((HOST, TCP_MITM))
        self.sock.listen(8)
        self.sock.settimeout(0.5)

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass

    def run(self):
        while not self._stop.is_set():
            try:
                client, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve_conn, args=(client,), daemon=True).start()

    def _transform(self, direction, payload, state):
        mode = self.mode
        if mode == "forward":
            return payload
        if mode == "flip" and direction == "c2s":
            state["c2s"] += 1
            if state["c2s"] == 5:  # offer, meta, file_meta, header-frame, chunk
                b = bytearray(payload)
                b[-1] ^= 0x01
                return bytes(b)
            return payload
        if mode == "substitute" and direction == "s2c":
            state["s2c"] += 1
            if state["s2c"] == 1:  # the e2e_accept frame
                try:
                    orig = json.loads(payload)
                    att = attacker_identity()
                    ts = orig.get("timestamp")
                    eph = orig.get("ephemeralPub")
                    new_pub = att.signing_pub_b64
                    header = f"{new_pub}:{eph}:{ts}"
                    orig["signingPub"] = new_pub
                    orig["signature"] = att.sign(header.encode())
                    return json.dumps(orig).encode()
                except Exception:
                    return payload
            return payload
        return payload

    def _pump(self, src, dst, direction, state):
        """Copy one direction with frame-aware transforms. Returns on EOF."""
        buf = b""
        while not self._stop.is_set():
            try:
                readable, _, _ = select.select([src], [], [], 0.5)
                if not readable:
                    continue
                data = src.recv(65536)
            except OSError:
                return
            if not data:
                return
            if self.mode == "forward":
                self.capture.extend(data)
                try:
                    dst.sendall(data)
                except OSError:
                    return
                continue
            buf += data
            while len(buf) >= 4:
                n = int.from_bytes(buf[:4], "big")
                if n <= 0 or n > 4 * 1024 * 1024:
                    return  # malformed - drop the tunnel
                if len(buf) < 4 + n:
                    break
                payload = buf[4:4 + n]
                buf = buf[4 + n:]
                new_payload = self._transform(direction, payload, state)
                try:
                    dst.sendall(len(new_payload).to_bytes(4, "big") + new_payload)
                except OSError:
                    return

    # NOTE: must not be named _handle — Thread.__init__ assigns
    # self._handle = _ThreadHandle() in Python 3.13, shadowing a method
    # with that name on any Thread subclass.
    def _serve_conn(self, client):
        client.settimeout(30)
        try:
            backend = socket.create_connection((HOST, TCP_B), timeout=10)
        except OSError:
            client.close()
            return
        backend.settimeout(30)
        state = {"c2s": 0, "s2c": 0}
        t1 = threading.Thread(target=self._pump, args=(client, backend, "c2s", state), daemon=True)
        t2 = threading.Thread(target=self._pump, args=(backend, client, "s2c", state), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        for s in (client, backend):
            try:
                s.close()
            except OSError:
                pass


def setup():
    wipe("sfM")
    wipe("sfATK")
    data = asyncio.run(ws_settings(WS_B, autoAccept=True, downloadPath=DEST_B))
    if data.get("type") != "settings:applied":
        print(f"FATAL: B settings failed: {data}", flush=True)
        sys.exit(2)
    clean_dir(DEST_B)
    write_file(f"{ART}/mitm-secret-payload.txt",
               MARKER + os.urandom(100 * 1024 - len(MARKER)))
    write_file(f"{ART}/mitm-flip.bin", os.urandom(80 * 1024))
    write_file(f"{ART}/mitm-sub.bin", b"substitute identity payload")


def m1_m2_forward_and_capture(proxy):
    r = send_transfer(
        [{"path": f"{ART}/mitm-secret-payload.txt", "wire": "mitm-secret-payload.txt"}],
        target_port=TCP_MITM,
        identity=test_identity("sfA"),
        trust=trust_for("sfM"),
    )
    dest = os.path.join(DEST_B, "mitm-secret-payload.txt")
    ok(
        "M1 transfer completes end-to-end through active proxy",
        r.outcome == "completed" and os.path.exists(dest)
        and file_sha(dest) == file_sha(f"{ART}/mitm-secret-payload.txt"),
        f"outcome={r.outcome} err={r.error}",
    )
    blob = bytes(proxy.capture)
    leaked = (MARKER in blob) or (b"mitm-secret-payload" in blob)
    ok(
        "M2 full MITM capture contains zero plaintext (name/payload)",
        len(blob) > 1000 and not leaked,
        f"captured={len(blob)}B leaked={leaked}",
    )


def m3_bitflip(proxy):
    proxy.mode = "flip"
    r = send_transfer(
        [{"path": f"{ART}/mitm-flip.bin", "wire": "mitm-flip.bin"}],
        target_port=TCP_MITM,
        identity=test_identity("sfA"),
        trust=trust_for("sfM"),
    )
    dest = os.path.join(DEST_B, "mitm-flip.bin")
    ok(
        "M3 MITM bit-flip in transit -> authentication failure, no file",
        r.outcome == "integrity_failed" and "authentication" in (r.error or "")
        and not os.path.exists(dest),
        f"outcome={r.outcome} err={r.error}",
    )


def m4_substitute_identity(proxy):
    proxy.mode = "substitute"
    r = send_transfer(
        [{"path": f"{ART}/mitm-sub.bin", "wire": "mitm-sub.bin"}],
        target_port=TCP_MITM,
        identity=test_identity("sfA"),
        trust=trust_for("sfM"),
    )
    ok(
        "M4 MITM swaps responder signing key -> client refuses (TOFU pin)",
        r.outcome == "pin_changed" and "CHANGED" in (r.error or ""),
        f"outcome={r.outcome} err={r.error}",
    )
    proxy.mode = "forward"


def m5_pin_change_direct(proxy):
    proxy.stop()
    time.sleep(0.3)
    r = send_transfer(
        [{"path": f"{ART}/mitm-sub.bin", "wire": "direct-pin.bin"}],
        target_port=TCP_A,
        identity=test_identity("sfOTHER"),
        trust=trust_for("sfOTHER"),
    )
    ok(
        "M5 second identity from a pinned address rejected server-side",
        r.outcome in ("handshake_failed", "pin_changed", "conn_error"),
        f"outcome={r.outcome} err={r.error}",
    )


def main():
    global ATTACKER
    setup()
    proxy = MITMProxy("forward")
    proxy.start()
    try:
        time.sleep(0.3)
        m1_m2_forward_and_capture(proxy)
        m3_bitflip(proxy)
        m4_substitute_identity(proxy)
        m5_pin_change_direct(proxy)
    finally:
        proxy.stop()
    asyncio.run(ws_call(WS_B, {"type": "identity:get"}, {"identity:info"}, timeout=5))
    finish("mitm2")


if __name__ == "__main__":
    main()
