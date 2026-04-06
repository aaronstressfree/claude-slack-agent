#!/usr/bin/env python3
"""Configuration for slack-alerts. Reads from ~/.config/slack-alerts/config.json.

On first run, prompts the user to set up their config.
Shared helpers (e.g. api_call) used by alert.py and inbox.py.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

CONFIG_DIR = os.path.expanduser("~/.config/slack-alerts")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
CREDS_PATH = os.path.expanduser("~/.config/slack-skill/credentials.json")

DEFAULT_CONFIG = {
    "user_id": "",
    "channel_id": "",
    "workspace_id": "",
    "creds_path": CREDS_PATH,
}

# --- Shared HTTP helper with retry + backoff ---

_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0  # seconds


def api_call(req: urllib.request.Request, timeout: int = 10) -> dict:
    """Make a Slack API call with retry logic and timeout.

    Handles:
    - HTTP 429 (rate limited): retries with Retry-After header or exponential backoff
    - URLError / TimeoutError: retries with exponential backoff
    - Max 3 retries

    Returns parsed JSON response dict.
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = e.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else _BASE_BACKOFF * (2 ** attempt)
                time.sleep(wait)
                last_exc = e
                continue
            # Non-retryable HTTP error
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            wait = _BASE_BACKOFF * (2 ** attempt)
            time.sleep(wait)
            last_exc = e
            continue
    # Exhausted retries
    raise last_exc


def api_call_raw(req: urllib.request.Request, timeout: int = 10) -> bytes:
    """Make an HTTP call with retry logic, returning raw bytes (for file uploads etc.).

    Same retry logic as api_call but does not parse JSON.
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = e.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else _BASE_BACKOFF * (2 ** attempt)
                time.sleep(wait)
                last_exc = e
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            wait = _BASE_BACKOFF * (2 ** attempt)
            time.sleep(wait)
            last_exc = e
            continue
    raise last_exc


# --- Config management ---


def load_config():
    """Load config, or return None if not set up."""
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(config: dict):
    """Save config."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get_token(config: dict = None):
    """Get the Slack token."""
    cfg = config or load_config()
    creds_path = cfg.get("creds_path", CREDS_PATH) if cfg else CREDS_PATH
    with open(creds_path) as f:
        return json.load(f)["token"]


def setup():
    """Interactive setup — detect user info from Slack token."""
    print("Setting up slack-alerts...")

    # Check for credentials
    if not os.path.exists(CREDS_PATH):
        print(f"Error: No Slack credentials found at {CREDS_PATH}")
        print("Run the slack skill auth flow first.")
        sys.exit(1)

    token = get_token({"creds_path": CREDS_PATH})

    # Detect user info
    req = urllib.request.Request(
        "https://slack.com/api/auth.test",
        data=b"{}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    auth = api_call(req)

    if not auth.get("ok"):
        print(f"Error: Slack auth failed: {auth.get('error')}")
        sys.exit(1)

    user_id = auth["user_id"]
    team_id = auth.get("team_id", "")
    user_name = auth.get("user", "")

    print(f"Detected user: {user_name} ({user_id})")
    print(f"Workspace: {team_id}")

    # Try to find or create the agent channel
    channel_id = find_or_create_channel(token, team_id, user_name)

    config = {
        "user_id": user_id,
        "channel_id": channel_id,
        "workspace_id": team_id,
        "creds_path": CREDS_PATH,
        "user_name": user_name,
    }
    save_config(config)
    print(f"Config saved to {CONFIG_PATH}")
    print(json.dumps(config, indent=2))


def find_or_create_channel(token: str, team_id: str, user_name: str):
    """Find or create the agent channel for this user."""
    channel_name = f"agent-{user_name}".lower().replace(" ", "-")[:80]

    # Search for existing channel
    params = f"types=public_channel,private_channel&limit=200&exclude_archived=true&team_id={team_id}"
    req = urllib.request.Request(
        f"https://slack.com/api/conversations.list?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    result = api_call(req)

    for ch in result.get("channels", []):
        if ch.get("name") == channel_name:
            print(f"Found existing channel: #{channel_name} ({ch['id']})")
            return ch["id"]

    # Try to create it
    data = json.dumps({"name": channel_name, "team_id": team_id}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/conversations.create",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        result = api_call(req)
        if result.get("ok"):
            ch_id = result["channel"]["id"]
            print(f"Created channel: #{channel_name} ({ch_id})")
            return ch_id
        else:
            print(f"Could not create channel: {result.get('error')}")
            print(f"Please create #{channel_name} manually and re-run setup.")
            sys.exit(1)
    except Exception as e:
        print(f"Error creating channel: {e}")
        print(f"Please create #{channel_name} manually and re-run setup.")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        config = load_config()
        if config:
            print(json.dumps(config, indent=2))
        else:
            print("Not configured. Run: python3 config.py setup")
    else:
        setup()
