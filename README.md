# Emby / Plex Discord Presence

Show what you're currently watching on your **Emby or Plex** server as your
Discord status.

```
🎬 Playing Emby
   Breaking Bad
   S02E07 · Negro y Azul        ⏱ 32:14 left
```

- **Movies** → title and year, with a time-remaining countdown
- **TV shows** → series name, season/episode, and episode title
- **Music** → track and artist
- **Artwork** → the real show poster / movie poster / album art on your
  profile. A public https Emby server is linked directly; Plex and
  LAN-only Emby servers re-host posters on Imgur instead (set
  `IMGUR_CLIENT_ID` in `.env` — see below). Without either, you get the
  server logo.
- **Paused** → shows a ⏸ Paused indicator
- Clears your status automatically when you stop playback

## How it works (and why it's secure)

One small Python script runs on **the same computer as your Discord desktop
app**. Every few seconds it asks your media server "what's playing?" and
updates your Discord status locally. That's it.

- No bot, no Discord token, and nothing hosted on the internet
- Your Emby API key / Plex token stays in a local `.env` file that git ignores
- The key/token is sent as an HTTP header, never in a URL
- Talks only to your own media server and the Discord app on your PC

## Setup (5 minutes)

**1. Get your server credentials**

- **Emby:** Emby Dashboard → **Advanced** → **API Keys** → **New API Key**.
  Name it `discord-presence` so you can revoke it later if you ever want to.
- **Plex:** you need your Plex auth token — follow
  [Plex's official guide](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token)
  (play any item in the Plex web app → ⋯ → **Get Info** → **View XML** →
  copy the `X-Plex-Token` value from the page's address). In `.env`, set
  `SERVER_TYPE=plex` and fill in `PLEX_URL`, `PLEX_TOKEN`, and
  `PLEX_USERNAME` instead of the Emby values.

**2. Create a Discord application**

Go to the [Discord Developer Portal](https://discord.com/developers/applications)
→ **New Application**. The name you give it is what Discord shows as
"Playing ..." — e.g. **Emby**. Copy the **Application ID** from the
General Information page.

*Optional:* under **Rich Presence → Art Assets**, upload an Emby logo with
the asset name `emby` so your status shows a nice icon.

**3. Install on your computer**

Follow the section for your OS below, then play something on Emby — your
status updates within ~15 seconds. Make sure the Discord **desktop app**
is running (the browser version can't show Rich Presence).

### Install on Windows

1. **Install Python** from [python.org/downloads](https://www.python.org/downloads/).
   On the first installer screen, tick **"Add python.exe to PATH"** before
   clicking Install.
2. **Download this app:** on the GitHub page click the green **Code**
   button → **Download ZIP**, and extract it somewhere permanent, e.g.
   `C:\Emby` (or `git clone https://github.com/iiMas1/Emby.git` if you
   have Git).
3. **Open PowerShell in that folder:** open the folder in File Explorer,
   then right-click an empty spot → **Open in Terminal**.
4. **Set up and configure:**

   ```powershell
   py -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   copy .env.example .env
   notepad .env
   ```

   In Notepad, fill in `EMBY_URL`, `EMBY_API_KEY`, `DISCORD_CLIENT_ID`,
   and your `EMBY_USERNAME`, then save and close.

   > If `py -m venv .venv` says Python isn't found, reinstall Python and
   > tick "Add python.exe to PATH", then open a new terminal.

5. **Run it:**

   ```powershell
   .venv\Scripts\python emby_discord_presence.py
   ```

### Install on macOS

1. **Check Python:** open **Terminal** (⌘-Space, type "Terminal") and run
   `python3 --version`. If macOS offers to install the Command Line Tools,
   accept — that includes Python. (Or install from
   [python.org/downloads](https://www.python.org/downloads/).)
2. **Download this app:**

   ```bash
   cd ~
   git clone https://github.com/iiMas1/Emby.git
   cd Emby
   ```

   (No Git? Download the ZIP from GitHub, double-click to extract, then
   `cd` into the extracted folder.)
3. **Set up and configure:**

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   cp .env.example .env
   open -e .env
   ```

   TextEdit opens the config — fill in `EMBY_URL`, `EMBY_API_KEY`,
   `DISCORD_CLIENT_ID`, and your `EMBY_USERNAME`, then save (⌘-S) and
   close.
4. **Run it:**

   ```bash
   .venv/bin/python emby_discord_presence.py
   ```

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

Setup (2 minutes): register an application at
[api.imgur.com/oauth2/addclient](https://api.imgur.com/oauth2/addclient)
(choose the option without a callback URL), then put the **Client ID** —
not the client secret — into `IMGUR_CLIENT_ID` in your `.env`.

Privacy note: uploaded posters are unlisted but technically public images
on Imgur. It's only cover art, never your token, titles, or account info —
but if you don't want that, leave `IMGUR_CLIENT_ID` empty and you'll get
the server logo instead.
| `HIDE_DETAILS` | `true` = show only "Watching a movie", no titles | `false` |

Also check Discord → **Settings → Activity Privacy** → "Share your detected
activities with others" must be on.

## Run it automatically (optional)

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
ExecStart=/usr/bin/python3 emby_discord_presence.py
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
