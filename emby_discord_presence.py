#!/usr/bin/env python3
"""Media server Discord Presence.

Shows what you're currently watching (or listening to) on your Emby or
Plex server as a Discord Rich Presence status.

Run this on the same computer where the Discord desktop app is running.
All configuration lives in a local .env file — see .env.example.
"""

import json
import logging
import os
import sys
import threading
import time

import certifi
import requests
import websocket
from dotenv import load_dotenv
from pypresence import ActivityType, Presence, StatusDisplayType
from pypresence.exceptions import DiscordError, DiscordNotFound, PipeClosed

TICKS_PER_SECOND = 10_000_000  # Emby reports positions in 100-nanosecond ticks

# Built-in Discord application ("Plex"), so no developer-portal setup is
# needed. Application IDs are public by design — set DISCORD_CLIENT_ID in
# .env to use your own application instead (its name is what Discord shows
# when no richer title is available, so Emby users may prefer their own).
DEFAULT_DISCORD_CLIENT_ID = "1562553954737594490"

# Built-in Imgur application for poster re-hosting, so artwork works with
# no setup. Imgur client IDs are public identifiers (they ship in every
# open-source app that uploads anonymously); set IMGUR_CLIENT_ID in .env
# to use your own, or SHOW_ARTWORK=false to disable artwork entirely.
DEFAULT_IMGUR_CLIENT_ID = "5cae6775116c078"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("media-discord-presence")


def load_config():
    """Read and validate settings from the environment / .env file."""
    load_dotenv()

    server_type = os.getenv("SERVER_TYPE", "emby").strip().lower()
    if server_type not in ("emby", "plex"):
        log.error("SERVER_TYPE must be 'emby' or 'plex', not %r", server_type)
        sys.exit(1)

    try:
        poll_interval = int(os.getenv("POLL_INTERVAL", "15"))
    except ValueError:
        log.warning("POLL_INTERVAL is not a number, using the default of 15s.")
        poll_interval = 15

    config = {
        "server_type": server_type,
        "server_name": "Plex" if server_type == "plex" else "Emby",
        "discord_client_id": os.getenv("DISCORD_CLIENT_ID", "").strip() or DEFAULT_DISCORD_CLIENT_ID,
        "poll_interval": max(5, poll_interval),
        "hide_details": os.getenv("HIDE_DETAILS", "false").lower() in ("1", "true", "yes"),
        "show_artwork": os.getenv("SHOW_ARTWORK", "true").lower() in ("1", "true", "yes"),
    }

    if server_type == "plex":
        config["url"] = os.getenv("PLEX_URL", "").rstrip("/")
        config["token"] = os.getenv("PLEX_TOKEN", "")
        config["username"] = os.getenv("PLEX_USERNAME", "").strip()
        config["device_id"] = os.getenv("PLEX_DEVICE_ID", "").strip().lower()
        required = (("PLEX_URL", "url"), ("PLEX_TOKEN", "token"))
    else:
        config["url"] = os.getenv("EMBY_URL", "").rstrip("/")
        config["token"] = os.getenv("EMBY_API_KEY", "")
        config["username"] = os.getenv("EMBY_USERNAME", "").strip()
        required = (("EMBY_URL", "url"), ("EMBY_API_KEY", "token"))

    missing = [name for name, key in required if not config[key]]
    if missing:
        log.error("Missing required settings: %s", ", ".join(missing))
        log.error("Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    if not config["url"].startswith(("http://", "https://")):
        log.error("The server URL must start with http:// or https://")
        sys.exit(1)

    # Discord's servers fetch the artwork, so the image URL must be reachable
    # from the internet over https, and the URL is visible to other Discord
    # users. Emby serves images without authentication, so linking directly
    # to a public Emby server is safe. Plex requires the auth token inside
    # every image URL, which would leak it — so Plex posters (and posters for
    # LAN-only Emby servers) are instead re-hosted on Imgur when an
    # IMGUR_CLIENT_ID is configured, and fall back to the static logo if not.
    artwork_base = ""
    if server_type == "emby":
        artwork_base = os.getenv("EMBY_PUBLIC_URL", "").rstrip("/") or config["url"]
    if not config["show_artwork"] or not artwork_base.startswith("https://"):
        artwork_base = ""
    config["artwork_base"] = artwork_base
    config["imgur_client_id"] = os.getenv("IMGUR_CLIENT_ID", "").strip() or DEFAULT_IMGUR_CLIENT_ID

    return config


ARTWORK_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artwork_cache.json")
_artwork_cache = None
_artwork_failures = set()


def imgur_artwork(config, cache_key, image_url, headers):
    """Re-host one poster on Imgur and return its public link, or None.

    The image is downloaded from the media server with the token in a
    header, then uploaded anonymously (as an unlisted image) to Imgur —
    only the picture leaves your network, never the token. Each poster is
    uploaded once and remembered in artwork_cache.json.
    """
    global _artwork_cache
    if _artwork_cache is None:
        try:
            with open(ARTWORK_CACHE_FILE) as cache_file:
                _artwork_cache = json.load(cache_file)
        except (OSError, ValueError):
            _artwork_cache = {}
    if cache_key in _artwork_cache:
        return _artwork_cache[cache_key]
    if cache_key in _artwork_failures:  # don't retry a bad poster every poll
        return None

    try:
        image = requests.get(image_url, headers=headers, timeout=15)
        image.raise_for_status()
        upload = requests.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": f"Client-ID {config['imgur_client_id']}"},
            files={"image": image.content},
            timeout=30,
        )
        upload.raise_for_status()
        link = upload.json()["data"]["link"]
    except (requests.RequestException, ValueError, KeyError) as error:
        log.warning("Could not upload poster to Imgur: %s", error)
        _artwork_failures.add(cache_key)
        return None

    _artwork_cache[cache_key] = link
    try:
        with open(ARTWORK_CACHE_FILE, "w") as cache_file:
            json.dump(_artwork_cache, cache_file, indent=1)
    except OSError as error:
        log.warning("Could not save artwork cache: %s", error)
    log.info("Poster uploaded to Imgur: %s", link)
    return link


def emby_artwork(item, config):
    """URL of the show poster / movie poster / album art, or None.

    A public https Emby server is linked directly — Emby serves item images
    without authentication, so no API key ever appears in the URL. A
    LAN-only server's posters are re-hosted on Imgur instead (when
    configured). Discord caps asset URLs at 256 characters.
    """
    if item.get("Type") == "Episode" and item.get("SeriesId") and item.get("SeriesPrimaryImageTag"):
        item_id, tag = item["SeriesId"], item["SeriesPrimaryImageTag"]  # show poster
    elif item.get("ImageTags", {}).get("Primary") and item.get("Id"):
        item_id, tag = item["Id"], item["ImageTags"]["Primary"]
    elif item.get("AlbumId") and item.get("AlbumPrimaryImageTag"):
        item_id, tag = item["AlbumId"], item["AlbumPrimaryImageTag"]  # album art
    else:
        return None

    image_path = f"/emby/Items/{item_id}/Images/Primary?tag={tag}&maxHeight=512&quality=90"
    if config["artwork_base"]:
        url = f"{config['artwork_base']}{image_path}"
        return url if len(url) <= 256 else None
    if config["imgur_client_id"] and config["show_artwork"] and not config["hide_details"]:
        return imgur_artwork(config, f"emby-{item_id}-{tag}",
                             f"{config['url']}{image_path}",
                             {"X-Emby-Token": config["token"]})
    return None


def plex_artwork(item, media_type, config):
    """Imgur URL of the show poster / movie poster / album art, or None.

    Plex image links only work with the auth token embedded, so they are
    never handed to Discord directly — see imgur_artwork.
    """
    if not config["imgur_client_id"] or not config["show_artwork"] or config["hide_details"]:
        return None
    if media_type == "Episode":
        path = item.get("grandparentThumb") or item.get("thumb")  # show poster
        key = item.get("grandparentRatingKey") or item.get("ratingKey")
    elif media_type == "Audio":
        path = item.get("parentThumb") or item.get("thumb")  # album art
        key = item.get("parentRatingKey") or item.get("ratingKey")
    else:
        path, key = item.get("thumb"), item.get("ratingKey")
    if not path or not key:
        return None
    return imgur_artwork(config, f"plex-{key}", f"{config['url']}{path}",
                         {"X-Plex-Token": config["token"]})


def fetch_emby(config):
    """Return the normalized now-playing state from Emby, or None.

    The API key is sent as a header, never in the URL, so it can't leak
    into proxy or server access logs.
    """
    response = requests.get(
        f"{config['url']}/emby/Sessions",
        headers={"X-Emby-Token": config["token"]},
        timeout=10,
    )
    response.raise_for_status()

    wanted_user = config["username"].lower()
    for session in response.json():
        item = session.get("NowPlayingItem")
        if not item:
            continue
        if wanted_user and session.get("UserName", "").lower() != wanted_user:
            continue
        play_state = session.get("PlayState", {})
        position = play_state.get("PositionTicks")
        runtime = item.get("RunTimeTicks")
        media_type = item.get("Type", "")
        return {
            "media_type": media_type,
            "title": item.get("Name", "Unknown"),
            "series": item.get("SeriesName"),
            "season": item.get("ParentIndexNumber"),
            "episode": item.get("IndexNumber"),
            "year": item.get("ProductionYear"),
            "artists": item.get("Artists", []),
            "album": item.get("Album"),
            "is_paused": play_state.get("IsPaused", False),
            "position_s": position // TICKS_PER_SECOND if position is not None else None,
            "runtime_s": runtime // TICKS_PER_SECOND if runtime else None,
            "artwork": emby_artwork(item, config),
        }
    return None


def plex_now_playing(item, config, position_ms, is_paused):
    """Normalize one Plex metadata item into the shared now-playing shape."""
    plex_type = item.get("type", "")
    media_type = {"movie": "Movie", "episode": "Episode", "track": "Audio"}.get(plex_type, plex_type)
    runtime = item.get("duration")
    return {
        "media_type": media_type,
        "title": item.get("title", "Unknown"),
        "series": item.get("grandparentTitle"),
        "season": item.get("parentIndex"),
        "episode": item.get("index"),
        "year": item.get("year"),
        # For music, Plex puts the artist in grandparentTitle and the
        # album in parentTitle.
        "artists": [item["grandparentTitle"]] if media_type == "Audio" and item.get("grandparentTitle") else [],
        "album": item.get("parentTitle") if media_type == "Audio" else None,
        "is_paused": is_paused,
        "position_s": position_ms // 1000 if position_ms is not None else None,  # Plex uses milliseconds
        "runtime_s": runtime // 1000 if runtime else None,
        "artwork": plex_artwork(item, media_type, config),
    }


def fetch_plex(config):
    """Return the normalized now-playing state from Plex, or None.

    The token is sent as a header, never in the URL, so it can't leak
    into proxy or server access logs.
    """
    response = requests.get(
        f"{config['url']}/status/sessions",
        headers={"X-Plex-Token": config["token"], "Accept": "application/json"},
        timeout=10,
    )
    response.raise_for_status()

    wanted_user = config["username"].lower()
    wanted_device = config["device_id"]
    for item in response.json().get("MediaContainer", {}).get("Metadata", []):
        user = item.get("User", {}).get("title", "")
        if wanted_user and user.lower() != wanted_user:
            continue
        player = item.get("Player", {})
        if wanted_device and player.get("machineIdentifier", "").lower() != wanted_device:
            continue
        return plex_now_playing(item, config, item.get("viewOffset"),
                                player.get("state") == "paused")
    return None


class PlexAlertListener:
    """Playback state over the Plex notifications websocket.

    Shared (non-admin) accounts get 403 from /status/sessions, but the
    websocket still delivers that account's own playback events — the same
    approach discord-rich-presence-plex uses. The token is sent as a
    header, never in the URL.
    """

    STALE_AFTER_S = 90  # no updates for this long -> assume playback ended

    def __init__(self, config):
        self.config = config
        self._lock = threading.Lock()
        self._session = None
        threading.Thread(target=self._run_forever, daemon=True).start()

    def _run_forever(self):
        url = self.config["url"].replace("http", "ws", 1) + "/:/websockets/notifications"
        while True:
            app = websocket.WebSocketApp(
                url,
                header={"X-Plex-Token": self.config["token"]},
                on_message=self._on_message,
            )
            # Pings detect silently-dead connections (sleep, network change)
            # that would otherwise hang forever without ever reconnecting.
            app.run_forever(sslopt={"ca_certs": certifi.where()},
                            ping_interval=30, ping_timeout=10)
            log.warning("Plex websocket disconnected, reconnecting in 5s...")
            time.sleep(5)

    def _on_message(self, _app, message):
        try:
            container = json.loads(message).get("NotificationContainer", {})
        except ValueError:
            return
        if container.get("type") != "playing":
            return
        wanted_device = self.config["device_id"]
        for notif in container.get("PlaySessionStateNotification", []):
            if wanted_device and notif.get("clientIdentifier", "").lower() != wanted_device:
                continue
            with self._lock:
                if notif.get("state") == "stopped":
                    self._session = None
                else:
                    self._session = {
                        "rating_key": notif.get("ratingKey"),
                        "state": notif.get("state"),
                        "position_ms": notif.get("viewOffset"),
                        "seen_at": time.monotonic(),
                    }

    def current(self):
        """Latest playback event, or None once it has gone stale."""
        with self._lock:
            session = self._session
        if not session:
            return None
        age = time.monotonic() - session["seen_at"]
        if age > self.STALE_AFTER_S:
            return None
        if session["state"] == "playing" and session["position_ms"] is not None:
            # Notifications only arrive every ~10s; extrapolate the position
            # in between so the Discord countdown doesn't jump around.
            session = {**session, "position_ms": session["position_ms"] + int(age * 1000)}
        return session


_plex_metadata_cache = {}


def fetch_plex_alerts(config, listener):
    """Like fetch_plex, but driven by websocket events (shared accounts)."""
    session = listener.current()
    if not session or not session.get("rating_key"):
        return None

    rating_key = session["rating_key"]
    item = _plex_metadata_cache.get(rating_key)
    if item is None:
        response = requests.get(
            f"{config['url']}/library/metadata/{rating_key}",
            headers={"X-Plex-Token": config["token"], "Accept": "application/json"},
            timeout=10,
        )
        if response.status_code == 404:  # item deleted from the library
            return None
        response.raise_for_status()
        metadata = response.json().get("MediaContainer", {}).get("Metadata", [])
        if not metadata:
            return None
        item = metadata[0]
        _plex_metadata_cache.clear()  # only the current item is ever needed
        _plex_metadata_cache[rating_key] = item

    return plex_now_playing(item, config, session["position_ms"],
                            session["state"] == "paused")


def clamp(text, fallback="Media"):
    """Discord requires presence strings between 2 and 128 characters."""
    text = (text or fallback).strip() or fallback
    if len(text) < 2:
        text += " "
    return text[:128]


def build_presence(now, config):
    """Translate the normalized now-playing state into Discord fields.

    Spotify-style card: a bare "Watching" / "Listening to" header, the
    work's title as the bold line, episode/year details under it, and a
    progress bar with elapsed/total times from the start+end timestamps.
    While paused, the detail line gains a ⏸ marker and the progress bar
    is dropped (Discord timers can't freeze), returning on resume.
    """
    media_type = now["media_type"]

    # An invisible activity name keeps the card header a bare "Watching" /
    # "Listening to", so the work's title leads the card body instead.
    name = "⠀"
    state = None
    if config["hide_details"]:
        generic = {
            "Movie": "Watching a movie",
            "Episode": "Watching a TV show",
            "Audio": "Listening to music",
        }.get(media_type, "Watching something")
        details, state = generic, f"on {config['server_name']}"
    elif media_type == "Episode":
        # Bold line = the series, detail line = season/episode and title.
        details = now["series"] or now["title"]
        season, episode = now["season"], now["episode"]
        marker = f"S{season:02d}E{episode:02d}" if season is not None and episode is not None else ""
        state = " · ".join(part for part in (marker, now["title"]) if part) or "Episode"
    elif media_type == "Audio":
        details = now["title"]
        artists = ", ".join(now["artists"])
        state = f"by {artists}" if artists else (now["album"] or "Music")
    else:  # Movie and anything else
        details = now["title"]
        state = f"({now['year']})" if now["year"] else "Movie"

    if now["is_paused"]:
        state = f"⏸ Paused · {state}" if state else "⏸ Paused"

    # Real poster/album art when available; never in privacy mode.
    image = None if config["hide_details"] else now["artwork"]
    logo = config["server_type"]  # Discord asset keys: "emby" and "plex"
    presence = {
        "activity_type": ActivityType.LISTENING if media_type == "Audio" else ActivityType.WATCHING,
        # The friends-list line shows the activity name by default, which
        # we keep invisible — point it at details (the work title) instead.
        "status_display_type": StatusDisplayType.DETAILS,
        "name": clamp(name) if name else None,
        "details": clamp(details),
        "state": clamp(state) if state else None,
        "large_image": image or logo,
        "large_text": clamp(details),
        "small_image": logo if image else None,
        "small_text": config["server_name"] if image else None,
    }
    presence = {key: value for key, value in presence.items() if value is not None}

    # Spotify-style progress bar: start+end together render elapsed/total.
    if not now["is_paused"] and now["position_s"] is not None and now["runtime_s"]:
        started = int(time.time()) - now["position_s"]
        presence["start"] = started
        presence["end"] = started + now["runtime_s"]

    return presence


def connect_discord(client_id):
    """Connect to the local Discord client, retrying until it's available."""
    while True:
        try:
            rpc = Presence(client_id)
            rpc.connect()
            log.info("Connected to Discord.")
            return rpc
        except (DiscordNotFound, DiscordError, ConnectionError, FileNotFoundError):
            log.warning("Discord desktop app not reachable, retrying in 15s...")
            time.sleep(15)


def main():
    config = load_config()
    fetch_now_playing = fetch_plex if config["server_type"] == "plex" else fetch_emby
    log.info("Watching %s at %s (user filter: %s)",
             config["server_name"], config["url"], config["username"] or "any")
    if config.get("device_id"):
        log.info("Only showing playback from device %s", config["device_id"])

    # Shared (non-admin) Plex accounts can't poll /status/sessions (403).
    # The notifications websocket still reports the account's own playback,
    # so switch to it automatically.
    listener = None

    def switch_to_alerts():
        nonlocal fetch_now_playing, listener
        log.info("No admin access to sessions — using websocket notifications instead.")
        listener = PlexAlertListener(config)
        fetch_now_playing = lambda cfg: fetch_plex_alerts(cfg, listener)
        # Events arrive pushed and reads are in-memory, so a fast
        # tick costs nothing and reacts to pause/resume promptly.
        config["poll_interval"] = min(config["poll_interval"], 3)

    if config["server_type"] == "plex":
        try:
            probe = requests.get(
                f"{config['url']}/status/sessions",
                headers={"X-Plex-Token": config["token"], "Accept": "application/json"},
                timeout=10,
            )
            if probe.status_code in (401, 403):
                switch_to_alerts()
        except requests.RequestException as error:
            log.warning("Could not probe %s yet: %s", config["server_name"], error)

    rpc = connect_discord(config["discord_client_id"])
    last_shown = None
    was_paused = False

    while True:
        try:
            now = fetch_now_playing(config)
        except (requests.RequestException, ValueError) as error:
            # A 401/403 at runtime means the startup probe was missed (e.g.
            # the network wasn't up yet) — switch to websocket mode now
            # instead of warning forever.
            if (config["server_type"] == "plex" and listener is None
                    and isinstance(error, requests.HTTPError)
                    and error.response is not None
                    and error.response.status_code in (401, 403)):
                switch_to_alerts()
            else:
                log.warning("Could not reach %s: %s", config["server_name"], error)
            now = None

        try:
            if now:
                presence = build_presence(now, config)
                shown = (presence.get("name", ""), presence["details"], presence.get("state", ""))
                if now["is_paused"] and not was_paused:
                    # Discord keeps counting down the previous timestamps on
                    # its own; a plain update doesn't always drop them.
                    rpc.clear()
                was_paused = now["is_paused"]
                rpc.update(**presence)
                if shown != last_shown:
                    log.info("Now playing: %s",
                             " — ".join(part for part in shown if part.strip("⠀ ")))
                last_shown = shown
            elif last_shown is not None:
                rpc.clear()
                log.info("Playback stopped, presence cleared.")
                last_shown = None
                was_paused = False
        except (PipeClosed, DiscordError, ConnectionError, BrokenPipeError):
            log.warning("Lost connection to Discord, reconnecting...")
            rpc = connect_discord(config["discord_client_id"])
            last_shown = None
            was_paused = False

        time.sleep(config["poll_interval"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Stopped.")
