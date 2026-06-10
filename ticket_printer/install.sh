#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/venv"
APP_DIR="$HOME/.local/share/applications"

echo "========================================"
echo " Ticket Printer - One-Click Install"
echo "========================================"
echo ""

# Step 1: Create virtual environment
if [ ! -f "$VENV/bin/python3" ]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv "$VENV"
else
    echo "[1/4] Virtual environment already exists."
fi

# Step 2: Install dependencies
echo "[2/4] Installing dependencies..."
"$VENV/bin/pip" install -r "$DIR/requirements.txt" --quiet
echo "      Done."

# Step 3: Make scripts executable
echo "[3/4] Making scripts executable..."
chmod +x "$DIR/run.sh"
chmod +x "$DIR/main.py"

# Step 4: Create desktop shortcuts
echo "[4/4] Creating desktop shortcuts..."

mkdir -p "$APP_DIR"

# --- GUI mode ---
DESKTOP_GUI="$HOME/Desktop/ticket_printer.desktop"
cat > "$DESKTOP_GUI" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Ticket Printer
Comment=Print thermal tickets (GUI mode)
Exec="$DIR/run.sh"
Icon=printer
Terminal=false
Path=$DIR
Categories=Utility;Office;
StartupNotify=true
EOF
chmod +x "$DESKTOP_GUI"
cp "$DESKTOP_GUI" "$APP_DIR/ticket_printer.desktop"

# --- Web mode ---
DESKTOP_WEB="$HOME/Desktop/ticket_printer_web.desktop"
cat > "$DESKTOP_WEB" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Ticket Printer (Web)
Comment=Print thermal tickets from mobile (web mode)
Exec="$DIR/run.sh" web
Icon=network-server
Terminal=true
Path=$DIR
Categories=Utility;Office;
StartupNotify=true
EOF
chmod +x "$DESKTOP_WEB"
cp "$DESKTOP_WEB" "$APP_DIR/ticket_printer_web.desktop"

echo ""
echo "========================================"
echo " Install complete!"
echo "========================================"
echo ""
echo " Desktop shortcuts created:"
echo "   ~/Desktop/ticket_printer.desktop      (GUI mode)"
echo "   ~/Desktop/ticket_printer_web.desktop  (Web server mode)"
echo ""
echo " Use GUI mode for local printing."
echo " Use Web mode then open http://0.0.0.0:5000 from your phone."
echo ""
