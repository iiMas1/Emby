#!/bin/bash
# Live log console for the Discord presence app — double-click to open.
echo "=== Emby/Plex Discord Presence — live logs (Ctrl+C to close) ==="
exec tail -n 40 -F /tmp/emby-discord-presence.err.log /tmp/emby-discord-presence.log
