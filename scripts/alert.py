#!/usr/bin/env python3
"""Slack agent alerts for Claude Code.

Posts messages, acks, alerts, and images to the session thread.
All configuration read from ~/.config/claude-slack-agent/config.json.

Commands:
  start <title>          — Create session thread
  post <msg>             — Post update (robot prefix + divider)
  alert <msg>            — Post with @mention + push notification
  ack                    — Post :loading_: typing indicator
  end                    — Post session ended message
  image <path> [caption] — Upload image to thread
"""
import json
import os
import sys
import urllib.request

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
TEAM_ID = _CFG.get("workspace_id", "")
CHANNEL = _CFG["channel_id"]


def get_token():
    creds_path = _CFG.get("creds_path", os.path.expanduser("~/.config/slack-skill/credentials.json"))
    with open(creds_path) as f:
        return json.load(f)["token"]


def _thread_path():
    return os.path.join(_state_dir(), "thread.json")


def load_thread():
    tp = _thread_path()
    if os.path.exists(tp):
        with open(tp) as f:
            return json.load(f).get("thread_ts")
    return None


def save_thread(thread_ts: str):
    state = _state_dir()
    os.makedirs(state, exist_ok=True)
    with open(_thread_path(), "w") as f:
        json.dump({"thread_ts": thread_ts, "channel": CHANNEL}, f)


def post(text: str, thread_ts: str = None):
    """Post a raw message to the channel."""
    token = get_token()
    payload = {"channel": CHANNEL, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    return json.loads(urllib.request.urlopen(req).read())


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
        print(json.dumps({"ok": False, "error": "no session -- run start first"}))
        sys.exit(1)
    result = post(f":robot_face: {message}\n\u2500 \u2500 \u2500", thread_ts=thread_ts)
    print(json.dumps({"ok": result.get("ok", False)}))


def cmd_ack():
    """Typing indicator."""
    thread_ts = load_thread()
    if thread_ts:
        post(":loading_:", thread_ts=thread_ts)
    print(json.dumps({"ok": True}))


def cmd_alert(message: str):
    """Post in thread with @mention + push notification."""
    token = get_token()
    thread_ts = load_thread()

    if thread_ts:
        post(f":robot_face: <@{USER_ID}> {message}\n\u2500 \u2500 \u2500", thread_ts=thread_ts)

    # Push notification via reminder
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
    result = json.loads(urllib.request.urlopen(req).read())
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
    import urllib.parse
    thread_ts = load_thread()
    token = get_token()

    if not os.path.exists(file_path):
        print(json.dumps({"ok": False, "error": f"file not found: {file_path}"}))
        sys.exit(1)

    filename = os.path.basename(file_path)
    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    # Step 1: Get upload URL
    params = urllib.parse.urlencode({"filename": filename, "length": os.path.getsize(file_path)})
    req = urllib.request.Request(
        f"https://slack.com/api/files.getUploadURLExternal?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    result = json.loads(urllib.request.urlopen(req).read())
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
    urllib.request.urlopen(req)

    # Step 3: Complete the upload
    complete_data = json.dumps({
        "files": [{"id": file_id, "title": filename}],
        "channel_id": CHANNEL,
        "thread_ts": thread_ts or "",
        "initial_comment": f":robot_face: {comment}\n\u2500 \u2500 \u2500" if comment else "",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/files.completeUploadExternal",
        data=complete_data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    result = json.loads(urllib.request.urlopen(req).read())
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
