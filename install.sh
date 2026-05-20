#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP="$HOME/Desktop/ticket_printer.desktop"
APP_DIR="$HOME/.local/share/applications"

chmod +x "$DIR/run.sh"

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Ticket Printer
Comment=Print thermal tickets for sales
Exec="$DIR/run.sh"
Icon=utilities-terminal
Terminal=false
Path=$DIR
Categories=Utility;Office;
StartupNotify=true
EOF

chmod +x "$DESKTOP"

# Also install to app menu
mkdir -p "$APP_DIR"
cp "$DESKTOP" "$APP_DIR/ticket_printer.desktop"

echo "✓ Desktop shortcut created at: $DESKTOP"
echo "  (also installed to application menu)"
