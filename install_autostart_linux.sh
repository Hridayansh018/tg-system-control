#!/bin/bash
# Install TG-System-Control as a systemd user service on Linux
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/tg-system-control.service"

mkdir -p "$SERVICE_DIR" "$DIR/temp"

PYTHON_BIN="$DIR/.venv/bin/python3"
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(which python3)"
fi

echo "========================================================"
echo "  Installing TG-System-Control as a systemd User Service"
echo "========================================================"
echo "Working Directory: $DIR"
echo "Python Binary:     $PYTHON_BIN"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=TG-System-Control Desktop Remote Controller
After=network-online.target graphical-session.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
# Screenshots / mouse / keyboard need the graphical session (X11). Adjust if your display differs.
Environment=DISPLAY=${DISPLAY:-:0}
Environment=XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}
ExecStart=$PYTHON_BIN -u $DIR/main.py
Restart=always
RestartSec=5
StandardOutput=append:$DIR/temp/agent_linux.log
StandardError=append:$DIR/temp/agent_linux_err.log

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now tg-system-control.service

# Enable lingering so service runs even when no graphical session is active
loginctl enable-linger "$USER" 2>/dev/null || true

echo ""
echo "✅ Auto-start service installed and running on Linux!"
echo "Service status: systemctl --user status tg-system-control"
echo "To uninstall later, run: systemctl --user disable --now tg-system-control && rm $SERVICE_FILE"
