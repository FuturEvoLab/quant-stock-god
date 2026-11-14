#!/bin/bash
# Quantriel — turn off macOS autostart (stops the background server and removes the login item).
LABEL="com.quantstockgod.server"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Autostart disabled and the background server stopped. Double-click Start-Quantriel.command to start it manually."
