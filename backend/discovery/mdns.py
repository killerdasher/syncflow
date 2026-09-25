import asyncio
import re
import socket
import time
from typing import Callable, Optional
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser

from .device import DeviceIdentity

MDNS_SERVICE_TYPE = "_syncflow._tcp.local."

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_MAC = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_SAFE_OS = re.compile(r"^[a-z0-9._-]{1,32}$")


def _safe_name(value: str, limit: int = 48) -> str:
    """Strip control/zero-width chars from attacker-supplied display names."""
    cleaned = "".join(ch for ch in str(value) if ch.isprintable())[:limit]
    return cleaned.strip() or "unknown"


def _safe_hostname(value: str, limit: int = 32) -> str:
    """DNS-label-safe version of a device hostname."""
    cleaned = re.sub(r"[^A-Za-z0-9-]", "-", str(value)).strip("-")[:limit]
    return cleaned or "device"


class MDNSDiscovery:
    def __init__(self, device_name: str, device_id: str, port: int = 18974):
        self.device = DeviceIdentity(name=device_name)
        self.device.id = device_id
        self.device.port = port
        self.zeroconf = Zeroconf()
        self.service_info: Optional[ServiceInfo] = None
        self.browser: Optional[ServiceBrowser] = None
        self._found_devices: dict[str, dict] = {}
        self._on_found: Optional[Callable] = None
        self._on_lost: Optional[Callable] = None

    async def register(self):
        properties = self.device.to_mdns_properties()
        encoded_props = {k.encode(): v.encode() for k, v in properties.items()}

        # Unique, DNS-safe instance name so identical hostnames never collide
        label = f"{_safe_hostname(self.device.name)}-{self.device.id[:8]}"

        self.service_info = ServiceInfo(
            MDNS_SERVICE_TYPE,
            f"{label}.{MDNS_SERVICE_TYPE}",
            addresses=[socket.inet_aton(self.device.ip)],
            port=self.device.port,
            properties=encoded_props,
            server=f"{label}.local.",
        )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.zeroconf.register_service, self.service_info)
        print(f"mDNS: Registered {label} on {self.device.ip}:{self.device.port}", flush=True)

    def start_browsing(
        self,
        on_found: Callable,
        on_lost: Callable,
    ):
        self._on_found = on_found
        self._on_lost = on_lost

        class Listener:
            def __init__(self, outer):
                self.outer = outer

            def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
                info = zc.get_service_info(type_, name)
                if info and self.outer.service_info and info.name != self.outer.service_info.name:
                    device = self._parse_service(info)
                    if device:
                        self.outer._found_devices[device["id"]] = device
                        if self.outer._on_found:
                            self.outer._on_found(device)

            def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
                for did, dev in list(self.outer._found_devices.items()):
                    if dev.get("mdns_name") == name:
                        del self.outer._found_devices[did]
                        if self.outer._on_lost:
                            self.outer._on_lost(did)
                        break

            def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
                pass

            def _parse_service(self, info: ServiceInfo) -> Optional[dict]:
                try:
                    props = {k.decode(errors="replace"): v.decode(errors="replace")
                             for k, v in info.properties.items()}

                    # Never trust TXT fields: validate before storing/displaying
                    device_id = props.get("id", "")
                    if not _SAFE_ID.match(device_id):
                        print("mDNS: rejected advertisement with invalid id", flush=True)
                        return None

                    raw_name = props.get("name") or info.name
                    raw_name = raw_name.replace("._syncflow._tcp.local.", "")
                    name = _safe_name(raw_name)

                    mac = props.get("mac") or ""
                    mac = mac if _SAFE_MAC.match(mac) else "unknown"

                    raw_os = (props.get("os") or "unknown").lower()
                    os_type = raw_os if _SAFE_OS.match(raw_os) else "unknown"

                    ip = "0.0.0.0"
                    if info.addresses:
                        ip = socket.inet_ntoa(info.addresses[0])

                    port = info.port if isinstance(info.port, int) else 0
                    if not (0 < port < 65536):
                        print("mDNS: rejected advertisement with invalid port", flush=True)
                        return None

                    return {
                        "id": device_id,
                        "name": name,
                        "mac": mac,
                        "ip": ip,
                        "port": port,
                        "os": os_type,
                        "icon": "laptop" if os_type in ("linux", "darwin") else "pc",
                        "status": "connected",
                        "connectionType": "lan",
                        "lastSeen": time.time() * 1000,
                        "mdns_name": info.name,
                    }
                except Exception as e:
                    print(f"mDNS parse error: {type(e).__name__}", flush=True)
                    return None

        listener = Listener(self)
        self.browser = ServiceBrowser(
            self.zeroconf, MDNS_SERVICE_TYPE, listener
        )
        print("mDNS: Browsing for devices...", flush=True)

    async def unregister(self):
        if self.service_info:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self.zeroconf.unregister_service, self.service_info
            )
        self.zeroconf.close()

    def get_found_devices(self) -> list[dict]:
        return list(self._found_devices.values())
