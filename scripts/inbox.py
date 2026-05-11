#!/usr/bin/env python3
"""Read and reply to Aaron's messages in the session thread.

ARCHITECTURE NOTE (2026-05-10):
The harness-owned listener.sh is DEPRECATED. The launchd-owned daemon.py
polls Slack and writes messages to a local queue file. `check` reads the
queue (no Slack round-trip). `reply` still posts to Slack and advances
the queue consume cursor so the daemon's next poll naturally skips the
echo.

Commands:
  check            Check for new messages (non-destructive; reads queue)
  check --advance  Check + advance consume cursor past all queued
  reply <msg>      Reply, advance consume cursor (no listener respawn)
  reply --no-respawn <msg>
                   Back-compat alias for reply (respawn no longer applies)
  reply --dry-run  Show what would be posted, do not call Slack
  health           Report queue state, daemon status, thread info
"""
import json
import os
import sys
import tempfile
import time
import urllib.request
import urllib.parse
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Import shared API helper from config.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import api_call  # noqa: E402

CONFIG_PATH = os.path.expanduser("~/.config/slack-alerts/config.json")
BASE_STATE_DIR = os.path.expanduser("~/.config/slack-alerts")
DAEMON_PID_PATH = os.path.join(BASE_STATE_DIR, "daemon.pid")


def _load_cfg():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    raise FileNotFoundError(
        f"Config not found at {CONFIG_PATH}. Run setup-bot-token.py first."
    )


def _session_id():
    sid = os.environ.get("CLAUDE_SESSION_ID", "")
    if sid:
        return sid
    return ""


def _state_dir():
    """Return session-specific state dir. Requires CLAUDE_SESSION_ID, with
    no global fallback (that's what caused the cross-session thread spam)."""
    sid = _session_id()
    if not sid:
        return None
    return os.path.join(BASE_STATE_DIR, "sessions", sid)


def _session_prefix():
    """Short tag for bot posts so Aaron can disambiguate concurrent sessions."""
    sid = _session_id()
    if not sid:
        return ""
    return f"[{sid[:6]}] "


_CFG = _load_cfg()
USER_ID = _CFG["user_id"]
CHANNEL = _CFG["channel_id"]


def _load_creds():
    with open(_CFG["creds_path"]) as f:
        return json.load(f)


def get_token():
    return _load_creds()["token"]


def get_post_token():
    """Prefer bot_token (posts as bot identity) over user token."""
    creds = _load_creds()
    return creds.get("bot_token", creds["token"])


def _thread_path():
    sd = _state_dir()
    return os.path.join(sd, "thread.json") if sd else None


def _queue_path():
    sd = _state_dir()
    return os.path.join(sd, "inbox-queue.jsonl") if sd else None


def _cursor_path():
    sd = _state_dir()
    return os.path.join(sd, "cursor.json") if sd else None


def load_thread():
    tp = _thread_path()
    if tp and os.path.exists(tp):
        with open(tp) as f:
            return json.load(f).get("thread_ts")
    return None


def _cursor_key():
    thread_ts = load_thread()
    return f"thread_{thread_ts}" if thread_ts else "global"


def load_cursor():
    """Load the consume cursor: highest queue ts the agent has acknowledged."""
    cp = _cursor_path()
    if cp and Path(cp).exists():
        with open(cp) as f:
            return json.load(f).get(_cursor_key(), "0")
    return "0"


def save_cursor(ts: str):
    """Atomic write of the consume cursor."""
    cp = _cursor_path()
    sd = _state_dir()
    if not cp or not sd:
        return
    os.makedirs(sd, exist_ok=True)
    data = {}
    if Path(cp).exists():
        try:
            with open(cp) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
    data[_cursor_key()] = ts
    fd, tmp_path = tempfile.mkstemp(prefix=".cursor.", dir=sd)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, cp)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _read_queue_messages(since: str):
    """Read the local queue file, return messages with ts > since.

    Queue is append-only JSONL. Each line is {"ts": "...", "text": "..."}.
    Malformed lines are skipped (defensive: don't crash on partial writes).
    """
    qp = _queue_path()
    if not qp or not os.path.exists(qp):
        return [], since
    messages = []
    latest = since
    with open(qp) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = msg.get("ts")
            if not ts or ts <= since:
                continue
            messages.append({"ts": ts, "text": msg.get("text", "")})
            if ts > latest:
                latest = ts
    return messages, latest


def get_recent_context(limit: int = 5):
    """Get the last N messages from the thread (both human and bot) for context.

    Still pulls from Slack so bot context (the agent's own replies) is included.
    The queue only has human messages.
    """
    thread_ts = load_thread()
    if not thread_ts:
        return []

    token = get_token()
    params = urllib.parse.urlencode({
        "channel": CHANNEL,
        "ts": thread_ts,
        "limit": str(limit * 3),
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
        return []
    if not result.get("ok"):
        return []

    context = []
    for msg in result.get("messages", []):
        if msg["ts"] == thread_ts:
            continue
        if msg.get("subtype"):
            continue
        text = msg.get("text", "")
        if text.strip() in ("...", ":loading_:"):
            continue
        stripped = text
        if stripped.startswith("[") and "] " in stripped[:12]:
            stripped = stripped.split("] ", 1)[1]
        is_agent = bool(msg.get("bot_id")) or stripped.startswith(":robot_face:")
        who = "agent" if is_agent else "aaron"
        context.append({"who": who, "text": text})
    return context[-limit:]


def cmd_check(advance: bool = False):
    """Check for new messages from the local queue. Optionally advance cursor."""
    cursor = load_cursor()
    messages, latest = _read_queue_messages(cursor)

    if advance and latest > cursor:
        save_cursor(latest)

    result = {
        "ok": True,
        "channel": CHANNEL,
        "thread_ts": load_thread(),
        "new_messages": len(messages),
        "messages": messages,
        "source": "queue",
    }
    if messages:
        result["recent_context"] = get_recent_context()

    print(json.dumps(result, indent=2))


def _daemon_alive():
    """Best-effort: is the launchd daemon currently running?"""
    if not os.path.exists(DAEMON_PID_PATH):
        return False
    try:
        with open(DAEMON_PID_PATH) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ValueError, OSError, ProcessLookupError, PermissionError):
        return False


def cmd_reply(message: str, respawn: bool = True, dry_run: bool = False):
    """Reply in thread and advance consume cursor past all queued messages.

    The `respawn` parameter is preserved for backward-compat with existing
    callers but no longer spawns a listener. The launchd daemon does the
    polling now. The flag is ignored.
    """
    if dry_run:
        text = f"{_session_prefix()}:robot_face: {message}\n─ ─ ─"
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "would_post": text,
            "daemon_alive": _daemon_alive(),
        }, indent=2))
        return

    thread_ts = load_thread()
    token = get_post_token()

    text = f"{_session_prefix()}:robot_face: {message}\n─ ─ ─"
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

    # Advance consume cursor: agent has now responded, so everything queued
    # up through "now" is acknowledged. Use the highest queued ts as cursor,
    # not the reply ts (the reply isn't in our queue, only human messages are).
    _, latest_queued = _read_queue_messages(load_cursor())
    if latest_queued > load_cursor():
        save_cursor(latest_queued)

    print(json.dumps({
        "ok": result.get("ok", False),
        "daemon_alive": _daemon_alive(),
        # Back-compat: callers still inspect listener_respawned / listener_alive.
        # The daemon replaces both, so we map both to daemon health.
        "listener_respawned": _daemon_alive(),
        "listener_alive": _daemon_alive(),
    }, indent=2))


def cmd_health():
    """Report daemon liveness, queue depth, thread, and session state. Read-only."""
    sd = _state_dir()
    daemon_alive = _daemon_alive()
    daemon_pid = None
    if os.path.exists(DAEMON_PID_PATH):
        try:
            with open(DAEMON_PID_PATH) as f:
                daemon_pid = int(f.read().strip())
        except (ValueError, OSError):
            daemon_pid = None

    cursor = load_cursor()
    unread, _ = _read_queue_messages(cursor)

    print(json.dumps({
        "ok": True,
        "session_id": _session_id() or None,
        "state_dir": sd,
        "thread_ts": load_thread(),
        "daemon_alive": daemon_alive,
        "daemon_pid": daemon_pid,
        "queue_unread": len(unread),
        "consume_cursor": cursor,
        # Back-compat keys (now reflect daemon state, not the dead listener).
        "listener_alive": daemon_alive,
        "listener_pid": daemon_pid,
    }, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: inbox.py [check [--advance]|reply [--no-respawn] [--dry-run] <msg>|health]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "check":
        advance = "--advance" in sys.argv[2:]
        cmd_check(advance=advance)
    elif cmd == "reply":
        args = sys.argv[2:]
        respawn = True
        dry_run = False
        if "--no-respawn" in args:
            respawn = False
            args = [a for a in args if a != "--no-respawn"]
        if "--dry-run" in args:
            dry_run = True
            args = [a for a in args if a != "--dry-run"]
        if not args and not dry_run:
            print("Usage: inbox.py reply [--no-respawn] [--dry-run] <message>", file=sys.stderr)
            sys.exit(1)
        cmd_reply(" ".join(args) if args else "", respawn=respawn, dry_run=dry_run)
    elif cmd == "health":
        cmd_health()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
