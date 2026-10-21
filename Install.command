#!/bin/bash
# Double-click installer for macOS — sets everything up and can enable
# start-at-login. Safe to run again any time.
set -e
cd "$(dirname "$0")"

echo "=== Emby / Plex Discord Presence — installer ==="

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is required but was not found."
    echo "Install it from https://www.python.org/downloads/ then run this again."
    exit 1
fi

if [ ! -d .venv ]; then
    echo "Creating Python environment..."
    python3 -m venv .venv
fi
echo "Installing dependencies..."
.venv/bin/pip install -q -r requirements.txt

if [ -f .env ]; then
    read -r -p "Already configured — run the sign-in setup again? [y/N] " again
    case "$again" in [Yy]*) .venv/bin/python setup.py ;; esac
else
    .venv/bin/python setup.py
fi

read -r -p "Start automatically when you log in? [Y/n] " autostart
case "$autostart" in
    [Nn]*)
        echo "Run it any time with:  .venv/bin/python emby_discord_presence.py"
        ;;
    *)
        PLIST="$HOME/Library/LaunchAgents/com.emby.discordpresence.plist"
        mkdir -p "$HOME/Library/LaunchAgents"
        cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.emby.discordpresence</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PWD/.venv/bin/python</string>
    <string>emby_discord_presence.py</string>
  </array>
  <key>WorkingDirectory</key><string>$PWD</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/emby-discord-presence.log</string>
  <key>StandardErrorPath</key><string>/tmp/emby-discord-presence.err.log</string>
</dict>
</plist>
PLIST_EOF
        launchctl bootout "gui/$(id -u)/com.emby.discordpresence" 2>/dev/null || true
        launchctl bootstrap "gui/$(id -u)" "$PLIST"
        echo "Installed and running — it starts automatically at login."
        echo "Live logs: double-click Logs.command"
        ;;
esac
