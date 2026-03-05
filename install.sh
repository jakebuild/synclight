#!/usr/bin/env bash
# Installs the SyncLight driver as a macOS Login Item (LaunchAgent).
# Run once: ./install.sh
# To uninstall: ./install.sh --uninstall

set -euo pipefail

LABEL="com.robobloq.synclight"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$SCRIPT_DIR/synclight.py"
PYTHON="$( (which /opt/homebrew/bin/python3.11 || which python3) 2>/dev/null | head -1 )"
LOG="$HOME/Library/Logs/SyncLight.log"

# ── uninstall ──────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "SyncLight driver uninstalled."
    exit 0
fi

# ── install dependency ─────────────────────────────────────────────────────────
echo "Installing Python dependencies..."
"$PYTHON" -m pip install --quiet hid pyobjc-framework-Cocoa

# ── create LaunchAgent plist ───────────────────────────────────────────────────
mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$HOME/Library/Logs"

cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SCRIPT</string>
    </array>

    <!-- Start at login and keep alive if it crashes -->
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$LOG</string>
    <key>StandardErrorPath</key>
    <string>$LOG</string>
</dict>
</plist>
EOF

# ── load the agent ─────────────────────────────────────────────────────────────
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"

echo ""
echo "SyncLight driver installed and running."
echo "  Script : $SCRIPT"
echo "  Logs   : $LOG"
echo ""
echo "To stop:      launchctl unload $PLIST"
echo "To uninstall: ./install.sh --uninstall"
