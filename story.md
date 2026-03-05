# How Claude Wrote a macOS Driver for the Robobloq SyncLight Strip

## The Problem

The user owned a **Robobloq SyncLight LED strip** — a smart ambient light designed to sync with your screen. The official driver (SyncLight app) hadn't been updated in a long time, and it had a simple but annoying bug: **the light stayed on even when the monitor turned off**. The user decided to write their own driver.

---

## Step 1 — Figuring Out How the Device Connects

Nobody knew how the device communicated. The user found a Python project on GitHub ([Feelin_Light_Q1_Python](https://github.com/kittle1990/Feelin_Light_Q1_Python)) that might control it. Claude fetched and analysed that repository.

**Finding:** The Python library used a LAN IP address (`192.168.0.68`) — suggesting the device was Wi-Fi based, not USB.

To verify, Claude asked the user to run a few terminal commands:

```bash
system_profiler SPUSBDataType   # check USB devices
ls /dev/tty.* /dev/cu.*         # check serial ports
arp -a                          # check network devices
```

The USB scan returned nothing. The ARP table showed a device at `192.168.68.68` — suspiciously matching the `.68` from the Python project example. But when Claude pinged it, there was no response.

**Dead end on the network theory.** Time to look elsewhere.

---

## Step 2 — Reverse Engineering the SyncLight App

Claude noticed the official SyncLight app was installed at `/Applications/SyncLight.app`. Since it was an **Electron app**, its JavaScript source was bundled inside `app.asar` — a readable archive.

Claude extracted it:

```bash
npx @electron/asar extract /Applications/SyncLight.app/Contents/Resources/app.asar /tmp/synclight_src
```

Inside `package.json`, a key dependency appeared:

```json
"@warren-robobloq/quiklight": "1.24.1"
```

This package was **unpacked on disk** (not inside the asar), meaning it was a native Node.js addon. Claude ran `strings` on the compiled binary — but it only revealed screen capture and audio functions, not the light protocol.

The real gold was in the webpack bundles.

---

## Step 3 — Reading the Webpack Bundle

The main bundle (`app.asar/.webpack/main/index.js`) was 2.3 MB of minified JavaScript. Claude searched it for meaningful patterns and found the device constants module:

```javascript
const LIGHT_VID = 6790    // 0x1A86 — WCH USB chip
const LIGHT_PID = 65031   // 0xFE07
const CDC_PID   = 65036
const BLE_PID   = 21845
const DONGLE_PID = 22102
```

**Revelation: the SyncLight strip is a USB HID device — not Wi-Fi at all.**

Claude then found the HID device filter:

```javascript
.filter(e =>
  e.productId === LIGHT_PID &&
  e.vendorId  === LIGHT_VID &&
  0 === e.interface
)
```

And the complete binary protocol (module 60895):

```
Packet layout:
  [0-1]   "RB"  (0x52 0x42) — header
  [2]     total packet length
  [3]     message ID (1–254, auto-increments)
  [4]     action code
  [5..n-2] payload
  [n-1]   checksum = sum(all preceding bytes) % 256
```

Before writing to the HID device, a `0x00` byte (HID report ID) must be prepended.

**All action codes extracted:**

| Action | Code |
|---|---|
| turnOffLight | 151 (0x97) |
| setSectionLED | 134 (0x86) |
| setBrightness | 135 (0x87) |
| setLedEffect | 133 (0x85) |
| setSyncScreen | 128 (0x80) |

---

## Step 4 — Writing the Driver

With the protocol fully understood, Claude wrote `synclight.py` — a Python daemon that:

1. Connects to the USB HID device (VID `0x1A86`, PID `0xFE07`)
2. Polls the display state every 2 seconds
3. Turns the light off when the display sleeps
4. Restores the light when the display wakes

**Dependency:** `pip install hid` + `brew install hidapi`

---

## Step 5 — The Display Sleep Detection Problem

The first attempt used `NSWorkspace` notifications (`NSWorkspaceScreensDidSleepNotification`) via PyObjC. When tested by forcing sleep with `pmset displaysleepnow`, nothing was logged — the background process didn't receive the notifications.

**Why:** `NSWorkspace` notifications require a proper GUI session. A daemon process spawned from a terminal doesn't have one.

**First fix attempt:** Switch to `ioreg` (IOKit registry) to check `IODisplayConnect / CurrentPowerState`. This is reliable on Intel Macs — but the user had **Apple Silicon**, where `IODisplayConnect` doesn't exist in the registry. The command returned nothing.

**Final fix:** Use CoreGraphics directly via `ctypes`:

```python
CGDisplayIsAsleep(displayID)   # catches forced sleep (pmset, lid close)
CGDisplayIsActive(displayID)   # catches energy-saver natural sleep
```

Both are needed — `CGDisplayIsAsleep` alone misses natural screen-off from the energy saver. Using `not CGDisplayIsActive` catches that case.

---

## Step 6 — The Turn-Off Command Didn't Work

The log showed `Light → OFF` being sent, but the light stayed on.

Action `0x97` (`turnOffLight`) existed in the protocol — but testing showed it had **no visible effect** on this device.

Claude ran a live test, sending different commands one by one while the user watched the strip:

- `turnOffLight` (0x97) → light stays on
- `setBrightness(0)` → light stays on
- `setSectionLED(0, 0, 0)` → **light turns off** ✓
- `setSectionLED(255, 200, 100)` → **light turns on** ✓

**Fix:** Use `setSectionLED(0, 0, 0)` (black) to turn off, and `setSectionLED(r, g, b)` to turn back on.

---

## Step 7 — The Wake Reconnect Problem

On display wake, the log showed:

```
Connect failed: exclusive access and device already open
```

**Root cause:** When the display sleeps, macOS cuts USB power to the device. On wake, the USB re-enumerates. The **SyncLight app** had a Login Item that relaunched on wake and grabbed the device before our driver could reconnect.

**Fix 1:** Kill the SyncLight app on wake before reconnecting.
**Fix 2:** After removing the app, macOS's own USB re-enumeration still takes a moment. The driver now disconnects the device cleanly before sleep, then retries reconnection for up to 30 seconds on wake.

---

## Step 8 — Writing the CLI

With the driver working, Claude wrote `sl.py` — a simple CLI for manual control:

```bash
sl on
sl off
sl color blue
sl color 255 128 0    # custom RGB
```

**Challenge:** The background driver held the HID device open exclusively. The CLI couldn't open it at the same time.

**Solution:** The CLI kills the driver, sends the command, then respawns the driver — all transparently. The user sees none of this.

---

## Step 9 — Restoring the Last Color on Wake

The final feature: when the display wakes, the light should restore the **last colour the user set**, not always warm white.

Claude added a shared state file (`~/.synclight`) containing the last RGB value. Both `sl.py` (writes on color change) and `synclight.py` (reads on wake) use it.

```
# ~/.synclight
0 100 255
```

Set the light to blue, let the screen sleep — it wakes up blue.

---

## What Was Built

Three files, ~300 lines total:

| File | Purpose |
|---|---|
| `synclight.py` | Background daemon — auto on/off with display sleep |
| `sl.py` | CLI — manual control and color changes |
| `install.sh` | Installs as a macOS LaunchAgent for auto-start at login |

**Setup:**
```bash
brew install hidapi
pip3 install hid pyobjc-framework-Cocoa
./install.sh
```

---

## Key Takeaways

- **The device wasn't what it seemed.** A Python project pointed to Wi-Fi, but the real protocol was USB HID.
- **The source was there all along.** The official Electron app contained the full JavaScript protocol implementation, just minified.
- **Action codes lie.** `turnOffLight` (0x97) exists in the protocol but does nothing. Only `setSectionLED(0,0,0)` actually turns the light off.
- **macOS daemon quirks.** NSWorkspace notifications don't work in background processes. `IODisplayConnect` doesn't exist on Apple Silicon. `CGDisplayIsActive` is the correct API for energy-saver sleep detection.
- **Exclusive HID access is a real constraint.** Only one process can hold a HID device at a time on macOS — the driver and CLI have to cooperate.
