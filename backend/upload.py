"""Phase 3 chunked companion upload: phone → desktop WS → transfer engine.

The companion renderer holds the bytes (a File picked in the webview) but
the backend has no path to them, so content streams over the already
authenticated WebSocket in 256 KiB binary frames while JSON control frames
drive the state machine:

  transfer:upload        announce a file {transferId, seq, name, size,
                           batchTotalBytes, targetIp, ...}
    <- transfer:upload:ready     {transferId, seq, chunkSize}
  <binary frames>        exactly `size` bytes, in order
  transfer:upload:end    {transferId, seq}
    <- transfer:upload:file-done {transferId, seq}
  ... next file (seq + 1) ...
  transfer:upload:finish {transferId}
    -> transfer:new  (files handed to the engine, which delivers them to the
                      target peer over the normal TCP path)

Security (docs/security-audit.md rules apply to these frames too):
  * dispatch happens only after the Phase 0 auth gate in ws_bridge
  * names are re-sanitized to a basename (no traversal, control chars)
  * sizes/sequence numbers strictly enforced; any violation aborts the
    session (staging deleted) but keeps the connection alive
  * one active session per connection; transferIds are unique while staged
  * staging lives in a 0700 dir under SYNCFLOW_HOME (or ~/.syncflow) and is
    removed on finish, cancel, or disconnect
"""
import asyncio
import os
import re
import shutil
import time
from typing import Optional

from transfer.engine import TRANSFER_ID_RE, sanitize_filename, san

# Keep in sync with main.py (cannot import: main imports this module).
TARGET_HOST_RE = re.compile(r"^[A-Za-z0-9.\-:]{1,64}$")
MAX_FILES_PER_UPLOAD = 1000

UPLOAD_JSON_TYPES = {"transfer:upload", "transfer:upload:end", "transfer:upload:finish"}

CHUNK_SIZE = 256 * 1024
MAX_UPLOAD_FILE = int(os.environ.get("SYNCFLOW_MAX_UPLOAD_MB", "8192")) * 1024 * 1024
MAX_UPLOAD_BATCH = MAX_FILES_PER_UPLOAD * MAX_UPLOAD_FILE
PROGRESS_INTERVAL = 0.5  # seconds between transfer:progress broadcasts


class _Session:
    __slots__ = (
        "transfer_id", "ws", "dir", "files", "next_seq", "fh", "open_seq",
        "open_name", "open_size", "open_received", "target_ip", "target_port",
        "target_device_id", "dest_folder", "batch_total", "bytes_received",
        "start_time", "_last_progress",
    )

    def __init__(self, transfer_id, ws, dirpath, target_ip, target_port,
                 target_device_id, dest_folder, batch_total):
        self.transfer_id = transfer_id
        self.ws = ws
        self.dir = dirpath
        self.files = []          # [{name, size, path, type}]
        self.next_seq = 0        # next acceptable announce/end seq
        self.fh = None           # open staging file while a frame run is active
        self.open_seq = None
        self.open_name = ""
        self.open_size = 0
        self.open_received = 0
        self.target_ip = target_ip
        self.target_port = target_port
        self.target_device_id = target_device_id
        self.dest_folder = dest_folder
        self.batch_total = batch_total
        self.bytes_received = 0
        self.start_time = time.time()
        self._last_progress = 0.0

    @property
    def active_file(self) -> bool:
        return self.fh is not None


class UploadManager:
    """Owns per-connection upload sessions and the staging directory."""

    def __init__(self, ws_bridge, transfer_engine):
        self.bridge = ws_bridge
        self.engine = transfer_engine
        home = os.environ.get("SYNCFLOW_HOME") or os.path.expanduser("~/.syncflow")
        self.staging_root = os.path.join(home, "staging")
        self.sessions: dict[str, _Session] = {}   # transferId -> session
        self.by_ws: dict = {}                     # ws -> transferId

    # ---------------------------------------------------------------- wiring
    async def handle(self, ws, data: dict) -> Optional[dict]:
        """Dispatch an upload control frame; returns the reply (or None)."""
        msg_type = data.get("type")
        if msg_type == "transfer:upload":
            return await self._announce(ws, data)
        if msg_type == "transfer:upload:end":
            return await self._end(ws, data)
        if msg_type == "transfer:upload:finish":
            return await self._finish(ws, data)
        return None

    async def on_chunk(self, ws, chunk: bytes):
        """Binary frame: append to the open staging file (auth already checked)."""
        session = self.sessions.get(self.by_ws.get(ws, ""), None)
        if session is None or not session.active_file:
            await self._fail(ws, None, "no active upload")
            return
        if len(chunk) > CHUNK_SIZE:
            await self._abort(ws, session, f"chunk exceeds {CHUNK_SIZE} bytes")
            return
        if session.open_received + len(chunk) > session.open_size:
            await self._abort(ws, session, "chunk exceeds announced size")
            return
        try:
            session.fh.write(chunk)
        except OSError as e:
            await self._abort(ws, session, f"staging write failed: {san(e, 120)}")
            return
        session.open_received += len(chunk)
        session.bytes_received += len(chunk)
        await self._maybe_progress(session)

    def cancel(self, transfer_id: str) -> bool:
        """Abort a staging session (command:cancel before engine hand-off)."""
        session = self.sessions.get(transfer_id)
        if session is None:
            return False
        self._destroy(session)
        return True

    def detach(self, ws):
        """Connection closed: drop the session and its staged bytes."""
        tid = self.by_ws.pop(ws, None)
        if tid is not None:
            session = self.sessions.pop(tid, None)
            if session is not None:
                self._destroy(session, announce=False)

    # -------------------------------------------------------------- handlers
    async def _announce(self, ws, data: dict) -> Optional[dict]:
        transfer_id = data.get("transferId")
        if not isinstance(transfer_id, str) or not TRANSFER_ID_RE.match(transfer_id):
            return {"type": "error", "error": "Invalid transfer id"}

        # One active session per connection — but the *next file of that very
        # session* is how multi-file batches are announced, so only a
        # different transferId on the same socket is refused here.
        existing_tid = self.by_ws.get(ws)
        if existing_tid is not None and existing_tid != transfer_id:
            return {"type": "error", "error": "Upload already in progress",
                    "transferId": transfer_id}
        if transfer_id in self.sessions and self.sessions[transfer_id].ws is not ws:
            return {"type": "error", "error": "Transfer id already staging",
                    "transferId": transfer_id}

        seq = data.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0 or seq >= MAX_FILES_PER_UPLOAD:
            return {"type": "error", "error": "Invalid file sequence",
                    "transferId": transfer_id}

        name_raw = data.get("name")
        if not isinstance(name_raw, str) or not name_raw.strip():
            return {"type": "error", "error": "Missing file name",
                    "transferId": transfer_id}
        name = sanitize_filename(name_raw)

        size = data.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            return {"type": "error", "error": "Invalid file size",
                    "transferId": transfer_id}
        if size > MAX_UPLOAD_FILE:
            mb = MAX_UPLOAD_FILE // (1024 * 1024)
            return {"type": "error", "error": f"File exceeds {mb} MB upload cap",
                    "transferId": transfer_id}

        target_ip = data.get("targetIp", "")
        if not isinstance(target_ip, str) or not TARGET_HOST_RE.match(target_ip):
            return {"type": "error", "error": "Invalid target address",
                    "transferId": transfer_id}
        try:
            target_port = int(data.get("targetPort") or 18974)
        except (TypeError, ValueError):
            target_port = 18974
        if not (0 < target_port < 65536):
            return {"type": "error", "error": "Invalid target port",
                    "transferId": transfer_id}
        target_device_id = data.get("targetDeviceId") or None
        if target_device_id is not None and (
            not isinstance(target_device_id, str) or not TRANSFER_ID_RE.match(target_device_id)
        ):
            return {"type": "error", "error": "Invalid target device id",
                    "transferId": transfer_id}
        dest_folder = data.get("destFolder") or None
        if dest_folder is not None and (not isinstance(dest_folder, str) or len(dest_folder) > 64):
            return {"type": "error", "error": "Invalid destination folder",
                    "transferId": transfer_id}
        if dest_folder:
            dest_folder = san(dest_folder, 64)

        batch_total = data.get("batchTotalBytes")
        if not isinstance(batch_total, int) or isinstance(batch_total, bool) or batch_total <= 0:
            batch_total = None

        # New session on first file; later files join the existing one and
        # must keep the same target.
        session = self.sessions.get(transfer_id)
        if session is None:
            if seq != 0:
                return {"type": "error", "error": "First file must start at sequence 0",
                        "transferId": transfer_id}
            if batch_total is None or batch_total > MAX_UPLOAD_BATCH:
                return {"type": "error", "error": "Invalid batch size",
                        "transferId": transfer_id}
            dirpath = os.path.join(self.staging_root, transfer_id)
            try:
                os.makedirs(dirpath, mode=0o700, exist_ok=True)
                os.chmod(self.staging_root, 0o700)
            except OSError as e:
                return {"type": "error", "error": f"Cannot stage upload: {san(e, 120)}",
                        "transferId": transfer_id}
            session = _Session(transfer_id, ws, dirpath, target_ip, target_port,
                               target_device_id, dest_folder, batch_total)
            self.sessions[transfer_id] = session
            self.by_ws[ws] = transfer_id
        else:
            if session.active_file:
                return {"type": "error", "error": "Upload busy", "transferId": transfer_id}
            if seq != session.next_seq:
                return {"type": "error", "error": "Out-of-sequence file",
                        "transferId": transfer_id}
            if len(session.files) >= MAX_FILES_PER_UPLOAD:
                return {"type": "error", "error": "Too many files in one upload",
                        "transferId": transfer_id}
            if session.target_ip != target_ip:
                return {"type": "error", "error": "Target changed mid-upload",
                        "transferId": transfer_id}
            if batch_total is not None:
                session.batch_total = batch_total

        if sum(f["size"] for f in session.files) + size > session.batch_total:
            return {"type": "error", "error": "Files exceed announced batch size",
                    "transferId": transfer_id}

        # Per-seq subdirectory: the engine derives the wire filename from
        # os.path.basename(), so the staged basename must be the exact
        # client-supplied (sanitized) name, while seq keeps duplicates apart.
        file_dir = os.path.join(session.dir, str(seq))
        path = os.path.join(file_dir, name)
        try:
            os.makedirs(file_dir, mode=0o700, exist_ok=True)
            fh = open(path, "wb")
        except OSError as e:
            self._destroy(session)
            return {"type": "error", "error": f"Cannot stage file: {san(e, 120)}",
                    "transferId": transfer_id}

        session.fh = fh
        session.open_seq = seq
        session.open_name = name
        session.open_size = size
        session.open_received = 0

        return {"type": "transfer:upload:ready", "transferId": transfer_id,
                "seq": seq, "chunkSize": CHUNK_SIZE}

    async def _end(self, ws, data: dict) -> Optional[dict]:
        session = self._session_for(ws, data)
        if session is None:
            return {"type": "error", "error": "No active upload",
                    "transferId": data.get("transferId") if isinstance(data.get("transferId"), str) else None}
        seq = data.get("seq")
        if not isinstance(seq, int) or seq != session.open_seq:
            await self._abort(ws, session, "end for wrong file")
            return None
        if session.open_received != session.open_size:
            received, expected = session.open_received, session.open_size
            await self._abort(ws, session, f"file ended at {received} of {expected} bytes")
            return None
        try:
            session.fh.close()
        except OSError:
            pass
        path = os.path.join(session.dir, str(seq), session.open_name)
        session.files.append({"name": session.open_name, "size": session.open_size,
                              "path": path, "type": "file"})
        session.fh = None
        session.open_seq = None
        session.next_seq = seq + 1
        await self._progress(session, force=True)
        return {"type": "transfer:upload:file-done", "transferId": session.transfer_id,
                "seq": seq}

    async def _finish(self, ws, data: dict) -> Optional[dict]:
        session = self._session_for(ws, data)
        if session is None:
            return {"type": "error", "error": "No active upload",
                    "transferId": data.get("transferId") if isinstance(data.get("transferId"), str) else None}
        if session.active_file:
            await self._abort(ws, session, "finish while a file is open")
            return None
        if not session.files:
            self._destroy(session, announce=False)
            return {"type": "error", "error": "No files were uploaded",
                    "transferId": data.get("transferId") or ""}

        paths = [f["path"] for f in session.files]
        dirpath = session.dir
        transfer_id = session.transfer_id
        # The session leaves the routing tables now; the staged dir survives
        # until the engine has consumed the files (cleanup task below).
        self.sessions.pop(transfer_id, None)
        self.by_ws.pop(ws, None)

        try:
            task = await self.engine.send_files(
                paths, session.target_ip, transfer_id=transfer_id,
                target_port=session.target_port,
                expected_device_id=session.target_device_id,
                dest_folder=session.dest_folder,
            )
        except Exception as e:
            shutil.rmtree(dirpath, ignore_errors=True)
            return {"type": "error", "error": san(e, 200), "transferId": transfer_id}

        asyncio.create_task(self._cleanup_when_done(task, dirpath))

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
                "files": [
                    {"name": f["name"], "size": f["size"], "path": f["path"], "type": f["type"]}
                    for f in task.files
                ],
                "startTime": int(task.start_time * 1000),
            },
        }

    # --------------------------------------------------------------- helpers
    def _session_for(self, ws, data: dict) -> Optional[_Session]:
        transfer_id = data.get("transferId")
        if not isinstance(transfer_id, str):
            return None
        session = self.sessions.get(transfer_id)
        if session is None or session.ws is not ws:
            return None
        return session

    async def _fail(self, ws, transfer_id, error: str):
        await self.bridge._safe_send(
            ws, {"type": "error", "error": error, "transferId": transfer_id}
        )

    async def _abort(self, ws, session: _Session, error: str):
        transfer_id = session.transfer_id
        self._destroy(session, announce=True, error=error)

    async def _progress(self, session: _Session, force: bool = False):
        now = time.monotonic()
        if not force and (now - session._last_progress) < PROGRESS_INTERVAL:
            return
        session._last_progress = now
        total = max(session.batch_total, session.bytes_received, 1)
        await self.bridge.send_message({
            "type": "transfer:progress",
            "transferId": session.transfer_id,
            "progress": min(1.0, session.bytes_received / total),
            "speed": 0,
            "bytesTransferred": session.bytes_received,
            "totalBytes": session.batch_total,
            "verified": False,
            "files": [
                {"name": f["name"], "size": f["size"], "path": f["path"], "type": f["type"]}
                for f in session.files
            ],
            "startTime": int(session.start_time * 1000),
        })

    async def _maybe_progress(self, session: _Session):
        await self._progress(session)

    def _destroy(self, session: _Session, announce: bool = True, error: str = None):
        if session.fh is not None:
            try:
                session.fh.close()
            except OSError:
                pass
            session.fh = None
        self.sessions.pop(session.transfer_id, None)
        if self.by_ws.get(session.ws) == session.transfer_id:
            self.by_ws.pop(session.ws, None)
        shutil.rmtree(session.dir, ignore_errors=True)
        if announce:
            if error:
                self.bridge.loop and asyncio.ensure_future(self.bridge._safe_send(
                    session.ws,
                    {"type": "error", "error": error, "transferId": session.transfer_id},
                ))
            else:
                self.bridge.loop and asyncio.ensure_future(self.bridge.send_message({
                    "type": "transfer:cancelled",
                    "transferId": session.transfer_id,
                    "success": True,
                }))

    async def _cleanup_when_done(self, task, dirpath: str):
        while getattr(task, "status", "") not in ("completed", "failed", "cancelled"):
            await asyncio.sleep(0.5)
        shutil.rmtree(dirpath, ignore_errors=True)
