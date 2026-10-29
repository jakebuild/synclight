# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

macOS daemon that controls a **Robobloq SyncLight LED strip** (also sold as Feelin Light Q1). It automatically turns the strip off when the display sleeps and restores it when the display wakes.

## Running

```bash
pip3 install hid
python3 synclight.py          # foreground, Ctrl+C to stop
```

To install as a login-item that starts automatically:
```bash
chmod +x install.sh && ./install.sh
./install.sh --uninstall      # remove
```

Logs when installed: `~/Library/Logs/SyncLight.log`

## Device protocol

**USB HID device** — no Wi-Fi, no serial port.

| Field        | Value                     |
|------------- |---------------------------|
| Vendor ID    | `0x1A86` (WCH USB chip)   |
| Product ID   | `0xFE07`                  |
| HID interface| `0`                       |

**Packet layout**

```
[0-1]   "RB"  (0x52 0x42)
[2]     total packet length
[3]     message ID  (1-254, auto-increments)
[4]     action code
[5..n-2] payload
[n-1]   checksum = sum(all preceding bytes) % 256
```

Before writing to the HID device, prepend one `0x00` byte (HID report ID).

**Key action codes** (from `/Applications/SyncLight.app` webpack bundle, module 60895):

| Action          | Code (dec) | Code (hex) |
|----------------|-----------|-----------|
| readDeviceInfo  | 130       | 0x82      |
| setSyncScreen   | 128       | 0x80      |
| setSectionLED   | 134       | 0x86      |
| setBrightness   | 135       | 0x87      |
| setAutoOff      | 137       | 0x89      |
| setLedEffect    | 133       | 0x85      |
| turnOffLight    | 151       | 0x97      |

**setSectionLED** takes an array of 5-byte LED segments: `[index, R, G, B, count]`.
**setSyncScreen** uses `SC` (0x53 0x43) as the 2-byte header instead of `RB`, with a 2-byte big-endian length field.

## Architecture

Single file: `synclight.py`

- `Protocol` class — pure functions that build binary command bytes
- `SyncLight` class — HID device handle, reconnects on demand
- `DisplayObserver(NSObject)` — PyObjC NSWorkspace observer for `NSWorkspaceScreensDidSleepNotification` / `NSWorkspaceScreensDidWakeNotification`
- `main()` — connects device, registers observer, runs `NSRunLoop.mainRunLoop()`

## Dependencies

- `hid` (PyPI) — Python bindings for `hidapi`
- `pyobjc-framework-Cocoa` — pre-installed on macOS system Python; needed for `NSWorkspace` notifications
