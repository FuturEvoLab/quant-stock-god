#!/bin/bash
# Quant Stock God — double-click to start on macOS.
# If it is already running (for example with autostart), just open the browser; otherwise run it in this
# Terminal window. Closing the window stops it.
cd "$(dirname "$0")"
PORT="${PORT:-8767}"
URL="http://127.0.0.1:$PORT"
if curl -s -m 2 "$URL/api/status" 2>/dev/null | grep -q '"yahoo"'; then
  echo "Quant Stock God is already running: $URL"
  open "$URL"
  exit 0
fi
# If another program holds the port, use the next free one
while lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1; do PORT=$((PORT + 1)); done
URL="http://127.0.0.1:$PORT"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 was not found. Install Python 3 (https://www.python.org/downloads/), then double-click this file again."
  read -n 1 -s -r -p "Press any key to close…"; exit 1
fi
export PORT
(sleep 1.5; open "$URL") &
echo "Starting Quant Stock God: $URL (close this window to stop it)"
python3 server.py
