#!/bin/bash
# Heartbeat poster: every HEARTBEAT_INTERVAL seconds (default 120), reads
# the current "what I'm doing" line from a per-session status file and posts
# it to Slack. Skips the post when the status hasn't changed since the last
# heartbeat (no idle pings).
#
# Status file: $HOME/.config/slack-alerts/sessions/<CLAUDE_SESSION_ID>/status.txt
# Set the status from Claude with:
#   bash $SLACK_ALERTS_DIR/scripts/agent.sh status "what I'm doing now"
#
# Run via run_in_background:true. Killed by `agent.sh stop`.

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSION_ID="${CLAUDE_SESSION_ID:-}"
INTERVAL="${HEARTBEAT_INTERVAL:-120}"

if [ -z "$SESSION_ID" ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: CLAUDE_SESSION_ID not set, heartbeat refusing to start" >&2
  exit 1
fi

STATE_DIR="$HOME/.config/slack-alerts/sessions/$SESSION_ID"
mkdir -p "$STATE_DIR"
STATUS_FILE="$STATE_DIR/status.txt"
PID_FILE="$STATE_DIR/heartbeat.pid"
LOGFILE="$STATE_DIR/heartbeat.log"

# Single-instance guard. If a previous heartbeat is still alive, exit cleanly.
if [ -f "$PID_FILE" ]; then
  prev_pid=$(cat "$PID_FILE" 2>/dev/null)
  if [ -n "$prev_pid" ] && kill -0 "$prev_pid" 2>/dev/null; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') heartbeat already running (pid $prev_pid), exiting" >> "$LOGFILE"
    exit 0
  fi
fi
echo $$ > "$PID_FILE"
trap 'rm -f "$PID_FILE"' EXIT

LAST_POSTED=""

while true; do
  sleep "$INTERVAL"
  if [ ! -f "$STATUS_FILE" ]; then
    continue
  fi
  STATUS=$(cat "$STATUS_FILE" 2>/dev/null)
  if [ -z "$STATUS" ]; then
    continue
  fi
  # Skip when status hasn't changed since the last heartbeat, no idle pings.
  if [ "$STATUS" = "$LAST_POSTED" ]; then
    continue
  fi
  python3 "$SCRIPTS_DIR/alert.py" post "❤️ $STATUS" >>"$LOGFILE" 2>&1
  if [ $? -eq 0 ]; then
    LAST_POSTED="$STATUS"
  fi
done
