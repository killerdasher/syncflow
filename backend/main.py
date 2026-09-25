#!/usr/bin/env python3
import asyncio
import os
import re
import signal
import socket
import sys
import time
from typing import Optional

from discovery.mdns import MDNSDiscovery
from transfer.engine import TransferEngine, TRANSFER_ID_RE, san
from networking import TCPServer
from ws_bridge import WebSocketBridge
from crypto.e2e import DeviceIdentityKeys
from crypto.blockchain import sha256_str

TARGET_HOST_RE = re.compile(r"^[A-Za-z0-9.\-:]{1,64}$")
MAX_FILES_PER_SEND = 1000
MAX_CHAT_LEN = 4000


class SyncFlowBackend:
    def __init__(self):
        self.ws_port = int(os.environ.get("SYNCFLOW_WS_PORT", "18973"))
        self.tcp_port = int(os.environ.get("SYNCFLOW_TCP_PORT", "18974"))
        identity_home = os.environ.get("SYNCFLOW_HOME")
        self.identity = DeviceIdentityKeys(
            storage_dir=os.path.join(identity_home, "identity") if identity_home else None
        )
        # Stable device id bound to the long-term identity (not random per boot)
        self.device_id = sha256_str(self.identity.signing_pub_b64)[:32]
        self.device_name = socket.gethostname()
        self.mdns = MDNSDiscovery(self.device_name, self.device_id, port=self.tcp_port)
        self.transfer_engine = TransferEngine(identity=self.identity, device_name=self.device_name)
        self.tcp_server = TCPServer(self.transfer_engine, port=self.tcp_port)
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
        if not isinstance(target_ip, str) or not TARGET_HOST_RE.match(target_ip):
            return {"type": "error", "error": "Invalid target address"}
        if not isinstance(file_paths, list) or len(file_paths) > MAX_FILES_PER_SEND:
            return {"type": "error", "error": "Invalid file list"}
        file_paths = [fp for fp in file_paths if isinstance(fp, str)]

        try:
            target_port = int(data.get("targetPort") or 18974)
        except (TypeError, ValueError):
            target_port = 18974
        if not (0 < target_port < 65536):
            return {"type": "error", "error": "Invalid target port"}

        transfer_id = data.get("transferId") or None
        if transfer_id is not None and (not isinstance(transfer_id, str) or not TRANSFER_ID_RE.match(transfer_id)):
            return {"type": "error", "error": "Invalid transfer id"}

        existing = [fp for fp in file_paths if os.path.exists(fp)]
        if not existing:
            return {
                "type": "transfer:error",
                "transferId": san(data.get("transferId", ""), 64),
                "error": "None of the selected files exist on disk",
            }

        task = await self.transfer_engine.send_files(
            existing, target_ip, transfer_id=transfer_id,
            target_port=target_port,
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
        if not isinstance(transfer_id, str) or not TRANSFER_ID_RE.match(transfer_id):
            return {"type": "error", "error": "Invalid transfer id"}
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
        raw = data.get("text", "")
        if not isinstance(raw, str):
            return {"type": "chat:error", "error": "Invalid message"}
        # Keep newlines/tabs only — strip every other control character
        text = "".join(ch for ch in raw if ch.isprintable() or ch in "\n\t")[:MAX_CHAT_LEN].strip()
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

        # Fan out to every discovered peer (best-effort, non-blocking)
        self._relay_chat(text)

        return {"type": "chat:ack", "messageId": message["id"], "hash": msg_hash}

    def _relay_chat(self, text: str):
        devices = [d for d in self.mdns.get_found_devices()
                   if d.get("id") and d["id"] != self.device_id and d.get("ip") and d.get("port")]
        for dev in devices:
            asyncio.ensure_future(self._relay_chat_to(dev["ip"], int(dev["port"]), text))

    async def _relay_chat_to(self, ip: str, port: int, text: str):
        try:
            await self.transfer_engine.send_chat(ip, text, target_port=port)
        except Exception as e:
            print(f"Chat relay error to {ip}: {san(e, 120)}", flush=True)

    async def _on_incoming_chat(self, message: dict):
        self._message_log.append(message)
        if len(self._message_log) > 500:
            self._message_log = self._message_log[-500:]
        if self.ws_bridge:
            await self.ws_bridge.send_message(message)

    async def _handle_chat_history(self, data: dict) -> dict:
        return {"type": "chat:history", "messages": self._message_log[-100:]}

    async def _handle_approval(self, data: dict) -> dict:
        transfer_id = data.get("transferId", "")
        if not isinstance(transfer_id, str) or not TRANSFER_ID_RE.match(transfer_id):
            return {"type": "error", "error": "Invalid transfer id"}
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
            if not isinstance(path, str):
                return {"type": "error", "error": "Invalid download path"}
            try:
                expanded = os.path.realpath(os.path.expanduser(path))
                home = os.path.realpath(os.path.expanduser("~"))
                # Confine downloads to the user's home — arbitrary paths
                # (e.g. /etc/..., /tmp/...) are rejected
                if expanded != home and not expanded.startswith(home + os.sep):
                    return {"type": "error", "error": "Download path must be inside your home directory"}
                self.transfer_engine.set_receive_dir(expanded)
                reply["downloadPath"] = expanded
            except (OSError, ValueError) as e:
                return {"type": "error", "error": f"Invalid download path: {san(e, 120)}"}

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

        self.ws_bridge = WebSocketBridge(port=self.ws_port)
        self._register_handlers()

        self.transfer_engine.set_progress_callback(self._on_transfer_progress)
        self.transfer_engine.set_chat_callback(self._on_incoming_chat)

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
