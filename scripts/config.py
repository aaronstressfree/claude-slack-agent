#!/usr/bin/env python3
"""Configuration for claude-slack-agent.

Commands:
  setup  — Interactive onboarding (detect user, find/create channel, save config)
  show   — Display current config

Config stored at ~/.config/claude-slack-agent/config.json
"""
import json
import os
import sys
import urllib.request

CONFIG_DIR = os.path.expanduser("~/.config/claude-slack-agent")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
CREDS_PATH = os.path.expanduser("~/.config/slack-skill/credentials.json")


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


def get_token(creds_path: str = None):
    """Get the Slack token from credentials."""
    path = creds_path or CREDS_PATH
    with open(path) as f:
        return json.load(f)["token"]


def find_channel(token: str, team_id: str, channel_name: str):
    """Find an existing channel by name. Returns channel ID or None."""
    import urllib.parse
    params = urllib.parse.urlencode({
        "types": "public_channel,private_channel",
        "limit": "200",
        "exclude_archived": "true",
        "team_id": team_id,
    })
    req = urllib.request.Request(
        f"https://slack.com/api/conversations.list?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read())

    for ch in result.get("channels", []):
        if ch.get("name") == channel_name:
            print(f"Found existing channel: #{channel_name} ({ch['id']})")
            return ch["id"]
    return None


def create_channel(token: str, team_id: str, channel_name: str, is_private: bool = True):
    """Create a new channel. Returns channel ID or exits on failure."""
    data = json.dumps({
        "name": channel_name,
        "team_id": team_id,
        "is_private": is_private,
    }).encode()
    req = urllib.request.Request(
        "https://slack.com/api/conversations.create",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        if result.get("ok"):
            ch_id = result["channel"]["id"]
            visibility = "private" if is_private else "public"
            print(f"Created {visibility} channel: #{channel_name} ({ch_id})")
            return ch_id
        else:
            print(f"Could not create channel: {result.get('error')}")
            print(f"Please create #{channel_name} manually and re-run setup.")
            sys.exit(1)
    except Exception as e:
        print(f"Error creating channel: {e}")
        print(f"Please create #{channel_name} manually and re-run setup.")
        sys.exit(1)


def find_or_create_channel(token: str, team_id: str, user_name: str, channel_name: str = None, is_private: bool = True):
    """Find or create the agent channel for this user."""
    if not channel_name:
        channel_name = f"agent-{user_name}".lower().replace(" ", "-")[:80]

    existing = find_channel(token, team_id, channel_name)
    if existing:
        return existing

    return create_channel(token, team_id, channel_name, is_private=is_private)


def detect_user(token: str):
    """Detect user info from Slack token. Returns (user_id, team_id, user_name) or exits."""
    req = urllib.request.Request(
        "https://slack.com/api/auth.test",
        data=b"{}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req)
    auth = json.loads(resp.read())

    if not auth.get("ok"):
        print(f"Error: Slack auth failed: {auth.get('error')}")
        sys.exit(1)

    return auth["user_id"], auth.get("team_id", ""), auth.get("user", "")


def setup(channel_name: str = None, is_private: bool = True):
    """Interactive setup -- detect user info from Slack token, find/create channel.

    Args:
        channel_name: Custom channel name (default: agent-{username})
        is_private: Whether to create a private channel (default: True)
    """
    print("Setting up claude-slack-agent...")

    # Check for credentials
    if not os.path.exists(CREDS_PATH):
        print(f"Error: No Slack credentials found at {CREDS_PATH}")
        print("You need to authenticate with Slack first.")
        print("Run the slack skill auth flow to get credentials.")
        sys.exit(1)

    token = get_token(CREDS_PATH)

    # Detect user info via auth.test
    user_id, team_id, user_name = detect_user(token)

    print(f"Detected user: {user_name} ({user_id})")
    print(f"Workspace: {team_id}")

    # Find or create the agent channel
    channel_id = find_or_create_channel(token, team_id, user_name, channel_name=channel_name, is_private=is_private)

    config = {
        "user_id": user_id,
        "channel_id": channel_id,
        "workspace_id": team_id,
        "user_name": user_name,
        "creds_path": CREDS_PATH,
    }
    save_config(config)
    print(f"\nConfig saved to {CONFIG_PATH}")
    print(json.dumps(config, indent=2))


def show():
    """Display current config."""
    config = load_config()
    if config:
        print(json.dumps(config, indent=2))
    else:
        print("Not configured. Run: python3 config.py setup")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: config.py [setup|show|detect] [--channel NAME] [--public]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "setup":
        # Parse optional flags
        channel_name = None
        is_private = True
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--channel" and i + 1 < len(args):
                channel_name = args[i + 1]
                i += 2
            elif args[i] == "--public":
                is_private = False
                i += 1
            else:
                i += 1
        setup(channel_name=channel_name, is_private=is_private)
    elif cmd == "show":
        show()
    elif cmd == "detect":
        # Just detect and print user info, used by onboarding flow
        if not os.path.exists(CREDS_PATH):
            print(json.dumps({"ok": False, "error": f"No credentials at {CREDS_PATH}"}))
            sys.exit(1)
        token = get_token(CREDS_PATH)
        user_id, team_id, user_name = detect_user(token)
        print(json.dumps({"ok": True, "user_id": user_id, "team_id": team_id, "user_name": user_name}))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Usage: config.py [setup|show|detect] [--channel NAME] [--public]", file=sys.stderr)
        sys.exit(1)
