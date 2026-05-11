#!/usr/bin/env python3
"""Read and reply to the user's messages in the session thread.

Commands:
  check            Check for new messages (non-destructive)
  check --advance  Check for new messages and advance cursor
  reply <msg>      Reply and advance cursor; auto-respawns listener.sh
  reply --no-respawn <msg>
                   Reply without auto-respawning the listener (use on shutdown)
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LISTENER_PATH = os.path.join(SCRIPT_DIR, "listener.sh")

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
    """Return session-specific state dir. Requires CLAUDE_SESSION_ID, with
    no global fallback (that's what caused the cross-session thread spam)."""
    sid = _session_id()
    if not sid:
        return None
    return os.path.join(BASE_STATE_DIR, "sessions", sid)


def _session_prefix():
    """Short tag for bot posts so the user can disambiguate concurrent sessions.

    Returns a string like '[0d24f7] ' (6 chars + brackets + trailing space)
    or '' when no session ID is available. Keep it cheap and stable so it
    doesn't churn across messages in the same thread.
    """
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
    """Get the best token for posting messages.
    Prefers bot_token (posts as bot identity) over user token (posts as user).
    """
    creds = _load_creds()
    return creds.get("bot_token", creds["token"])


def _thread_path():
    sd = _state_dir()
    return os.path.join(sd, "thread.json") if sd else None


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
    cp = _cursor_path()
    if cp and Path(cp).exists():
        with open(cp) as f:
            return json.load(f).get(_cursor_key(), "0")
    return "0"


def save_cursor(ts: str):
    """Write the cursor atomically: tmp file in the same dir, then rename.

    Atomic write prevents a partial-write race if two processes try to
    update the cursor simultaneously (defense in depth alongside the
    single-listener invariant). Rename within the same filesystem is
    atomic on POSIX, so readers either see the old cursor or the new one,
    never a half-written file.
    """
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
        # Best-effort cleanup; do not raise (a missed cursor advance is
        # recoverable, but a thrown exception would lose the reply.)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


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
    """Get user messages (no bot_id, no subtype) newer than `since`."""
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
        # Skip our own messages posted with user token (no bot_id).
        # Bot messages always start with :robot_face: or :loading_: prefix,
        # optionally preceded by a session prefix like "[abc123] ".
        text = msg.get("text", "")
        stripped = text
        if stripped.startswith("[") and "] " in stripped[:12]:
            stripped = stripped.split("] ", 1)[1]
        if stripped.startswith(":robot_face:") or stripped.startswith(":loading_:") or stripped.startswith("_Session ended"):
            continue
        messages.append({"ts": msg["ts"], "text": text})
        if msg["ts"] > latest:
            latest = msg["ts"]

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
        return []  # Gracefully degrade; context is nice-to-have, not critical
    if not result.get("ok"):
        return []

    context = []
    for msg in result.get("messages", []):
        # Skip the parent message and subtypes
        if msg["ts"] == thread_ts:
            continue
        if msg.get("subtype"):
            continue
        text = msg.get("text", "")
        # Skip ack messages
        if text.strip() in ("...", ":loading_:"):
            continue
        # Identify agent messages by bot_id OR :robot_face: prefix (user token fallback).
        # Strip a possible session prefix like "[abc123] " before checking.
        stripped = text
        if stripped.startswith("[") and "] " in stripped[:12]:
            stripped = stripped.split("] ", 1)[1]
        is_agent = bool(msg.get("bot_id")) or stripped.startswith(":robot_face:")
        who = "agent" if is_agent else "user"
        context.append({"who": who, "text": text})

    # Return last N
    return context[-limit:]


def cmd_check(advance: bool = False):
    """Check for new messages. Optionally advance cursor."""
    cursor = load_cursor()
    messages, latest = get_human_messages(cursor)

    # Advance cursor if requested and there are new messages
    if advance and latest > cursor:
        save_cursor(latest)

    result = {
        "ok": True,
        "channel": CHANNEL,
        "thread_ts": load_thread(),
        "new_messages": len(messages),
        "messages": messages,
    }
    # Only fetch recent context when there are new messages (saves an API call per poll)
    if messages:
        result["recent_context"] = get_recent_context()

    print(json.dumps(result, indent=2))


def _listener_alive():
    """Return True if the session's listener PID file points to a live process.

    Used by `_spawn_listener` to verify a respawn actually took, and by
    `cmd_health` so external callers can confirm the inbound channel.
    """
    sd = _state_dir()
    if not sd:
        return False
    pidfile = os.path.join(sd, "listener.pid")
    try:
        with open(pidfile) as f:
            pid = int(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True


def _spawn_listener():
    """Spawn a detached background listener process, then self-test.

    listener.sh enforces the single-listener invariant via its own PID file:
    a second spawn while one is already alive becomes a silent no-op. So
    "did the spawn take" is really "is *some* listener alive after we
    spawned" not "did our specific child survive". We retry once if the
    PID file is missing after 0.5s, then once more after a longer wait,
    then give up and report `false` so the caller surfaces the failure.
    """
    sd = _state_dir()
    if not sd:
        return False
    os.makedirs(sd, exist_ok=True)
    log_path = os.path.join(sd, "listener.log")

    def _spawn_once():
        try:
            log_fp = open(log_path, "a")
            subprocess.Popen(
                ["bash", LISTENER_PATH],
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            return True
        except Exception:
            return False

    if not _spawn_once():
        return False
    time.sleep(0.5)
    if _listener_alive():
        return True

    # Retry once. The first spawn may have lost a race with another spawn
    # call that already cleaned its PID file mid-flight.
    if not _spawn_once():
        return False
    time.sleep(0.8)
    return _listener_alive()


def cmd_reply(message: str, respawn: bool = True, dry_run: bool = False):
    """Reply in thread and advance cursor past all current messages.

    When respawn is True (the default), spawn a fresh background listener
    after the reply succeeds and verify it actually came up. The result
    includes `listener_respawned`, which is now grounded in a PID-file
    check (was a blind `true` previously).

    `dry_run=True` skips the Slack post but still exercises the respawn
    path. Useful for tests.
    """
    if dry_run:
        respawned = _spawn_listener() if respawn else False
        text = f"{_session_prefix()}:robot_face: {message}\n─ ─ ─"
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "would_post": text,
            "listener_respawned": respawned,
            "listener_alive": _listener_alive(),
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

    # Use the reply's timestamp as cursor; anything before our reply is "seen"
    if result.get("ok") and result.get("message", {}).get("ts"):
        save_cursor(result["message"]["ts"])

    # Auto-respawn DISABLED 2026-05-10: subprocess.Popen detaches the new
    # listener from the harness's task-notification system. The agent must
    # explicitly restart the listener via Bash run_in_background after this
    # reply. The `respawn` flag is preserved for API compatibility but
    # always returns False in this path.
    respawned = False

    print(json.dumps({
        "ok": result.get("ok", False),
        "listener_respawned": respawned,
        "listener_alive": _listener_alive(),
    }, indent=2))


def cmd_health():
    """Report listener liveness and session state. Read-only.

    Used by the watchdog (healthcheck.sh) and by the user when they want
    to confirm the bot is alive without restarting anything.
    """
    sd = _state_dir()
    alive = _listener_alive()
    pid = None
    if sd:
        pidfile = os.path.join(sd, "listener.pid")
        try:
            with open(pidfile) as f:
                pid = int(f.read().strip())
        except (FileNotFoundError, ValueError, OSError):
            pid = None
    print(json.dumps({
        "ok": True,
        "session_id": _session_id() or None,
        "state_dir": sd,
        "thread_ts": load_thread(),
        "listener_alive": alive,
        "listener_pid": pid,
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
