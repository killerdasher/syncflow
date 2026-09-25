import asyncio
import json
from typing import Optional


class TCPClient:
    def __init__(self):
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self, host: str, port: int = 18974) -> bool:
        try:
            self._reader, self._writer = await asyncio.open_connection(host, port)
            print(f"Connected to {host}:{port}", flush=True)
            return True
        except Exception as e:
            print(f"Connection failed: {e}", flush=True)
            return False

    async def send_message(self, message: dict) -> Optional[dict]:
        if not self._writer:
            return None

        data = json.dumps(message).encode()
        self._writer.write(len(data).to_bytes(4, "big"))
        self._writer.write(data)
        await self._writer.drain()

        resp_len = int.from_bytes(await self._reader.readexactly(4), "big")
        resp = json.loads(await self._reader.readexactly(resp_len))
        return resp

    async def send_raw(self, data: bytes):
        if self._writer:
            self._writer.write(data)
            await self._writer.drain()

    async def read_exact(self, n: int) -> bytes:
        if self._reader:
            return await self._reader.readexactly(n)
        return b""

    async def disconnect(self):
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._reader = None
            self._writer = None
