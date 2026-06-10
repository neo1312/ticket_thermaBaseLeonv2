#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/run.log"
VENV="$DIR/venv"

{
    echo "===== $(date) ====="
    echo "DIR=$DIR"

    cd "$DIR"

    if [ ! -f "$VENV/bin/python3" ]; then
        echo "Creating virtual environment..."
        python3 -m venv "$VENV"
    fi

    echo "Checking dependencies..."
    if ! "$VENV/bin/python3" -c "import requests" 2>/dev/null; then
        echo "Installing requirements..."
        "$VENV/bin/pip" install -r requirements.txt --quiet 2>&1
    fi

    echo "Launching main.py..."
    "$VENV/bin/python3" main.py
} >> "$LOG" 2>&1
