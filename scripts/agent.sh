#!/bin/bash
# Usage: agent.sh start "description"
#        agent.sh stop
#        agent.sh status [text]
#
# Architecture (2026-05-10): polling runs in a launchd-owned daemon, not in
# a harness-owned listener. This script only manages session lifecycle
# (thread.json, session.ended marker, caffeinate, heartbeat). It ensures
# the daemon is loaded as a side effect of `start`.
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPTS_DIR/.." && pwd)"
LABEL="xyz.aaronstevens.slack-alerts"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

# Session isolation: REQUIRE CLAUDE_SESSION_ID.
SESSION_ID="${CLAUDE_SESSION_ID:-}"
if [ -z "$SESSION_ID" ]; then
  echo '{"status": "error", "message": "CLAUDE_SESSION_ID not set; refusing to operate on global state"}' >&2
  exit 1
fi
STATE_DIR="$HOME/.config/slack-alerts/sessions/$SESSION_ID"
mkdir -p "$STATE_DIR"

# Ensure the launchd daemon is loaded. Idempotent: no-op if already running.
ensure_daemon_loaded() {
  if launchctl list | grep -q "$LABEL"; then
    return 0
  fi
  if [ ! -f "$PLIST_DEST" ]; then
    # First-time install: run the installer.
    if [ -f "$SKILL_DIR/install-daemon.sh" ]; then
      bash "$SKILL_DIR/install-daemon.sh" >/dev/null 2>&1 || true
    fi
  else
    launchctl load -w "$PLIST_DEST" 2>/dev/null || true
  fi
}

# Kill this session's heartbeat by PID file.
kill_session_heartbeat() {
  if [ -f "$STATE_DIR/heartbeat.pid" ]; then
    local pid
    pid=$(cat "$STATE_DIR/heartbeat.pid")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
    fi
    rm -f "$STATE_DIR/heartbeat.pid"
  fi
  if [ -n "$SESSION_ID" ]; then
    pkill -f "CLAUDE_SESSION_ID=$SESSION_ID.*heartbeat.sh" 2>/dev/null
  fi
  rm -f "$STATE_DIR/heartbeat.pid"
}

# Kill a caffeinate process by PID file, with validation.
kill_caffeinate() {
  local pidfile="$1"
  if [ -f "$pidfile" ]; then
    local pid
    pid=$(cat "$pidfile")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      local pname
      pname=$(ps -p "$pid" -o comm= 2>/dev/null)
      if [ "$pname" = "caffeinate" ]; then
        kill "$pid" 2>/dev/null
      fi
    fi
    rm -f "$pidfile"
  fi
}

case "$1" in
  start)
    TITLE="${*:2}"
    [ -z "$TITLE" ] && TITLE="Claude Code session"

    ensure_daemon_loaded

    # Clear any stale session.ended marker so the daemon picks this session
    # back up when start is called after a previous stop.
    rm -f "$STATE_DIR/session.ended"

    THREAD_FILE="$STATE_DIR/thread.json"
    if [ -f "$THREAD_FILE" ] && [ -s "$THREAD_FILE" ]; then
      # Session already running; just ensure caffeinate is alive.
      if [ -f "$STATE_DIR/caffeinate.pid" ]; then
        CAFF_PID=$(cat "$STATE_DIR/caffeinate.pid")
        if ! kill -0 "$CAFF_PID" 2>/dev/null; then
          caffeinate -d -i -s &
          echo $! > "$STATE_DIR/caffeinate.pid"
        fi
      else
        caffeinate -d -i -s &
        echo $! > "$STATE_DIR/caffeinate.pid"
      fi
      echo '{"status": "already_running"}'
      exit 0
    fi

    kill_caffeinate "$STATE_DIR/caffeinate.pid"
    caffeinate -d -i -s &
    echo $! > "$STATE_DIR/caffeinate.pid"

    if ! python3 "$SCRIPTS_DIR/alert.py" start "$TITLE"; then
      echo '{"status": "error", "message": "Failed to create Slack thread"}'
      exit 1
    fi
    python3 "$SCRIPTS_DIR/alert.py" post "Ready. Reply here to send instructions."

    echo '{"status": "started"}'
    ;;

  stop)
    kill_session_heartbeat

    kill_caffeinate "$STATE_DIR/caffeinate.pid"
    if [ ! -f "$STATE_DIR/caffeinate.pid" ]; then
      pkill -P 1 -x caffeinate 2>/dev/null || true
    fi

    python3 "$SCRIPTS_DIR/alert.py" end 2>/dev/null

    # Tell the daemon to stop polling this session.
    touch "$STATE_DIR/session.ended"

    # Clear thread + status so next start creates a fresh session.
    rm -f "$STATE_DIR/thread.json" "$STATE_DIR/session-thread.json" "$STATE_DIR/status.txt"

    echo '{"status": "stopped"}'
    ;;

  status)
    STATUS_TEXT="${*:2}"
    if [ -z "$STATUS_TEXT" ]; then
      if [ -f "$STATE_DIR/status.txt" ]; then
        cat "$STATE_DIR/status.txt"
      else
        echo ""
      fi
      exit 0
    fi
    echo "$STATUS_TEXT" > "$STATE_DIR/status.txt"
    echo '{"status": "set"}'
    ;;

  *)
    echo "Usage: agent.sh [start <description>|stop|status [text]]" >&2
    exit 1
    ;;
esac
