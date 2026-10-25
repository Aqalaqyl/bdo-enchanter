#!/usr/bin/env bash
# One-shot installer for Debian/Ubuntu-based systems (apt). Creates a local
# virtualenv in .venv and installs everything the enhancer needs.
set -euo pipefail
cd "$(dirname "$0")"

if command -v apt-get >/dev/null 2>&1; then
    echo "==> Installing system packages (sudo required)"
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-venv python3-tk python3-dev \
        tesseract-ocr libgl1 libxcb-xinerama0 libxkbcommon-x11-0
else
    echo "!! No apt-get found. Install manually: python3 (with venv + tkinter), tesseract-ocr"
fi

echo "==> Creating virtualenv (.venv)"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    echo
    echo "!! You are on a Wayland session. Screen capture and clicks require X11."
    echo "   Log out and choose an 'X11' / 'Xorg' session at the login screen."
fi

echo
echo "Done. Now run the guided setup:"
echo "    .venv/bin/python enchanter.py setup"
