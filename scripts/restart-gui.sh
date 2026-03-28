#!/usr/bin/env bash
# Restart the music-dl GUI server on port 8765
set -euo pipefail

PORT=8765
VENV="$(dirname "$0")/../TIDALDL-PY/.venv/bin/python"

# Kill existing server
lsof -ti :"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1

cd "$(dirname "$0")/../TIDALDL-PY"
exec "$VENV" -c "from tidal_dl.gui.server import run; run(open_browser=False)"
