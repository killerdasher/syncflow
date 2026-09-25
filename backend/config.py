import os
import json
from typing import Optional


DEFAULT_CONFIG = {
    "device_name": "",
    "port": 18973,
    "tcp_port": 18974,
    "relay_server": "",
    "relay_token": "",
    "encryption_enabled": True,
    "download_path": os.path.expanduser("~/Downloads/SyncFlow"),
    "auto_accept": False,
    "max_concurrent_transfers": 4,
    "sync_folders": [],
}


class Config:
    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = config_dir or os.path.expanduser("~/.syncflow")
        self.config_file = os.path.join(self.config_dir, "config.json")
        os.makedirs(self.config_dir, exist_ok=True)
        self._config = DEFAULT_CONFIG.copy()
        self._load()

    def _load(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    saved = json.load(f)
                    self._config.update(saved)
            except Exception:
                pass

    def _save(self):
        with open(self.config_file, "w") as f:
            json.dump(self._config, f, indent=2)

    def get(self, key: str, default=None):
        return self._config.get(key, default)

    def set(self, key: str, value):
        self._config[key] = value
        self._save()

    def update(self, updates: dict):
        self._config.update(updates)
        self._save()

    def to_dict(self) -> dict:
        return self._config.copy()
