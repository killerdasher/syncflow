"""Phase 0 LAN mode + pairing auth — 23 checks.

Spawns two fresh backends:
  * LAN-mode instance  (SYNCFLOW_WS_HOST=0.0.0.0, WS 19993, TCP 19984)
  * default instance   (loopback bind, WS 19994, TCP 19985)

Covers: loopback default unchanged, opt-in LAN bind, unauthenticated remote
command rejection, pairing-code generation (local-only), wrong-code +
single-use + token issue, token auth on fresh sockets, bogus tokens,
Capacitor origin acceptance, and unit-level TTL/lockout/perms behaviour of
backend/pairing.py.
"""
import asyncio
import base64
import json
import os
import socket
import stat
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))  # backend/ for pairing module
from proto_lib import ok, finish  # noqa: E402
import pairing as pairing_mod  # noqa: E402


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

ART = "/tmp/opencode"
HOME_LAN = f"{ART}/sfLAN"
HOME_DEF = f"{ART}/sfLAN2"
WS_LAN, TCP_LAN = 19993, 19984
WS_DEF, TCP_DEF = 19994, 19985
PY = os.path.join(os.path.dirname(HERE), "venv", "bin", "python3")
if not os.path.exists(PY):
    PY = sys.executable


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


def _spawn(env_extra, log_path):
    env = {
        **os.environ,
        "SYNCFLOW_HOME": env_extra.pop("SYNCFLOW_HOME"),
        "SYNCFLOW_WS_PORT": str(env_extra.pop("SYNCFLOW_WS_PORT")),
        "SYNCFLOW_TCP_PORT": str(env_extra.pop("SYNCFLOW_TCP_PORT")),
        **env_extra,
    }
    log = open(log_path, "w")
    proc = subprocess.Popen(
        [PY, "-u", os.path.join(os.path.dirname(HERE), "main.py")],
        env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    return proc, log


def _connect(host, port, origin=None, timeout=5.0):
    websockets = __import__("websockets")
    kwargs = {"open_timeout": timeout}
    if origin is not None:
        kwargs["origin"] = origin
    return websockets.connect(f"ws://{host}:{port}", **kwargs)


async def _call(host, port, msg, expect, origin=None, timeout=6.0):
    """Connect, send one message, wait for a message of an expected type."""
    async with _connect(host, port, origin=origin) as ws:
        await ws.send(json.dumps(msg))
        deadline = time.time() + timeout
        while True:
            rem = deadline - time.time()
            if rem <= 0:
                raise TimeoutError(f"no {sorted(expect)} within {timeout}s")
            raw = await asyncio.wait_for(ws.recv(), rem)
            if not isinstance(raw, str):
                continue
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("type") in expect:
                return data


async def run_lan_tests():
    ips = lan_ips()
    lan_ip = ips[0] if ips else None

    # --- default instance: behaviour unchanged ----------------------------
    r = await _call("127.0.0.1", WS_DEF, {"type": "identity:get"}, {"identity:info"})
    ok("L1 default mode: loopback identity:get needs no auth",
       r.get("type") == "identity:info", f"type={r.get('type')}")

    refused = False
    if lan_ip:
        try:
            await asyncio.wait_for(_connect(lan_ip, WS_DEF).__aenter__(), 3.0)
        except Exception as e:
            refused = "refused" in str(e).lower() or "unreachable" in str(e).lower() \
                or isinstance(e, (ConnectionRefusedError, OSError))
    ok("L2 default mode: LAN-IP connect refused (loopback bind unchanged)",
       refused, f"lan_ip={lan_ip}")

    # --- LAN-mode instance ------------------------------------------------
    r = await _call("127.0.0.1", WS_LAN, {"type": "identity:get"}, {"identity:info"})
    ok("L3 LAN mode: loopback desktop still unauthenticated",
       r.get("type") == "identity:info", f"type={r.get('type')}")

    out = subprocess.run(["ss", "-ltn"], capture_output=True, text=True).stdout
    lan_bind = [l for l in out.splitlines() if f":{WS_LAN}" in l]
    ok("L4 LAN mode: WS bound to all interfaces (opt-in)",
       any("0.0.0.0" in l or "*:" in l or "[::]" in l for l in lan_bind),
       f"bind={lan_bind}")

    if not lan_ip:
        ok("L5-14 skipped: no non-loopback LAN IP", False, "lan_ips empty")
        return

    # unauthenticated remote reads
    r = await _call(lan_ip, WS_LAN, {"type": "identity:get"}, {"auth_required"})
    ok("L5 remote identity:get rejected before pairing",
       r.get("type") == "auth_required", f"type={r.get('type')}")

    r = await _call(lan_ip, WS_LAN, {"type": "pairing:generate"}, {"auth_required", "error"})
    ok("L6 remote pairing:generate also gated (codes are local-only)",
       r.get("type") == "auth_required", f"type={r.get('type')}")

    # code generation from loopback
    r = await _call("127.0.0.1", WS_LAN, {"type": "pairing:generate"}, {"pairing:code"})
    code = r.get("code", "")
    ok("L7 desktop pairing:generate returns an 8-char code",
       isinstance(code, str) and len(code) == 8, f"code_len={len(code) if code else 0}")

    # companion-facing payload: QR + endpoint metadata for the Phase 1 shim
    qr = r.get("qr", "")
    ok("L7b pairing:code carries an SVG QR data URL",
       isinstance(qr, str) and qr.startswith("data:image/svg+xml;base64,"),
       f"qr_prefix={qr[:30] if isinstance(qr, str) else type(qr).__name__}")
    try:
        svg = base64.b64decode(qr.split(",", 1)[1], validate=True).decode("utf-8")
    except Exception:
        svg = ""
    ok("L7c QR decodes to an SVG with modules",
       "<svg" in svg and 'viewBox="0 0' in svg and "<path" in svg,
       f"svg_len={len(svg)}")
    ok("L7d endpoint metadata (ttl, host, port, lanMode)",
       r.get("expiresIn") == 300
       and isinstance(r.get("host"), str)
       and bool(r.get("host"))
       and r.get("port") == WS_LAN
       and r.get("lanMode") is True,
       f"expiresIn={r.get('expiresIn')} host={r.get('host')!r} "
       f"port={r.get('port')} lanMode={r.get('lanMode')}")

    # wrong code
    r = await _call(lan_ip, WS_LAN, {"type": "pairing", "code": "ZZZZZZZZ"}, {"pair_fail"})
    ok("L8 wrong pairing code rejected",
       r.get("type") == "pair_fail" and r.get("error") in ("bad_code", "locked"),
       f"resp={r}")

    # correct code -> token
    r = await _call(lan_ip, WS_LAN, {"type": "pairing", "code": code}, {"pair_ok", "pair_fail"})
    token = r.get("token", "")
    ok("L9 correct code issues a bearer token",
       r.get("type") == "pair_ok" and isinstance(token, str) and len(token) >= 32,
       f"type={r.get('type')} token_len={len(token) if token else 0}")

    r = await _call(lan_ip, WS_LAN, {"type": "pairing", "code": code}, {"pair_fail"})
    ok("L10 code is single-use (replay fails)",
       r.get("type") == "pair_fail", f"resp={r}")

    # token auth on a fresh socket + full command access
    async with _connect(lan_ip, WS_LAN) as ws:
        await ws.send(json.dumps({"type": "auth", "token": token}))
        raw = json.loads(await asyncio.wait_for(ws.recv(), 6.0))
        ok("L11 fresh socket authenticates with the token",
           raw.get("type") == "auth_ok", f"resp={raw}")
        await ws.send(json.dumps({"type": "identity:get"}))
        raw = json.loads(await asyncio.wait_for(ws.recv(), 6.0))
        ok("L12 authenticated remote may send commands",
           raw.get("type") == "identity:info", f"resp={raw}")

    r = await _call(lan_ip, WS_LAN,
                    {"type": "auth", "token": "made-up-token-attacker"}, {"auth_fail"})
    ok("L13 forged token rejected", r.get("type") == "auth_fail", f"resp={r}")

    # Capacitor origin: handshake accepted, auth still required
    r = await _call(lan_ip, WS_LAN, {"type": "identity:get"}, {"auth_required"},
                    origin="capacitor://localhost")
    ok("L14 Capacitor origin accepted at handshake (auth still required)",
       r.get("type") == "auth_required", f"resp={r}")

    # pairing.json owner-only on disk
    ppath = os.path.join(HOME_LAN, "pairing.json")
    if os.path.exists(ppath):
        mode = stat.S_IMODE(os.stat(ppath).st_mode)
        ok("L15 pairing.json owner-only (0600)",
           not (mode & 0o077), f"mode={oct(mode)}")
    else:
        ok("L15 pairing.json owner-only (0600)", False, "file missing")


def run_unit_tests():
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="sfPair-")
    try:
        state = os.path.join(tmp, "pairing.json")
        pm = pairing_mod.PairingManager(state)

        # TTL expiry
        pm.generate(now=1000.0, ttl=5.0)
        err = pm.pair("SHOULDFAIL", now=1006.0)
        ok("L16 unit: expired code refused", err == "expired", f"err={err}")

        # lockout after 5 wrong attempts
        pm2 = pairing_mod.PairingManager(os.path.join(tmp, "p2.json"))
        code = pm2.generate(now=1000.0, ttl=300.0)
        results = [pm2.pair("ZZZZZZZZ", now=1000.0 + i) for i in range(5)]
        ok("L17 unit: 5 wrong codes lock pairing out",
           results[-1] == "locked" and all(r in ("bad_code", "locked") for r in results),
           f"results={results}")
        # even the correct code is refused while locked
        err = pm2.pair(code, now=1010.0)
        ok("L18 unit: correct code refused during lockout",
           err == "locked", f"err={err}")

        # token round-trip + fresh manager reload (persistence)
        pm3 = pairing_mod.PairingManager(os.path.join(tmp, "p3.json"))
        code3 = pm3.generate(now=2000.0, ttl=300.0)
        token = pm3.pair(code3, now=2001.0)
        ok("L19 unit: token issued and verified",
           isinstance(token, str) and len(token) >= 32 and pm3.check_token(token),
           f"token_len={len(token) if isinstance(token, str) else 0}")
        reloaded = pairing_mod.PairingManager(os.path.join(tmp, "p3.json"))
        ok("L20 unit: token survives restart, raw token not stored",
           reloaded.check_token(token)
           and token not in open(os.path.join(tmp, "p3.json")).read(),
           "reloaded ok")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    _free_ports(WS_LAN, TCP_LAN, WS_DEF, TCP_DEF)
    for d in (HOME_LAN, HOME_DEF):
        subprocess.run(["rm", "-rf", d])

    proc_def, log_def = _spawn(
        {
            "SYNCFLOW_HOME": HOME_DEF,
            "SYNCFLOW_WS_PORT": WS_DEF,
            "SYNCFLOW_TCP_PORT": TCP_DEF,
            "SYNCFLOW_WS_HOST": "",  # explicit: default loopback even if exported
        },
        f"{ART}/lan-def.log",
    )
    proc_lan, log_lan = _spawn(
        {
            "SYNCFLOW_HOME": HOME_LAN,
            "SYNCFLOW_WS_PORT": WS_LAN,
            "SYNCFLOW_TCP_PORT": TCP_LAN,
            "SYNCFLOW_WS_HOST": "0.0.0.0",
        },
        f"{ART}/lan-mode.log",
    )
    try:
        _wait_port(WS_DEF, proc_def)
        _wait_port(WS_LAN, proc_lan)
        time.sleep(4)  # mDNS settle parity with run_all
        asyncio.run(run_lan_tests())
        run_unit_tests()
    finally:
        for proc in (proc_def, proc_lan):
            try:
                proc.terminate()
                proc.wait(timeout=8)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        _free_ports(WS_LAN, TCP_LAN, WS_DEF, TCP_DEF)

    finish("t_lan_auth")
