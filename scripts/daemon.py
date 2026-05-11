#!/usr/bin/env python3
"""Persistent Slack polling daemon.

Architecture:
- Owned by launchd, not the Claude Code harness. Survives harness reaps,
  agent dispatches, idle periods, computer sleep/wake.
- Walks ~/.config/slack-alerts/sessions/* every POLL_INTERVAL seconds.
- For each session with thread.json present and no session.ended marker,
  fetches Slack replies > daemon_cursor and appends each new human message
  to inbox-queue.jsonl in that session's state dir.
- inbox.py check reads the queue (instant, no Slack round-trip).
- inbox.py reply still posts to Slack directly and advances the queue
  consume cursor so the daemon's next poll naturally skips its own echo.

Cursors:
- daemon_cursor.json: highest Slack ts the daemon has appended for this
  session. The daemon never goes backward; this is the watermark used as
  `oldest` on the next conversations.replies fetch.
- queue_cursor.json: highest Slack ts the consumer (inbox.py check) has
  drained. Messages between queue_cursor and end-of-file are unread.

Why both:
- The daemon doesn't care whether the agent has read the messages; it just
  needs to know what it's already written so it doesn't double-append.
- The consumer doesn't care what's on Slack; it just walks its local queue.

No new pypi deps. urllib + stdlib only.
"""
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path.home() / ".config" / "slack-alerts"
SESSIONS_DIR = BASE_DIR / "sessions"
CONFIG_PATH = BASE_DIR / "config.json"
DAEMON_LOG = BASE_DIR / "daemon.log"
DAEMON_PID = BASE_DIR / "daemon.pid"

POLL_INTERVAL = float(os.environ.get("SLACK_DAEMON_POLL_INTERVAL", "3.0"))
HTTP_TIMEOUT = 10
MAX_RETRIES = 3


def log(msg: str):
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} {msg}\n"
    try:
        with open(DAEMON_LOG, "a") as f:
            f.write(line)
    except OSError:
        pass
    # Also write to stdout so launchctl-captured logs pick it up.
    sys.stdout.write(line)
    sys.stdout.flush()


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"config not found at {CONFIG_PATH}")
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_creds(creds_path: str):
    with open(creds_path) as f:
        return json.load(f)


def slack_api(url: str, token: str, params: dict = None, retries: int = MAX_RETRIES):
    """GET helper for Slack Web API. Returns parsed JSON dict, or {} on terminal failure."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    backoff = 2.0
    for attempt in range(retries):
        try:
            resp = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
            return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = float(e.headers.get("Retry-After", backoff))
                log(f"slack 429, sleeping {retry_after}s")
                time.sleep(retry_after)
                continue
            log(f"slack HTTP {e.code}: {e.reason}")
            return {}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log(f"slack network error (attempt {attempt + 1}): {e}")
            time.sleep(backoff)
            backoff *= 2
    return {}


def list_active_sessions():
    """Return list of (session_id, state_dir) for sessions that should be polled.

    A session is "active" if:
    - state_dir exists
    - thread.json exists and is non-empty
    - session.ended marker file does NOT exist
    """
    if not SESSIONS_DIR.exists():
        return []
    sessions = []
    for entry in SESSIONS_DIR.iterdir():
        if not entry.is_dir():
            continue
        thread_file = entry / "thread.json"
        ended_marker = entry / "session.ended"
        if not thread_file.exists() or thread_file.stat().st_size == 0:
            continue
        if ended_marker.exists():
            continue
        sessions.append((entry.name, entry))
    return sessions


def load_thread_meta(state_dir: Path):
    """Read thread.json. Return dict or None."""
    tp = state_dir / "thread.json"
    try:
        with open(tp) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def load_daemon_cursor(state_dir: Path, thread_ts: str) -> str:
    """The daemon's high-water mark of Slack ts it has already written to queue."""
    cp = state_dir / "daemon_cursor.json"
    if not cp.exists():
        return "0"
    try:
        with open(cp) as f:
            data = json.load(f)
        return data.get(f"thread_{thread_ts}", "0")
    except (OSError, json.JSONDecodeError):
        return "0"


def save_daemon_cursor(state_dir: Path, thread_ts: str, ts: str):
    """Atomic write of daemon cursor."""
    cp = state_dir / "daemon_cursor.json"
    data = {}
    if cp.exists():
        try:
            with open(cp) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}
    data[f"thread_{thread_ts}"] = ts
    tmp = cp.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, cp)


def append_to_queue(state_dir: Path, message: dict):
    """Append a JSON message to inbox-queue.jsonl (one per line)."""
    qp = state_dir / "inbox-queue.jsonl"
    with open(qp, "a") as f:
        f.write(json.dumps(message) + "\n")


def is_human_message(msg: dict, user_id: str, thread_ts: str) -> bool:
    """Filter logic: only Aaron's real messages, not bot echoes or parent."""
    if msg.get("bot_id"):
        return False
    if msg.get("subtype"):
        return False
    if msg.get("user") != user_id:
        return False
    if msg.get("ts") == thread_ts:
        return False
    text = msg.get("text", "")
    stripped = text
    # Strip session prefix like "[abc123] "
    if stripped.startswith("[") and "] " in stripped[:12]:
        stripped = stripped.split("] ", 1)[1]
    if stripped.startswith(":robot_face:"):
        return False
    if stripped.startswith(":loading_:"):
        return False
    if stripped.startswith("_Session ended"):
        return False
    return True


def poll_session(session_id: str, state_dir: Path, token: str, user_id: str, channel: str):
    """Poll one session. Append new human messages to its inbox queue."""
    meta = load_thread_meta(state_dir)
    if not meta:
        return
    thread_ts = meta.get("thread_ts")
    if not thread_ts:
        return

    cursor = load_daemon_cursor(state_dir, thread_ts)
    result = slack_api(
        "https://slack.com/api/conversations.replies",
        token,
        params={
            "channel": channel,
            "ts": thread_ts,
            "oldest": cursor,
            "inclusive": "false",
            "limit": "50",
        },
    )
    if not result.get("ok"):
        # Quiet failure mode: log and move on. Per-session errors must not
        # poison the daemon loop.
        err = result.get("error", "unknown")
        if err:
            log(f"session {session_id[:6]} conversations.replies error: {err}")
        return

    messages = result.get("messages", [])
    new_latest = cursor
    appended = 0
    for msg in messages:
        ts = msg.get("ts")
        if not ts or ts <= cursor:
            continue
        if is_human_message(msg, user_id, thread_ts):
            append_to_queue(state_dir, {"ts": ts, "text": msg.get("text", "")})
            appended += 1
        # Advance daemon cursor past every message we saw, even bot echoes,
        # so we never re-fetch them.
        if ts > new_latest:
            new_latest = ts

    if new_latest > cursor:
        save_daemon_cursor(state_dir, thread_ts, new_latest)
    if appended:
        log(f"session {session_id[:6]} +{appended} message(s)")


def loop():
    cfg = load_config()
    user_id = cfg["user_id"]
    channel = cfg["channel_id"]
    creds = load_creds(cfg["creds_path"])
    token = creds["token"]

    log(f"daemon starting, poll_interval={POLL_INTERVAL}s, channel={channel}")

    while True:
        try:
            sessions = list_active_sessions()
            for session_id, state_dir in sessions:
                try:
                    poll_session(session_id, state_dir, token, user_id, channel)
                except Exception as e:  # noqa: BLE001
                    # Defensive: per-session error must not kill the loop.
                    log(f"session {session_id[:6]} unexpected error: {e}")
        except Exception as e:  # noqa: BLE001
            log(f"loop-level error: {e}")
        time.sleep(POLL_INTERVAL)


def write_pid():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    with open(DAEMON_PID, "w") as f:
        f.write(str(os.getpid()))


def remove_pid():
    try:
        DAEMON_PID.unlink()
    except FileNotFoundError:
        pass


def handle_term(signum, frame):
    log(f"received signal {signum}, exiting")
    remove_pid()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_term)
    write_pid()
    try:
        loop()
    finally:
        remove_pid()
