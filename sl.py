#!/opt/homebrew/bin/python3.11
"""
sl — SyncLight CLI

Usage:
  sl on                  Turn light on (warm white)
  sl off                 Turn light off
  sl color warm          Warm white  (255, 200, 100)
  sl color white         Pure white  (255, 255, 255)
  sl color cool          Cool white  (200, 220, 255)
  sl color red           Red         (255,   0,   0)
  sl color green         Green       (  0, 255,   0)
  sl color blue          Blue        (  0, 100, 255)
  sl color purple        Purple      (150,   0, 255)
  sl color R G B         Custom RGB  e.g.  sl color 255 128 0
"""

import os
import sys

try:
    import hid
except ImportError:
    print("Missing dependency: pip3 install hid")
    sys.exit(1)

VENDOR_ID  = 0x1A86
PRODUCT_ID = 0xFE07

STATE_FILE = os.path.expanduser("~/.synclight")

PRESETS = {
    "warm":   (255, 200, 100),
    "white":  (255, 255, 255),
    "cool":   (200, 220, 255),
    "red":    (255,   0,   0),
    "green":  (  0, 255,   0),
    "blue":   (  0, 100, 255),
    "purple": (150,   0, 255),
}


# ── protocol ──────────────────────────────────────────────────────────────────

def _cksum(buf):
    return sum(buf) % 256

def _set_color(r, g, b):
    led = bytearray([0, r, g, b, 255])
    n = 6 + len(led)
    buf = bytearray(n)
    buf[0:2] = b"RB"
    buf[2] = n
    buf[3] = 1
    buf[4] = 0x86          # setSectionLED
    buf[5:5 + len(led)] = led
    buf[n - 1] = _cksum(buf[:n - 1])
    return bytes(buf)


# ── device ────────────────────────────────────────────────────────────────────

import os
import signal
import subprocess
import time


DRIVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "synclight.py")
PYTHON = sys.executable


def _driver_running():
    try:
        subprocess.check_output(["pgrep", "-f", "python.*synclight.py"], text=True)
        return True
    except subprocess.CalledProcessError:
        return False


def _send(data):
    # Kill driver to release exclusive HID access, restart it after
    was_running = _driver_running()
    if was_running:
        subprocess.run(["pkill", "-f", "python.*synclight.py"], capture_output=True)
        time.sleep(0.5)

    try:
        devices = hid.enumerate(VENDOR_ID, PRODUCT_ID)
        if not devices:
            print("SyncLight not found. Is it plugged in?")
            sys.exit(1)
        dev = hid.Device(path=devices[0]["path"])
        dev.write(bytes([0x00]) + data)
        dev.close()
    finally:
        if was_running:
            subprocess.Popen([PYTHON, DRIVER_SCRIPT],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_on():
    try:
        r, g, b = (int(x) for x in open(STATE_FILE).read().strip().split())
    except Exception:
        r, g, b = 255, 200, 100
    _send(_set_color(r, g, b))
    print(f"Light on  rgb({r}, {g}, {b})")

def cmd_off():
    _send(_set_color(0, 0, 0))
    print("Light off")

def cmd_color(args):
    if not args:
        print("Usage: sl color <name|R G B>")
        print("Names:", ", ".join(PRESETS))
        sys.exit(1)

    if args[0] in PRESETS:
        r, g, b = PRESETS[args[0]]
    elif len(args) == 3:
        try:
            r, g, b = int(args[0]), int(args[1]), int(args[2])
            if not all(0 <= v <= 255 for v in (r, g, b)):
                raise ValueError
        except ValueError:
            print("RGB values must be integers 0-255")
            sys.exit(1)
    else:
        print(f"Unknown colour '{args[0]}'. Available:", ", ".join(PRESETS))
        sys.exit(1)

    open(STATE_FILE, "w").write(f"{r} {g} {b}\n")
    _send(_set_color(r, g, b))
    print(f"Color → rgb({r}, {g}, {b})")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0].lower()
    if cmd == "on":
        cmd_on()
    elif cmd == "off":
        cmd_off()
    elif cmd == "color":
        cmd_color(args[1:])
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
