#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/run.log"
VENV="$DIR/venv"
export PYTHONUNBUFFERED=1

{
    echo "===== $(date) ====="
    echo "DIR=$DIR"

    cd "$DIR"
    fuser -k 5000/tcp 2>/dev/null || true

    if [ ! -f "$VENV/bin/python3" ]; then
        echo "Creating virtual environment..."
        python3 -m venv "$VENV"
    fi

    echo "Checking dependencies..."
    if ! "$VENV/bin/python3" -c "import requests, flask, reportlab" 2>/dev/null; then
        echo "Installing requirements..."
        "$VENV/bin/pip" install -r requirements.txt --quiet 2>&1
    fi

    MODE="${1:-gui}"
    echo "Launching main.py (mode=$MODE)..."
    if [ "$MODE" = "web" ]; then
        "$VENV/bin/python3" main.py --web
    else
        "$VENV/bin/python3" main.py
    fi
} >> "$LOG" 2>&1
