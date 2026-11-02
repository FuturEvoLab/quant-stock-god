#!/bin/bash
# Quant Stock God — start automatically at macOS login and keep running in the background, so watchlist and
# major-news alerts keep working. Double-click again to reinstall with the latest settings; to undo, double-click
# Disable-Autostart-macOS.command.
cd "$(dirname "$0")"
DIR="$(pwd)"
LABEL="com.quantstockgod.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGDIR="$HOME/Library/Logs/QuantStockGod"
PORT="${PORT:-8767}"
PY="$(command -v python3)"
if [ -z "$PY" ]; then
  echo "python3 was not found. Install Python 3 (https://www.python.org/downloads/) first."
  read -n 1 -s -r -p "Press any key to close…"; exit 1
fi
mkdir -p "$HOME/Library/LaunchAgents" "$LOGDIR"
# If a manually started copy holds the port, ask the user to close it so two servers don't fight over it
if lsof -iTCP:$PORT -sTCP:LISTEN >/dev/null 2>&1 && ! launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  echo "Port $PORT is already in use (maybe a manually started Quant Stock God or another program). Close it, then double-click this file again."
  lsof -iTCP:$PORT -sTCP:LISTEN
  read -n 1 -s -r -p "Press any key to close…"; exit 1
fi
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/server.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict><key>PORT</key><string>$PORT</string><key>PYTHONUNBUFFERED</key><string>1</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>ProcessType</key><string>Standard</string>
  <key>StandardOutPath</key><string>$LOGDIR/server.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/server.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Autostart enabled: $LABEL"
echo "Log: $LOGDIR/server.log"
for i in $(seq 1 20); do
  if curl -s -m 2 "http://127.0.0.1:$PORT/api/status" | grep -q '"yahoo"'; then
    echo "Server is running: http://127.0.0.1:$PORT"; open "http://127.0.0.1:$PORT"; exit 0
  fi
  sleep 1
done
echo "The server is not responding yet. Open http://127.0.0.1:$PORT in a moment, or check the log."
