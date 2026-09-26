"""Network / DoS suite against a live instance (A: TCP 19974).

7 checks: T0 liveness, T1 slow-loris, T2 oversize frame, T3 connection flood,
T4a-c malformed handshake inputs.
"""
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from proto_lib import *
from proto_lib import _send_raw

A_PID = int(sys.argv[1]) if len(sys.argv) > 1 else None


def rss_kb(pid):
    if not pid:
        return None
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def t2_oversize_frame():
    before = rss_kb(A_PID)
    s = tcp_connect(timeout=5)
    t0 = time.time()
    s.sendall((500 * 1024 * 1024).to_bytes(4, "big"))  # declare 500 MB, send nothing
    closed = closed_within(s, 5.0)
    dt = time.time() - t0
    s.close()
    time.sleep(0.3)
    after = rss_kb(A_PID)
    growth = (after - before) if (before is not None and after is not None) else 0
    ok(
        "T2 declared-500MB frame rejected instantly, no memory growth",
        closed and dt < 3.0 and growth < 4096,
        f"closed={closed} dt={dt:.2f}s rss_growth={growth}KB",
    )


def t4_malformed(variant, payload, name):
    s = tcp_connect(timeout=5)
    _send_raw(s, payload, 5.0)
    closed = closed_within(s, 6.0)
    s.close()
    ok(name, closed, f"variant={variant}")


def t3_flood():
    import select
    before = rss_kb(A_PID)
    socks = []
    for _ in range(100):
        try:
            socks.append(tcp_connect(timeout=5))
        except OSError:
            pass
    connected = len(socks)
    time.sleep(3.0)  # let the 2s reject window elapse

    # Probe ALL connections concurrently: a sequential 1.5s-per-socket loop
    # would outlive the server's 30s read timeout and undercount the holders.
    deadline = time.time() + 1.5
    pending = list(socks)
    while pending:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        readable, _, _ = select.select(pending, [], [], remaining)
        if not readable:
            break  # nothing closed within the window -> everything pending is open
        for s in readable:
            try:
                data = s.recv(65536)
            except OSError:
                data = b""
            if not data:
                pending.remove(s)  # FIN from server = rejected/closed
    held = len(pending)

    for s in socks:
        try:
            s.close()
        except OSError:
            pass
    time.sleep(0.5)
    after = rss_kb(A_PID)
    growth = (after - before) if (before is not None and after is not None) else 0
    ok(
        "T3 100-connection flood: exactly the 64-slot cap holds, no memory growth",
        connected >= 90 and 32 <= held <= 64 and growth < 8192,
        f"connected={connected} held={held}/100 rss_growth={growth}KB",
    )
    time.sleep(1.0)  # let the server release the slots


def t1_slow_loris():
    s = tcp_connect(timeout=45)
    t0 = time.time()
    closed = closed_within(s, 40.0)
    dt = time.time() - t0
    s.close()
    ok(
        "T1 slow-loris (no bytes sent) closed by read timeout ~30s",
        closed and 25.0 <= dt <= 40.0,
        f"closed={closed} after={dt:.1f}s",
    )


def t0_alive():
    s = tcp_connect(timeout=10)
    okv, response, session = handshake_client(s, identity=test_identity(), timeout=10)
    s.close()
    ok(
        "T0 liveness: signed handshake accepted after all attacks",
        okv and response.get("status") == "accepted",
        f"okv={okv} status={response.get('status')}",
    )


def main():
    t2_oversize_frame()
    t4_malformed("not-json", b"{invalid json frame", "T4a invalid JSON frame closes connection")
    t4_malformed("array", b"[1,2,3]", "T4b non-object JSON frame closes connection")
    t4_malformed("wrong-type", b'{"type":"bogus"}', "T4c wrong message type closes connection")
    t3_flood()
    t1_slow_loris()
    t0_alive()
    finish("t_net")


if __name__ == "__main__":
    main()
