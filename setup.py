#!/usr/bin/env python3
"""Interactive sign-in for Emby or Plex — no manual tokens.

Run this once and it writes .env for you.

Plex uses the official PIN link flow (the same one Plex apps use): it
opens plex.tv/link in your browser, you enter the short code shown here,
and plex.tv hands the script a token only after you approve — the script
never sees your password, and it discovers your servers automatically.

Emby has no central link service, so the script asks for your server
address and signs in with your username and password once, keeping only
the access token Emby returns — the password itself is never stored.
"""

import getpass
import os
import re
import sys
import time
import webbrowser

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE, ".env")
HEADERS = {
    "Accept": "application/json",
    "X-Plex-Client-Identifier": "emby-discord-presence",
    "X-Plex-Product": "Emby/Plex Discord Presence",
    "X-Plex-Device-Name": "Discord Presence Setup",
}


def set_env(key, value):
    """Write one KEY=value line into .env, replacing any existing one."""
    value = str(value)
    if any(character in value for character in " #\"'"):
        value = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    line = f"{key}={value}"
    with open(ENV_PATH) as env_file:
        content = env_file.read()
    pattern = rf"^{re.escape(key)}=.*$"
    if re.search(pattern, content, re.M):
        # A replacement function keeps backslashes in tokens literal —
        # a plain re.sub would interpret them as group references.
        content = re.sub(pattern, lambda _match: line, content, flags=re.M)
    else:
        content += f"\n{line}\n"
    with open(ENV_PATH, "w") as env_file:
        env_file.write(content)
    try:
        os.chmod(ENV_PATH, 0o600)  # tokens live here — owner-only
    except OSError:
        pass


def setup_emby():
    """Sign in to an Emby server and keep only its access token."""
    url = input("Emby server address (e.g. http://192.168.1.10:8096): ").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    if url.startswith("http://"):
        print("Note: plain http is fine on your home network, but use https")
        print("for a server you reach over the internet.")
    username = input("Emby username: ").strip()
    password = getpass.getpass("Emby password (not stored, not shown): ")

    response = requests.post(
        f"{url}/emby/Users/AuthenticateByName",
        json={"Username": username, "Pw": password},
        headers={
            "X-Emby-Authorization": 'MediaBrowser Client="Discord Presence", '
                                    'Device="Setup", DeviceId="emby-discord-presence", '
                                    'Version="1.0"',
        },
        timeout=10,
    )
    if response.status_code == 401:
        print("Wrong username or password.")
        sys.exit(1)
    response.raise_for_status()
    token = response.json()["AccessToken"]

    set_env("SERVER_TYPE", "emby")
    set_env("EMBY_URL", url)
    set_env("EMBY_API_KEY", token)
    set_env("EMBY_USERNAME", username)
    print(f"\nSigned in to {url} (account: {username}).")


def setup_plex():
    """Sign in via plex.tv/link and discover the account's servers."""
    response = requests.post("https://plex.tv/api/v2/pins", headers=HEADERS,
                             data={"strong": "true"}, timeout=10)
    response.raise_for_status()
    pin = response.json()
    print("\n  1. Opening https://plex.tv/link in your browser...")
    print(f"  2. Enter this code there:  {pin['code']}\n")
    webbrowser.open("https://plex.tv/link")

    token = None
    for _ in range(120):  # up to ~10 minutes
        time.sleep(5)
        try:
            check = requests.get(f"https://plex.tv/api/v2/pins/{pin['id']}",
                                 headers=HEADERS, timeout=10).json()
        except (requests.RequestException, ValueError):
            continue  # transient network hiccup — keep waiting
        if check.get("authToken"):
            token = check["authToken"]
            break
        print("  waiting for approval...", end="\r")
    if not token:
        print("Timed out waiting for approval on plex.tv.")
        sys.exit(1)
    print("\nSigned in ✔")

    auth = {**HEADERS, "X-Plex-Token": token}
    username = requests.get("https://plex.tv/api/v2/user",
                            headers=auth, timeout=10).json().get("username", "")

    resources = requests.get("https://plex.tv/api/v2/resources?includeHttps=1",
                             headers=auth, timeout=10).json()
    servers = [r for r in resources if "server" in (r.get("provides") or "")]
    if not servers:
        print("No Plex servers are linked to this account.")
        sys.exit(1)
    if len(servers) == 1:
        server = servers[0]
        print(f"Found your server: {server['name']}")
    else:
        for number, candidate in enumerate(servers, 1):
            shared = "" if candidate.get("owned") else " (shared)"
            print(f"  {number}. {candidate['name']}{shared}")
        while True:
            try:
                picked = int(input("Which server? "))
                if 1 <= picked <= len(servers):
                    break
            except ValueError:
                pass
            print(f"Enter a number between 1 and {len(servers)}.")
        server = servers[picked - 1]

    # Prefer direct remote connections over relay, and remote over LAN —
    # a LAN address stops working the moment the laptop leaves the house.
    connections = sorted(server.get("connections", []),
                         key=lambda c: (bool(c.get("relay")), bool(c.get("local"))))
    url = None
    for connection in connections:
        try:
            requests.get(connection["uri"] + "/identity", headers=HEADERS, timeout=5)
            url = connection["uri"].rstrip("/")
            break
        except requests.RequestException:
            continue
    if not url:
        print(f"Could not reach any address of {server['name']} from here.")
        sys.exit(1)

    # Shared servers only accept their own access token, not the account
    # token — using it transparently is what lets non-admin accounts work.
    set_env("SERVER_TYPE", "plex")
    set_env("PLEX_URL", url)
    set_env("PLEX_TOKEN", server.get("accessToken") or token)
    set_env("PLEX_USERNAME", username)
    print(f"\nSigned in to {server['name']} at {url} (account: {username}).")


def main():
    if not os.path.exists(ENV_PATH):
        with open(os.path.join(BASE, ".env.example")) as example:
            content = example.read()
        with open(ENV_PATH, "w") as env_file:
            env_file.write(content)

    choice = input("Which media server do you use? [1] Plex  [2] Emby: ").strip()
    if choice in ("2", "emby", "Emby"):
        setup_emby()
    else:
        setup_plex()

    with open(ENV_PATH) as env_file:
        existing = re.search(r"^DISCORD_CLIENT_ID=(.+)$", env_file.read(), re.M)
    if existing:
        print("Discord Application ID already configured — keeping it.")
    else:
        print("\nOptional — the tool ships with a built-in Discord application,")
        print("so you can just press Enter. To use your own instead, create one")
        print("at https://discord.com/developers/applications and paste its")
        print("Application ID here.")
        app_id = input("Discord Application ID [press Enter for built-in]: ").strip()
        if app_id:
            set_env("DISCORD_CLIENT_ID", app_id)

    runner = r".venv\Scripts\python" if os.name == "nt" else ".venv/bin/python"
    print(f"\nAll set — start the app with:  {runner} emby_discord_presence.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
