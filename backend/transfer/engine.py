import asyncio
import hashlib
import json
import os
import time
import uuid
from typing import Optional, Callable

from crypto.blockchain import TransferChain
from crypto.e2e import DeviceIdentityKeys, SessionCrypto, handshake_offer, handshake_accept, handshake_complete

CHUNK_SIZE = 65536


class TransferTask:
    def __init__(self, files: list[dict], target_ip: str, target_port: int = 18974, transfer_id: Optional[str] = None):
        self.id = transfer_id or str(uuid.uuid4())
        self.files = files
        self.target_ip = target_ip
        self.target_port = target_port
        self.status = "pending"
        self.progress = 0.0
        self.bytes_transferred = 0
        self.total_bytes = sum(f.get("size", 0) for f in files)
        self.speed = 0
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.error: Optional[str] = None
        self._cancelled = False
        self.chains: list[dict] = []
        self.verified = False
        self.from_device: Optional[str] = None
        self.to_device: Optional[str] = None
        self._last_emit = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "files": self.files,
            "status": self.status,
            "progress": self.progress,
            "bytesTransferred": self.bytes_transferred,
            "totalBytes": self.total_bytes,
            "speed": self.speed,
            "startTime": int(self.start_time * 1000),
            "endTime": int(self.end_time * 1000) if self.end_time else None,
            "error": self.error,
            "verified": self.verified,
            "fromDevice": self.from_device,
            "toDevice": self.to_device,
        }


class TransferEngine:
    def __init__(self, identity: Optional[DeviceIdentityKeys] = None, device_name: str = "Unknown device"):
        self.active_transfers: dict[str, TransferTask] = {}
        self.completed_transfers: list[dict] = []
        self.verified_transfers: dict[str, dict] = {}
        self._progress_callback: Optional[Callable] = None
        self._receive_dir = os.path.expanduser("~/Downloads/SyncFlow")
        self.identity = identity or DeviceIdentityKeys()
        self.device_name = device_name
        os.makedirs(self._receive_dir, exist_ok=True)

    def set_receive_dir(self, path: str):
        self._receive_dir = path
        os.makedirs(self._receive_dir, exist_ok=True)

    def set_progress_callback(self, callback: Callable):
        self._progress_callback = callback

    async def send_files(self, file_paths: list[str], target_ip: str, target_port: int = 18974, transfer_id: Optional[str] = None) -> TransferTask:
        files = []
        for fp in file_paths:
            if os.path.exists(fp):
                stat = os.stat(fp)
                files.append({
                    "name": os.path.basename(fp),
                    "path": fp,
                    "size": stat.st_size,
                    "type": "application/octet-stream",
                })

        task = TransferTask(files, target_ip, target_port, transfer_id=transfer_id)
        self.active_transfers[task.id] = task
        asyncio.create_task(self._execute_transfer(task))
        return task

    async def _execute_transfer(self, task: TransferTask):
        try:
            task.status = "transferring"
            reader, writer = await asyncio.open_connection(task.target_ip, task.target_port)

            offer, session = handshake_offer(self.identity)
            offer["type"] = "transfer_start"
            offer["transferId"] = task.id
            offer["security"] = "e2e-blockchain-v1"
            offer["senderName"] = self.device_name
            offer["files"] = [
                {"name": f["name"], "size": f["size"]}
                for f in task.files
            ]

            await self._write_msg(writer, offer)

            response = await self._read_msg(reader)
            if response.get("status") != "accepted":
                task.status = "failed"
                task.error = response.get("error", "Transfer rejected")
                writer.close()
                await writer.wait_closed()
                return

            if not handshake_complete(self.identity, response, session):
                task.status = "failed"
                task.error = "E2E handshake failed — identity mismatch, possible MITM"
                writer.close()
                await writer.wait_closed()
                return

            for file_info in task.files:
                if task._cancelled:
                    break
                await self._send_file(reader, writer, file_info, task, session)

            if not task._cancelled:
                final = {
                    "type": "transfer_complete",
                    "verified": True,
                    "chains": task.chains,
                }
                await self._write_msg(writer, final)
                task.status = "completed"
                task.progress = 1.0
                task.verified = True
                task.end_time = time.time()

            writer.close()
            await writer.wait_closed()

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.end_time = time.time()

        finally:
            if task.id in self.active_transfers:
                del self.active_transfers[task.id]
            self.completed_transfers.append(task.to_dict())
            if self._progress_callback:
                await self._progress_callback(task)

    async def _send_file(self, reader, writer, file_info: dict, task: TransferTask, session: SessionCrypto):
        file_path = file_info["path"]
        file_size = file_info["size"]

        chain = TransferChain(task.id, file_info["name"], self.identity.signing_pub_b64)

        await self._write_msg(writer, {
            "type": "file_start",
            "name": file_info["name"],
            "size": file_size,
            "senderPub": self.identity.signing_pub_b64,
        })

        sent = 0
        with open(file_path, "rb") as f:
            while sent < file_size:
                if task._cancelled:
                    break

                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break

                block = chain.append_chunk(chunk, signer=self.identity)
                encrypted = session.encrypt(chunk)

                frame = {
                    "blockIndex": block.index,
                    "blockHash": block.block_hash(),
                    "prevHash": block.prev_hash,
                    "chunkHash": block.chunk_hash,
                    "sig": block.signature,
                }
                frame_bytes = json.dumps(frame).encode()
                writer.write(len(frame_bytes).to_bytes(4, "big"))
                writer.write(frame_bytes)
                writer.write(len(encrypted).to_bytes(4, "big"))
                writer.write(encrypted)
                await writer.drain()

                sent += len(chunk)
                task.bytes_transferred += len(chunk)
                task.progress = task.bytes_transferred / max(task.total_bytes, 1)

                elapsed = time.time() - task.start_time
                if elapsed > 0:
                    task.speed = task.bytes_transferred / elapsed

                if self._progress_callback:
                    await self._progress_callback(task)

                await asyncio.sleep(0)

        manifest = chain.to_manifest()
        task.chains.append(manifest)
        await self._write_msg(writer, {"type": "file_manifest", "manifest": manifest})

        ack = await self._read_msg(reader)
        if not ack.get("verified"):
            task.status = "failed"
            task.error = f"Receiver rejected: {ack.get('reason', 'verification failed')}"
            raise RuntimeError(task.error)

    async def receive_transfer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        task: Optional[TransferTask] = None
        try:
            header = await self._read_msg(reader)

            session = SessionCrypto(self.identity)
            accept, session = handshake_accept(self.identity, header)
            accept["status"] = "accepted"

            await self._write_msg(writer, accept)

            files = header.get("files", [])
            task = TransferTask(
                [
                    {"name": f.get("name", "file"), "size": f.get("size", 0), "path": "", "type": "application/octet-stream"}
                    for f in files
                ],
                target_ip=(writer.get_extra_info("peername") or ("", 0))[0],
                transfer_id=header.get("transferId") or None,
            )
            task.status = "transferring"
            task.from_device = header.get("senderName") or "Unknown device"
            task.to_device = "This Device"
            task.verified = True
            self.active_transfers[task.id] = task

            for file_info in files:
                await self._receive_file(reader, writer, file_info, session, task)

            final = await self._read_msg(reader)

            if task.status == "transferring":
                task.status = "completed"
                task.progress = 1.0
                task.end_time = time.time()

        except Exception as e:
            print(f"Receive error: {e}", flush=True)
            if task:
                task.status = "failed"
                task.error = str(e)
                task.end_time = time.time()
        finally:
            if task:
                if task.id in self.active_transfers:
                    del self.active_transfers[task.id]
                self.completed_transfers.append(task.to_dict())
                if self._progress_callback:
                    await self._progress_callback(task)
            writer.close()
            await writer.wait_closed()

    async def _receive_file(self, reader, writer, file_info: dict, session: SessionCrypto, task: Optional[TransferTask] = None):
        fh = await self._read_msg(reader)

        file_name = fh["name"]
        file_size = fh["size"]
        safe_name = os.path.basename(file_name)
        dest_path = os.path.join(self._receive_dir, safe_name)

        counter = 1
        while os.path.exists(dest_path):
            name, ext = os.path.splitext(safe_name)
            dest_path = os.path.join(self._receive_dir, f"{name}_{counter}{ext}")
            counter += 1

        decrypted_chunks: list[bytes] = []
        received = 0

        while received < file_size:
            frame_len = int.from_bytes(await reader.readexactly(4), "big")
            frame = json.loads(await reader.readexactly(frame_len))

            enc_len = int.from_bytes(await reader.readexactly(4), "big")
            enc_blob = await reader.readexactly(enc_len)

            chunk = session.decrypt(enc_blob)
            decrypted_chunks.append(chunk)
            received += len(chunk)

            if task:
                task.bytes_transferred += len(chunk)
                task.progress = task.bytes_transferred / max(task.total_bytes, 1)
                now = time.time()
                if now - task._last_emit > 0.25:
                    task._last_emit = now
                    if task.total_bytes > 0:
                        task.speed = task.bytes_transferred / max(now - task.start_time, 0.001)
                    if self._progress_callback:
                        await self._progress_callback(task)

        manifest_msg = await self._read_msg(reader)
        manifest = manifest_msg.get("manifest", {})

        verified, reason = TransferChain.verify_manifest(manifest, decrypted_chunks)

        with open(dest_path, "wb") as f:
            for chunk in decrypted_chunks:
                f.write(chunk)

        if verified:
            self.verified_transfers[manifest.get("transferId", "")] = {
                "fileName": safe_name,
                "destPath": dest_path,
                "merkleRoot": manifest.get("merkleRoot"),
            }
            print(f"VERIFIED+DECRYPTED: {safe_name} -> {dest_path}", flush=True)
        else:
            if task:
                task.verified = False
            print(f"INTEGRITY FAIL: {safe_name} — {reason}", flush=True)

        if task and task._last_emit > 0 and self._progress_callback:
            await self._progress_callback(task)

        await self._write_msg(writer, {
            "verified": verified,
            "reason": reason,
            "fileName": safe_name,
            "destPath": dest_path,
        })

    def _file_hash(self, file_path: str) -> str:
        h = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
        except Exception:
            pass
        return h.hexdigest()

    def cancel_transfer(self, transfer_id: str) -> bool:
        task = self.active_transfers.get(transfer_id)
        if task:
            task._cancelled = True
            task.status = "cancelled"
            return True
        return False

    def get_active_transfers(self) -> list[dict]:
        return [t.to_dict() for t in self.active_transfers.values()]

    @staticmethod
    async def _write_msg(writer, data: dict):
        raw = json.dumps(data).encode()
        writer.write(len(raw).to_bytes(4, "big"))
        writer.write(raw)
        await writer.drain()

    @staticmethod
    async def _read_msg(reader) -> dict:
        length = int.from_bytes(await reader.readexactly(4), "big")
        raw = await reader.readexactly(length)
        return json.loads(raw)
