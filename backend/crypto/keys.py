import os
import json
from typing import Optional


class KeyManager:
    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = storage_dir or os.path.expanduser("~/.syncflow/keys")
        os.makedirs(self.storage_dir, exist_ok=True)
        self._keys: dict[str, bytes] = {}
        self._load_keys()

    def _load_keys(self):
        key_file = os.path.join(self.storage_dir, "device.key")
        if os.path.exists(key_file):
            with open(key_file, "rb") as f:
                self._keys["device"] = f.read()
        else:
            self._keys["device"] = os.urandom(32)
            with open(key_file, "wb") as f:
                f.write(self._keys["device"])

    def get_device_key(self) -> bytes:
        return self._keys["device"]

    def generate_pairing_key(self) -> str:
        import secrets
        return secrets.token_urlsafe(32)

    def save_peer_key(self, peer_id: str, key: bytes):
        peer_file = os.path.join(self.storage_dir, f"peer_{peer_id}.key")
        with open(peer_file, "wb") as f:
            f.write(key)

    def get_peer_key(self, peer_id: str) -> Optional[bytes]:
        peer_file = os.path.join(self.storage_dir, f"peer_{peer_id}.key")
        if os.path.exists(peer_file):
            with open(peer_file, "rb") as f:
                return f.read()
        return None
