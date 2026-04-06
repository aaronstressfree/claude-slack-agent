#!/bin/bash
# Usage: agent.sh start "description"
#        agent.sh stop
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

# Session isolation: use CLAUDE_SESSION_ID if available.
# If not set, generate a fallback from parent PID to avoid sharing state.
SESSION_ID="${CLAUDE_SESSION_ID:-}"
if [ -z "$SESSION_ID" ]; then
  SESSION_ID="fallback-$$-$(date +%s)"
  export CLAUDE_SESSION_ID="$SESSION_ID"
fi
STATE_DIR="$HOME/.config/slack-alerts/sessions/$SESSION_ID"
mkdir -p "$STATE_DIR"

# Kill this session's listener by PID file first, fall back to pattern match
kill_session_listener() {
  # Prefer PID file (reliable, session-scoped)
  if [ -f "$STATE_DIR/listener.pid" ]; then
    local pid
    pid=$(cat "$STATE_DIR/listener.pid")
    # Verify PID is still a listener process before killing
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
    fi
    rm -f "$STATE_DIR/listener.pid"
    return
  fi

  # Fall back to pattern match — only use session-scoped pattern
  if [ -n "$SESSION_ID" ]; then
    pkill -f "CLAUDE_SESSION_ID=$SESSION_ID.*listener.sh" 2>/dev/null
  fi
  # If no SESSION_ID and no PID file, don't kill anything — too risky
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

    # Kill only this session's listener
    kill_session_listener

    # Kill any existing caffeinate from previous sessions before spawning new one
    kill_caffeinate "$STATE_DIR/caffeinate.pid"

    # Keep Mac awake — PID stored per-session
    caffeinate -d -i -s &
    echo $! > "$STATE_DIR/caffeinate.pid"

    python3 "$SCRIPTS_DIR/alert.py" start "$TITLE"
    python3 "$SCRIPTS_DIR/alert.py" post "Ready. Reply here to send instructions."

    echo '{"status": "started"}'
    ;;

  stop)
    # Kill only this session's listener
    kill_session_listener

    # Stop this session's caffeinate (with process name validation + pkill fallback)
    kill_caffeinate "$STATE_DIR/caffeinate.pid"
    # Fallback: kill any orphaned caffeinate started by this script
    # (only if PID file was missing/stale)
    if [ ! -f "$STATE_DIR/caffeinate.pid" ]; then
      pkill -P 1 -x caffeinate 2>/dev/null || true
    fi

    python3 "$SCRIPTS_DIR/alert.py" end 2>/dev/null
    echo '{"status": "stopped"}'
    ;;

  *)
    echo "Usage: agent.sh [start <description>|stop]" >&2
    exit 1
    ;;
esac
