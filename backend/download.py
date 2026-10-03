"""Phase 3 chunked companion download: desktop -> phone WS receive.

The desktop already holds the bytes of completed transfers on disk; a
companion that mirrors the transfer list can pull any of them back over
the SAME authenticated WebSocket, in the reverse direction of upload.py:

  transfer:download         {transferId, fileIndex}
    <- transfer:download:ready      {transferId, fileIndex, name, size,
                                      chunkSize}
  <binary frames>           exactly `size` bytes, in order
    <- transfer:download:progress   {transferId, fileIndex, received,
                                      size} (throttled)
    <- transfer:download:file-done  {transferId, fileIndex, received,
                                      sha256}
  transfer:download:cancel  {transferId}
    -> transfer:download:cancelled  {transferId, success}

Security (docs/security-audit.md rules apply to these frames too):
  * dispatch happens only after the Phase 0 auth gate in ws_bridge
  * the path is resolved SERVER-SIDE from the engine's task table — the
    client supplies only a transferId + fileIndex, never a path
  * a file must be fully present on disk (received files are only listed
    once the engine verified and renamed them); vanished files fail clean
  * one active stream per connection AND per transferId; any violation
    returns an error frame but keeps the connection alive
  * sockets that vanish mid-stream simply cancel the reader task
"""
import asyncio
import hashlib
import os
import time
from typing import Optional

from transfer.engine import TRANSFER_ID_RE, san

DOWNLOAD_JSON_TYPES = {"transfer:download", "transfer:download:cancel"}

CHUNK_SIZE = 256 * 1024
PROGRESS_INTERVAL = 0.5  # seconds between transfer:download:progress frames
MAX_FILE_INDEX = 1000


class _Stream:
    __slots__ = ("transfer_id", "file_index", "ws", "path", "name", "size",
                 "sent", "cancelled", "task")

    def __init__(self, transfer_id, file_index, ws, path, name, size):
        self.transfer_id = transfer_id
        self.file_index = file_index
        self.ws = ws
        self.path = path
        self.name = name
        self.size = size
        self.sent = 0
        self.cancelled = False
        self.task = None


class DownloadManager:
    """Owns per-connection download streams (read-only, no staging)."""

    def __init__(self, ws_bridge, transfer_engine):
        self.bridge = ws_bridge
        self.engine = transfer_engine
        self.active: dict = {}        # ws -> _Stream
        self.by_transfer: dict = {}   # transferId -> _Stream

    # ---------------------------------------------------------------- wiring
    async def handle(self, ws, data: dict) -> Optional[dict]:
        """Dispatch a download control frame; returns an error reply (or None).

        The `ready` frame is NOT returned — it is sent by the stream task
        itself so ordering (ready before any binary) is guaranteed even for
        tiny files that stream immediately.
        """
        msg_type = data.get("type")
        if msg_type == "transfer:download":
            return await self._start(ws, data)
        if msg_type == "transfer:download:cancel":
            return self._cancel(ws, data)
        return None

    def is_active(self, ws) -> bool:
        return ws in self.active

    def cancel(self, transfer_id: str) -> bool:
        """command:cancel fallback: stop an in-flight companion download."""
        stream = self.by_transfer.get(transfer_id)
        if stream is None:
            return False
        stream.cancelled = True
        return True

    def detach(self, ws):
        """Connection closed: stop pushing; the read task cleans up after it."""
        stream = self.active.get(ws)
        if stream is not None:
            stream.cancelled = True

    # -------------------------------------------------------------- handlers
    async def _start(self, ws, data: dict) -> Optional[dict]:
        transfer_id = data.get("transferId")
        if not isinstance(transfer_id, str) or not TRANSFER_ID_RE.match(transfer_id):
            return {"type": "error", "error": "Invalid transfer id",
                    "transferId": transfer_id if isinstance(transfer_id, str) else None}
        file_index = data.get("fileIndex")
        if (not isinstance(file_index, int) or isinstance(file_index, bool)
                or file_index < 0 or file_index >= MAX_FILE_INDEX):
            return {"type": "error", "error": "Invalid file index",
                    "transferId": transfer_id}
        if ws in self.active:
            return {"type": "error", "error": "Download already in progress",
                    "transferId": transfer_id}
        if transfer_id in self.by_transfer:
            return {"type": "error", "error": "Transfer is already being downloaded",
                    "transferId": transfer_id}

        try:
            path, name, size = self._lookup(transfer_id, file_index)
        except ValueError as e:
            return {"type": "error", "error": str(e), "transferId": transfer_id}

        stream = _Stream(transfer_id, file_index, ws, path, name, size)
        self.active[ws] = stream
        self.by_transfer[transfer_id] = stream
        stream.task = asyncio.ensure_future(self._stream(stream))
        return None  # ready frame is sent by _stream (ordering guarantee)

    def _cancel(self, ws, data: dict) -> dict:
        transfer_id = data.get("transferId")
        if not isinstance(transfer_id, str) or not TRANSFER_ID_RE.match(transfer_id):
            return {"type": "error", "error": "Invalid transfer id",
                    "transferId": transfer_id if isinstance(transfer_id, str) else None}
        stream = self.by_transfer.get(transfer_id)
        success = stream is not None and stream.ws is ws
        if success:
            stream.cancelled = True
        return {"type": "transfer:download:cancelled", "transferId": transfer_id,
                "success": success}

    def _lookup(self, transfer_id: str, file_index: int):
        """Resolve (path, name, size) server-side; raise ValueError if unusable."""
        task = self.engine.active_transfers.get(transfer_id)
        if task is not None:
            dests = task.dest_paths
            files = task.files
        else:
            entry = None
            for candidate in reversed(self.engine.completed_transfers):
                if candidate.get("id") == transfer_id:
                    entry = candidate
                    break
            if entry is None:
                raise ValueError("Transfer not found")
            dests = entry.get("destPaths") or []
            files = entry.get("files") or []

        if file_index >= len(files):
            raise ValueError("File index out of range")
        fmeta = files[file_index] if isinstance(files[file_index], dict) else {}

        # Received files: dest_paths (verified locations). Sent files:
        # the original source path — but only if it still exists on disk.
        path = None
        if file_index < len(dests) and isinstance(dests[file_index], str):
            path = dests[file_index]
        elif isinstance(fmeta.get("path"), str) and fmeta.get("path"):
            path = fmeta["path"]
        if not path:
            raise ValueError("File is not available on the desktop yet")

        if not os.path.isfile(path):
            raise ValueError("File no longer exists on the desktop")

        name = str(fmeta.get("name") or "") or os.path.basename(path)
        try:
            size = os.path.getsize(path)
        except OSError as e:
            raise ValueError(f"Cannot read file: {san(e, 120)}")
        return path, name, size

    # --------------------------------------------------------------- helpers
    async def _stream(self, stream: _Stream):
        try:
            # Ordering guarantee: this frame precedes every binary frame.
            await self.bridge._safe_send(stream.ws, {
                "type": "transfer:download:ready",
                "transferId": stream.transfer_id,
                "fileIndex": stream.file_index,
                "name": stream.name,
                "size": stream.size,
                "chunkSize": CHUNK_SIZE,
            })
            digest = hashlib.sha256()
            last_progress = time.monotonic()
            chunks_sent = 0
            with open(stream.path, "rb") as fh:
                while not stream.cancelled:
                    chunk = fh.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    try:
                        await stream.ws.send(chunk)
                    except Exception:
                        stream.cancelled = True  # socket vanished mid-push
                        break
                    digest.update(chunk)
                    stream.sent += len(chunk)
                    chunks_sent += 1
                    if chunks_sent % 8 == 0:
                        # Yield the loop every ~2 MB: a large push in one
                        # tight task would starve this connection's read
                        # loop, delaying cancel/detach control frames until
                        # the whole file drained.
                        await asyncio.sleep(0)
                    now = time.monotonic()
                    if now - last_progress >= PROGRESS_INTERVAL:
                        last_progress = now
                        await self.bridge._safe_send(stream.ws, {
                            "type": "transfer:download:progress",
                            "transferId": stream.transfer_id,
                            "fileIndex": stream.file_index,
                            "received": stream.sent,
                            "size": stream.size,
                        })
            if not stream.cancelled:
                await self.bridge._safe_send(stream.ws, {
                    "type": "transfer:download:file-done",
                    "transferId": stream.transfer_id,
                    "fileIndex": stream.file_index,
                    "received": stream.sent,
                    "size": stream.size,
                    "sha256": digest.hexdigest(),
                })
        except Exception as e:
            print(f"Download stream error: {san(e, 160)}", flush=True)
        finally:
            if self.active.get(stream.ws) is stream:
                del self.active[stream.ws]
            if self.by_transfer.get(stream.transfer_id) is stream:
                del self.by_transfer[stream.transfer_id]
