#!/bin/bash
# Install TG-System-Control as a launchd User Agent on macOS
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_FILE="$PLIST_DIR/com.hermes.tgsystemcontrol.plist"

mkdir -p "$PLIST_DIR" "$DIR/temp"

PYTHON_BIN="$DIR/.venv/bin/python3"
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(which python3)"
fi

echo "========================================================"
echo "  Installing TG-System-Control to macOS LaunchAgents"
echo "========================================================"
echo "Working Directory: $DIR"
echo "Python Binary:     $PYTHON_BIN"

cat <<EOF > "$PLIST_FILE"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hermes.tgsystemcontrol</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>-u</string>
        <string>$DIR/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$DIR/temp/agent_mac.log</string>
    <key>StandardErrorPath</key>
    <string>$DIR/temp/agent_mac_err.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST_FILE" 2>/dev/null || true
launchctl load "$PLIST_FILE"

echo ""
echo "✅ Auto-start installed and launched successfully on macOS!"
echo "Plist location: $PLIST_FILE"
echo "To uninstall later, run: launchctl unload $PLIST_FILE && rm $PLIST_FILE"
