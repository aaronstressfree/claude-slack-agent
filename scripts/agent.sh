#!/bin/bash
# Usage: agent.sh start "description"
#        agent.sh stop
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

# Session isolation: REQUIRE CLAUDE_SESSION_ID. Falling back to a global
# state dir is what caused cross-session bleed and the "Session started"
# spam; every hook without a session ID would target the same legacy file.
SESSION_ID="${CLAUDE_SESSION_ID:-}"
if [ -z "$SESSION_ID" ]; then
  echo '{"status": "error", "message": "CLAUDE_SESSION_ID not set; refusing to operate on global state"}' >&2
  exit 1
fi
STATE_DIR="$HOME/.config/slack-alerts/sessions/$SESSION_ID"
mkdir -p "$STATE_DIR"

# Kill this session's listener by PID file first, fall back to pattern match.
# Always clears the PID file at the end so a stale file never lingers and
# blocks a future listener.sh from claiming the slot.
kill_session_listener() {
  if [ -f "$STATE_DIR/listener.pid" ]; then
    local pid
    pid=$(cat "$STATE_DIR/listener.pid")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
    fi
    rm -f "$STATE_DIR/listener.pid"
  fi

  # Defensive sweep: any stragglers for this session that lost their PID
  # file (process forked oddly, kernel race, etc.) get cleaned up here.
  if [ -n "$SESSION_ID" ]; then
    pkill -f "CLAUDE_SESSION_ID=$SESSION_ID.*listener.sh" 2>/dev/null
  fi
  # Explicit final cleanup: ensure no stale PID file survives.
  rm -f "$STATE_DIR/listener.pid"
}

# Kill this session's heartbeat by PID file
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

# Kill this session's healthcheck (watchdog) by PID file
kill_session_healthcheck() {
  if [ -f "$STATE_DIR/healthcheck.pid" ]; then
    local pid
    pid=$(cat "$STATE_DIR/healthcheck.pid")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
    fi
    rm -f "$STATE_DIR/healthcheck.pid"
  fi
  if [ -n "$SESSION_ID" ]; then
    pkill -f "CLAUDE_SESSION_ID=$SESSION_ID.*healthcheck.sh" 2>/dev/null
  fi
  rm -f "$STATE_DIR/healthcheck.pid"
}

# Kill a caffeinate process by PID file, with validation
kill_caffeinate() {
  local pidfile="$1"
  if [ -f "$pidfile" ]; then
    local pid
    pid=$(cat "$pidfile")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      # Verify this PID is actually a caffeinate process
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

    # Check if this session already has an active thread; skip re-creating.
    # Strictly session-scoped: do NOT consult the legacy global path, which
    # used to magnetize spam from sessions running hooks without a session ID.
    THREAD_FILE="$STATE_DIR/thread.json"
    if [ -f "$THREAD_FILE" ] && [ -s "$THREAD_FILE" ]; then
      # Session already running; just ensure caffeinate is alive
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

    # Kill only this session's listener
    kill_session_listener

    # Kill any existing caffeinate from previous sessions before spawning new one
    kill_caffeinate "$STATE_DIR/caffeinate.pid"

    # Keep Mac awake; PID stored per-session
    caffeinate -d -i -s &
    echo $! > "$STATE_DIR/caffeinate.pid"

    if ! python3 "$SCRIPTS_DIR/alert.py" start "$TITLE"; then
      echo '{"status": "error", "message": "Failed to create Slack thread"}'
      exit 1
    fi
    python3 "$SCRIPTS_DIR/alert.py" post "Ready. Reply here to send instructions."

    # Auto-spawn listener so callers don't have to remember the second command.
    # listener.sh has its own PID-file dedup, so a duplicate call is a no-op.
    LOGFILE="$STATE_DIR/listener.log"
    nohup bash "$SCRIPTS_DIR/listener.sh" >> "$LOGFILE" 2>&1 < /dev/null &
    disown 2>/dev/null || true

    # Auto-spawn the healthcheck watchdog. It restarts the listener if it
    # ever dies silently. Single-instance, so a duplicate call is a no-op.
    HC_LOG="$STATE_DIR/healthcheck.log"
    nohup bash "$SCRIPTS_DIR/healthcheck.sh" >> "$HC_LOG" 2>&1 < /dev/null &
    disown 2>/dev/null || true

    echo '{"status": "started"}'
    ;;

  stop)
    # Kill this session's listener, heartbeat, and healthcheck watchdog
    kill_session_listener
    kill_session_heartbeat
    kill_session_healthcheck

    # Stop this session's caffeinate (with process name validation + pkill fallback)
    kill_caffeinate "$STATE_DIR/caffeinate.pid"
    # Fallback: kill any orphaned caffeinate started by this script
    # (only if PID file was missing/stale)
    if [ ! -f "$STATE_DIR/caffeinate.pid" ]; then
      pkill -P 1 -x caffeinate 2>/dev/null || true
    fi

    python3 "$SCRIPTS_DIR/alert.py" end 2>/dev/null

    # Clear thread + status file so next start creates a fresh session
    rm -f "$STATE_DIR/thread.json" "$STATE_DIR/session-thread.json" "$STATE_DIR/status.txt"

    echo '{"status": "stopped"}'
    ;;

  status)
    # Set the current "what I'm doing" line for the heartbeat poster.
    # Usage: agent.sh status "building the doc site"
    STATUS_TEXT="${*:2}"
    if [ -z "$STATUS_TEXT" ]; then
      # Read mode; print current status
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
