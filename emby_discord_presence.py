#!/usr/bin/env python3
"""Media server Discord Presence.

Shows what you're currently watching (or listening to) on your Emby or
Plex server as a Discord Rich Presence status.

Run this on the same computer where the Discord desktop app is running.
All configuration lives in a local .env file — see .env.example.
"""

import logging
import os
import sys
import time

import requests
from dotenv import load_dotenv
from pypresence import Presence
from pypresence.exceptions import DiscordError, DiscordNotFound, PipeClosed

TICKS_PER_SECOND = 10_000_000  # Emby reports positions in 100-nanosecond ticks

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

    config = {
        "server_type": server_type,
        "server_name": "Plex" if server_type == "plex" else "Emby",
        "discord_client_id": os.getenv("DISCORD_CLIENT_ID", "").strip(),
        "poll_interval": max(5, int(os.getenv("POLL_INTERVAL", "15"))),
        "hide_details": os.getenv("HIDE_DETAILS", "false").lower() in ("1", "true", "yes"),
        "show_artwork": os.getenv("SHOW_ARTWORK", "true").lower() in ("1", "true", "yes"),
    }

    if server_type == "plex":
        config["url"] = os.getenv("PLEX_URL", "").rstrip("/")
        config["token"] = os.getenv("PLEX_TOKEN", "")
        config["username"] = os.getenv("PLEX_USERNAME", "").strip()
        required = (("PLEX_URL", "url"), ("PLEX_TOKEN", "token"))
    else:
        config["url"] = os.getenv("EMBY_URL", "").rstrip("/")
        config["token"] = os.getenv("EMBY_API_KEY", "")
        config["username"] = os.getenv("EMBY_USERNAME", "").strip()
        required = (("EMBY_URL", "url"), ("EMBY_API_KEY", "token"))

    missing = [name for name, key in required if not config[key]]
    if not config["discord_client_id"]:
        missing.append("DISCORD_CLIENT_ID")
    if missing:
        log.error("Missing required settings: %s", ", ".join(missing))
        log.error("Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    if not config["url"].startswith(("http://", "https://")):
        log.error("The server URL must start with http:// or https://")
        sys.exit(1)

    # Discord's servers fetch the artwork, so the image URL must be reachable
    # from the internet over https, and the URL is visible to other Discord
    # users. Emby serves images without authentication, so this is safe.
    # Plex requires the auth token inside every image URL, which would leak
    # it — Plex therefore always falls back to the static logo.
    artwork_base = ""
    if server_type == "emby":
        artwork_base = os.getenv("EMBY_PUBLIC_URL", "").rstrip("/") or config["url"]
    if not config["show_artwork"] or not artwork_base.startswith("https://"):
        artwork_base = ""
    config["artwork_base"] = artwork_base

    return config


def emby_artwork_url(item, base):
    """Public URL of the show poster / movie poster / album art, or None.

    Emby serves item images without authentication, so no API key ever
    appears in this URL. Discord caps asset URLs at 256 characters.
    """
    if not base:
        return None
    if item.get("Type") == "Episode" and item.get("SeriesId") and item.get("SeriesPrimaryImageTag"):
        item_id, tag = item["SeriesId"], item["SeriesPrimaryImageTag"]  # show poster
    elif item.get("ImageTags", {}).get("Primary"):
        item_id, tag = item.get("Id"), item["ImageTags"]["Primary"]
    elif item.get("AlbumId") and item.get("AlbumPrimaryImageTag"):
        item_id, tag = item["AlbumId"], item["AlbumPrimaryImageTag"]  # album art
    else:
        return None
    url = f"{base}/emby/Items/{item_id}/Images/Primary?tag={tag}&maxHeight=512&quality=90"
    return url if item_id and len(url) <= 256 else None


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
            "artwork": emby_artwork_url(item, config["artwork_base"]),
        }
    return None


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
    for item in response.json().get("MediaContainer", {}).get("Metadata", []):
        user = item.get("User", {}).get("title", "")
        if wanted_user and user.lower() != wanted_user:
            continue
        plex_type = item.get("type", "")
        media_type = {"movie": "Movie", "episode": "Episode", "track": "Audio"}.get(plex_type, plex_type)
        position = item.get("viewOffset")
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
            "is_paused": item.get("Player", {}).get("state") == "paused",
            "position_s": position // 1000 if position is not None else None,  # Plex uses milliseconds
            "runtime_s": runtime // 1000 if runtime else None,
            "artwork": None,  # see load_config: Plex image URLs would leak the token
        }
    return None


def clamp(text, fallback="Media"):
    """Discord requires presence strings between 2 and 128 characters."""
    text = (text or fallback).strip() or fallback
    if len(text) < 2:
        text += " "
    return text[:128]


def build_presence(now, config):
    """Translate the normalized now-playing state into Discord fields."""
    media_type = now["media_type"]

    if config["hide_details"]:
        generic = {
            "Movie": "Watching a movie",
            "Episode": "Watching a TV show",
            "Audio": "Listening to music",
        }.get(media_type, "Watching something")
        details, state = generic, f"on {config['server_name']}"
    elif media_type == "Episode":
        details = now["series"] or now["title"]
        season, episode = now["season"], now["episode"]
        marker = f"S{season:02d}E{episode:02d}" if season is not None and episode is not None else ""
        state = " · ".join(part for part in (marker, now["title"]) if part)
    elif media_type == "Audio":
        details = now["title"]
        artists = ", ".join(now["artists"])
        state = f"by {artists}" if artists else (now["album"] or "Music")
    else:  # Movie and anything else
        details = now["title"]
        state = f"({now['year']})" if now["year"] else "Movie"

    # Real poster/album art when available; never in privacy mode.
    image = None if config["hide_details"] else now["artwork"]
    logo = config["server_type"]  # Discord asset keys: "emby" and "plex"
    presence = {
        "details": clamp(details),
        "state": clamp(f"⏸ Paused · {state}" if now["is_paused"] else state),
        "large_image": image or logo,
        "large_text": clamp(config["server_name"] if config["hide_details"] else details),
        "small_image": logo if image else None,
        "small_text": config["server_name"] if image else None,
    }
    presence = {key: value for key, value in presence.items() if value is not None}

    # Show a "time remaining" countdown while actively playing.
    if not now["is_paused"] and now["position_s"] is not None and now["runtime_s"]:
        remaining = max(0, now["runtime_s"] - now["position_s"])
        presence["end"] = int(time.time()) + remaining

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

    rpc = connect_discord(config["discord_client_id"])
    last_shown = None

    while True:
        try:
            now = fetch_now_playing(config)
        except (requests.RequestException, ValueError) as error:
            log.warning("Could not reach %s: %s", config["server_name"], error)
            now = None

        try:
            if now:
                presence = build_presence(now, config)
                shown = (presence["details"], presence["state"])
                rpc.update(**presence)
                if shown != last_shown:
                    log.info("Now playing: %s — %s", *shown)
                last_shown = shown
            elif last_shown is not None:
                rpc.clear()
                log.info("Playback stopped, presence cleared.")
                last_shown = None
        except (PipeClosed, DiscordError, ConnectionError, BrokenPipeError):
            log.warning("Lost connection to Discord, reconnecting...")
            rpc = connect_discord(config["discord_client_id"])
            last_shown = None

        time.sleep(config["poll_interval"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Stopped.")
