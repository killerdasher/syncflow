#!/usr/bin/env python3
"""Capture README screenshots of the running app via Chrome DevTools Protocol.

Usage:
  1. Launch a dedicated app instance (isolated home + profile + debug port):
       SYNCFLOW_HOME=/tmp/sfshot-home <app> --remote-debugging-port=9444 \
         --user-data-dir=/tmp/sfshot-profile &
  2. python3 tools/make_screenshots.py [output_dir]

Seeds demo state (transfers/devices/settings), reloads, walks the sidebar
pages and saves 1600x900 PNGs: dashboard.png, transfers.png, chat.png,
settings.png. Requires the backend WS (127.0.0.1:18973) for chat shots.
"""
import asyncio
import base64
import json
import os
import sys
import time
import urllib.request

CDP = "http://127.0.0.1:9444"
WS_APP = "ws://127.0.0.1:18973"
PAGE = 1600
HEIGHT = 900


def page_targets():
    with urllib.request.urlopen(CDP + "/json/list", timeout=5) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]


def seed_script() -> str:
    now = int(time.time() * 1000)
    transfers = {
        "state": {
            "transfers": [
                {
                    "id": "shot-t1",
                    "fromDevice": "This Device",
                    "toDevice": "STUDIO-PC",
                    "files": [{"name": "report-q3.pdf", "path": "~/Documents/report-q3.pdf", "size": 2411724, "type": "pdf"}],
                    "status": "completed",
                    "progress": 1,
                    "speed": 0,
                    "bytesTransferred": 2411724,
                    "totalBytes": 2411724,
                    "startTime": now - 620000,
                    "endTime": now - 560000,
                    "verified": True,
                    "destFolder": "Documents",
                    "destPath": "C:\\Users\\studio\\Documents\\report-q3.pdf",
                },
                {
                    "id": "shot-t2",
                    "fromDevice": "STUDIO-PC",
                    "toDevice": "This Device",
                    "files": [{"name": "design-assets.zip", "path": "~/Desktop/design-assets.zip", "size": 48211904, "type": "zip"}],
                    "status": "completed",
                    "progress": 1,
                    "speed": 0,
                    "bytesTransferred": 48211904,
                    "totalBytes": 48211904,
                    "startTime": now - 3600000,
                    "endTime": now - 3480000,
                    "verified": True,
                    "destFolder": "Downloads",
                },
            ]
        },
        "version": 1,
    }
    devices = {
        "state": {
            "devices": [
                {
                    "id": "3f9ac21b8e77d4a0",
                    "name": "WORK-LAPTOP",
                    "mac": "00:1a:2b:3c:4d:5e",
                    "ip": "192.168.0.50",
                    "os": "windows",
                    "status": "connected",
                    "connectionType": "lan",
                    "lastSeen": now,
                    "icon": "pc",
                    "manual": True,
                }
            ],
            "selectedDevice": None,
        }
    }
    settings = {
        "state": {
            "settings": {
                "deviceName": "",
                "autoAccept": False,
                "downloadPath": "~/Downloads/SyncFlow",
                "syncFolders": [],
                "maxConcurrent": 4,
            },
            "pendingSyncs": {},
        },
        "version": 1,
    }
    return (
        "localStorage.setItem('syncflow-transfers', %s);"
        "localStorage.setItem('syncflow-devices', %s);"
        "localStorage.setItem('syncflow-settings', %s);"
        % (json.dumps(json.dumps(transfers)), json.dumps(json.dumps(devices)), json.dumps(json.dumps(settings)))
    )


async def ws_chat_send(ws, text: str, sender: str = "parrot"):
    await ws.send(json.dumps({"type": "chat:send", "text": text, "fromDevice": sender}))


async def main() -> int:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots"
    os.makedirs(out_dir, exist_ok=True)

    import websockets

    targets = page_targets()
    if not targets:
        print("No CDP page target — is the app running with --remote-debugging-port=9444?")
        return 1

    async with websockets.connect(targets[0]["webSocketDebuggerUrl"], max_size=100_000_000) as ws:
        mid = 0

        async def cmd(method, params=None):
            nonlocal mid
            mid += 1
            my_id = mid
            await ws.send(json.dumps({"id": my_id, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == my_id:
                    if "error" in msg:
                        print(f"CDP error in {method}: {msg['error']}")
                    return msg

        async def evaluate(expr):
            r = await cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            return (r.get("result", {}).get("result", {}) or {}).get("value")

        async def shot(name):
            r = await cmd("Page.captureScreenshot", {"format": "png"})
            data = r.get("result", {}).get("data")
            if not data:
                print(f"FAIL screenshot {name}")
                return
            path = os.path.join(out_dir, name)
            with open(path, "wb") as f:
                f.write(base64.b64decode(data))
            print(f"saved {path}")

        async def nav(label, marker):
            await evaluate(
                "(() => { const els=[...document.querySelectorAll('button')];"
                "const b=els.find(e=>e.textContent.trim()===arguments0) || els.find(e=>e.textContent.includes(arguments0));"
                "if(b){b.click();return 'clicked';} return 'NOTFOUND'; })()".replace("arguments0", json.dumps(label))
            )
            for _ in range(40):
                await asyncio.sleep(0.25)
                body = await evaluate("document.body.innerText")
                if body and marker.lower() in body.lower():
                    return True
            print(f"  warn: marker {marker!r} not seen for {label}")
            return False

        await cmd("Page.enable")
        await cmd("Runtime.enable")
        await cmd(
            "Emulation.setDeviceMetricsOverride",
            {"width": PAGE, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False},
        )

        # Seed demo state, then reload so stores hydrate from it
        await evaluate(seed_script())
        await cmd("Page.reload")
        await asyncio.sleep(4)

        # Wait for the shell
        for _ in range(40):
            body = await evaluate("document.body.innerText")
            if body and "Dashboard" in body:
                break
            await asyncio.sleep(0.25)

        # Wait for the renderer to connect to the backend (positive signal)
        for _ in range(80):
            body = await evaluate("document.body.innerText")
            if body and "Backend Connected" in body:
                break
            await asyncio.sleep(0.25)
        else:
            print("  warn: backend status never became online")

        # -- Dashboard (devices may also arrive via live mDNS discovery)
        await asyncio.sleep(3)
        await shot("dashboard.png")

        # -- Chat: realistic 2-way conversation (incoming via direct E2E TCP
        #    from localhost — no mDNS relay, so no other LAN device is spammed)
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "tests"))
        import proto_lib

        try:
            async with websockets.connect(WS_APP, open_timeout=5) as app_ws:
                r = await asyncio.to_thread(
                    proto_lib.raw_chat,
                    "Hey! Did the release build go out?",
                    "127.0.0.1", 18974,
                    sender_name="STUDIO-PC",
                )
                print(f"  incoming 1: {r}")
                await asyncio.sleep(0.4)
                await ws_chat_send(app_ws, "Yep — all three OS installers, auto-built.")
                await asyncio.sleep(0.4)
                r = await asyncio.to_thread(
                    proto_lib.raw_chat,
                    "Nice — I'll test the Windows one tonight.",
                    "127.0.0.1", 18974,
                    sender_name="STUDIO-PC",
                )
                print(f"  incoming 2: {r}")
        except Exception as e:
            print(f"chat seeding skipped: {type(e).__name__}: {e}")
        await nav("Chat", "auto-built")
        await asyncio.sleep(1.5)
        await shot("chat.png")

        # -- Transfers (seeded history)
        await nav("Transfers", "report-q3.pdf")
        await asyncio.sleep(1)
        await shot("transfers.png")

        # -- Settings → Security tab (pinned devices + honest security model)
        await nav("Settings", "General Settings")
        for attempt in range(3):
            await evaluate(
                "(() => { const els=[...document.querySelectorAll('button')];"
                "const b=els.find(e=>e.textContent.trim()==='Security');"
                "if(b){b.click();return 'clicked';} return 'NOTFOUND'; })()"
            )
            for _ in range(24):
                await asyncio.sleep(0.25)
                body = await evaluate("document.body.innerText")
                if body and "Pinned Devices" in body:
                    break
            else:
                continue
            break
        else:
            print("  warn: Security tab not reached")
        await shot("settings.png")

    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
