#!/usr/bin/env python3
import asyncio
import json
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
from upload import UploadManager
from download import DownloadManager
from pairing import PairingManager
from crypto.e2e import DeviceIdentityKeys
from crypto.blockchain import sha256_str
from sas import compute_sas

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
        self.upload: Optional[UploadManager] = None
        self.download: Optional[DownloadManager] = None
        self._running = False
        self._message_log: list[dict] = []
        # Chat history survives restarts (bounded, written to the app home)
        self._chat_path = os.path.join(
            os.path.dirname(os.path.abspath(self.identity.storage_dir)), "chat_log.json"
        )
        self._load_chat_log()
        # Manually added peers (peers:add) — chat relays fan out to these even
        # when mDNS discovery is one-way or blocked (classic firewall asymmetry).
        self._known_peers_path = os.path.join(os.path.dirname(self._chat_path), "known_peers.json")
        self._known_peers: dict[str, dict] = {}
        self._load_known_peers()
        # Outbound chat outbox: message id -> {text, created, targets:{addr:...}}.
        # Failed deliveries are retried with backoff until TTL (see _chat_worker).
        self._chat_outbox: dict[str, dict] = {}
        # One tick at a time: the worker and on-demand triggers share it.
        self._chat_tick_lock = asyncio.Lock()
        # Incoming message ids seen recently — relays arrive over multiple
        # paths (direct + multi-hop), so duplicates must be dropped once.
        self._seen_chat_ids: dict[str, float] = {}
        self._chat_worker_task: Optional[asyncio.Task] = None

    def _load_chat_log(self):
        try:
            if os.path.exists(self._chat_path):
                with open(self._chat_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._message_log = [
                        m for m in data[-500:] if isinstance(m, dict) and isinstance(m.get("text"), str)
                    ]
        except Exception:
            self._message_log = []

    def _save_chat_log(self):
        try:
            os.makedirs(os.path.dirname(self._chat_path), exist_ok=True, mode=0o700)
            # Chat history is sensitive: owner-only (0600), even for files
            # created by older builds with the looser default umask.
            fd = os.open(self._chat_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(self._message_log[-500:], f)
            os.chmod(self._chat_path, 0o600)
        except Exception:
            pass

    def _load_known_peers(self):
        try:
            if os.path.exists(self._known_peers_path):
                with open(self._known_peers_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for addr, peer in data.items():
                        if (
                            isinstance(peer, dict)
                            and isinstance(peer.get("ip"), str)
                            and isinstance(peer.get("port"), int)
                            and 0 < peer["port"] < 65536
                        ):
                            self._known_peers[str(addr)[:80]] = peer
        except Exception:
            self._known_peers = {}

    def _save_known_peers(self):
        try:
            os.makedirs(os.path.dirname(self._known_peers_path), exist_ok=True, mode=0o700)
            # Address book is sensitive: owner-only (0600), same as chat_log.
            fd = os.open(self._known_peers_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(self._known_peers, f, indent=2)
            os.chmod(self._known_peers_path, 0o600)
        except Exception:
            pass

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
        self.ws_bridge.on("identity:sas", self._handle_sas)
        self.ws_bridge.on("settings:apply", self._handle_settings)
        self.ws_bridge.on("peers:list", self._handle_peers_list)
        self.ws_bridge.on("peers:forget", self._handle_peers_forget)
        self.ws_bridge.on("peers:add", self._handle_peers_add)
        self.ws_bridge.on("peers:remove", self._handle_peers_remove)
        self.ws_bridge.on("diag:probe", self._handle_diag_probe)
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

    async def _handle_sas(self, data: dict) -> dict:
        # Out-of-band verification: both sides recompute the same icon
        # sequence from the two device IDs (see backend/sas.py).
        peer = data.get("peerDeviceId")
        try:
            result = compute_sas(self.device_id, peer)
        except ValueError:
            return {"type": "error", "error": "Invalid device id"}
        return {
            "type": "identity:sas",
            "peerDeviceId": peer,
            "codes": result["codes"],
            "hash": result["hash"],
        }

    async def _handle_send(self, data: dict) -> dict:
        # Parse the transfer id first so every validation error below can
        # reference it — the UI uses it to fail the right pending transfer.
        transfer_id = data.get("transferId") or None
        if transfer_id is not None and (not isinstance(transfer_id, str) or not TRANSFER_ID_RE.match(transfer_id)):
            return {"type": "error", "error": "Invalid transfer id"}
        tid = {"transferId": transfer_id} if transfer_id else {}

        target_ip = data.get("targetIp", "")
        file_paths = data.get("files", [])

        if not target_ip or not file_paths:
            return {"type": "error", "error": "Missing target IP or files", **tid}
        if not isinstance(target_ip, str) or not TARGET_HOST_RE.match(target_ip):
            return {"type": "error", "error": "Invalid target address", **tid}
        if not isinstance(file_paths, list) or len(file_paths) > MAX_FILES_PER_SEND:
            return {"type": "error", "error": "Invalid file list", **tid}
        file_paths = [fp for fp in file_paths if isinstance(fp, str)]

        try:
            target_port = int(data.get("targetPort") or 18974)
        except (TypeError, ValueError):
            target_port = 18974
        if not (0 < target_port < 65536):
            return {"type": "error", "error": "Invalid target port", **tid}

        expected_device_id = data.get("targetDeviceId") or None
        if expected_device_id is not None and (
            not isinstance(expected_device_id, str) or not TRANSFER_ID_RE.match(expected_device_id)
        ):
            return {"type": "error", "error": "Invalid target device id", **tid}

        dest_folder = data.get("destFolder") or None
        if dest_folder is not None and (not isinstance(dest_folder, str) or len(dest_folder) > 64):
            return {"type": "error", "error": "Invalid destination folder", **tid}
        if dest_folder:
            dest_folder = san(dest_folder, 64)

        existing = [fp for fp in file_paths if os.path.exists(fp)]
        if not existing:
            return {
                "type": "transfer:error",
                "transferId": san(data.get("transferId", ""), 64),
                "error": "None of the selected files exist on disk",
            }

        task = await self.transfer_engine.send_files(
            existing, target_ip, transfer_id=transfer_id,
            target_port=target_port, expected_device_id=expected_device_id,
            dest_folder=dest_folder,
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
        if not success and self.upload is not None:
            # Phase 3: cancel while still staging (before engine hand-off)
            success = self.upload.cancel(transfer_id)
        if not success and self.download is not None:
            # Phase 3: cancel a companion pulling a file off this desktop
            success = self.download.cancel(transfer_id)
        return {"type": "transfer:cancelled", "transferId": transfer_id, "success": success}

    async def _handle_devices_list(self, data: dict) -> dict:
        devices = [d for d in self.mdns.get_found_devices() if d.get("id") != self.device_id]
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
        self._save_chat_log()

        if self.ws_bridge:
            await self.ws_bridge.send_message(message)

        # Fan out to every relay target (mDNS + manually added peers). The
        # outbox retries with backoff and reports chat:delivered/failed.
        self._relay_chat(message["id"], text)

        return {"type": "chat:ack", "messageId": message["id"], "hash": msg_hash}

    def _chat_targets(self) -> dict[str, dict]:
        """Relay targets = mDNS-discovered ∪ manually added peers.

        The previous implementation only used mDNS, so manually added
        devices (or one-way mDNS behind a firewall) silently never got
        messages — files worked because they carry an explicit targetIp.
        """
        targets: dict[str, dict] = {}
        for dev in self.mdns.get_found_devices():
            if not dev.get("id") or dev["id"] == self.device_id or not dev.get("ip") or not dev.get("port"):
                continue
            addr = f"{dev['ip']}:{int(dev['port'])}"
            targets[addr] = {
                "ip": dev["ip"],
                "port": int(dev["port"]),
                "deviceId": dev["id"],
                "name": str(dev.get("name", ""))[:64],
            }
        for addr, peer in self._known_peers.items():
            if peer.get("deviceId") and peer["deviceId"] == self.device_id:
                continue  # never relay to ourselves
            if addr not in targets:
                targets[addr] = {
                    "ip": peer["ip"],
                    "port": int(peer["port"]),
                    "deviceId": peer.get("deviceId"),
                    "name": str(peer.get("name", ""))[:64],
                }
        return targets

    def _relay_chat(self, msg_id: str, text: str):
        now = time.time()
        targets = self._chat_targets()
        entry = {
            "text": text,
            "created": now,
            "reportedFailed": False,
            "orphan": not targets,  # born with no target: may self-heal when a peer appears
            "targets": {
                addr: {**t, "attempts": 0, "next": now} for addr, t in targets.items()
            },
        }
        self._chat_outbox[msg_id] = entry
        if targets:
            asyncio.ensure_future(self._chat_outbox_tick())

    async def _report_chat_failed(self, msg_id: str, target: Optional[str], reason: str):
        entry = self._chat_outbox.get(msg_id)
        if entry is not None and entry.get("reportedFailed") and target is None:
            return  # no-target failure already reported once for this message
        if self._chat_outbox.get(msg_id) is entry and target is None:
            entry["reportedFailed"] = True
        if self.ws_bridge:
            await self.ws_bridge.send_message(
                {"type": "chat:failed", "messageId": msg_id, "target": target, "reason": san(reason, 160)}
            )

    async def _report_chat_delivered(self, msg_id: str, target: str):
        if self.ws_bridge:
            await self.ws_bridge.send_message(
                {"type": "chat:delivered", "messageId": msg_id, "target": target}
            )

    def _attach_target_to_outbox(self, ip: str, port: int, device_id: Optional[str], name: str):
        """A peer became visible (mDNS found or peers:add): unblock pending
        deliveries to it, and give orphaned messages a target to heal on."""
        addr = f"{ip}:{port}"
        for entry in list(self._chat_outbox.values()):
            t = entry.get("targets", {}).get(addr)
            if t is not None:
                t["next"] = 0  # retry immediately
            elif entry.get("orphan"):
                entry["targets"][addr] = {
                    "ip": ip, "port": int(port), "deviceId": device_id,
                    "name": str(name)[:64], "attempts": 0, "next": 0,
                }
                entry["orphan"] = False

    # Retry schedule: 5s, 10s, 30s, 60s, then every 60s. ~1440 attempts/day,
    # capped by CHAT_OUTBOX_TTL (24h) so a dead peer can't queue forever.
    _CHAT_RETRY_BACKOFF = (5.0, 10.0, 30.0, 60.0)
    _CHAT_OUTBOX_TTL = 24 * 3600.0
    _CHAT_MAX_ATTEMPTS = 1440

    async def _chat_outbox_tick(self):
        if self._chat_tick_lock.locked():
            return  # a tick is already running; it will see our entries
        async with self._chat_tick_lock:
            await self._chat_outbox_tick_inner()

    async def _chat_outbox_tick_inner(self):
        now = time.time()
        for msg_id, entry in list(self._chat_outbox.items()):
            if now - entry.get("created", now) > self._CHAT_OUTBOX_TTL:
                for addr in entry.get("targets", {}):
                    await self._report_chat_failed(msg_id, addr, "Delivery timed out")
                self._chat_outbox.pop(msg_id, None)
                continue
            for addr, t in list(entry.get("targets", {}).items()):
                if t.get("next", 0) > now:
                    continue
                ok = False
                try:
                    ok = await self.transfer_engine.send_chat(
                        t["ip"], entry["text"], target_port=t["port"],
                        expected_device_id=t.get("deviceId") or None,
                    )
                except Exception as e:
                    print(f"Chat relay error to {addr}: {san(e, 120)}", flush=True)
                if ok:
                    entry["targets"].pop(addr, None)
                    await self._report_chat_delivered(msg_id, addr)
                else:
                    t["attempts"] = int(t.get("attempts", 0)) + 1
                    if t["attempts"] >= self._CHAT_MAX_ATTEMPTS:
                        entry["targets"].pop(addr, None)
                        await self._report_chat_failed(
                            msg_id, addr, f"Delivery failed after {t['attempts']} attempts"
                        )
                    else:
                        backoff = self._CHAT_RETRY_BACKOFF[
                            min(t["attempts"] - 1, len(self._CHAT_RETRY_BACKOFF) - 1)
                        ]
                        t["next"] = now + backoff
            if self._chat_outbox.get(msg_id) is not entry:
                continue
            if entry.get("orphan") and not entry.get("targets"):
                # Born without any relay target. Give discovery a grace window
                # (mDNS browse needs a second or two), then tell the sender —
                # but keep the entry so a later peers:add/find can still heal it.
                if not entry.get("reportedFailed") and now - entry.get("created", now) > 60:
                    await self._report_chat_failed(msg_id, None, "No known devices to deliver to")
            elif not entry.get("targets"):
                self._chat_outbox.pop(msg_id, None)

    async def _chat_worker(self):
        """Background retry loop: queued messages keep trying for life."""
        while self._running:
            await asyncio.sleep(2.0)
            try:
                if self._chat_outbox:
                    await self._chat_outbox_tick()
            except Exception as e:
                print(f"Chat worker error: {san(e, 120)}", flush=True)

    async def _on_security_event(self, event: dict):
        """Broadcast security events (e.g., identity change) to all WS clients."""
        if self.ws_bridge and self.ws_bridge.loop:
            await self.ws_bridge.send_message({
                "type": "security:identity-changed",
                "key": event.get("key", ""),
                "reason": event.get("reason", ""),
            })

    async def _on_incoming_chat(self, message: dict):
        # Multi-path relay: the same message can arrive directly AND via
        # another peer's fan-out. Dedup by id so the UI never shows doubles.
        msg_id = message.get("id")
        if isinstance(msg_id, str) and msg_id:
            now = time.time()
            if msg_id in self._seen_chat_ids:
                return
            self._seen_chat_ids[msg_id] = now
            if len(self._seen_chat_ids) > 512:
                cutoff = now - 600
                self._seen_chat_ids = {
                    k: v for k, v in self._seen_chat_ids.items() if v >= cutoff
                }
        self._message_log.append(message)
        if len(self._message_log) > 500:
            self._message_log = self._message_log[-500:]
        self._save_chat_log()
        if self.ws_bridge:
            await self.ws_bridge.send_message(message)

    async def _handle_chat_history(self, data: dict) -> dict:
        return {"type": "chat:history", "messages": self._message_log[-100:]}

    async def _handle_approval(self, data: dict) -> dict:
        transfer_id = data.get("transferId", "")
        if not isinstance(transfer_id, str) or not TRANSFER_ID_RE.match(transfer_id):
            return {"type": "error", "error": "Invalid transfer id"}
        approve = data.get("type") == "transfer:approve"
        files_sel = data.get("files")
        if approve and files_sel is not None:
            # Subset approval: non-empty, <=1000 unique non-negative ints.
            # (Range vs the declared file count is checked by the engine,
            # which is the only side that knows it at decision time.)
            if (
                not isinstance(files_sel, list)
                or not files_sel
                or len(files_sel) > 1000
                or any(not isinstance(i, int) or isinstance(i, bool) or i < 0 for i in files_sel)
                or len(set(files_sel)) != len(files_sel)
            ):
                return {"type": "error", "error": "Invalid file selection"}
        if approve:
            success = self.transfer_engine.approve_transfer(transfer_id, files_sel)
        else:
            success = self.transfer_engine.decline_transfer(transfer_id)
        return {
            "type": "transfer:decision",
            "transferId": transfer_id,
            "approved": approve,
            "success": success,
        }

    async def _handle_settings(self, data: dict) -> Optional[dict]:
        path = data.get("downloadPath")
        auto_accept = data.get("autoAccept")
        device_name = data.get("deviceName")
        max_concurrent = data.get("maxConcurrent")
        sync_folders = data.get("syncFolders")
        reply: dict = {"type": "settings:applied"}

        if auto_accept is not None:
            # Strict: JSON garbage must not flip auto-accept (bool("no") is True).
            if not isinstance(auto_accept, bool):
                return {"type": "error", "error": "Invalid auto accept value"}
            self.transfer_engine.set_approval(not auto_accept)
            reply["autoAccept"] = auto_accept

        if device_name is not None:
            if not isinstance(device_name, str):
                return {"type": "error", "error": "Invalid device name"}
            name = san(device_name.strip(), 48)
            if name and name != self.device_name:
                self.device_name = name
                self.transfer_engine.device_name = name
                try:
                    await self.mdns.rename(name)
                    reply["deviceName"] = name
                except Exception as e:
                    print(f"mDNS rename error: {san(e, 120)}", flush=True)
                    reply["deviceName"] = name

        if max_concurrent is not None:
            try:
                self.transfer_engine.set_max_concurrent(int(max_concurrent))
                reply["maxConcurrent"] = self.transfer_engine.max_concurrent
            except (TypeError, ValueError):
                return {"type": "error", "error": "Invalid max concurrent value"}

        if sync_folders is not None:
            if not isinstance(sync_folders, list):
                return {"type": "error", "error": "Invalid sync folders"}
            self.transfer_engine.set_sync_folders(sync_folders)
            reply["syncFolders"] = len(self.transfer_engine.sync_folders)

        if path is not None and not isinstance(path, str):
            return {"type": "error", "error": "Invalid download path"}
        if path:
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

        # Every settings:apply MUST answer (protocol.md §6): a no-op request
        # still gets settings:applied — swallowing the reply hung clients.
        return reply

    @staticmethod
    def _peer_view(p: dict) -> dict:
        view = {k: v for k, v in p.items() if k != "pub"}
        view["deviceId"] = sha256_str(p.get("pub", ""))[:32]
        return view

    async def _handle_peers_list(self, data: dict) -> dict:
        return {"type": "peers:list", "peers": [self._peer_view(p) for p in self.transfer_engine.trust.list_peers()]}

    async def _handle_peers_forget(self, data: dict) -> dict:
        key = data.get("key")
        if not isinstance(key, str) or not re.match(r"^[A-Za-z0-9.:\-]{1,64}$", key):
            return {"type": "error", "error": "Invalid peer key"}
        success = self.transfer_engine.trust.forget(key)
        remaining = self.transfer_engine.trust.list_peers()
        return {
            "type": "peers:updated",
            "key": key,
            "success": success,
            "peers": [self._peer_view(p) for p in remaining],
        }

    @staticmethod
    def _parse_peer_addr(data: dict) -> tuple[Optional[str], int, Optional[str]]:
        """Validate {ip, port} for peers:add/remove. Returns (ip, port, error)."""
        ip = data.get("ip", "")
        if not isinstance(ip, str) or not ip or not TARGET_HOST_RE.match(ip) or ":" in ip:
            return None, 0, "Invalid target address"
        try:
            port = int(data.get("port") or 18974)
        except (TypeError, ValueError):
            return None, 0, "Invalid target port"
        if not (0 < port < 65536):
            return None, 0, "Invalid target port"
        return ip, port, None

    async def _handle_peers_add(self, data: dict) -> dict:
        ip, port, err = self._parse_peer_addr(data)
        if err:
            return {"type": "error", "error": err}
        device_id = data.get("deviceId") or None
        if device_id is not None and (
            not isinstance(device_id, str) or not TRANSFER_ID_RE.match(device_id)
        ):
            return {"type": "error", "error": "Invalid device id"}
        name = data.get("name")
        name = san(name, 64) if isinstance(name, str) else ""

        addr = f"{ip}:{port}"
        self._known_peers[addr] = {
            "ip": ip,
            "port": port,
            "deviceId": device_id,
            "name": name,
            "addedAt": time.time(),
        }
        self._save_known_peers()
        # A peer that just became reachable may unblock queued messages.
        self._attach_target_to_outbox(ip, port, device_id, name)
        return {"type": "peers:added", "peer": self._known_peers[addr]}

    async def _handle_peers_remove(self, data: dict) -> dict:
        ip, port, err = self._parse_peer_addr(data)
        if err:
            return {"type": "error", "error": err}
        addr = f"{ip}:{port}"
        success = self._known_peers.pop(addr, None) is not None
        if success:
            self._save_known_peers()
        return {"type": "peers:removed", "addr": addr, "success": success}

    async def _handle_diag_probe(self, data: dict) -> dict:
        """Connection doctor: plain TCP reachability + latency to a peer."""
        ip, port, err = self._parse_peer_addr(data)
        if err:
            return {"type": "diag:result", "ok": False, "error": err}
        started = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), 3.0)
            latency_ms = round((time.monotonic() - started) * 1000, 1)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            return {"type": "diag:result", "ok": True, "ip": ip, "port": port, "latencyMs": latency_ms}
        except Exception as e:
            return {
                "type": "diag:result",
                "ok": False,
                "ip": ip,
                "port": port,
                "latencyMs": None,
                "error": san(e, 120),
            }

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
                "destPath": (task.dest_paths[-1] if task.dest_paths else None),
                "destFolder": task.dest_folder,
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
        # Phase 0: pairing codes/tokens for LAN mode live in the app home
        # (owner-only, same directory as the chat log).
        self.ws_bridge.set_pairing(
            PairingManager(os.path.join(os.path.dirname(self._chat_path), "pairing.json"))
        )
        self.upload = UploadManager(self.ws_bridge, self.transfer_engine)
        self.ws_bridge.set_upload(self.upload)
        self.download = DownloadManager(self.ws_bridge, self.transfer_engine)
        self.ws_bridge.set_download(self.download)
        self._register_handlers()

        self.transfer_engine.set_progress_callback(self._on_transfer_progress)
        self.transfer_engine.set_chat_callback(self._on_incoming_chat)
        self.transfer_engine.set_security_callback(self._on_security_event)

        await self.mdns.register()
        self.mdns.start_browsing(self._on_device_found, self._on_device_lost)

        await self.tcp_server.start()

        # Chat retry worker: drains the outbox with backoff so messages
        # survive transient peer absence / firewall hiccups.
        self._chat_worker_task = asyncio.ensure_future(self._chat_worker())

        try:
            await self.ws_bridge.start()
        except Exception as e:
            print(f"WS Bridge error: {e}", flush=True)

    def _on_device_found(self, device_info):
        if device_info.get("id") == self.device_id:
            return  # never surface our own advertisement as a peer
        print(f"Device found: {device_info['name']} ({device_info['ip']})", flush=True)
        if self.ws_bridge and self.ws_bridge.loop:
            # zeroconf thread → hop onto the event loop: unblock/attach any
            # queued chat deliveries for this peer before announcing it.
            asyncio.run_coroutine_threadsafe(
                self._on_peer_visible(device_info), self.ws_bridge.loop,
            )

    async def _on_peer_visible(self, device_info: dict):
        try:
            if device_info.get("ip") and device_info.get("port"):
                self._attach_target_to_outbox(
                    str(device_info["ip"]),
                    int(device_info["port"]),
                    device_info.get("id"),
                    str(device_info.get("name", "")),
                )
                if self._chat_outbox:
                    asyncio.ensure_future(self._chat_outbox_tick())
        except Exception as e:
            print(f"Peer visible error: {san(e, 120)}", flush=True)
        if self.ws_bridge:
            await self.ws_bridge.send_message({"type": "device:connected", "device": device_info})

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
        if self._chat_worker_task is not None:
            try:
                self._chat_worker_task.cancel()
                await self._chat_worker_task
            except (asyncio.CancelledError, Exception):
                pass
            self._chat_worker_task = None
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
