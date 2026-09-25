import asyncio
import socket
import platform
import uuid
from typing import Callable, Optional


def get_mac_address() -> str:
    mac = uuid.getnode()
    return ':'.join(f'{(mac >> (8 * i)) & 0xFF:02X}' for i in reversed(range(6)))


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_os_type() -> str:
    system = platform.system().lower()
    return system if system in ('windows', 'linux', 'darwin') else 'unknown'


def get_device_icon(os_type: str) -> str:
    icons = {
        'windows': 'pc',
        'linux': 'laptop',
        'darwin': 'laptop',
    }
    return icons.get(os_type, 'unknown')


class DeviceIdentity:
    def __init__(self, name: Optional[str] = None):
        self.id = str(uuid.uuid4())
        self.name = name or socket.gethostname()
        self.mac = get_mac_address()
        self.ip = get_local_ip()
        self.os = get_os_type()
        self.icon = get_device_icon(self.os)
        self.port = 18974

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "mac": self.mac,
            "ip": self.ip,
            "os": self.os,
            "icon": self.icon,
            "port": self.port,
            "status": "connected",
            "connectionType": "lan",
            "lastSeen": __import__('time').time() * 1000,
        }

    def to_mdns_properties(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "mac": self.mac,
            "os": self.os,
            "port": str(self.port),
        }
