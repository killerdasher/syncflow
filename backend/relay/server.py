#!/usr/bin/env python3
import asyncio
import json
import secrets
from typing import Set, Dict, Optional
from websockets.server import serve, WebSocketServerProtocol


class RelayServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: Dict[str, WebSocketServerProtocol] = {}
        self._tokens: Set[str] = set()
        self._pairs: Dict[str, str] = {}

    def generate_token(self) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens.add(token)
        return token

    async def _handle_client(self, ws: WebSocketServerProtocol, path: str):
        client_id = None
        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                    msg_type = data.get("type", "")

                    if msg_type == "auth":
                        token = data.get("token", "")
                        if token in self._tokens or not self._tokens:
                            client_id = data.get("clientId", secrets.token_hex(8))
                            self.clients[client_id] = ws
                            await ws.send(json.dumps({
                                "type": "auth_ok",
                                "clientId": client_id,
                            }))
                            print(f"Client authenticated: {client_id}")
                        else:
                            await ws.send(json.dumps({"type": "auth_fail"}))

                    elif msg_type == "relay":
                        target = data.get("target")
                        if target and target in self.clients:
                            payload = data.get("payload", {})
                            await self.clients[target].send(json.dumps({
                                "type": "relay",
                                "from": client_id,
                                "payload": payload,
                            }))

                    elif msg_type == "signal":
                        target = data.get("target")
                        if target and target in self.clients:
                            await self.clients[target].send(json.dumps({
                                "type": "signal",
                                "from": client_id,
                                "sdp": data.get("sdp"),
                                "candidate": data.get("candidate"),
                            }))

                except json.JSONDecodeError:
                    pass

        except Exception as e:
            print(f"Client error: {e}")
        finally:
            if client_id and client_id in self.clients:
                del self.clients[client_id]
                print(f"Client disconnected: {client_id}")

    async def start(self):
        server = await serve(self._handle_client, self.host, self.port)
        print(f"Relay server running on ws://{self.host}:{self.port}")
        await asyncio.Future()


def main():
    server = RelayServer()
    asyncio.run(server.start())


if __name__ == "__main__":
    main()
