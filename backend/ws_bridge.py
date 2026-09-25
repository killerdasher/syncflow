import asyncio
import json
from typing import Optional, Set, Callable, Any
from websockets.server import serve

# Browser-enforced origins only: file:// pages report the string "null",
# the Vite dev server reports its localhost origin. Cross-origin browser
# pages (evil.example.com) are rejected at handshake time. Non-browser
# clients (None) are allowed — they can't be held to Origin anyway and
# the TCP port is protected by E2E encryption.
ALLOWED_ORIGINS = [
    "null",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://[::1]:5173",
    None,
]

MAX_WS_MESSAGE = 1_048_576  # bytes


def _san(value, limit: int = 200) -> str:
    text = "" if value is None else str(value)
    return "".join(ch for ch in text if ch.isprintable())[:limit]


class WebSocketBridge:
    def __init__(self, port: int = 18973):
        self.port = port
        self.clients: Set = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._handlers: dict[str, Callable] = {}

    def on(self, message_type: str, handler: Callable):
        self._handlers[message_type] = handler

    async def start(self):
        self.loop = asyncio.get_event_loop()
        self._server = await serve(
            self._handle_client,
            "127.0.0.1",
            self.port,
            origins=ALLOWED_ORIGINS,
            max_size=MAX_WS_MESSAGE,
            ping_interval=20,
            ping_timeout=20,
        )
        print(f"SYNCFLOW_PORT:{self.port}", flush=True)
        print(f"WebSocket bridge listening on ws://127.0.0.1:{self.port}", flush=True)
        await asyncio.Future()

    async def _handle_client(self, ws):
        self.clients.add(ws)
        print(f"Electron client connected ({len(self.clients)} total)", flush=True)

        try:
            async for message in ws:
                # Robustness: malformed input never kills the connection
                try:
                    data = json.loads(message)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    await self._safe_send(ws, {"type": "error", "error": "invalid JSON"})
                    continue
                if not isinstance(data, dict):
                    await self._safe_send(ws, {"type": "error", "error": "message must be an object"})
                    continue

                msg_type = data.get("type", "")
                if not isinstance(msg_type, str):
                    await self._safe_send(ws, {"type": "error", "error": "invalid message type"})
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

        for client in self.clients:
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
