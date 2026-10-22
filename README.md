# Emby / Plex Discord Presence

Show what you're currently watching on your **Emby or Plex** server as your
Discord status.

```
Watching
   Breaking Bad
   S02E07 · Negro y Azul
   ▶ ━━━●─────── 12:46 / 47:12
```

- **TV shows** → series name in bold, season/episode and title under it,
  and a Spotify-style progress bar with elapsed/total times
- **Movies** → title and year, same progress bar
- **Music** → shows as **Listening**, with track and artist
- **Artwork** → the real show poster / movie poster / album art on your
  profile. A public https Emby server is linked directly; Plex and
  LAN-only Emby servers re-host posters on Imgur instead (set
  `IMGUR_CLIENT_ID` in `.env` — see below). Without either, you get the
  server logo.
- **Paused or stopped** → the status disappears, just like Spotify, and
  comes back when you resume

## How it works (and why it's secure)

One small Python script runs on **the same computer as your Discord desktop
app**. Every few seconds it asks your media server "what's playing?" and
updates your Discord status locally. That's it.

- No bot, no Discord token, and nothing hosted on the internet
- Your Emby API key / Plex token stays in a local `.env` file that git ignores
- The key/token is sent as an HTTP header, never in a URL
- Talks only to your own media server and the Discord app on your PC

## Setup (5 minutes)

No tokens or API keys to hunt down — the interactive `setup.py` signs you
in and writes the whole config for you:

- **Plex:** opens plex.tv/link in your browser, you type a short code
  there, and it discovers your servers automatically (works with shared
  servers too — your password never touches the script).
- **Emby:** asks for your server address and your normal Emby login, signs
  in once, and keeps only the access token — the password is never stored.
- **Discord:** nothing to do — a built-in Discord application ships with
  the tool. (Optionally paste your own Application ID at the prompt to
  control the fallback activity name and icon assets.)

*Optional, own-application users:* under **Rich Presence → Art Assets**,
upload a logo named `emby` or `plex` so the status shows a nice icon when
no poster is available.

Follow the section for your OS below, then play something — your status
updates within seconds. Make sure the Discord **desktop app** is running
(the browser version can't show Rich Presence).

### Install on Windows

1. **Install Python** from [python.org/downloads](https://www.python.org/downloads/).
   On the first installer screen, tick **"Add python.exe to PATH"** before
   clicking Install.
2. **Copy this one line into PowerShell** (right-click Start → "Terminal"
   or "Windows PowerShell"), press Enter, and answer the prompts (Plex or
   Emby, sign in, auto-start) — it downloads the latest version into
   `~\Emby` and sets everything up. That's it.

   ```powershell
   $d="$HOME\Emby"; mkdir -Force $d >$null; iwr -useb https://codeload.github.com/iiMas1/Emby/zip/refs/heads/master -OutFile "$env:TEMP\emby.zip"; Expand-Archive -Force "$env:TEMP\emby.zip" "$env:TEMP\emby-x"; Copy-Item -Force -Recurse "$env:TEMP\emby-x\Emby-master\*" $d; Set-Location $d; cmd /c install.bat
   ```

   Running the same line again later updates to the latest version and
   keeps your settings.

   <details><summary>Prefer clicking? ZIP method</summary>

   Download the ZIP from the green **Code** button, extract it somewhere
   permanent (e.g. `C:\Emby`), and double-click `install.bat`. To update
   later, double-click `update.bat` — your settings are kept.
   </details>

   <details><summary>Prefer the terminal? Manual steps</summary>

   ```powershell
   py -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   .venv\Scripts\python setup.py
   .venv\Scripts\python emby_discord_presence.py
   ```
   </details>

### Install on macOS

1. **Check Python:** open **Terminal** (⌘-Space, type "Terminal") and run
   `python3 --version`. If macOS offers to install the Command Line Tools,
   accept — that includes Python. (Or install from
   [python.org/downloads](https://www.python.org/downloads/).)
2. **Copy this one line into Terminal** (⌘-Space, type "Terminal"),
   press Enter, and answer the prompts (Plex or Emby, sign in,
   auto-start) — it downloads the latest version into `~/Emby` and sets
   everything up, including starting automatically at login. That's it.

   ```bash
   mkdir -p ~/Emby && cd ~/Emby && curl -fsSL https://codeload.github.com/iiMas1/Emby/tar.gz/refs/heads/master | tar xz --strip-components 1 && bash Install.command
   ```

   Running the same line again later updates to the latest version and
   keeps your settings.

## Options

All options live in `.env`:

| Setting | What it does | Default |
|---|---|---|
| `SERVER_TYPE` | `emby` or `plex` | `emby` |
| `EMBY_USERNAME` / `PLEX_USERNAME` | Only show playback from this account | any account |
| `EMBY_PUBLIC_URL` | Public https address of your Emby server, used for poster art | empty |
| `IMGUR_CLIENT_ID` | Enables poster art for Plex / LAN-only Emby (see below) | empty |
| `SHOW_ARTWORK` | `false` = never show poster art | `true` |
| `POLL_INTERVAL` | Seconds between checks (min 5) | `15` |

### Poster art via Imgur (Plex, or Emby without a public URL)

Discord's servers have to fetch the poster image themselves, and the image
URL is visible to other Discord users. Plex image links only work with your
auth token embedded in them, so handing them to Discord would leak access to
your server — and a LAN-only Emby server simply isn't reachable by Discord
at all. The fix: the script downloads the poster locally (token stays in a
header) and re-hosts **just the picture** on Imgur as an anonymous unlisted
image, once per show/movie/album (cached in `artwork_cache.json`).

No setup needed — a built-in Imgur application ships with the tool. To
use your own instead, register one at
[api.imgur.com/oauth2/addclient](https://api.imgur.com/oauth2/addclient)
(choose the option without a callback URL) and put the **Client ID** —
not the client secret — into `IMGUR_CLIENT_ID` in your `.env`.

Privacy note: uploaded posters are unlisted but technically public images
on Imgur. It's only cover art, never your token, titles, or account info —
but if you don't want that, leave `IMGUR_CLIENT_ID` empty and you'll get
the server logo instead.
| `HIDE_DETAILS` | `true` = show only "Watching a movie", no titles | `false` |

Also check Discord → **Settings → Activity Privacy** → "Share your detected
activities with others" must be on.

## Run it automatically (optional)

The Windows and macOS installers already offer this — the steps below are
only for Linux or manual setups.

**Windows:** press `Win+R`, type `shell:startup`, press Enter, and create a
file there named `emby-presence.bat` containing (adjust the path to where
you put the app):

```bat
@echo off
cd /d C:\Emby
start "" .venv\Scripts\pythonw.exe emby_discord_presence.py
```

(`pythonw.exe` runs it in the background without a console window. To stop
it, end the `pythonw.exe` process in Task Manager.)

**macOS (launchd):** create
`~/Library/LaunchAgents/com.emby.discordpresence.plist` (adjust both paths
to where you put the app, replacing `YOURNAME`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.emby.discordpresence</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOURNAME/Emby/.venv/bin/python</string>
    <string>emby_discord_presence.py</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/YOURNAME/Emby</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```

Then run `launchctl load ~/Library/LaunchAgents/com.emby.discordpresence.plist`.
It now starts on every login; stop it with `launchctl unload` of the same file.

**Linux (systemd user service):** create
`~/.config/systemd/user/emby-discord-presence.service`:

```ini
[Unit]
Description=Emby Discord Presence

[Service]
WorkingDirectory=/path/to/Emby
ExecStart=/path/to/Emby/.venv/bin/python emby_discord_presence.py
Restart=on-failure

[Install]
WantedBy=default.target
```

Then: `systemctl --user enable --now emby-discord-presence`

## Troubleshooting

- **"Discord desktop app not reachable"** — open the Discord desktop app;
  the script reconnects automatically.
- **Status never appears** — check Discord's Activity Privacy setting
  (above), and confirm `EMBY_USERNAME` matches your Emby account exactly.
- **"Could not reach Emby"** — check `EMBY_URL` is reachable from this
  computer (open it in a browser) and the API key is valid.
