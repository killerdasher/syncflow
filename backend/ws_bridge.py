import asyncio
import json
import os
from typing import Optional, Set, Callable, Any
from websockets.server import serve

from pairing import CODE_TTL, lan_ip, pair_qr
from upload import UPLOAD_JSON_TYPES
from download import DOWNLOAD_JSON_TYPES

# Browser-enforced origins only: file:// pages report the string "null",
# the Vite dev server reports its localhost origin. Cross-origin browser
# pages (evil.example.com) are rejected at handshake time. Non-browser
# clients (None) are allowed — they can't be held to Origin anyway and
# the TCP port is protected by E2E encryption. Capacitor/localhost entries
# cover the Phase 1+ mobile companion webview (origin is NOT the auth
# mechanism — pairing codes/tokens are).
ALLOWED_ORIGINS = [
    "null",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://[::1]:5173",
    "capacitor://localhost",
    "http://localhost",
    "https://localhost",
    None,
]

MAX_WS_MESSAGE = 1_048_576  # bytes


def _san(value, limit: int = 200) -> str:
    text = "" if value is None else str(value)
    return "".join(ch for ch in text if ch.isprintable())[:limit]


class WebSocketBridge:
    def __init__(self, port: int = 18973, host: Optional[str] = None):
        self.port = port
        # Phase 0 LAN mode: SYNCFLOW_WS_HOST opts the control plane into a
        # non-loopback bind; remote peers must pair (code -> token) first.
        # Default (unset/empty) stays loopback-only, exactly as before.
        env_host = os.environ.get("SYNCFLOW_WS_HOST", "").strip()
        self.host = host or env_host or "127.0.0.1"
        self.lan_mode = self.host not in ("127.0.0.1", "::1")
        self.pairing = None  # set by set_pairing(); fail-closed if absent
        self.upload = None   # set by set_upload(); Phase 3 chunked uploads
        self.download = None  # set by set_download(); Phase 3 chunked downloads
        self.clients: Set = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._handlers: dict[str, Callable] = {}

    def set_pairing(self, manager):
        self.pairing = manager

    def set_upload(self, manager):
        self.upload = manager

    def set_download(self, manager):
        self.download = manager

    def on(self, message_type: str, handler: Callable):
        self._handlers[message_type] = handler

    async def start(self):
        self.loop = asyncio.get_event_loop()
        self._server = await serve(
            self._handle_client,
            self.host,
            self.port,
            origins=ALLOWED_ORIGINS,
            max_size=MAX_WS_MESSAGE,
            ping_interval=20,
            ping_timeout=20,
        )
        print(f"SYNCFLOW_PORT:{self.port}", flush=True)
        print(f"WebSocket bridge listening on ws://{self.host}:{self.port}", flush=True)
        if self.lan_mode:
            print(
                "LAN mode: non-loopback clients must pair — run pairing:generate "
                "on this machine, then the client sends pairing/auth",
                flush=True,
            )
        await asyncio.Future()

    async def _handle_client(self, ws):
        self.clients.add(ws)
        peer = "?"
        try:
            peer = ws.remote_address[0] if ws.remote_address else "?"
        except Exception:
            pass
        is_local = peer in ("127.0.0.1", "::1", "::ffff:127.0.0.1") or str(peer).startswith("127.")
        # Loopback (the desktop renderer) and default-mode connections are
        # trusted as today; LAN-mode remote peers start unauthenticated.
        authed = is_local or not self.lan_mode
        print(f"Electron client connected ({len(self.clients)} total) peer={peer}", flush=True)

        try:
            async for message in ws:
                # Phase 3: raw binary frames are upload payload. They carry
                # no type field, so they are routed before JSON parsing and
                # only ever reach an authenticated client's staging session.
                if isinstance(message, (bytes, bytearray)):
                    if not authed:
                        await self._safe_send(
                            ws,
                            {"type": "auth_required",
                             "error": "pairing required: send pairing:generate from the desktop, then pairing/auth"},
                        )
                    elif self.download is not None and self.download.is_active(ws):
                        # Downloading is read-only: client binary frames are
                        # a protocol violation while a stream is pushing.
                        await self._safe_send(
                            ws, {"type": "error", "error": "unexpected binary frame during download"},
                        )
                    elif self.upload is not None:
                        await self.upload.on_chunk(ws, bytes(message))
                    continue

                # Robustness: malformed input never kills the connection.
                # ValueError (the base of JSONDecodeError/UnicodeDecodeError)
                # also covers e.g. Python's int-digit conversion limit on
                # absurdly large numbers — found by t_fuzz F2.
                try:
                    data = json.loads(message)
                except ValueError:
                    await self._safe_send(ws, {"type": "error", "error": "invalid JSON"})
                    continue
                if not isinstance(data, dict):
                    await self._safe_send(ws, {"type": "error", "error": "message must be an object"})
                    continue

                msg_type = data.get("type", "")
                if not isinstance(msg_type, str):
                    await self._safe_send(ws, {"type": "error", "error": "invalid message type"})
                    continue

                # Phase 0 gate: unauthenticated remote sockets may only pair
                # or authenticate — everything else is refused.
                if not authed:
                    if msg_type == "pairing" and self.pairing is not None:
                        token = self.pairing.pair(data.get("code"))
                        if token in ("locked", "no_code", "expired", "bad_code"):
                            await self._safe_send(
                                ws, {"type": "pair_fail", "error": token}
                            )
                        else:
                            authed = True
                            await self._safe_send(
                                ws, {"type": "pair_ok", "token": token}
                            )
                        continue
                    if msg_type == "auth" and self.pairing is not None:
                        if self.pairing.check_token(data.get("token")):
                            authed = True
                            await self._safe_send(ws, {"type": "auth_ok"})
                        else:
                            await self._safe_send(ws, {"type": "auth_fail"})
                        continue
                    await self._safe_send(
                        ws,
                        {
                            "type": "auth_required",
                            "error": "pairing required: send pairing:generate from the desktop, then pairing/auth",
                        },
                    )
                    continue

                # Mint a pairing code — desktop/loopback only, even for
                # already-authenticated remote peers.
                if msg_type == "pairing:generate":
                    if not is_local or self.pairing is None:
                        await self._safe_send(
                            ws, {"type": "error", "error": "pairing:generate is local-only"}
                        )
                        continue
                    code = self.pairing.generate()
                    host = lan_ip()
                    print(f"Pairing code generated (valid {CODE_TTL:.0f}s)", flush=True)
                    await self._safe_send(
                        ws,
                        {
                            "type": "pairing:code",
                            "code": code,
                            "expiresIn": int(CODE_TTL),
                            "host": host,
                            "port": self.port,
                            "lanMode": bool(self.lan_mode),
                            "qr": pair_qr(
                                f"syncflow://pair?host={host}&port={self.port}&code={code}"
                            ),
                        },
                    )
                    continue

                # Phase 3 upload control frames — dispatched here (post-auth,
                # same as every handler) so the manager gets the connection.
                if self.upload is not None and msg_type in UPLOAD_JSON_TYPES:
                    try:
                        response = await self.upload.handle(ws, data)
                        if response:
                            await ws.send(json.dumps(response))
                    except Exception as e:
                        print(f"Handler error for {_san(msg_type, 64)}: {_san(e, 160)}", flush=True)
                        await self._safe_send(ws, {"type": "error", "error": _san(e, 200)})
                    continue

                # Phase 3 download control frames — same contract.
                if self.download is not None and msg_type in DOWNLOAD_JSON_TYPES:
                    try:
                        response = await self.download.handle(ws, data)
                        if response:
                            await ws.send(json.dumps(response))
                    except Exception as e:
                        print(f"Handler error for {_san(msg_type, 64)}: {_san(e, 160)}", flush=True)
                        await self._safe_send(ws, {"type": "error", "error": _san(e, 200)})
                    continue

                handler = self._handlers.get(msg_type)
                if handler is None:
                    print(f"Unknown message type: {_san(msg_type, 64)}", flush=True)
                    continue

                try:
                    response = await handler(data)
                    if response:
                        await ws.send(json.dumps(response))
                except Exception as e:
                    # One bad request must not tear down the client session
                    print(f"Handler error for {_san(msg_type, 64)}: {_san(e, 160)}", flush=True)
                    await self._safe_send(ws, {"type": "error", "error": _san(e, 200)})
        except Exception as e:
            print(f"Client error: {_san(e, 160)}", flush=True)
        finally:
            if self.upload is not None:
                self.upload.detach(ws)
            if self.download is not None:
                self.download.detach(ws)
            self.clients.discard(ws)
            print(f"Electron client disconnected ({len(self.clients)} remaining)", flush=True)

    async def _safe_send(self, ws, message: dict):
        try:
            await ws.send(json.dumps(message))
        except Exception:
            pass

    async def send_message(self, message: dict):
        if not self.clients:
            return

        data = json.dumps(message)
        disconnected = set()

        # Snapshot: clients may join/leave while we await sends
        for client in list(self.clients):
            try:
                await client.send(data)
            except Exception:
                disconnected.add(client)

        self.clients -= disconnected

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        for client in self.clients.copy():
            try:
                await client.close()
            except Exception:
                pass

        self.clients.clear()
