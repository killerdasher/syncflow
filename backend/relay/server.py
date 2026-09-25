#!/usr/bin/env python3
import asyncio
import json
import re
import secrets
from typing import Set, Dict

CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class RelayServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: Dict[str, object] = {}
        self._tokens: Set[str] = set()
        self._pairs: Dict[str, str] = {}

    def generate_token(self) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens.add(token)
        return token

    async def _handle_client(self, ws, path: str = ""):
        client_id = None
        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue

                msg_type = data.get("type", "")

                if msg_type == "auth":
                    token = data.get("token", "")
                    # Default deny: tokens are issued by generate_token();
                    # an empty token set means NO client may authenticate.
                    candidate = data.get("clientId", "")
                    if (
                        self._tokens
                        and token in self._tokens
                        and isinstance(candidate, str)
                        and CLIENT_ID_RE.match(candidate)
                        and candidate not in self.clients
                    ):
                        client_id = candidate
                        self.clients[client_id] = ws
                        await ws.send(json.dumps({
                            "type": "auth_ok",
                            "clientId": client_id,
                        }))
                        print(f"Client authenticated: {client_id}")
                    else:
                        await ws.send(json.dumps({"type": "auth_fail"}))

                elif msg_type in ("relay", "signal"):
                    if client_id is None:
                        continue
                    target = data.get("target")
                    if not (isinstance(target, str) and CLIENT_ID_RE.match(target)):
                        continue
                    if target in self.clients:
                        if msg_type == "relay":
                            payload = data.get("payload", {})
                            await self.clients[target].send(json.dumps({
                                "type": "relay",
                                "from": client_id,
                                "payload": payload,
                            }))
                        else:
                            await self.clients[target].send(json.dumps({
                                "type": "signal",
                                "from": client_id,
                                "sdp": data.get("sdp"),
                                "candidate": data.get("candidate"),
                            }))

        except Exception as e:
            print(f"Client error: {type(e).__name__}")
        finally:
            if client_id and client_id in self.clients:
                del self.clients[client_id]
                print(f"Client disconnected: {client_id}")

    async def start(self):
        from websockets.asyncio.server import serve
        await serve(self._handle_client, self.host, self.port)
        print(f"Relay server running on ws://{self.host}:{self.port}")
        await asyncio.Future()


def main():
    server = RelayServer()
    asyncio.run(server.start())


if __name__ == "__main__":
    main()
