import asyncio
import json
from typing import Optional, Set, Callable, Any
from websockets.server import serve


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
        )
        print(f"SYNCFLOW_PORT:{self.port}", flush=True)
        print(f"WebSocket bridge listening on ws://127.0.0.1:{self.port}", flush=True)
        await asyncio.Future()

    async def _handle_client(self, ws):
        self.clients.add(ws)
        print(f"Electron client connected ({len(self.clients)} total)", flush=True)

        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "")

                    if msg_type in self._handlers:
                        response = await self._handlers[msg_type](data)
                        if response:
                            await ws.send(json.dumps(response))
                    else:
                        print(f"Unknown message type: {msg_type}", flush=True)

                except json.JSONDecodeError:
                    print(f"Invalid JSON received: {str(message)[:100]}", flush=True)
        except Exception as e:
            print(f"Client error: {e}", flush=True)
        finally:
            self.clients.discard(ws)
            print(f"Electron client disconnected ({len(self.clients)} remaining)", flush=True)

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
