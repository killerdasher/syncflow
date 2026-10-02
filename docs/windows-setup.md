SyncFlow - Windows Setup Guide
==============================

WHAT THIS IS
------------
SyncFlow is a peer-to-file/chat app for your local network. This folder is
the complete app. The PC running it and your laptop will discover each other
and you can send files and chat between them.

PREREQUISITES (install once, on the PC)
---------------------------------------
1. Node.js 20 or newer
   https://nodejs.org  (download the LTS installer, click Next through it)
2. Python 3.11 or newer
   https://python.org/downloads/
   IMPORTANT: in the installer, tick "Add python.exe to PATH" before
   clicking Install.

Both installs require a restart of any open Command Prompt windows.

FIRST RUN
---------
1. Unzip this folder anywhere (e.g. C:\SyncFlow). Avoid OneDrive-synced
   folders.
2. Double-click  start-windows.bat
3. The first run installs all dependencies (1-5 minutes, needs internet).
4. The SyncFlow window opens. Done.

EVERY RUN AFTER THAT
--------------------
Just double-click  start-windows.bat  (starts in a few seconds).

CONNECTING TO YOUR LAPTOP
-------------------------
1. Put both machines on the SAME network (same Wi-Fi/router).
2. Start SyncFlow on both. Wait ~5 seconds - the other device appears on
   the dashboard automatically (mDNS discovery).
3. If it does not appear, click "Add Device" and enter the other machine's
   IP address:
     - Windows PC: open Command Prompt, run   ipconfig   -> "IPv4 Address"
     - Linux laptop: run   hostname -I
4. When Windows or your firewall asks, click ALLOW for Python and/or
   Node.js on private networks.
5. Chat tab: type a message, press send - it relays to the other device.
6. Send Files: drop files on the dashboard or click "Send Files", pick the
   device, send. The other side gets an approval prompt unless
   Settings -> Auto-accept transfers is enabled.

TROUBLESHOOTING
---------------
- "Node.js not found" / "Python not found" -> reinstall with the options
  above (PATH), then open a NEW command window and try again.
- Firewall blocks: allow Python/Node.js on private networks, or run:
    netsh advfirewall firewall add rule name="SyncFlow TCP" dir=in action=allow protocol=TCP localport=18974
- Devices not discovering each other: use manual IP via "Add Device"
  (works even when mDNS is blocked).
- Chat/files only work when both devices are on the same network.

DATA
----
Identity and pinned-device data:  %USERPROFILE%\.syncflow\
Received files by default:        %USERPROFILE%\Downloads\SyncFlow\
