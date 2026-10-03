import asyncio
import json
import os
import re
import time
import uuid
from typing import Optional, Callable

from crypto.blockchain import TransferChain, sha256_str
from crypto.e2e import (
    DeviceIdentityKeys,
    SessionCrypto,
    PeerTrustStore,
    handshake_offer,
    handshake_accept,
    handshake_complete,
)

CHUNK_SIZE = 65536

# Wire limits — every length-prefixed read is bounded (memory-DoS defense)
MAX_JSON_MSG = 256 * 1024
MAX_META_BLOB = 256 * 1024
MAX_FRAME_BLOB = 16 * 1024
MAX_CHUNK_BLOB = CHUNK_SIZE + 64
MAX_ACK_BLOB = 16 * 1024

# Timeouts — every socket read is bounded (slow-loris defense)
CONNECT_TIMEOUT = 10.0
HDR_TIMEOUT = 30.0
META_TIMEOUT = 30.0
DECISION_TIMEOUT = 90.0
STREAM_TIMEOUT = 120.0

TRANSFER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CHAT_RATE_LIMIT = 30          # messages per window
CHAT_RATE_WINDOW = 60.0       # seconds


def san(value, limit: int = 512) -> str:
    """Strip control characters from attacker-influenced strings (log/UI safety)."""
    text = "" if value is None else str(value)
    return "".join(ch for ch in text if ch.isprintable())[:limit]



def sentence(value, limit: int = 512) -> str:
    """UI-facing errors are sentence-cased (protocol.md §11)."""
    text = san(value, limit)
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1:]
    return text

def sanitize_filename(name: str) -> str:
    """Constrain a peer-supplied filename to a safe basename inside the receive dir."""
    name = str(name).replace("\\", "/")
    name = name.split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable())
    name = name.strip().lstrip(".").strip()
    if not name or name in (".", ".."):
        name = "file"

    stem, ext = os.path.splitext(name)
    reserved = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
    if stem.lower() in reserved:
        name = "_" + name
    if len(name) > 200:
        stem, ext = os.path.splitext(name)
        name = stem[:180] + ext[:20]
    return name


class IntegrityError(Exception):
    pass


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
        self.expected_device_id: Optional[str] = None
        self.declared_id: Optional[str] = None
        # sender: optional destination folder name the receiver maps to one of
        # ITS configured sync folders; receiver: resolved absolute dir.
        self.dest_folder: Optional[str] = None
        self.dest_dir: Optional[str] = None
        self.dest_paths: list[str] = []
        # receiver: files skipped by a partial accept (subset approval)
        self.skipped = 0
        self._last_emit = 0.0
        self._writer: Optional[asyncio.StreamWriter] = None

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
            # Phase 3 companion download: server-side locations of received
            # files (index-aligned with `files`); empty for sends, whose
            # source paths already live in files[i].path.
            "destPaths": list(self.dest_paths),
            # receiver: count of files the user chose not to accept
            "skipped": self.skipped,
        }


class TransferEngine:
    def __init__(self, identity: Optional[DeviceIdentityKeys] = None, device_name: str = "Unknown device"):
        self.active_transfers: dict[str, TransferTask] = {}
        self.completed_transfers: list[dict] = []
        self.verified_transfers: dict[str, dict] = {}
        self._progress_callback: Optional[Callable] = None
        self._chat_callback: Optional[Callable] = None
        self._security_callback: Optional[Callable] = None
        self._receive_dir = os.path.expanduser("~/Downloads/SyncFlow")
        self.identity = identity or DeviceIdentityKeys()
        self.device_name = device_name
        self.require_approval = True
        self._pending_approvals: dict[str, asyncio.Future] = {}
        self.trust = PeerTrustStore(
            os.path.join(os.path.dirname(os.path.abspath(self.identity.storage_dir)), "peers.json")
        )
        self._chat_times: dict[str, list[float]] = {}
        # Outbound concurrency: at most `max_concurrent` simultaneous sends
        self.max_concurrent = 4
        self._active_sends = 0
        self._slot_cond = asyncio.Condition()
        # Receiver-side sync folders: basename -> absolute path (validated,
        # inside home). An incoming destFolder only ever maps to one of these.
        self.sync_folders: dict[str, str] = {}
        os.makedirs(self._receive_dir, exist_ok=True)

    def set_receive_dir(self, path: str):
        self._receive_dir = path
        os.makedirs(self._receive_dir, exist_ok=True)

    def set_max_concurrent(self, n: int):
        try:
            n = int(n)
        except (TypeError, ValueError):
            return
        self.max_concurrent = max(1, min(n, 8))

    def set_sync_folders(self, folders: list):
        """Configure receiver-side sync folders (basename -> realpath).
        Only folders inside the user's home are accepted."""
        home = os.path.realpath(os.path.expanduser("~"))
        mapping: dict[str, str] = {}
        for entry in folders[:50]:
            if not isinstance(entry, dict):
                continue
            local = entry.get("localPath")
            if not isinstance(local, str) or not local:
                continue
            try:
                real = os.path.realpath(os.path.expanduser(local))
            except (OSError, ValueError):
                continue
            if real == home or not real.startswith(home + os.sep):
                continue
            name = san(os.path.basename(real), 64)
            if name and name not in (".", ".."):
                mapping.setdefault(name, real)
        self.sync_folders = mapping

    async def _acquire_slot(self, task: Optional["TransferTask"] = None) -> bool:
        async with self._slot_cond:
            while self._active_sends >= self.max_concurrent:
                if task is not None and task._cancelled:
                    return False
                try:
                    await asyncio.wait_for(self._slot_cond.wait(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
            self._active_sends += 1
            return True

    async def _release_slot(self):
        try:
            async with self._slot_cond:
                self._active_sends = max(0, self._active_sends - 1)
                self._slot_cond.notify()
        except Exception:
            pass

    def set_progress_callback(self, callback: Callable):
        self._progress_callback = callback

    async def _emit(self, task: "TransferTask"):
        """Progress/display failures must never fail or abort a transfer."""
        if self._progress_callback:
            try:
                await self._progress_callback(task)
            except Exception:
                pass

    def set_approval(self, enabled: bool):
        self.require_approval = enabled

    def set_security_callback(self, callback: Callable):
        self._security_callback = callback

    def set_chat_callback(self, callback: Callable):
        self._chat_callback = callback

    def approve_transfer(self, transfer_id: str, files: Optional[list] = None) -> bool:
        fut = self._pending_approvals.get(transfer_id)
        if fut and not fut.done():
            # Subset approval: the resolved value is either True (accept all)
            # or the list of accepted file indexes (validated by the WS layer,
            # range-checked again here before anything is framed).
            fut.set_result(list(files) if files else True)
            return True
        return False

    def decline_transfer(self, transfer_id: str) -> bool:
        fut = self._pending_approvals.get(transfer_id)
        if fut and not fut.done():
            fut.set_result("declined")
            return True
        return False

    async def _request_approval(self, task: "TransferTask", timeout: float = 60.0):
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending_approvals[task.id] = fut
        task.status = "awaiting"
        await self._emit(task)
        try:
            done, _ = await asyncio.wait({fut}, timeout=timeout)
            if not done:
                task.error = "Timed out waiting for approval"
                return "timeout"
            return fut.result()
        finally:
            self._pending_approvals.pop(task.id, None)

    # ------------------------------------------------------------------
    # Framing helpers (all bounded + timed)
    # ------------------------------------------------------------------

    @staticmethod
    async def _read_raw(reader, timeout: float, max_len: int) -> bytes:
        hdr = await asyncio.wait_for(reader.readexactly(4), timeout)
        n = int.from_bytes(hdr, "big")
        if n <= 0 or n > max_len:
            raise ValueError(f"frame size {n} out of range (max {max_len})")
        return await asyncio.wait_for(reader.readexactly(n), timeout)

    @classmethod
    async def _read_json(cls, reader, timeout: float, max_len: int = MAX_JSON_MSG) -> dict:
        raw = await cls._read_raw(reader, timeout, max_len)
        try:
            data = json.loads(raw)
        except Exception:
            raise ValueError("message is not valid JSON")
        if not isinstance(data, dict):
            raise ValueError("message must be a JSON object")
        return data

    @classmethod
    async def _read_blob(cls, reader, timeout: float, max_len: int) -> bytes:
        return await cls._read_raw(reader, timeout, max_len)

    @staticmethod
    async def _write_json(writer, data: dict, timeout: float):
        raw = json.dumps(data).encode()
        if len(raw) > MAX_JSON_MSG:
            raise ValueError("outgoing message too large")
        writer.write(len(raw).to_bytes(4, "big"))
        writer.write(raw)
        await asyncio.wait_for(writer.drain(), timeout)

    @staticmethod
    async def _write_blob(writer, blob: bytes, timeout: float, max_len: int):
        if len(blob) == 0 or len(blob) > max_len:
            raise ValueError(f"blob size {len(blob)} out of range")
        writer.write(len(blob).to_bytes(4, "big"))
        writer.write(blob)
        await asyncio.wait_for(writer.drain(), timeout)

    @classmethod
    async def _write_enc(cls, writer, session: SessionCrypto, payload: dict, timeout: float, max_len: int):
        await cls._write_blob(writer, session.encrypt(json.dumps(payload).encode()), timeout, max_len)

    @classmethod
    async def _read_enc(cls, reader, session: SessionCrypto, timeout: float, max_len: int) -> dict:
        blob = await cls._read_blob(reader, timeout, max_len)
        try:
            data = json.loads(session.decrypt(blob))
        except Exception:
            raise IntegrityError("encrypted message failed authentication")
        if not isinstance(data, dict):
            raise IntegrityError("encrypted message must be an object")
        return data

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send_files(self, file_paths: list[str], target_ip: str, target_port: int = 18974, transfer_id: Optional[str] = None, expected_device_id: Optional[str] = None, dest_folder: Optional[str] = None) -> TransferTask:
        files = []
        for fp in file_paths:
            if os.path.exists(fp) and not os.path.isdir(fp):
                stat = os.stat(fp)
                files.append({
                    "name": os.path.basename(fp),
                    "path": fp,
                    "size": stat.st_size,
                    "type": "application/octet-stream",
                })

        task = TransferTask(files, target_ip, target_port, transfer_id=transfer_id)
        task.expected_device_id = expected_device_id
        task.dest_folder = san(dest_folder, 64) if dest_folder else None
        self.active_transfers[task.id] = task
        asyncio.create_task(self._execute_transfer(task))
        return task

    async def _execute_transfer(self, task: TransferTask):
        writer: Optional[asyncio.StreamWriter] = None
        slot = False
        try:
            task.status = "pending"
            # Wait for a concurrency slot before opening the connection
            if not await self._acquire_slot(task):
                task.status = "cancelled"
                task.error = task.error or "Cancelled"
                return
            slot = True
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(task.target_ip, task.target_port), CONNECT_TIMEOUT
            )
            task._writer = writer

            offer, session = handshake_offer(self.identity)
            await self._write_json(writer, offer, HDR_TIMEOUT)

            response = await self._read_json(reader, HDR_TIMEOUT)

            # Verify identity BEFORE trusting anything in the response
            if not handshake_complete(self.identity, response, session, initiator=True):
                task.status = "failed"
                task.error = "E2E handshake failed — identity mismatch or MITM detected"
                return

            # Bind the connection to the device we meant to reach: the
            # advertised deviceId is a hash of the peer's signing key, so a
            # different responder cannot claim to be that device.
            if task.expected_device_id:
                actual_id = sha256_str(str(response.get("signingPub", "")))[:32]
                if actual_id != task.expected_device_id:
                    task.status = "failed"
                    task.error = "Peer identity does not match the selected device (possible MITM)"
                    return

            pin_ok, pin_why = self.trust.check(
                f"{task.target_ip}:{task.target_port}", response.get("signingPub", "")
            )
            if not pin_ok:
                if self._security_callback:
                    await self._security_callback({"type": "identity_changed", "key": f"{task.target_ip}:{task.target_port}", "reason": pin_why})
                task.status = "failed"
                task.error = sentence(pin_why)
                return

            # Response status is now authenticated — safe to act on
            if response.get("status") != "accepted":
                task.status = "failed"
                task.error = sentence(response.get("error", "Transfer rejected"))
                return

            meta = {
                "kind": "transfer",
                "transferId": task.id,
                "senderName": san(self.device_name, 64),
                "files": [
                    {"name": sanitize_filename(os.path.basename(f["name"])), "size": f["size"]}
                    for f in task.files
                ],
            }
            if task.dest_folder:
                meta["destFolder"] = task.dest_folder
            await self._write_enc(writer, session, meta, STREAM_TIMEOUT, MAX_META_BLOB)

            decision = await self._read_enc(reader, session, DECISION_TIMEOUT, MAX_META_BLOB)
            if decision.get("status") != "accepted":
                reason = decision.get("reason", "user")
                task.error = sentence(decision.get("error") or "Transfer declined by receiver")
                task.status = "cancelled" if reason == "user" else "failed"
                return

            # Subset approval: receiver named the indexes it accepted.
            # Shape was validated receiver-side before framing; anything
            # malformed here is a protocol violation -> fail closed.
            to_send = task.files
            sel = decision.get("files")
            if sel is not None:
                valid = (
                    isinstance(sel, list) and sel
                    and all(isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in sel)
                    and len(set(sel)) == len(sel)
                    and max(sel) < len(task.files)
                )
                if not valid:
                    task.status = "failed"
                    task.error = "Invalid file selection"
                    return
                to_send = [task.files[i] for i in sorted(sel)]
                task.skipped = len(task.files) - len(to_send)
                task.total_bytes = sum(f.get("size", 0) for f in to_send)

            task.status = "transferring"
            for file_info in to_send:
                if task._cancelled:
                    break
                await self._send_file(reader, writer, file_info, task, session)

            if not task._cancelled:
                await self._write_enc(
                    writer, session,
                    {"type": "transfer_complete", "verified": True},
                    STREAM_TIMEOUT, MAX_ACK_BLOB,
                )
                task.status = "completed"
                task.progress = 1.0
                task.verified = True

        except asyncio.TimeoutError:
            task.status = "failed"
            task.error = "Connection timed out"
        except asyncio.CancelledError:
            task.status = "cancelled"
            task.error = task.error or "Cancelled"
            raise
        except (ConnectionError, asyncio.IncompleteReadError, OSError) as e:
            if task._cancelled:
                task.status = "cancelled"
            else:
                task.status = "failed"
                task.error = "Connection lost" if isinstance(e, (ConnectionError, asyncio.IncompleteReadError)) else sentence(str(e))
        except Exception as e:
            task.status = "failed"
            task.error = sentence(str(e))
        finally:
            task.end_time = time.time()
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            if task.id in self.active_transfers:
                del self.active_transfers[task.id]
            self.completed_transfers.append(task.to_dict())
            if self._progress_callback:
                try:
                    await self._progress_callback(task)
                except Exception:
                    pass
            if slot:
                await self._release_slot()

    async def _send_file(self, reader, writer, file_info: dict, task: TransferTask, session: SessionCrypto):
        file_path = file_info["path"]
        file_size = file_info["size"]
        # Same canonical name the receiver will derive: signed headers,
        # metadata and the on-disk name must all agree.
        file_name = sanitize_filename(os.path.basename(file_info["name"]))

        chain = TransferChain(task.id, file_name, self.identity.signing_pub_b64)

        await self._write_enc(writer, session, {
            "type": "file_meta",
            "name": file_name,
            "size": file_size,
        }, STREAM_TIMEOUT, MAX_META_BLOB)

        sent = 0
        with open(file_path, "rb") as f:
            while sent < file_size:
                if task._cancelled:
                    break

                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break

                block = chain.append_chunk(chunk, signer=self.identity)
                frame = {"header": block.header(), "sig": block.signature}
                enc_frame = session.encrypt(json.dumps(frame).encode())
                enc_chunk = session.encrypt(chunk)

                await self._write_blob(writer, enc_frame, STREAM_TIMEOUT, MAX_FRAME_BLOB)
                await self._write_blob(writer, enc_chunk, STREAM_TIMEOUT, MAX_CHUNK_BLOB)

                sent += len(chunk)
                task.bytes_transferred += len(chunk)
                task.progress = task.bytes_transferred / max(task.total_bytes, 1)

                elapsed = time.time() - task.start_time
                if elapsed > 0:
                    task.speed = task.bytes_transferred / elapsed

                if time.time() - task._last_emit > 0.25:
                    task._last_emit = time.time()
                    await self._emit(task)

        await self._write_enc(writer, session, chain.wire_manifest(), STREAM_TIMEOUT, MAX_META_BLOB)
        task.chains.append(chain.wire_manifest())

        ack = await self._read_enc(reader, session, STREAM_TIMEOUT, MAX_ACK_BLOB)
        if not ack.get("verified"):
            task.status = "failed"
            task.error = sentence(ack.get("reason", "verification failed"))
            raise IntegrityError(task.error)

    # ------------------------------------------------------------------
    # Chat (E2E relayed to peers over the transfer port)
    # ------------------------------------------------------------------

    async def send_chat(self, target_ip: str, text: str, target_port: int = 18974, expected_device_id: Optional[str] = None) -> bool:
        reader = writer = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(target_ip, target_port), CONNECT_TIMEOUT
            )
            offer, session = handshake_offer(self.identity)
            await self._write_json(writer, offer, HDR_TIMEOUT)

            response = await self._read_json(reader, HDR_TIMEOUT)
            if not handshake_complete(self.identity, response, session, initiator=True):
                print(f"Chat: handshake failed for {target_ip}", flush=True)
                return False
            if expected_device_id:
                actual_id = sha256_str(str(response.get("signingPub", "")))[:32]
                if actual_id != expected_device_id:
                    print(f"Chat: peer identity mismatch for {target_ip}", flush=True)
                    return False
            pin_ok, pin_why = self.trust.check(f"{target_ip}:{target_port}", response.get("signingPub", ""))
            if not pin_ok:
                if self._security_callback:
                    await self._security_callback({"type": "identity_changed", "key": f"{target_ip}:{target_port}", "reason": pin_why})
                print(f"Chat: {san(pin_why)}", flush=True)
                return False
            if response.get("status") != "accepted":
                return False

            meta = {
                "kind": "chat",
                "text": text,
                "fromDevice": san(self.device_name, 64),
                "ts": time.time(),
            }
            await self._write_enc(writer, session, meta, STREAM_TIMEOUT, MAX_META_BLOB)
            ack = await self._read_enc(reader, session, STREAM_TIMEOUT, MAX_ACK_BLOB)
            return bool(ack.get("ok"))
        except Exception as e:
            print(f"Chat relay to {target_ip} failed: {san(e, 120)}", flush=True)
            return False
        finally:
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    def _chat_rate_limited(self, ip: str) -> bool:
        now = time.time()
        times = self._chat_times.setdefault(ip, [])
        times[:] = [t for t in times if now - t < CHAT_RATE_WINDOW]
        if len(times) >= CHAT_RATE_LIMIT:
            return True
        times.append(now)
        return False

    async def receive_transfer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        task: Optional[TransferTask] = None
        src_ip = (writer.get_extra_info("peername") or ("0.0.0.0", 0))[0]
        try:
            # Step 1: authenticated handshake offer (no filenames yet)
            offer = await self._read_json(reader, HDR_TIMEOUT)
            if offer.get("type") != "e2e_offer":
                raise ValueError("expected e2e_offer handshake")

            pin_ok, pin_why = self.trust.check(src_ip, offer.get("signingPub", ""))
            if not pin_ok:
                if self._security_callback:
                    await self._security_callback({"type": "identity_changed", "key": src_ip, "reason": pin_why})
                raise ValueError(pin_why)

            accept, session = handshake_accept(self.identity, offer)  # verifies sig + freshness
            await self._write_json(writer, {**accept, "status": "accepted"}, HDR_TIMEOUT)
            signer_pub = offer["signingPub"]

            # Step 2: encrypted metadata (filenames/sender never plaintext)
            meta = await self._read_enc(reader, session, META_TIMEOUT, MAX_META_BLOB)
            kind = meta.get("kind")

            if kind == "chat":
                await self._handle_incoming_chat(meta, offer, session, writer, src_ip)
                return

            if kind != "transfer":
                raise ValueError("unknown encrypted payload kind")

            sender_name = san(meta.get("senderName", "Unknown device"), 64)
            self.trust.check(src_ip, signer_pub, name=sender_name)  # refresh display name

            raw_files = meta.get("files")
            if not isinstance(raw_files, list) or not raw_files:
                raise ValueError("transfer declared no files")
            if len(raw_files) > 1000:
                raise ValueError("too many files in one transfer")

            files = []
            for entry in raw_files[:1000]:
                if not isinstance(entry, dict):
                    raise ValueError("invalid file entry")
                size = entry.get("size", 0)
                if not isinstance(size, int) or size < 0:
                    raise ValueError("invalid file size")
                files.append({
                    "name": sanitize_filename(str(entry.get("name", "file"))),
                    "size": size,
                    "path": "",
                    "type": "application/octet-stream",
                })

            transfer_id = str(meta.get("transferId", ""))
            if not TRANSFER_ID_RE.match(transfer_id):
                transfer_id = str(uuid.uuid4())

            # Sync-folder routing: the sender may name a destination folder,
            # but it only ever resolves against folders THIS device configured
            # (exact basename match). Anything unknown falls back to the
            # download directory — a peer can never choose an arbitrary path.
            dest_folder = san(meta.get("destFolder", ""), 64)
            resolved_dir = self.sync_folders.get(dest_folder) if dest_folder else None

            # Unique receive id: sender's id is only advisory (never trusted
            # for bookkeeping), so concurrent receives can never collide and
            # received ids can never clash with local send ids.
            task = TransferTask(
                files, target_ip=src_ip, transfer_id=f"in-{uuid.uuid4().hex[:16]}"
            )
            task.declared_id = transfer_id
            task.dest_dir = resolved_dir
            task.dest_folder = dest_folder or None
            task.from_device = sender_name
            task.to_device = "This Device"
            task.verified = False
            task._writer = writer
            self.active_transfers[task.id] = task

            selected: Optional[list] = None
            if self.require_approval:
                decision = await self._request_approval(task)
                if isinstance(decision, list):
                    # Defence in depth: WS validated shape (non-empty, ints,
                    # unique, >= 0); range can only be checked against the
                    # declared file count, which only we know.
                    if decision and len(set(decision)) == len(decision) and max(decision) < len(files):
                        selected = sorted(decision)
                        decision = True
                    else:
                        decision = "declined"
                if decision is not True:
                    if decision == "timeout":
                        task.status = "failed"
                        error = task.error or "Timed out waiting for approval"
                        reason = "timeout"
                    else:
                        task.status = "cancelled"
                        task.error = "Transfer declined by receiver"
                        error = task.error
                        reason = "user"
                    task.end_time = time.time()
                    await self._write_enc(
                        writer, session,
                        {"status": "declined", "reason": reason, "error": error},
                        HDR_TIMEOUT, MAX_META_BLOB,
                    )
                    return
                if task._cancelled:
                    await self._write_enc(
                        writer, session,
                        {"status": "declined", "reason": "user", "error": "Transfer declined by receiver"},
                        HDR_TIMEOUT, MAX_META_BLOB,
                    )
                    task.status = "cancelled"
                    task.end_time = time.time()
                    return

            accept_frame = {"status": "accepted"}
            if selected is not None:
                accept_frame["files"] = selected
            await self._write_enc(
                writer, session, accept_frame, HDR_TIMEOUT, MAX_META_BLOB
            )
            task.status = "transferring"

            if selected is not None and len(selected) < len(files):
                # Partial accept: the sender transmits exactly these indexes,
                # so task bookkeeping (files, totals, destPaths alignment)
                # narrows to the accepted set.
                task.skipped = len(files) - len(selected)
                files = [files[i] for i in selected]
                task.files = files
                task.total_bytes = sum(f.get("size", 0) for f in files)

            all_verified = True
            for expected in files:
                ok = await self._receive_file(reader, writer, expected, session, task, signer_pub)
                if not ok:
                    all_verified = False
                    break

            if all_verified and not task._cancelled:
                final = await self._read_enc(reader, session, STREAM_TIMEOUT, MAX_ACK_BLOB)
                if final.get("type") == "transfer_complete" and task.bytes_transferred == task.total_bytes:
                    task.status = "completed"
                    task.progress = 1.0
                    task.verified = True
                else:
                    task.status = "failed"
                    task.error = "Transfer completion mismatch"

        except IntegrityError as e:
            print(f"Integrity failure from {src_ip}: {san(e, 160)}", flush=True)
            if task:
                if task._cancelled:
                    task.status = "cancelled"
                else:
                    task.status = "failed"
                    task.error = sentence(e)
                    task.verified = False
        except asyncio.TimeoutError:
            if task:
                task.status = "cancelled" if task._cancelled else "failed"
                if task.status == "failed":
                    task.error = "Connection timed out"
            else:
                print(f"Handshake timeout from {src_ip}", flush=True)
        except Exception as e:
            print(f"Receive error from {src_ip}: {type(e).__name__}: {san(e, 160)}", flush=True)
            if task:
                if task._cancelled:
                    task.status = "cancelled"
                else:
                    task.status = "failed"
                    task.error = sentence(e) or "Transfer failed"
        finally:
            if task:
                task.end_time = task.end_time or time.time()
                if task.id in self.active_transfers:
                    del self.active_transfers[task.id]
                self.completed_transfers.append(task.to_dict())
                if self._progress_callback:
                    try:
                        await self._progress_callback(task)
                    except Exception:
                        pass
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_incoming_chat(self, meta: dict, offer: dict, session: SessionCrypto, writer, src_ip: str):
        try:
            text = meta.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty chat message")
            text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")[:4000]
            if not text.strip():
                raise ValueError("empty chat message")
            if self._chat_rate_limited(src_ip):
                await self._write_enc(writer, session, {"ok": False, "error": "Rate limited"}, HDR_TIMEOUT, MAX_ACK_BLOB)
                return

            sender_pub = offer.get("signingPub", "")
            device_id = sha256_str(sender_pub)[:32]
            msg_hash = sha256_str(text + str(meta.get("ts", "")) + device_id)
            message = {
                "type": "chat:message",
                "id": msg_hash[:16],
                "fromDevice": san(meta.get("fromDevice", "Unknown device"), 64),
                "deviceId": device_id,
                "text": text,
                "timestamp": float(meta.get("ts")) if isinstance(meta.get("ts"), (int, float)) else time.time(),
                "hash": msg_hash,
            }
            if self._chat_callback:
                await self._chat_callback(message)
            await self._write_enc(writer, session, {"ok": True}, HDR_TIMEOUT, MAX_ACK_BLOB)
        except Exception as e:
            print(f"Chat receive error from {src_ip}: {type(e).__name__}: {san(e, 120)}", flush=True)

    async def _receive_file(
        self,
        reader,
        writer,
        expected: dict,
        session: SessionCrypto,
        task: TransferTask,
        signer_pub: str,
    ) -> bool:
        """Stream-verify one file. Writes the destination ONLY after full
        verification (signatures, chain, merkle, size) succeeds."""
        expected_name = expected["name"]
        expected_size = expected["size"]

        file_meta = await self._read_enc(reader, session, STREAM_TIMEOUT, MAX_META_BLOB)
        if file_meta.get("type") != "file_meta":
            raise IntegrityError("expected file metadata")
        if sanitize_filename(str(file_meta.get("name", ""))) != expected_name or file_meta.get("size") != expected_size:
            raise IntegrityError("file metadata mismatch with declared transfer")

        base_dir = task.dest_dir or self._receive_dir
        dest_path = os.path.join(base_dir, expected_name)

        counter = 1
        while os.path.exists(dest_path):
            stem, ext = os.path.splitext(expected_name)
            dest_path = os.path.join(base_dir, f"{stem}_{counter}{ext}")
            counter += 1

        # Confinement check AFTER the unique-name loop: the final path must
        # stay inside the chosen directory (symlink escape defense).
        real_dir = os.path.realpath(base_dir)
        real_dest = os.path.realpath(dest_path)
        if not (real_dest == real_dir or real_dest.startswith(real_dir + os.sep)):
            raise IntegrityError("destination escapes receive directory")

        tmp_path = dest_path + f".part-{uuid.uuid4().hex[:8]}"
        block_hashes: list[str] = []
        prev_hash = TransferChain.GENESIS_HASH
        received = 0
        last_emit = 0.0

        try:
            with open(tmp_path, "wb") as out:
                while True:
                    blob = await self._read_blob(reader, STREAM_TIMEOUT, MAX_FRAME_BLOB)
                    try:
                        frame = json.loads(session.decrypt(blob))
                    except Exception:
                        raise IntegrityError("frame failed authentication")
                    if not isinstance(frame, dict):
                        raise IntegrityError("invalid frame")

                    if frame.get("type") == "file_manifest":
                        manifest = frame
                        break
                    if "header" not in frame:
                        raise IntegrityError("unexpected message in file stream")

                    data_blob = await self._read_blob(reader, STREAM_TIMEOUT, MAX_CHUNK_BLOB)
                    try:
                        chunk = session.decrypt(data_blob)
                    except Exception:
                        raise IntegrityError("chunk failed authentication")

                    ok, reason, block_hash = TransferChain.verify_chunk(
                        str(frame.get("header", "")),
                        str(frame.get("sig", "")),
                        chunk,
                        expected_index=len(block_hashes),
                        expected_prev=prev_hash,
                        expected_name=expected_name,
                        expected_signer=signer_pub,
                        verify_fn=self.identity.verify,
                    )
                    if not ok:
                        raise IntegrityError(reason)

                    block_hashes.append(block_hash)
                    prev_hash = block_hash
                    out.write(chunk)
                    received += len(chunk)
                    if received > expected_size:
                        raise IntegrityError("received more data than declared size")

                    task.bytes_transferred += len(chunk)
                    task.progress = task.bytes_transferred / max(task.total_bytes, 1)
                    now = time.time()
                    if now - last_emit > 0.25:
                        last_emit = now
                        task._last_emit = now
                        task.speed = task.bytes_transferred / max(now - task.start_time, 0.001)
                        await self._emit(task)

            # Full verification before the file becomes visible
            if received != expected_size:
                raise IntegrityError(f"size mismatch: got {received} bytes, declared {expected_size}")
            if manifest.get("blockCount") != len(block_hashes):
                raise IntegrityError("manifest block count mismatch")
            expected_chain = block_hashes[-1] if block_hashes else TransferChain.GENESIS_HASH
            if manifest.get("chainHash") != expected_chain:
                raise IntegrityError("manifest chain hash mismatch")
            hash_list = list(block_hashes)
            while len(hash_list) > 1:
                if len(hash_list) % 2 == 1:
                    hash_list.append(hash_list[-1])
                hash_list = [
                    sha256_str(hash_list[i] + hash_list[i + 1])
                    for i in range(0, len(hash_list), 2)
                ]
            expected_merkle = hash_list[0] if hash_list else sha256_str("empty")
            if manifest.get("merkleRoot") != expected_merkle:
                raise IntegrityError("merkle root mismatch")
            if manifest.get("senderPubkey") not in (signer_pub, self.identity.signing_pub_b64):
                raise IntegrityError("manifest sender key mismatch")

            os.replace(tmp_path, dest_path)
            task.dest_paths.append(dest_path)
            if manifest.get("transferId"):
                self.verified_transfers[str(manifest.get("transferId"))] = {
                    "fileName": expected_name,
                    "destPath": dest_path,
                    "merkleRoot": manifest.get("merkleRoot"),
                }
            print(f"VERIFIED+DECRYPTED: {san(expected_name, 120)} -> {san(dest_path, 200)}", flush=True)
            await self._write_enc(writer, session, {"verified": True, "destPath": dest_path}, STREAM_TIMEOUT, MAX_ACK_BLOB)
            return True

        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass
            reason = san(e, 200) or "verification failed"
            try:
                await self._write_enc(
                    writer, session,
                    {"verified": False, "reason": reason},
                    STREAM_TIMEOUT, MAX_ACK_BLOB,
                )
            except Exception:
                pass
            if isinstance(e, IntegrityError):
                raise
            raise IntegrityError(reason)

    # ------------------------------------------------------------------

    def cancel_transfer(self, transfer_id: str) -> bool:
        task = self.active_transfers.get(transfer_id)
        if task:
            prev_status = task.status
            task._cancelled = True
            task.status = "cancelled"
            fut = self._pending_approvals.get(transfer_id)
            if fut and not fut.done():
                fut.set_result("declined")
            # Close the socket only while data streams; during approval keep
            # it open so the receive loop can deliver a clean decline.
            if task._writer and prev_status not in ("pending", "awaiting"):
                try:
                    task._writer.close()
                except Exception:
                    pass
            return True
        return False

    def get_active_transfers(self) -> list[dict]:
        return [t.to_dict() for t in self.active_transfers.values()]
