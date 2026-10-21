#!/usr/bin/env python3
"""Emby Discord Presence.

Shows what you're currently watching (or listening to) on your Emby server
as a Discord Rich Presence status.

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
log = logging.getLogger("emby-discord-presence")


def load_config():
    """Read and validate settings from the environment / .env file."""
    load_dotenv()

    config = {
        "emby_url": os.getenv("EMBY_URL", "").rstrip("/"),
        "emby_public_url": os.getenv("EMBY_PUBLIC_URL", "").rstrip("/"),
        "emby_api_key": os.getenv("EMBY_API_KEY", ""),
        "emby_username": os.getenv("EMBY_USERNAME", "").strip(),
        "discord_client_id": os.getenv("DISCORD_CLIENT_ID", "").strip(),
        "poll_interval": max(5, int(os.getenv("POLL_INTERVAL", "15"))),
        "hide_details": os.getenv("HIDE_DETAILS", "false").lower() in ("1", "true", "yes"),
        "show_artwork": os.getenv("SHOW_ARTWORK", "true").lower() in ("1", "true", "yes"),
    }

    # Discord's servers fetch the artwork, so the image URL must be reachable
    # from the internet over https. Use EMBY_PUBLIC_URL if given, otherwise
    # EMBY_URL when it's already https; LAN-only http servers get no artwork.
    artwork_base = config["emby_public_url"] or config["emby_url"]
    if not config["show_artwork"] or not artwork_base.startswith("https://"):
        artwork_base = ""
    config["artwork_base"] = artwork_base

    missing = [
        name
        for name, key in (
            ("EMBY_URL", "emby_url"),
            ("EMBY_API_KEY", "emby_api_key"),
            ("DISCORD_CLIENT_ID", "discord_client_id"),
        )
        if not config[key]
    ]
    if missing:
        log.error("Missing required settings: %s", ", ".join(missing))
        log.error("Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    if not config["emby_url"].startswith(("http://", "https://")):
        log.error("EMBY_URL must start with http:// or https://")
        sys.exit(1)

    return config


def fetch_now_playing(config):
    """Return the active session for the configured user, or None.

    The API key is sent as a header, never in the URL, so it can't leak
    into proxy or server access logs.
    """
    response = requests.get(
        f"{config['emby_url']}/emby/Sessions",
        headers={"X-Emby-Token": config["emby_api_key"]},
        timeout=10,
    )
    response.raise_for_status()

    wanted_user = config["emby_username"].lower()
    for session in response.json():
        if "NowPlayingItem" not in session:
            continue
        if wanted_user and session.get("UserName", "").lower() != wanted_user:
            continue
        return session
    return None


def clamp(text, fallback="Emby"):
    """Discord requires presence strings between 2 and 128 characters."""
    text = (text or fallback).strip() or fallback
    if len(text) < 2:
        text += " "
    return text[:128]


def artwork_url(item, base):
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


def build_presence(session, config):
    """Translate an Emby session into Discord Rich Presence fields."""
    item = session["NowPlayingItem"]
    play_state = session.get("PlayState", {})
    is_paused = play_state.get("IsPaused", False)
    media_type = item.get("Type", "")

    if config["hide_details"]:
        generic = {
            "Movie": "Watching a movie",
            "Episode": "Watching a TV show",
            "Audio": "Listening to music",
        }.get(media_type, "Watching something")
        details, state = generic, "on Emby"
    elif media_type == "Episode":
        details = item.get("SeriesName") or item.get("Name", "Unknown")
        season = item.get("ParentIndexNumber")
        episode = item.get("IndexNumber")
        marker = f"S{season:02d}E{episode:02d}" if season is not None and episode is not None else ""
        state = " · ".join(part for part in (marker, item.get("Name", "")) if part)
    elif media_type == "Audio":
        details = item.get("Name", "Unknown")
        artists = ", ".join(item.get("Artists", []))
        state = f"by {artists}" if artists else item.get("Album", "Music")
    else:  # Movie and anything else
        details = item.get("Name", "Unknown")
        year = item.get("ProductionYear")
        state = f"({year})" if year else "Movie"

    # Real poster/album art when available; never in privacy mode.
    image = None if config["hide_details"] else artwork_url(item, config["artwork_base"])
    presence = {
        "details": clamp(details),
        "state": clamp(f"⏸ Paused · {state}" if is_paused else state),
        "large_image": image or "emby",
        "large_text": clamp("Emby" if config["hide_details"] else details),
        "small_image": "emby" if image else None,
        "small_text": "Emby" if image else None,
    }
    presence = {key: value for key, value in presence.items() if value is not None}

    # Show a "time remaining" countdown while actively playing.
    position = play_state.get("PositionTicks")
    runtime = item.get("RunTimeTicks")
    if not is_paused and position is not None and runtime:
        remaining = max(0, (runtime - position) // TICKS_PER_SECOND)
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
    log.info("Watching Emby at %s (user filter: %s)",
             config["emby_url"], config["emby_username"] or "any")

    rpc = connect_discord(config["discord_client_id"])
    last_shown = None

    while True:
        try:
            session = fetch_now_playing(config)
        except requests.RequestException as error:
            log.warning("Could not reach Emby: %s", error)
            session = None

        try:
            if session:
                presence = build_presence(session, config)
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
