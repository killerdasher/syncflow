"""Portable backend smoke test (Linux/macOS/Windows CI).

Starts a fresh backend instance with isolated ports/home, waits for the
SYNCFLOW_PORT banner, performs a WebSocket chat:history round-trip, tears down.
Exit 0 = pass. Complements the full POSIX suite in run_all.sh (Linux only).
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def main() -> int:
    ws_port, tcp_port = free_port(), free_port()
    home = tempfile.mkdtemp(prefix="sfsmoke_")
    env = dict(
        os.environ,
        SYNCFLOW_HOME=home,
        SYNCFLOW_WS_PORT=str(ws_port),
        SYNCFLOW_TCP_PORT=str(tcp_port),
        PYTHONUNBUFFERED="1",
    )
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    frozen = os.environ.get("SYNCFLOW_SMOKE_FROZEN")
    if frozen:
        frozen = os.path.abspath(frozen)
        cmd = [frozen]
        print(f"SMOKE target: frozen backend {frozen}", flush=True)
    else:
        cmd = [sys.executable, "main.py"]
    proc = subprocess.Popen(
        cmd,
        cwd=backend_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    started = False
    deadline = time.time() + 45
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        print(line, end="", flush=True)
        if "SYNCFLOW_PORT:" in line:
            started = True
            break
    if not started or proc.poll() is not None:
        print("SMOKE FAIL: backend did not start", flush=True)
        proc.kill()
        return 1

    try:
        import websockets

        async with websockets.connect(f"ws://127.0.0.1:{ws_port}", open_timeout=10) as ws:
            await ws.send(json.dumps({"type": "chat:history"}))
            resp = await asyncio.wait_for(ws.recv(), 10)
            if "chat:history" not in resp:
                print(f"SMOKE FAIL: unexpected WS response: {resp[:200]}", flush=True)
                return 1
    except Exception as e:
        print(f"SMOKE FAIL: WS round-trip error: {type(e).__name__}: {e}", flush=True)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("SMOKE OK: backend start + WS chat:history round-trip", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
