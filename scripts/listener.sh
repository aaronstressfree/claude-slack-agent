#!/bin/bash
# Continuously polls for new Slack messages. Auto-acks immediately.
# Writes messages to a queue file for Claude to read.
# Run with run_in_background:true — does NOT need restarting after each message.
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

# Session isolation
SESSION_ID="${CLAUDE_SESSION_ID:-}"
if [ -n "$SESSION_ID" ]; then
  STATE_DIR="$HOME/.config/slack-alerts/sessions/$SESSION_ID"
else
  STATE_DIR="$HOME/.config/slack-alerts"
fi
mkdir -p "$STATE_DIR"
echo $$ > "$STATE_DIR/listener.pid"
trap 'rm -f "$STATE_DIR/listener.pid"' EXIT

LOGFILE="$STATE_DIR/listener.log"
QUEUE="$STATE_DIR/message_queue.json"

while true; do
  result=$(python3 "$SCRIPTS_DIR/inbox.py" check --advance 2>>"$LOGFILE")
  exit_code=$?
  if [ $exit_code -ne 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: inbox.py check failed (exit $exit_code)" >> "$LOGFILE"
    sleep 5
    continue
  fi

  count=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('new_messages',0))" 2>>"$LOGFILE")
  if [ $? -ne 0 ] || [ -z "$count" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: failed to parse message count" >> "$LOGFILE"
    count="0"
  fi

  if [ "${count:-0}" -gt 0 ] 2>/dev/null; then
    # Auto-ack immediately so Aaron sees we got the message
    python3 "$SCRIPTS_DIR/alert.py" ack 2>>"$LOGFILE"
    # Write to queue file for Claude to read
    echo "$result" > "$QUEUE"
    # Exit to notify Claude via task notification
    exit 0
  fi
  sleep 5
done
