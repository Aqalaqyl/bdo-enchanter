#!/usr/bin/env bash
# One-shot installer for Debian/Ubuntu-based Linux. Creates .venv with every
# Python dependency and installs the system packages the enhancer needs.
set -euo pipefail
cd "$(dirname "$0")"

if command -v apt-get >/dev/null 2>&1; then
    echo "==> Installing system packages (sudo required)"
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3 python3-venv python3-tk python3-dev \
        tesseract-ocr xdotool libgl1
else
    echo "!! apt-get not found. Install these yourself: python3 (with venv and tkinter),"
    echo "   tesseract-ocr, xdotool. Then re-run this script."
fi

echo "==> Creating virtualenv (.venv) and installing Python packages"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
# pynput's X11 backend only needs python-xlib; skip its evdev dependency (needs a compiler).
.venv/bin/pip install --quiet --no-deps "pynput>=1.7.6"

if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    echo
    echo "!! You are on a Wayland session. Screen capture and clicks need X11:"
    echo "   log out and choose an 'X11' / 'Xorg' session on the login screen."
fi

echo
echo "Done. Next, with the game running in windowed/borderless mode:"
echo "    ./enchanter setup"
