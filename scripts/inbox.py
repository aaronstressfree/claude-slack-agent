#!/usr/bin/env python3
"""Read and reply to user messages in the session thread.

All configuration read from ~/.config/claude-slack-agent/config.json.

Commands:
  check          -- Check for new messages (non-destructive)
  reply <msg>    -- Reply and advance cursor
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from pathlib import Path

CONFIG_PATH = os.path.expanduser("~/.config/claude-slack-agent/config.json")
BASE_STATE_DIR = os.path.expanduser("~/.config/claude-slack-agent")


def _load_cfg():
    if not os.path.exists(CONFIG_PATH):
        print(json.dumps({"ok": False, "error": "Not configured. Run: python3 config.py setup"}))
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _session_id():
    """Get session ID from env var."""
    return os.environ.get("CLAUDE_SESSION_ID", "")


def _state_dir():
    """Return session-specific state dir, or global fallback."""
    sid = _session_id()
    if sid:
        return os.path.join(BASE_STATE_DIR, "sessions", sid)
    return BASE_STATE_DIR


_CFG = _load_cfg()
USER_ID = _CFG["user_id"]
CHANNEL = _CFG["channel_id"]


def get_token():
    creds_path = _CFG.get("creds_path", os.path.expanduser("~/.config/slack-skill/credentials.json"))
    with open(creds_path) as f:
        return json.load(f)["token"]


def _thread_path():
    return os.path.join(_state_dir(), "thread.json")


def _cursor_path():
    return os.path.join(_state_dir(), "cursor.json")


def load_thread():
    tp = _thread_path()
    if os.path.exists(tp):
        with open(tp) as f:
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
    return json.loads(urllib.request.urlopen(req).read())


def get_human_messages(since: str):
    """Get user's messages (no bot_id, no subtype) newer than `since`."""
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
    """Get the last N messages from the thread (both human and bot) for context."""
    thread_ts = load_thread()
    if not thread_ts:
        return []
    result = fetch_thread_replies("0")
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
        if msg.get("text", "").strip() in ("...", ":loading_:"):
            continue
        who = "agent" if msg.get("bot_id") else "user"
        context.append({"who": who, "text": msg.get("text", "")})

    # Return last N
    return context[-limit:]


def cmd_check():
    """Check for new messages. Does NOT advance cursor."""
    cursor = load_cursor()
    messages, _ = get_human_messages(cursor)
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
    token = get_token()

    text = f":robot_face: {message}\n\u2500 \u2500 \u2500"
    payload = {"channel": CHANNEL, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    result = json.loads(urllib.request.urlopen(req).read())

    # Advance cursor past all current human messages
    cursor = load_cursor()
    _, latest = get_human_messages(cursor)
    if latest > cursor:
        save_cursor(latest)

    print(json.dumps({
        "ok": result.get("ok", False),
        "recent_context": get_recent_context(),
    }, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: inbox.py [check|reply <message>]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "check":
        cmd_check()
    elif cmd == "reply":
        if len(sys.argv) < 3:
            print("Usage: inbox.py reply <message>", file=sys.stderr)
            sys.exit(1)
        cmd_reply(" ".join(sys.argv[2:]))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
