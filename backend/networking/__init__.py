import asyncio
from typing import Callable, Optional

MAX_CONNECTIONS = 64
CONN_WAIT_TIMEOUT = 2.0


class TCPServer:
    def __init__(self, transfer_engine, port: int = 18974):
        self.port = port
        self.transfer_engine = transfer_engine
        self._server: Optional[asyncio.AbstractServer] = None
        self._on_transfer_start: Optional[Callable] = None
        self._sem = asyncio.Semaphore(MAX_CONNECTIONS)

    def set_transfer_callback(self, callback: Callable):
        self._on_transfer_start = callback

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", self.port
        )
        print(f"TCP Server listening on port {self.port}", flush=True)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        try:
            if self._sem.locked():
                try:
                    await asyncio.wait_for(self._sem.acquire(), CONN_WAIT_TIMEOUT)
                except asyncio.TimeoutError:
                    print(f"Rejected connection from {addr}: at capacity", flush=True)
                    writer.close()
                    await writer.wait_closed()
                    return
            else:
                self._sem.acquire_nowait()

            try:
                print(f"TCP connection from {addr}", flush=True)
                await self.transfer_engine.receive_transfer(reader, writer)
            except Exception as e:
                safe = "".join(ch for ch in str(e) if ch.isprintable())[:160]
                print(f"Connection handler error from {addr}: {type(e).__name__}: {safe}", flush=True)
            finally:
                self._sem.release()
        except Exception:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            print("TCP Server stopped", flush=True)
