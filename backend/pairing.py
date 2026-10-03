#!/usr/bin/env python3
"""Phase 0 pairing: one-time codes -> bearer tokens for LAN-mode clients.

Desktop (loopback) requests a code via the `pairing:generate` bridge message.
A remote client proves the code over its WS connection and receives a
32-byte token; every later connection authenticates with that token
(`auth`). Codes are single-use, expire after 5 minutes, and five wrong
attempts lock pairing out for 5 minutes. Only token *hashes* are persisted
(owner-only file), mirroring the relay template in backend/relay/server.py.
"""
import hashlib
import json
import os
import secrets
import socket
import time

# RFC 4648 base32 alphabet (32 symbols) — 8 chars = 40 bits of entropy
B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
CODE_LEN = 8
CODE_TTL = 300.0
MAX_FAILS = 5
LOCK_SECS = 300.0

FAIL_ERRORS = ("locked", "no_code", "expired", "bad_code")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def lan_ip() -> str:
    """Best-effort primary LAN address (UDP route lookup; sends no packets)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 80))  # TEST-NET: route lookup only
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def pair_qr(payload: str) -> str:
    """data: URL with an SVG QR of payload.

    Uses qrcode only for the module matrix and renders the SVG here so the
    backend does not need Pillow (qrcode's PIL image factory would).
    """
    import base64

    import qrcode

    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    h, w = len(matrix), len(matrix[0])
    path = "".join(
        f"M{x} {y}h1v1h-1z"
        for y, row in enumerate(matrix)
        for x, dark in enumerate(row)
        if dark
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"'
        ' shape-rendering="crispEdges">'
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>'
        f'<path d="{path}" fill="#000000"/></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


class PairingManager:
    def __init__(self, state_path: str):
        self.state_path = state_path
        self._state = {
            "codeHash": None,
            "codeExpires": 0.0,
            "fails": 0,
            "lockedUntil": 0.0,
            "tokens": {},
        }
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for key in ("codeHash", "codeExpires", "fails", "lockedUntil", "tokens"):
                        if key in data:
                            self._state[key] = data[key]
        except Exception:
            pass

    def _save(self):
        try:
            root = os.path.dirname(self.state_path)
            if root:
                os.makedirs(root, exist_ok=True, mode=0o700)
            fd = os.open(self.state_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(self._state, f)
            os.chmod(self.state_path, 0o600)
        except Exception:
            pass

    def generate(self, now: float = None, ttl: float = CODE_TTL) -> str:
        now = time.time() if now is None else now
        code = "".join(secrets.choice(B32) for _ in range(CODE_LEN))
        self._state["codeHash"] = _digest(code)
        self._state["codeExpires"] = now + ttl
        self._state["fails"] = 0
        self._save()
        return code

    def pair(self, code, now: float = None) -> str:
        """Return a fresh bearer token, or one of FAIL_ERRORS."""
        now = time.time() if now is None else now
        if self._state.get("lockedUntil", 0.0) > now:
            return "locked"
        stored = self._state.get("codeHash")
        if not stored:
            return "no_code"
        if now > float(self._state.get("codeExpires", 0.0)):
            self._state["codeHash"] = None
            self._save()
            return "expired"
        if not isinstance(code, str):
            return "bad_code"
        candidate = _digest(code.strip().upper())
        if not secrets.compare_digest(candidate, stored):
            fails = int(self._state.get("fails", 0)) + 1
            self._state["fails"] = fails
            if fails >= MAX_FAILS:
                self._state["lockedUntil"] = now + LOCK_SECS
                self._state["fails"] = 0
                self._state["codeHash"] = None  # kill the code as well
            self._save()
            return "locked" if self._state.get("lockedUntil", 0.0) > now else "bad_code"
        # success: single use
        self._state["codeHash"] = None
        self._state["codeExpires"] = 0.0
        self._state["fails"] = 0
        token = secrets.token_urlsafe(32)
        self._state.setdefault("tokens", {})[_digest(token)] = now
        self._save()
        return token

    def check_token(self, token, now: float = None) -> bool:
        if not isinstance(token, str) or not token:
            return False
        return _digest(token) in self._state.get("tokens", {})
