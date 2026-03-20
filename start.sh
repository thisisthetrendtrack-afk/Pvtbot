#!/usr/bin/env bash
set -euo pipefail

if ! python3 -c "import telegram, requests" >/dev/null 2>&1; then
  echo "Installing missing dependencies from requirements.txt..."
  python3 -m pip install -r requirements.txt
fi

exec python3 bot.py
