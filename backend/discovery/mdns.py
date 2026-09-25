import asyncio
import socket
import time
from typing import Callable, Optional
from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser

from .device import DeviceIdentity

MDNS_SERVICE_TYPE = "_syncflow._tcp.local."


class MDNSDiscovery:
    def __init__(self, device_name: str, device_id: str):
        self.device = DeviceIdentity(name=device_name)
        self.device.id = device_id
        self.zeroconf = Zeroconf()
        self.service_info: Optional[ServiceInfo] = None
        self.browser: Optional[ServiceBrowser] = None
        self._found_devices: dict[str, dict] = {}
        self._on_found: Optional[Callable] = None
        self._on_lost: Optional[Callable] = None

    async def register(self):
        properties = self.device.to_mdns_properties()
        encoded_props = {k.encode(): v.encode() for k, v in properties.items()}

        self.service_info = ServiceInfo(
            MDNS_SERVICE_TYPE,
            f"{self.device.name}.{MDNS_SERVICE_TYPE}",
            addresses=[socket.inet_aton(self.device.ip)],
            port=self.device.port,
            properties=encoded_props,
            server=f"{self.device.name}.local.",
        )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.zeroconf.register_service, self.service_info)
        print(f"mDNS: Registered {self.device.name} on {self.device.ip}:{self.device.port}", flush=True)

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
                    props = {k.decode(): v.decode() for k, v in info.properties.items()}
                    ip = "0.0.0.0"
                    if info.addresses:
                        ip = socket.inet_ntoa(info.addresses[0])

                    return {
                        "id": props.get("id", ""),
                        "name": props.get("name", info.name),
                        "mac": props.get("mac") or "unknown",
                        "ip": ip,
                        "os": props.get("os", "unknown"),
                        "icon": "laptop" if props.get("os") in ("linux", "darwin") else "pc",
                        "status": "connected",
                        "connectionType": "lan",
                        "lastSeen": time.time() * 1000,
                        "mdns_name": info.name,
                    }
                except Exception as e:
                    print(f"mDNS parse error: {e}", flush=True)
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
