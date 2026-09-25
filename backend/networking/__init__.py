import asyncio
import json
from typing import Callable, Optional


class TCPServer:
    def __init__(self, transfer_engine, port: int = 18974):
        self.port = port
        self.transfer_engine = transfer_engine
        self._server: Optional[asyncio.AbstractServer] = None
        self._on_transfer_start: Optional[Callable] = None

    def set_transfer_callback(self, callback: Callable):
        self._on_transfer_start = callback

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", self.port
        )
        print(f"TCP Server listening on port {self.port}", flush=True)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        print(f"TCP connection from {addr}", flush=True)
        await self.transfer_engine.receive_transfer(reader, writer)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            print("TCP Server stopped", flush=True)
