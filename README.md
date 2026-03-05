# SyncLight macOS Driver

A custom macOS driver for the **Robobloq SyncLight LED strip** that automatically turns the light off when your display sleeps and restores it when the display wakes. Includes a CLI for manual control.

The official SyncLight app hadn't been updated in years and had a bug: the light stayed on when the monitor turned off. This replaces it entirely.

## How It Works

The SyncLight strip is a USB HID device (VID `0x1A86`, PID `0xFE07`). The protocol was reverse-engineered from the official Electron app's webpack bundle. Display sleep is detected using CoreGraphics (`CGDisplayIsAsleep` + `CGDisplayIsActive`) via ctypes — no GUI session required.

See [story.md](story.md) for the full reverse-engineering story.

## Requirements

```bash
brew install hidapi
pip3 install hid pyobjc-framework-Cocoa
```

## Install

```bash
./install.sh
```

This installs the driver as a LaunchAgent so it starts automatically at login.

To uninstall:

```bash
./install.sh --uninstall
```

## CLI

```bash
sl on                  # Turn light on (restores last color)
sl off                 # Turn light off
sl color warm          # Warm white  (255, 200, 100)
sl color white         # Pure white  (255, 255, 255)
sl color cool          # Cool white  (200, 220, 255)
sl color red           # Red
sl color green         # Green
sl color blue          # Blue
sl color purple        # Purple
sl color 255 128 0     # Custom RGB
```

The last color set is saved to `~/.synclight` and restored when the display wakes.

## Files

| File | Purpose |
|---|---|
| `synclight.py` | Background daemon — auto on/off with display sleep |
| `sl.py` | CLI — manual control and color changes |
| `install.sh` | Installs as a macOS LaunchAgent for auto-start at login |

## Logs

```bash
tail -f ~/Library/Logs/SyncLight.log
```

## Manual Usage (without install)

```bash
python3 synclight.py
```

## Protocol Notes

- Header: `RB` (0x52 0x42)
- Packet: `[header][length][msg_id][action][payload][checksum]`
- HID write prepends a `0x00` report-ID byte
- `turnOffLight` (0x97) exists in the protocol but has no effect — use `setSectionLED(0,0,0)` to turn off
