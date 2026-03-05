#!/opt/homebrew/bin/python3.11
"""
SyncLight macOS Driver
Turns off the Robobloq SyncLight strip when the display sleeps,
and restores it when the display wakes.

Requirements:
    pip3 install hid

Usage:
    python3 synclight.py          # run in foreground (Ctrl+C to stop)
    ./install.sh                  # install as login item (auto-start)
"""

import sys
import time
import threading
import signal
import logging
import os
import subprocess
import ctypes
import ctypes.util

try:
    import hid
except ImportError:
    print("Missing dependency: run  pip3 install hid")
    sys.exit(1)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


# ── USB identifiers ────────────────────────────────────────────────────────────

VENDOR_ID  = 0x1A86   # WCH USB chip (南京沁恒微电子)
PRODUCT_ID = 0xFE07   # SyncLight strip
INTERFACE  = 0        # HID interface index


# ── Protocol packet builder ────────────────────────────────────────────────────
#
# Every packet:
#   [0-1]  Header: "RB" (0x52 0x42)
#   [2]    Total length (including header and checksum)
#   [3]    Message ID (1-254, wraps around)
#   [4]    Action code
#   [5..n-2]  Payload
#   [n-1]  Checksum: sum(all preceding bytes) % 256
#
# Before sending over HID, prepend a 0x00 report-ID byte.
# ──────────────────────────────────────────────────────────────────────────────

class Protocol:
    _id = 0

    @classmethod
    def _next_id(cls) -> int:
        cls._id = (cls._id % 254) + 1
        return cls._id

    @staticmethod
    def _cksum(buf: bytearray) -> int:
        return sum(buf) % 256

    @classmethod
    def set_brightness(cls, value: int) -> bytes:
        """Action 0x87 (135) — set brightness (5-100). Only works when light is on."""
        value = max(5, min(100, value))
        mid = cls._next_id()
        buf = bytearray([0x52, 0x42, 0x07, mid, 0x87, value, 0x00])
        buf[6] = cls._cksum(buf[:6])
        return bytes(buf)

    @classmethod
    def set_color(cls, r: int, g: int, b: int) -> bytes:
        """Action 0x86 (134) — set solid colour across all LEDs.
        Segment format: [index, R, G, B, count]  (5 bytes per segment).
        index=0, count=255 covers all LEDs.
        Also used to turn the light ON after turnOffLight.
        """
        led_data = bytearray([0, r, g, b, 255])
        mid = cls._next_id()
        pkt_len = 6 + len(led_data)
        buf = bytearray(pkt_len)
        buf[0:2] = b"RB"
        buf[2] = pkt_len
        buf[3] = mid
        buf[4] = 0x86
        buf[5:5 + len(led_data)] = led_data
        buf[pkt_len - 1] = cls._cksum(buf[:pkt_len - 1])
        return bytes(buf)


# ── Device handle ──────────────────────────────────────────────────────────────

STATE_FILE = os.path.expanduser("~/.synclight")

def _load_color():
    try:
        parts = open(STATE_FILE).read().strip().split()
        return tuple(int(x) for x in parts)
    except Exception:
        return (255, 200, 100)

def _save_color(r, g, b):
    try:
        open(STATE_FILE, "w").write(f"{r} {g} {b}\n")
    except Exception:
        pass


class SyncLight:
    def __init__(self):
        self._dev = None
        self._lock = threading.Lock()
        self._color = _load_color()

    # ── connection ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        with self._lock:
            if self._dev:
                return True
            try:
                devices = hid.enumerate(VENDOR_ID, PRODUCT_ID)
                # Prefer interface 0; fall back to first entry if enumeration
                # doesn't report interface numbers (platform quirk).
                target = next(
                    (d for d in devices if d.get("interface_number", 0) == INTERFACE),
                    devices[0] if devices else None,
                )
                if target is None:
                    return False
                dev = hid.Device(path=target["path"])
                self._dev = dev
                log.info("SyncLight connected")
                return True
            except Exception as exc:
                log.warning("Connect failed: %s", exc)
                self._dev = None
                return False

    def disconnect(self):
        with self._lock:
            if self._dev:
                try:
                    self._dev.close()
                except Exception:
                    pass
                self._dev = None
                log.info("SyncLight disconnected")

    # ── I/O ───────────────────────────────────────────────────────────────────

    def _write(self, data: bytes) -> bool:
        """Send a command packet. Prepends the HID report-ID byte (0x00)."""
        with self._lock:
            if not self._dev:
                return False
            try:
                self._dev.write(bytes([0x00]) + data)
                return True
            except Exception as exc:
                log.warning("Write failed: %s", exc)
                self._dev = None
                return False

    def _ensure_connected(self) -> bool:
        return self._dev is not None or self.connect()

    # ── commands ──────────────────────────────────────────────────────────────

    def turn_off(self):
        if self._ensure_connected():
            self._write(Protocol.set_color(0, 0, 0))
            log.info("Light → OFF")

    def turn_on(self):
        r, g, b = self._color
        # Retry for up to 30s — USB device needs time to re-enumerate after sleep.
        for attempt in range(30):
            if attempt > 0:
                time.sleep(1)
            self._dev = None
            if self._ensure_connected() and self._write(Protocol.set_color(r, g, b)):
                log.info("Light → ON  rgb(%d,%d,%d)", r, g, b)
                return
        log.warning("Light → ON failed after retries")

    def set_color(self, r: int, g: int, b: int):
        self._color = (r, g, b)
        _save_color(r, g, b)
        if self._ensure_connected():
            self._write(Protocol.set_color(r, g, b))
            log.info("Color → rgb(%d,%d,%d)", r, g, b)


# ── IOKit display sleep/wake via CGDisplay notifications ──────────────────────
#
# Uses CGDisplayRegisterReconfigurationCallback + IOKit power assertions to
# detect display sleep/wake. This works from any process (daemon or GUI app).
# ──────────────────────────────────────────────────────────────────────────────


class DisplayMonitor:
    """
    Detects display sleep using two CoreGraphics APIs:
      - CGDisplayIsAsleep   : true when display is forced off (pmset / lid close)
      - CGDisplayIsActive   : false when display is off via energy saver
    Either condition means the display is off.
    """

    _cg = None

    @classmethod
    def _lib(cls):
        if cls._cg is None:
            cls._cg = ctypes.cdll.LoadLibrary(
                ctypes.util.find_library("CoreGraphics") or
                "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
            )
            cls._cg.CGMainDisplayID.restype = ctypes.c_uint32
            cls._cg.CGDisplayIsAsleep.argtypes = [ctypes.c_uint32]
            cls._cg.CGDisplayIsAsleep.restype  = ctypes.c_bool
            cls._cg.CGDisplayIsActive.argtypes = [ctypes.c_uint32]
            cls._cg.CGDisplayIsActive.restype  = ctypes.c_bool
        return cls._cg

    @classmethod
    def is_display_asleep(cls) -> bool:
        cg = cls._lib()
        d  = cg.CGMainDisplayID()
        return bool(cg.CGDisplayIsAsleep(d)) or not bool(cg.CGDisplayIsActive(d))


# ── entry point ────────────────────────────────────────────────────────────────

def main():
    light = SyncLight()

    log.info("SyncLight driver starting  (VID=0x%04X PID=0x%04X)", VENDOR_ID, PRODUCT_ID)

    if not light.connect():
        log.warning("Device not found at startup — will retry on next command")

    def _shutdown(*_):
        log.info("Shutting down")
        light.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("Monitoring display state (polling every 2s)")

    was_asleep = DisplayMonitor.is_display_asleep()
    if was_asleep:
        light.turn_off()

    while True:
        time.sleep(2)
        is_asleep = DisplayMonitor.is_display_asleep()
        if is_asleep and not was_asleep:
            log.info("Display sleeping")
            light.turn_off()
            light.disconnect()   # release device before USB power cut
        elif not is_asleep and was_asleep:
            log.info("Display waking")
            light.turn_on()
        was_asleep = is_asleep


if __name__ == "__main__":
    main()
