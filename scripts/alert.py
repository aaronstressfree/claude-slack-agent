#!/usr/bin/env python3
"""Slack agent for Claude Code → #agent-aaron channel.

Message design:
- Session header: bold title with robot emoji (parent message)
- Replies: clean text, no prefix clutter. Bot identity is implicit from bot_id.
- Ack: just "..." — minimal
- Alerts: @mention for push notification
"""
import json
import os
import sys
import urllib.request

# Import shared API helper from config.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import api_call, api_call_raw

CONFIG_PATH = os.path.expanduser("~/.config/slack-alerts/config.json")
BASE_STATE_DIR = os.path.expanduser("~/.config/slack-alerts")


def _load_cfg():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {
        "user_id": "U03U7J0DG9Z",
        "workspace_id": "T05HJ0CKWG5",
        "channel_id": "C0AP4PD0ENN",
        "creds_path": os.path.expanduser("~/.config/slack-skill/credentials.json"),
    }


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
TEAM_ID = _CFG["workspace_id"]
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


def save_thread(thread_ts: str):
    state = _state_dir()
    os.makedirs(state, exist_ok=True)
    with open(_thread_path(), "w") as f:
        json.dump({"thread_ts": thread_ts, "channel": CHANNEL}, f)


def post(text: str, thread_ts: str = None):
    """Post a raw message to the channel using bot token when available."""
    token = get_post_token()
    payload = {"channel": CHANNEL, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    return api_call(req)


def cmd_start(title: str):
    """Create session thread. This is the only message with the robot emoji."""
    result = post(f":robot_face:  *{title}*")
    if result.get("ok"):
        thread_ts = result["message"]["ts"]
        save_thread(thread_ts)
        print(json.dumps({"ok": True, "thread_ts": thread_ts}))
    else:
        print(json.dumps({"ok": False, "error": result.get("error")}))
        sys.exit(1)


def cmd_post(message: str):
    """Post a message in the thread with robot emoji prefix."""
    thread_ts = load_thread()
    if not thread_ts:
        print(json.dumps({"ok": False, "error": "no session — run start first"}))
        sys.exit(1)
    result = post(f":robot_face: {message}\n─ ─ ─", thread_ts=thread_ts)
    print(json.dumps({"ok": result.get("ok", False)}))


def cmd_ack():
    """Typing indicator."""
    thread_ts = load_thread()
    if thread_ts:
        post(":loading_:", thread_ts=thread_ts)
    print(json.dumps({"ok": True}))


def cmd_alert(message: str):
    """Post in thread with @mention + push notification."""
    token = get_token()  # reminders.add needs user token
    thread_ts = load_thread()

    if thread_ts:
        post(f":robot_face: <@{USER_ID}> {message}\n─ ─ ─", thread_ts=thread_ts)

    # Push notification
    data = json.dumps({
        "text": message,
        "time": "in 1 second",
        "user": USER_ID,
        "team_id": TEAM_ID,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/reminders.add",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    result = api_call(req)
    print(json.dumps({"ok": result.get("ok", False)}))


def cmd_end():
    """Post session ended message."""
    thread_ts = load_thread()
    if thread_ts:
        post("_Session ended._", thread_ts=thread_ts)
    print(json.dumps({"ok": True}))


def cmd_image(file_path: str, comment: str = ""):
    """Upload an image to the session thread."""
    import mimetypes
    thread_ts = load_thread()
    token = get_post_token()

    if not os.path.exists(file_path):
        print(json.dumps({"ok": False, "error": f"file not found: {file_path}"}))
        sys.exit(1)

    filename = os.path.basename(file_path)
    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    # Step 1: Get upload URL (query params, not JSON body)
    import urllib.parse
    params = urllib.parse.urlencode({"filename": filename, "length": os.path.getsize(file_path)})
    req = urllib.request.Request(
        f"https://slack.com/api/files.getUploadURLExternal?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    result = api_call(req)
    if not result.get("ok"):
        print(json.dumps({"ok": False, "error": result.get("error")}))
        sys.exit(1)

    upload_url = result["upload_url"]
    file_id = result["file_id"]

    # Step 2: Upload the file
    with open(file_path, "rb") as f:
        file_data = f.read()
    req = urllib.request.Request(upload_url, data=file_data, method="POST")
    req.add_header("Content-Type", content_type)
    api_call_raw(req)

    # Step 3: Complete the upload
    complete_data = json.dumps({
        "files": [{"id": file_id, "title": filename}],
        "channel_id": CHANNEL,
        "thread_ts": thread_ts or "",
        "initial_comment": f":robot_face: {comment}\n─ ─ ─" if comment else "",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/files.completeUploadExternal",
        data=complete_data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    result = api_call(req)
    print(json.dumps({"ok": result.get("ok", False), "file_id": file_id}))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: alert.py [start|post|alert|ack|end|image] [message/path]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    msg = " ".join(sys.argv[2:])

    {"start": lambda: cmd_start(msg or "New session"),
     "post": lambda: cmd_post(msg),
     "alert": lambda: cmd_alert(msg),
     "ack": cmd_ack,
     "end": cmd_end,
     "image": lambda: cmd_image(sys.argv[2], " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""),
    }.get(cmd, lambda: cmd_alert(" ".join(sys.argv[1:])))()
