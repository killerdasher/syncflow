import asyncio
import json
from typing import Optional, Callable


class RelayClient:
    def __init__(self, relay_url: str, auth_token: str):
        self.relay_url = relay_url
        self.auth_token = auth_token
        self._ws = None
        self._connected = False
        self._on_message: Optional[Callable] = None

    async def connect(self) -> bool:
        try:
            import websockets
            self._ws = await websockets.connect(
                self.relay_url,
                additional_headers={"Authorization": f"Bearer {self.auth_token}"},
            )
            self._connected = True
            print(f"Connected to relay: {self.relay_url}", flush=True)
            return True
        except Exception as e:
            print(f"Relay connection failed: {e}", flush=True)
            return False

    async def listen(self):
        if not self._ws:
            return

        try:
            async for message in self._ws:
                if self._on_message:
                    data = json.loads(message)
                    await self._on_message(data)
        except Exception as e:
            print(f"Relay listen error: {e}", flush=True)
            self._connected = False

    async def send(self, message: dict):
        if self._ws and self._connected:
            await self._ws.send(json.dumps(message))

    async def disconnect(self):
        if self._ws:
            await self._ws.close()
            self._connected = False
