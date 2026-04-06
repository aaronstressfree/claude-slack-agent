#!/usr/bin/env python3
"""Read and reply to Aaron's messages in the session thread.

Commands:
  check          — Check for new messages (non-destructive)
  check --advance — Check for new messages and advance cursor
  reply <msg>    — Reply and advance cursor
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from pathlib import Path

# Import shared API helper from config.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import api_call

CONFIG_PATH = os.path.expanduser("~/.config/slack-alerts/config.json")
BASE_STATE_DIR = os.path.expanduser("~/.config/slack-alerts")


def _load_cfg():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    raise FileNotFoundError(
        f"Config not found at {CONFIG_PATH}. Run setup-bot-token.py first."
    )


def _session_id():
    """Get session ID, falling back to Claude Code's PID via grandparent resolution.

    Process chain: Claude Code (PID X) → bash → python3 this_script.py
    - Bash's PPID = X (Claude Code)
    - Python's ppid = bash PID
    - Python's grandparent = X (Claude Code)
    All scripts from the same Claude Code session resolve to the same X.
    """
    sid = os.environ.get("CLAUDE_SESSION_ID", "")
    if sid:
        return sid
    return ""


def _state_dir():
    """Return session-specific state dir, or global fallback."""
    sid = _session_id()
    if sid:
        return os.path.join(BASE_STATE_DIR, "sessions", sid)
    return BASE_STATE_DIR


_CFG = _load_cfg()
USER_ID = _CFG["user_id"]
CHANNEL = _CFG["channel_id"]


def _load_creds():
    with open(_CFG["creds_path"]) as f:
        return json.load(f)

def get_token():
    return _load_creds()["token"]

def get_post_token():
    """Get the best token for posting messages.
    Prefers bot_token (posts as bot identity) over user token (posts as user).
    """
    creds = _load_creds()
    return creds.get("bot_token", creds["token"])


def _thread_path():
    return os.path.join(_state_dir(), "thread.json")


def _cursor_path():
    return os.path.join(_state_dir(), "cursor.json")


def load_thread():
    tp = _thread_path()
    if os.path.exists(tp):
        with open(tp) as f:
            return json.load(f).get("thread_ts")
    # Backward compat: check old global session-thread.json
    global_path = os.path.join(BASE_STATE_DIR, "session-thread.json")
    if os.path.exists(global_path):
        with open(global_path) as f:
            return json.load(f).get("thread_ts")
    return None


def _cursor_key():
    thread_ts = load_thread()
    return f"thread_{thread_ts}" if thread_ts else "global"


def load_cursor():
    cp = _cursor_path()
    if Path(cp).exists():
        with open(cp) as f:
            return json.load(f).get(_cursor_key(), "0")
    # Backward compat: check old global inbox-cursor.json
    global_cursor = os.path.join(BASE_STATE_DIR, "inbox-cursor.json")
    if Path(global_cursor).exists():
        with open(global_cursor) as f:
            return json.load(f).get(_cursor_key(), "0")
    return "0"


def save_cursor(ts: str):
    cp = _cursor_path()
    os.makedirs(_state_dir(), exist_ok=True)
    data = {}
    if Path(cp).exists():
        with open(cp) as f:
            data = json.load(f)
    data[_cursor_key()] = ts
    with open(cp, "w") as f:
        json.dump(data, f)


def fetch_thread_replies(since: str):
    """Fetch replies in the session thread newer than `since`."""
    token = get_token()
    thread_ts = load_thread()
    if not thread_ts:
        return {"ok": False, "error": "no session thread"}

    params = urllib.parse.urlencode({
        "channel": CHANNEL,
        "ts": thread_ts,
        "oldest": since,
        "inclusive": "false",
        "limit": "50",
    })
    req = urllib.request.Request(
        f"https://slack.com/api/conversations.replies?{params}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    return api_call(req)


def get_human_messages(since: str):
    """Get Aaron's messages (no bot_id, no subtype) newer than `since`."""
    thread_ts = load_thread()
    result = fetch_thread_replies(since)
    if not result.get("ok"):
        return [], since

    messages = []
    latest = since
    for msg in result.get("messages", []):
        # Skip bot messages, subtypes, and the parent message
        if msg.get("bot_id") or msg.get("subtype"):
            continue
        if msg.get("user") != USER_ID:
            continue
        if msg["ts"] <= since:
            continue
        if thread_ts and msg["ts"] == thread_ts:
            continue
        messages.append({"ts": msg["ts"], "text": msg.get("text", "")})
        if msg["ts"] > latest:
            latest = msg["ts"]

    messages.reverse()  # oldest first
    return messages, latest


def get_recent_context(limit: int = 5):
    """Get the last N messages from the thread (both human and bot) for context.
    Uses latest=true to fetch only the most recent messages, not all of them."""
    thread_ts = load_thread()
    if not thread_ts:
        return []

    # Fetch only the latest messages instead of all since "0"
    token = get_token()
    params = urllib.parse.urlencode({
        "channel": CHANNEL,
        "ts": thread_ts,
        "limit": str(limit * 3),  # Fetch extra to account for skipped messages
        "inclusive": "false",
        "latest": "999999999999.999999",
    })
    req = urllib.request.Request(
        f"https://slack.com/api/conversations.replies?{params}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    try:
        result = api_call(req)
    except Exception:
        return []  # Gracefully degrade — context is nice-to-have, not critical
    if not result.get("ok"):
        return []

    context = []
    for msg in result.get("messages", []):
        # Skip the parent message and subtypes
        if msg["ts"] == thread_ts:
            continue
        if msg.get("subtype"):
            continue
        # Skip ack messages
        if msg.get("text", "").strip() == "...":
            continue
        who = "agent" if msg.get("bot_id") else "aaron"
        context.append({"who": who, "text": msg.get("text", "")})

    # Return last N
    return context[-limit:]


def cmd_check(advance: bool = False):
    """Check for new messages. Optionally advance cursor."""
    cursor = load_cursor()
    messages, latest = get_human_messages(cursor)

    # Advance cursor if requested and there are new messages
    if advance and latest > cursor:
        save_cursor(latest)

    print(json.dumps({
        "ok": True,
        "channel": CHANNEL,
        "thread_ts": load_thread(),
        "new_messages": len(messages),
        "messages": messages,
        "recent_context": get_recent_context(),
    }, indent=2))


def cmd_reply(message: str):
    """Reply in thread and advance cursor past all current messages."""
    thread_ts = load_thread()
    token = get_post_token()

    text = f":robot_face: {message}\n─ ─ ─"
    payload = {"channel": CHANNEL, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    result = api_call(req)

    # Use the reply's timestamp as cursor — anything before our reply is "seen"
    if result.get("ok") and result.get("message", {}).get("ts"):
        save_cursor(result["message"]["ts"])

    print(json.dumps({
        "ok": result.get("ok", False),
    }, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: inbox.py [check [--advance]|reply <message>]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "check":
        advance = "--advance" in sys.argv[2:]
        cmd_check(advance=advance)
    elif cmd == "reply":
        if len(sys.argv) < 3:
            print("Usage: inbox.py reply <message>", file=sys.stderr)
            sys.exit(1)
        cmd_reply(" ".join(sys.argv[2:]))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
