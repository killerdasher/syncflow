import asyncio
import hashlib
import socket
import platform
import uuid
from typing import Callable, Optional


def pseudo_mac(device_id: str) -> str:
    """Stable, locally-administered pseudonym in MAC format.

    Derived from the device id (a hash of the public signing key), never from
    the hardware NIC: the real MAC must not leak over mDNS, where any LAN
    observer could OUI-lookup the vendor and track the machine across
    networks. The locally-administered bit is set so the value is
    unambiguously not a burned-in address.
    """
    digest = bytearray(hashlib.sha256(str(device_id).encode()).digest()[:6])
    digest[0] = (digest[0] & 0xFE) | 0x02  # clear multicast, set local
    return ":".join(f"{b:02X}" for b in digest)


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
        self.ip = get_local_ip()
        self.os = get_os_type()
        self.icon = get_device_icon(self.os)
        self.port = 18974

    @property
    def mac(self) -> str:
        # Derived from the *current* id: MDNSDiscovery replaces id with the
        # stable device id after construction, and this must follow.
        return pseudo_mac(self.id)

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
