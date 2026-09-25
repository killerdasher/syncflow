#!/usr/bin/env python3
import asyncio
import os
import signal
import socket
import sys
import time
import uuid
from typing import Optional

from discovery.mdns import MDNSDiscovery
from transfer.engine import TransferEngine
from networking import TCPServer
from ws_bridge import WebSocketBridge
from crypto.e2e import DeviceIdentityKeys
from crypto.blockchain import sha256_str


class SyncFlowBackend:
    def __init__(self):
        self.device_id = str(uuid.uuid4())
        self.device_name = socket.gethostname()
        self.identity = DeviceIdentityKeys()
        self.mdns = MDNSDiscovery(self.device_name, self.device_id)
        self.transfer_engine = TransferEngine(identity=self.identity, device_name=self.device_name)
        self.tcp_server = TCPServer(self.transfer_engine)
        self.ws_bridge: Optional[WebSocketBridge] = None
        self._running = False
        self._message_log: list[dict] = []

    def _register_handlers(self):
        if not self.ws_bridge:
            return

        self.ws_bridge.on("command:send", self._handle_send)
        self.ws_bridge.on("command:cancel", self._handle_cancel)
        self.ws_bridge.on("devices:list", self._handle_devices_list)
        self.ws_bridge.on("transfers:list", self._handle_transfers_list)
        self.ws_bridge.on("chat:send", self._handle_chat_send)
        self.ws_bridge.on("chat:history", self._handle_chat_history)
        self.ws_bridge.on("identity:get", self._handle_identity)
        self.ws_bridge.on("settings:apply", self._handle_settings)
        self.ws_bridge.on("transfer:approve", self._handle_approval)
        self.ws_bridge.on("transfer:decline", self._handle_approval)

    async def _handle_identity(self, data: dict) -> dict:
        return {
            "type": "identity:info",
            "signingPub": self.identity.signing_pub_b64,
            "x25519Pub": self.identity.x25519_pub_b64,
            "deviceId": self.device_id,
            "deviceName": self.device_name,
        }

    async def _handle_send(self, data: dict) -> dict:
        target_ip = data.get("targetIp", "")
        file_paths = data.get("files", [])

        if not target_ip or not file_paths:
            return {"type": "error", "error": "Missing target IP or files"}

        existing = [fp for fp in file_paths if os.path.exists(fp)]
        if not existing:
            return {
                "type": "transfer:error",
                "transferId": data.get("transferId", ""),
                "error": "None of the selected files exist on disk",
            }

        task = await self.transfer_engine.send_files(
            existing, target_ip, transfer_id=data.get("transferId") or None
        )

        return {
            "type": "transfer:new",
            "transfer": {
                "id": task.id,
                "status": task.status,
                "progress": 0,
                "bytesTransferred": 0,
                "totalBytes": task.total_bytes,
                "speed": 0,
                "verified": False,
                "files": [{"name": f["name"], "size": f["size"], "path": f["path"], "type": f["type"]} for f in task.files],
                "startTime": int(task.start_time * 1000),
            },
        }

    async def _handle_cancel(self, data: dict) -> dict:
        transfer_id = data.get("transferId", "")
        success = self.transfer_engine.cancel_transfer(transfer_id)
        return {"type": "transfer:cancelled", "transferId": transfer_id, "success": success}

    async def _handle_devices_list(self, data: dict) -> dict:
        devices = self.mdns.get_found_devices()
        return {"type": "devices:update", "devices": devices}

    async def _handle_transfers_list(self, data: dict) -> dict:
        active = self.transfer_engine.get_active_transfers()
        completed = self.transfer_engine.completed_transfers[-20:]
        return {"type": "transfers:update", "active": active, "completed": completed}

    async def _handle_chat_send(self, data: dict) -> dict:
        text = data.get("text", "").strip()
        if not text:
            return {"type": "chat:error", "error": "Empty message"}

        msg_hash = sha256_str(text + str(time.time()) + self.device_id)
        message = {
            "type": "chat:message",
            "id": msg_hash[:16],
            "fromDevice": data.get("fromDevice") or self.device_name,
            "deviceId": self.device_id,
            "text": text,
            "timestamp": time.time(),
            "hash": msg_hash,
        }

        self._message_log.append(message)
        if len(self._message_log) > 500:
            self._message_log = self._message_log[-500:]

        if self.ws_bridge:
            await self.ws_bridge.send_message(message)

        return {"type": "chat:ack", "messageId": message["id"], "hash": msg_hash}

    async def _handle_chat_history(self, data: dict) -> dict:
        return {"type": "chat:history", "messages": self._message_log[-100:]}

    async def _handle_approval(self, data: dict) -> dict:
        transfer_id = data.get("transferId", "")
        approve = data.get("type") == "transfer:approve"
        handler = self.transfer_engine.approve_transfer if approve else self.transfer_engine.decline_transfer
        success = handler(transfer_id)
        return {
            "type": "transfer:decision",
            "transferId": transfer_id,
            "approved": approve,
            "success": success,
        }

    async def _handle_settings(self, data: dict) -> Optional[dict]:
        path = data.get("downloadPath")
        auto_accept = data.get("autoAccept")
        reply: dict = {"type": "settings:applied"}

        if auto_accept is not None:
            self.transfer_engine.set_approval(not bool(auto_accept))
            reply["autoAccept"] = bool(auto_accept)

        if path:
            try:
                expanded = os.path.expanduser(path)
                self.transfer_engine.set_receive_dir(expanded)
                reply["downloadPath"] = expanded
            except OSError as e:
                return {"type": "error", "error": f"Invalid download path: {e}"}

        return reply if len(reply) > 1 else None

    async def _on_transfer_progress(self, task):
        if self.ws_bridge and self.ws_bridge.loop:
            file_list = [
                {"name": f.get("name", ""), "size": f.get("size", 0), "path": f.get("path", ""), "type": f.get("type", "")}
                for f in task.files
            ]
            await self.ws_bridge.send_message({
                "type": "transfer:progress",
                "transferId": task.id,
                "progress": task.progress,
                "speed": task.speed,
                "bytesTransferred": task.bytes_transferred,
                "totalBytes": task.total_bytes,
                "status": task.status,
                "verified": task.verified,
                "fromDevice": task.from_device,
                "toDevice": task.to_device,
                "files": file_list,
                "startTime": int(task.start_time * 1000),
            })

            if task.status in ("completed", "failed", "cancelled"):
                msg_type = "transfer:complete" if task.status == "completed" else "transfer:error"
                if task.status == "cancelled":
                    await self.ws_bridge.send_message({
                        "type": "transfer:cancelled",
                        "transferId": task.id,
                        "success": True,
                    })
                else:
                    await self.ws_bridge.send_message({
                        "type": msg_type,
                        "transferId": task.id,
                        "error": task.error,
                        "verified": task.verified,
                    })

    async def start(self):
        self._running = True
        print(f"Device: {self.device_name} ({self.device_id[:8]}...)", flush=True)
        print(f"Identity: {self.identity.signing_pub_b64[:32]}...", flush=True)

        self.ws_bridge = WebSocketBridge(port=18973)
        self._register_handlers()

        self.transfer_engine.set_progress_callback(self._on_transfer_progress)

        await self.mdns.register()
        self.mdns.start_browsing(self._on_device_found, self._on_device_lost)

        await self.tcp_server.start()

        try:
            await self.ws_bridge.start()
        except Exception as e:
            print(f"WS Bridge error: {e}", flush=True)

    def _on_device_found(self, device_info):
        print(f"Device found: {device_info['name']} ({device_info['ip']})", flush=True)
        if self.ws_bridge and self.ws_bridge.loop:
            asyncio.run_coroutine_threadsafe(
                self.ws_bridge.send_message({"type": "device:connected", "device": device_info}),
                self.ws_bridge.loop,
            )

    def _on_device_lost(self, device_id):
        print(f"Device lost: {device_id}", flush=True)
        if self.ws_bridge and self.ws_bridge.loop:
            asyncio.run_coroutine_threadsafe(
                self.ws_bridge.send_message({"type": "device:disconnected", "deviceId": device_id}),
                self.ws_bridge.loop,
            )

    async def stop(self):
        if not self._running:
            return
        self._running = False
        try:
            await self.mdns.unregister()
        except Exception as e:
            print(f"mDNS unregister error: {e}", flush=True)
        try:
            await self.tcp_server.stop()
        except Exception as e:
            print(f"TCP stop error: {e}", flush=True)
        if self.ws_bridge:
            try:
                await self.ws_bridge.stop()
            except Exception as e:
                print(f"WS stop error: {e}", flush=True)
        print("SyncFlow backend stopped", flush=True)


def main():
    backend = SyncFlowBackend()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    shutting_down = False

    async def shutdown():
        try:
            await backend.stop()
        finally:
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.stop()

    def signal_handler():
        nonlocal shutting_down
        if not shutting_down:
            shutting_down = True
            loop.create_task(shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(backend.start())
    except KeyboardInterrupt:
        loop.run_until_complete(backend.stop())
    except asyncio.CancelledError:
        # start() task was cancelled by the shutdown handler — clean exit
        pass
    except RuntimeError:
        # loop.stop() was called by the signal handler — clean shutdown
        pass
    except Exception as e:
        print(f"Backend error: {type(e).__name__}: {e}", flush=True)
    finally:
        try:
            if not loop.is_closed():
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
        except Exception:
            pass
        # Force exit: zeroconf/executor threads can otherwise keep the process alive
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


if __name__ == "__main__":
    main()
