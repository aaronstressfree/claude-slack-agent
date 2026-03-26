#!/bin/bash
# Usage: agent.sh start "description"
#        agent.sh stop
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$HOME/.config/claude-slack-agent"

# Session ID: use CLAUDE_SESSION_ID env var
SESSION_ID="${CLAUDE_SESSION_ID:-}"

# Build a grep pattern to identify THIS session's listener
if [ -n "$SESSION_ID" ]; then
  LISTENER_PATTERN="CLAUDE_SESSION_ID=$SESSION_ID.*listener.sh"
else
  LISTENER_PATTERN="listener.sh"
fi

case "$1" in
  start)
    TITLE="${*:2}"
    [ -z "$TITLE" ] && TITLE="Claude Code session"

    # Check if setup is needed
    if [ ! -f "$STATE_DIR/config.json" ]; then
      echo "First-time setup: detecting Slack identity..."
      python3 "$SCRIPTS_DIR/config.py" setup
      if [ $? -ne 0 ]; then
        echo '{"ok": false, "error": "Setup failed. See output above."}'
        exit 1
      fi
    fi

    # Kill only this session's listener (or all if no session ID)
    pkill -f "$LISTENER_PATTERN" 2>/dev/null

    # Keep Mac awake while agent is running
    caffeinate -d -i -s &
    echo $! > "$STATE_DIR/caffeinate.pid"

    python3 "$SCRIPTS_DIR/alert.py" start "$TITLE"
    python3 "$SCRIPTS_DIR/alert.py" post "Ready. Reply here to send instructions."

    echo '{"status": "started"}'
    ;;

  stop)
    # Kill only this session's listener
    pkill -f "$LISTENER_PATTERN" 2>/dev/null

    # Stop caffeinate
    if [ -f "$STATE_DIR/caffeinate.pid" ]; then
      kill "$(cat "$STATE_DIR/caffeinate.pid")" 2>/dev/null
      rm -f "$STATE_DIR/caffeinate.pid"
    fi

    python3 "$SCRIPTS_DIR/alert.py" end 2>/dev/null
    echo '{"status": "stopped"}'
    ;;

  *)
    echo "Usage: agent.sh [start <description>|stop]" >&2
    exit 1
    ;;
esac
