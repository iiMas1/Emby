# Emby Discord Presence

Show what you're currently watching on your Emby server as your Discord status.

```
🎬 Playing Emby
   Breaking Bad
   S02E07 · Negro y Azul        ⏱ 32:14 left
```

- **Movies** → title and year, with a time-remaining countdown
- **TV shows** → series name, season/episode, and episode title
- **Music** → track and artist
- **Artwork** → the real show poster / movie poster / album art on your
  profile, when your Emby server is reachable over public https
  (see `EMBY_PUBLIC_URL` in `.env.example`); otherwise the Emby logo
- **Paused** → shows a ⏸ Paused indicator
- Clears your status automatically when you stop playback

## How it works (and why it's secure)

One small Python script runs on **the same computer as your Discord desktop
app**. Every few seconds it asks your Emby server "what's playing?" and
updates your Discord status locally. That's it.

- No bot, no Discord token, and nothing hosted on the internet
- Your Emby API key stays in a local `.env` file that git ignores
- The API key is sent as an HTTP header, never in the URL
- Talks only to your own Emby server and the Discord app on your PC

## Setup (5 minutes)

**1. Get an Emby API key**

Emby Dashboard → **Advanced** → **API Keys** → **New API Key**. Name it
`discord-presence` so you can revoke it later if you ever want to.

**2. Create a Discord application**

Go to the [Discord Developer Portal](https://discord.com/developers/applications)
→ **New Application**. The name you give it is what Discord shows as
"Playing ..." — e.g. **Emby**. Copy the **Application ID** from the
General Information page.

*Optional:* under **Rich Presence → Art Assets**, upload an Emby logo with
the asset name `emby` so your status shows a nice icon.

**3. Configure**

```bash
git clone https://github.com/iiMas1/Emby.git
cd Emby
cp .env.example .env
```

Open `.env` and fill in `EMBY_URL`, `EMBY_API_KEY`, `DISCORD_CLIENT_ID`,
and your `EMBY_USERNAME` (so only your own playback shows up).

**4. Install and run**

Needs [Python 3.9+](https://www.python.org/downloads/) — on Windows, tick
"Add Python to PATH" during install.

```bash
pip install -r requirements.txt
python emby_discord_presence.py
```

Make sure the Discord **desktop app** is running (the browser version
can't show Rich Presence), then play something on Emby. Your status
updates within ~15 seconds.

## Options

All options live in `.env`:

| Setting | What it does | Default |
|---|---|---|
| `EMBY_USERNAME` | Only show playback from this Emby account | any account |
| `EMBY_PUBLIC_URL` | Public https address of your server, used for poster art | empty |
| `SHOW_ARTWORK` | `false` = never show poster art | `true` |
| `POLL_INTERVAL` | Seconds between checks (min 5) | `15` |
| `HIDE_DETAILS` | `true` = show only "Watching a movie", no titles | `false` |

Also check Discord → **Settings → Activity Privacy** → "Share your detected
activities with others" must be on.

## Run it automatically (optional)

**Windows:** press `Win+R`, type `shell:startup`, and drop in a shortcut to
a `start-emby-presence.bat` file containing:

```bat
@echo off
cd /d C:\path\to\Emby
pythonw emby_discord_presence.py
```

(`pythonw` runs it without a console window.)

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
