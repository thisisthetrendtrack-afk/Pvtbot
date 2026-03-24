#!/usr/bin/env bash
set -euo pipefail

# Railway/hosted deployments sometimes end up with smart quotes after copy/paste.
# Normalize common unicode quote characters before Python starts.
python3 - <<'PY'
from pathlib import Path

targets = [Path("bot.py"), Path("run.py")]
replacements = {
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
}

for path in targets:
    if not path.exists():
        continue
    original = path.read_text(encoding="utf-8")
    normalized = original
    for bad, good in replacements.items():
        normalized = normalized.replace(bad, good)
    if normalized != original:
        path.write_text(normalized, encoding="utf-8")
        print(f"Normalized unicode quotes in {path}")
PY

if ! python3 -c "import telegram, requests" >/dev/null 2>&1; then
  echo "Installing missing dependencies from requirements.txt..."
  python3 -m pip install -r requirements.txt
fi

exec python3 bot.py
